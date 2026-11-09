"""오류를 자체 GlitchTip 으로 보낸다(2026-09-16).

**이 저장소는 오류 수집기가 없었다** — 백엔드 로그는 컨테이너 stdout 에만 남고,
그것을 보는 사람이 없으면 5xx 가 며칠씩 조용히 났다. 그래서 Sentry SDK 로 오류를
보내는데, 받는 쪽은 sentry.io 가 아니라 **우리가 띄운 GlitchTip**
(주소는 `SENTRY_DSN` 이 가리킨다)이다 — 수업 제출물·이름·이메일을 다루는 서버라
오류 본문이 바깥 업체로 나가지 않는 편이 낫다. SDK 는 같으므로 DSN 만 그쪽을
가리킨다.

**DSN 이 없으면 아무것도 하지 않는다.** dev·CI 는 `SENTRY_DSN` 을 주지 않으므로
SDK 가 꺼진 채로 돈다 — 테스트가 네트워크를 치지 않는다는 뜻이기도 하다.

**보내지 않는 것**(`send_default_pii=False` 에 더해 이 모듈이 정하는 것):

- **사용자 식별은 내부 id 하나뿐이다**(`accounts.middleware` 와
  `core.operator_auth` 가 붙인다). 이메일·이름·IP 는 붙이지 않는다.
- **스택 프레임의 지역 변수는 보내지 않는다**(`include_local_variables=False`,
  #590). SDK 기본값은 프레임마다 지역 변수를 싣는다 — 채점 경로의 `raw_key`·
  `headers`(강사 OpenAI 키가 든 `Authorization: Bearer`), `call_internal` 의
  `X-Internal-Token`, 들어온 요청 객체의 로그인 토큰이 그 길로 평문으로 실렸다
  (GlitchTip 오류 67~91). 이름 목록으로 골라 지우는 방식은 새 변수·dict 안의
  값마다 다시 뚫리므로 통째로 끈다. 잃은 진단 정보는 진입점(채점·스캔·제출)이
  **식별자만** 태그·컨텍스트로 메운다(`tag_error_scope`) — 키·소스·프롬프트 같은
  값은 싣지 않는다. `request_id` 태그로 Loki 로그와 이어진다(`core.request_id`).
- **요청 본문과 쿠키·인증 헤더**는 SDK 설정(`max_request_body_size="never"`)에
  더해 `scrub_secrets` 가 보내기 직전에 직접 지운다 — SDK 의 기본 필터는
  `Authorization`·`Cookie` 는 지우지만 우리 내부 헤더 `X-Internal-Token` 은 모른다.
  프레임 변수도 거기서 한 번 더 지운다(설정 하나를 믿지 않는다 — 프론트엔드
  `scrubSensitiveRequestData` 와 같은 원칙, #460).
- **정상적인 거절은 오류가 아니다.** 422(입력 검증)·404·403 은 사용자가 잘못
  요청했을 때 우리가 의도적으로 내는 응답이라, 그걸 다 보내면 진짜 사고가 그
  소음에 묻힌다(`drop_expected_error`). 5xx 와 처리되지 않은 예외만 보낸다.
- **배포가 Redis 를 바꿔 끼우는 몇 초도 오류가 아니다.** celery 워커는 브로커를
  잃으면 재시도마다 ERROR 로그를 남기고 스스로 다시 붙는다 — 그 첫 몇 번은
  보내지 않고, 재시도가 쌓이면(진짜 장애) 그대로 보낸다
  (`_is_transient_broker_reconnect`, GlitchTip 오류 66).
- **`manage.py shell` 에서 손으로 친 명령의 예외는 앱 결함이 아니다**(#893·#889,
  GlitchTip 오류 107). 이벤트의 예외 스택에 Django 의 `shell` 명령 프레임
  (`django/core/management/commands/shell.py`)이 있으면 버린다
  (`_is_manage_shell_error`). SDK 초기화를 shell 에서 건너뛰지 않는 것은 일부러다 —
  진입점에서 명령 이름을 풀어야 하고 shell 안에서 부른 앱 코드의 로깅 통합까지
  갈라진다. **범위는 shell 만**: 다른 관리 명령·웹 요청·celery 오류는 그대로 보낸다.
"""

from __future__ import annotations

import os
import re
from typing import Any

