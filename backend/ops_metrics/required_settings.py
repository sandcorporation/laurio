"""운영 필수 설정 — 서비스 컨테이너 안에서 실제로 읽히는 값이 비었는지 본다(#1124).

문의 이메일이 backend·celery 에 넘어가지 않은 채 운영됐고 첫 실사용에서야 드러났다. compose 의 `:?` 는
compose 파일이 그 키를 서비스에 넘기는 곳만 지킨다 — 서비스마다 넘어가는 환경이 다르고, 운영 설정(DB)이 env
보다 앞서는 키도 있다. 그래서 배포 뒤 확인(`scripts/ci/post-deploy-check.sh`)이 서비스마다 그 컨테이너 안에서
`python manage.py check_required_settings --service <이름>` 을 부른다.

**표는 여기 한 곳이다** — `REQUIRED`. 확인 스크립트의 서비스 목록은 이 표의 서비스와 같아야 한다(시험이 본다).
출력은 키 이름과 「비어 있음」뿐이다. 값·길이·해시는 어디에도 내지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from django.conf import settings

from core.adapters import is_fake_adapter_binding
from core.runtime_settings_port import VENDOR_ANTHROPIC, VENDOR_OPENAI, ScoringVendor

from policies import runtime_settings

ALIGO_ADAPTER_PREFIX = "notifications.adapters_aligo."


@dataclass(frozen=True)
class Required:
    """필수 설정 하나 — `name` 은 운영 `.env.prod` 에서 찾을 이름, `read` 는 그 서비스가 실제로 쓰는 값."""

    name: str
    services: tuple[str, ...]
    read: Callable[[], str | None]
    when: Callable[[], bool] = lambda: True


def _django(attr: str) -> Callable[[], str | None]:
    return lambda: getattr(settings, attr, None)


def _runtime(key: str) -> Callable[[], str | None]:
    """운영 설정(DB) → env 순서 — `runtime_settings.setting_value` 의 해석 그대로."""

    return lambda: runtime_settings.setting_value(key)


def _aligo_in_use() -> bool:
    adapters = (
        settings.NOTIFICATION_ALIMTALK_ADAPTER,
        settings.NOTIFICATION_SMS_ADAPTER,
        settings.NOTIFICATION_LMS_ADAPTER,
    )
    return any(path.startswith(ALIGO_ADAPTER_PREFIX) for path in adapters)


def _contest_scoring_uses(vendor: ScoringVendor) -> Callable[[], bool]:
    """공모전 AI 채점이 실물 어댑터로 켜져 있고 운영 설정의 벤더가 `vendor` 일 때만 그 키가 필요하다."""

    def when() -> bool:
        return (
            not is_fake_adapter_binding(settings.LLM_ADAPTER_MODE)
            and runtime_settings.contest_ai_scoring_enabled()
            and runtime_settings.scoring_vendor() == vendor
        )

    return when


WEB_AND_WORKER = ("backend", "celery-worker")

REQUIRED: tuple[Required, ...] = (
    # 알림 문구의 「문의처」(notifications/rendering.py) — compose 는 `SUPPORT_EMAIL` 을 이 이름으로 넘긴다.
    Required("SUPPORT_EMAIL", WEB_AND_WORKER, _django("PUBLIC_SUPPORT_EMAIL")),
    # 알림톡·문자 발송(notifications/adapters_aligo.py) — 어댑터가 알리고일 때만.
    Required("ALIGO_API_KEY", WEB_AND_WORKER, _django("ALIGO_API_KEY"), _aligo_in_use),
    Required("ALIGO_USER_ID", WEB_AND_WORKER, _django("ALIGO_USER_ID"), _aligo_in_use),
    Required("ALIGO_SENDER_PHONE_NUMBER", WEB_AND_WORKER, _django("ALIGO_SENDER_PHONE_NUMBER"), _aligo_in_use),
    # 운영 경보(ops_metrics/alerts.py) — 경보 검사는 celery-worker 의 beat 가 1분마다 돈다.
    Required("OPS_ALERT_DISCORD_WEBHOOK_URL", WEB_AND_WORKER, _django("OPS_ALERT_DISCORD_WEBHOOK_URL")),
    # 공모전 채점 벤더 키 — 스캔은 celery-worker 에서 돈다. 운영 채점 방식이 쓰는 벤더만.
    Required(
        "OPEN_AI_API_KEY", ("celery-worker",), _runtime("OPEN_AI_API_KEY"),
        _contest_scoring_uses(VENDOR_OPENAI),
    ),
    Required(
        "ANTHROPIC_API_KEY", ("celery-worker",), _runtime("ANTHROPIC_API_KEY"),
        _contest_scoring_uses(VENDOR_ANTHROPIC),
    ),
)


def services() -> list[str]:
    """표에 나오는 서비스 — 나온 차례대로."""

    seen: list[str] = []
    for item in REQUIRED:
        for service in item.services:
            if service not in seen:
                seen.append(service)
    return seen


def missing(service: str) -> list[str]:
    """`service` 에 필요한데 비어 있는 키 이름들 — 값은 돌려주지 않는다."""

    return [
        item.name
        for item in REQUIRED
        if service in item.services and item.when() and not (item.read() or "").strip()
    ]
