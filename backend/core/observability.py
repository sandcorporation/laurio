"""오류를 자체 GlitchTip 으로 보낸다(2026-09-16).

**이 저장소는 오류 수집기가 없었다** — 백엔드 로그는 컨테이너 stdout 에만 남고,
그것을 보는 사람이 없으면 5xx 가 며칠씩 조용히 났다. 그래서 Sentry SDK 로 오류를
보내는데, 받는 쪽은 sentry.io 가 아니라 **우리가 띄운 GlitchTip**
(`glitchtip.honeycombpizza.link`)이다 — 수업 제출물·이름·이메일을 다루는 서버라
오류 본문이 바깥 업체로 나가지 않는 편이 낫다. SDK 는 같으므로 DSN 만 그쪽을
가리킨다.

**DSN 이 없으면 아무것도 하지 않는다.** dev·CI 는 `SENTRY_DSN` 을 주지 않으므로
SDK 가 꺼진 채로 돈다 — 테스트가 네트워크를 치지 않는다는 뜻이기도 하다.

**보내지 않는 것**(`send_default_pii=False` 에 더해 이 모듈이 정하는 것):

- **사용자 식별은 내부 id 하나뿐이다**(`accounts.middleware` 와
  `core.operator_auth` 가 붙인다). 이메일·이름·IP 는 붙이지 않는다.
- **요청 본문과 쿠키·헤더의 인증 값**은 SDK 설정으로 아예 막는다
  (`max_request_body_size="never"`) — 제출 소스나 OpenAI 키가 오류에 실려 나갈
  길을 없앤다.
- **정상적인 거절은 오류가 아니다.** 422(입력 검증)·404·403 은 사용자가 잘못
  요청했을 때 우리가 의도적으로 내는 응답이라, 그걸 다 보내면 진짜 사고가 그
  소음에 묻힌다(`drop_expected_error`). 5xx 와 처리되지 않은 예외만 보낸다.
"""

from __future__ import annotations

import os
from typing import Any

#: 어느 배포에서 났는지 — GlitchTip 의 environment 필터가 이 값을 쓴다.
_ENVIRONMENT_ENV = "CODEMIT_DEPLOYMENT_TARGET"
#: 어느 커밋에서 났는지. `deploy.sh` 가 배포하는 커밋 SHA 를 넣는다.
_RELEASE_ENV = "SENTRY_RELEASE"


def _status_code_of(exc: BaseException) -> int | None:
    """그 예외가 대신하는 HTTP 상태 코드. 없으면 None(=진짜 예외)."""

    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


def drop_expected_error(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """`before_send` — 의도한 4xx 응답이면 버리고(None), 그 밖이면 그대로 보낸다.

    판정 근거는 예외 객체다: django-ninja 의 `HttpError` 와 Django 의 `Http404`·
    `PermissionDenied`·`SuspiciousOperation` 이 모두 status 로 환산되는 예외다.
    `hint` 에 예외가 없는 이벤트(로그 레코드 등)는 그대로 보낸다.
    """

    exc_info = hint.get("exc_info")
    if not exc_info:
        return event
    exc = exc_info[1]

    from django.core.exceptions import PermissionDenied, SuspiciousOperation
    from django.http import Http404

    if isinstance(exc, (Http404, PermissionDenied, SuspiciousOperation)):
        return None

    status = _status_code_of(exc)
    if status is not None and 400 <= status < 500:
        return None
    return event


def configure_sentry() -> bool:
    """DSN 이 있으면 SDK 를 켠다. 켰으면 True.

    `settings.py` 가 import 시점에 한 번 부른다 — gunicorn·uvicorn·celery worker·
    beat·관리 명령이 모두 Django 설정을 거치므로 다섯 프로세스 전부가 이 한 줄로
    켜진다(백엔드 이미지 하나로 다섯이 뜬다, CLAUDE.md 「배포」).
    """

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    import sentry_sdk
    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get(_ENVIRONMENT_ENV, "development"),
        release=os.environ.get(_RELEASE_ENV, "").strip() or None,
        integrations=[DjangoIntegration(), CeleryIntegration()],
        # 오류만 보낸다 — 성능 추적은 켜지 않았다(GlitchTip 이 리플레이를 받지
        # 못하는 것과 달리 트레이싱은 받지만, 지금 필요한 것은 오류다).
        traces_sample_rate=0.0,
        send_default_pii=False,
        max_request_body_size="never",
        before_send=drop_expected_error,
    )
    return True


def capture_handled_exception(exc: BaseException, **tags: str) -> None:
    """이미 처리했지만(500으로 튀지 않는다) 운영자가 알아야 할 예외를 보낸다.

    `drop_expected_error`(`before_send`)는 **처리되지 않은** 예외·5xx만 거르는
    판정이라, 여기처럼 코드가 이미 잡아서 물러난(fallback) 경로에는 적용되지
    않는다 — `capture_exception`을 직접 부르지 않으면 이런 실패는 GlitchTip에
    영영 남지 않는다(검색 엔진이 죽어 DB 검색으로 물러난 사실을 아무도 모르게
    되는 것이 `contests.search.search_contests`가 이 함수를 쓰는 이유다, #450).

    `set_sentry_user_id`와 같은 이유로 SDK가 꺼져 있으면(DSN 없는 dev·CI)
    무해하게 지나간다.
    """

    try:
        import sentry_sdk
    except ModuleNotFoundError:  # pragma: no cover - 의존성은 항상 설치된다
        return
    sentry_sdk.capture_exception(exc, tags=tags or None)


def set_sentry_user_id(user_id: int | str | None) -> None:
    """이 요청의 사용자를 내부 id 하나로만 표시한다. SDK 가 꺼져 있으면 무해하다."""

    try:
        import sentry_sdk
    except ModuleNotFoundError:  # pragma: no cover - 의존성은 항상 설치된다
        return
    if user_id is None:
        sentry_sdk.set_user(None)
        return
    sentry_sdk.set_user({"id": str(user_id)})