#: 어느 배포에서 났는지 — GlitchTip 의 environment 필터가 이 값을 쓴다.
_ENVIRONMENT_ENV = "CODEMIT_DEPLOYMENT_TARGET"
#: 어느 커밋에서 났는지. `deploy.sh` 가 배포하는 커밋 SHA 를 넣는다.
_RELEASE_ENV = "SENTRY_RELEASE"


def _status_code_of(exc: BaseException) -> int | None:
    """그 예외가 대신하는 HTTP 상태 코드. 없으면 None(=진짜 예외)."""

    status = getattr(exc, "status_code", None)
    return status if isinstance(status, int) else None


#: celery 소비자가 브로커에 다시 붙으려 할 때 남기는 로그의 로거 이름·템플릿 머리.
_CELERY_CONSUMER_LOGGER = "celery.worker.consumer.consumer"
_CELERY_CONNECTION_ERROR_HEAD = "consumer: Cannot connect to "
#: 「Trying again in 2.00 seconds... (1/100)」의 앞 숫자 — 몇 번째 재시도인가.
_RETRY_COUNT = re.compile(r"\((\d+)/\d+\)")
#: 이 횟수 **미만**의 재시도는 보내지 않는다. celery 의 재시도 간격이 2·4·6·8초로
#: 늘어나므로 넷째까지가 약 20초다 — 배포가 redis 컨테이너를 다시 만드는 시간보다
#: 넉넉하고, 그보다 오래 못 붙으면 배포의 틈이 아니라 장애다.
_TRANSIENT_BROKER_RETRIES = 5


def _is_transient_broker_reconnect(hint: dict[str, Any]) -> bool:
    """celery 워커가 브로커를 잠깐 잃고 다시 붙는 중인 로그 레코드인가.

    판정 근거는 로그 레코드의 로거 이름과 **포맷 전 템플릿**이다(메시지 본문이
    아니다 — 인자에 섞이는 연결 주소·예외 문구가 달라도 갈리지 않게). 재시도
    횟수를 읽지 못하면(「Trying to reconnect...」 갈래 등) 보낸다 — 모르는 것을
    버리지 않는다. 재시도가 끝내 실패하면 워커가 「Unrecoverable error」를
    CRITICAL 로 남기고 죽으므로 그것도 그대로 보내진다.
    """

    record = hint.get("log_record")
    if record is None or getattr(record, "name", None) != _CELERY_CONSUMER_LOGGER:
        return False
    if not str(getattr(record, "msg", "")).startswith(_CELERY_CONNECTION_ERROR_HEAD):
        return False
    args = getattr(record, "args", None)
    if not isinstance(args, tuple) or not args:
        return False
    match = _RETRY_COUNT.search(str(args[-1]))
    return match is not None and int(match.group(1)) < _TRANSIENT_BROKER_RETRIES


_SHELL_COMMAND_MODULE = "django.core.management.commands.shell"
_SHELL_COMMAND_PATH = "django/core/management/commands/shell.py"


def _is_manage_shell_error(event: dict[str, Any]) -> bool:
    """예외 스택 프레임에 `manage.py shell` 명령(Django)이 있으면 True.

    `module`·`abs_path`·`filename` 어느 쪽이 와도 맞게 본다(경로 구분자는 `/` 로 통일).
    """

    values = (event.get("exception") or {}).get("values") or []
    for value in values:
        for frame in (value.get("stacktrace") or {}).get("frames") or []:
            if frame.get("module") == _SHELL_COMMAND_MODULE:
                return True
            for key in ("abs_path", "filename"):
                path = str(frame.get(key) or "").replace("\\", "/")
                if path.endswith(_SHELL_COMMAND_PATH):
                    return True
    return False


def drop_expected_error(
    event: dict[str, Any], hint: dict[str, Any]
) -> dict[str, Any] | None:
    """`before_send` — 의도한 4xx 응답이면 버리고(None), 그 밖이면 그대로 보낸다.

    판정 근거는 예외 객체다: django-ninja 의 `HttpError` 와 Django 의 `Http404`·
    `PermissionDenied`·`SuspiciousOperation` 이 모두 status 로 환산되는 예외다.
    `hint` 에 예외가 없는 이벤트(로그 레코드 등)는 그대로 보낸다 — 배포 중
    브로커 재접속 로그(`_is_transient_broker_reconnect`)만 예외다.
    """

    if _is_transient_broker_reconnect(hint):
        return None

    if _is_manage_shell_error(event):
        return None

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


#: 이벤트에서 지우는 요청 헤더(소문자). 프론트엔드 `CREDENTIAL_HEADERS` 와 같은 목록이다.
_CREDENTIAL_HEADERS = frozenset(
    {
        "cookie",
        "set-cookie",
        "authorization",
        "proxy-authorization",
        "x-internal-token",
        "x-operator-origin",
    }
)


def _drop_frame_vars(container: Any) -> None:
    """`exception.values[]`·`threads.values[]` 의 프레임에서 `vars` 를 지운다."""

    values = container.get("values") if isinstance(container, dict) else None
    for value in values or ():
        frames = ((value or {}).get("stacktrace") or {}).get("frames") or ()
        for frame in frames:
            if isinstance(frame, dict):
                frame.pop("vars", None)


def scrub_secrets(event: dict[str, Any]) -> dict[str, Any]:
    """보내기 직전에 자격증명이 실릴 수 있는 자리를 지운다(#590).

    요청의 쿠키·본문은 통째로, 헤더는 `_CREDENTIAL_HEADERS` 에 든 이름만(대소문자
    무시), 스택 프레임의 지역 변수는 전부. `include_local_variables=False` 가 이미
    프레임 변수를 막지만 그 설정 하나가 빠지는 날을 대비해 여기서도 지운다.
    """

    request = event.get("request")
    if isinstance(request, dict):
        request.pop("cookies", None)
        request.pop("data", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for name in list(headers):
                if str(name).lower() in _CREDENTIAL_HEADERS:
                    del headers[name]
    _drop_frame_vars(event.get("exception"))
    _drop_frame_vars(event.get("threads"))
    return event


def before_send(event: dict[str, Any], hint: dict[str, Any]) -> dict[str, Any] | None:
    """SDK 의 `before_send` — 의도한 거절·배포 중 소음은 버리고, 남은 것은 비밀을 지워 보낸다."""

    kept = drop_expected_error(event, hint)
    return None if kept is None else scrub_secrets(kept)


def sentry_init_options(dsn: str) -> dict[str, Any]:
    """`sentry_sdk.init` 에 넘기는 설정 — 시험이 같은 설정으로 전송만 흉내 내 켠다."""

    from sentry_sdk.integrations.celery import CeleryIntegration
    from sentry_sdk.integrations.django import DjangoIntegration

    return {
        "dsn": dsn,
        "environment": os.environ.get(_ENVIRONMENT_ENV, "development"),
        "release": os.environ.get(_RELEASE_ENV, "").strip() or None,
        "integrations": [DjangoIntegration(), CeleryIntegration()],
        # 오류만 보낸다 — 성능 추적은 켜지 않았다(GlitchTip 이 리플레이를 받지
        # 못하는 것과 달리 트레이싱은 받지만, 지금 필요한 것은 오류다).
        "traces_sample_rate": 0.0,
        "send_default_pii": False,
        # 프레임 지역 변수에 키·토큰이 평문으로 실렸다(#590) — 위 모듈 docstring.
        "include_local_variables": False,
        "max_request_body_size": "never",
        "before_send": before_send,
    }


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

    sentry_sdk.init(**sentry_init_options(dsn))
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


def tag_error_scope(context: str, **identifiers: int | str | None) -> None:
    """이 요청·태스크에서 나는 오류에 **식별자만** 붙인다(#590) — 태그와 `context` 한 묶음.

    프레임 지역 변수를 끈 대신(`include_local_variables=False`) 어느 클래스·문제·
    제출·스캔·모델에서 났는지를 여기서 남긴다. 넘기는 값은 번호·이름 같은 식별자뿐이다
    — 키·소스·프롬프트·토큰을 넘기지 않는다. None 은 건너뛴다. SDK 가 꺼져 있으면
    (DSN 없는 dev·CI) 무해하다.
    """

    try:
        import sentry_sdk
    except ModuleNotFoundError:  # pragma: no cover - 의존성은 항상 설치된다
        return
    kept = {name: value for name, value in identifiers.items() if value is not None}
    for name, value in kept.items():
        sentry_sdk.set_tag(name, str(value))
    sentry_sdk.set_context(context, kept)
