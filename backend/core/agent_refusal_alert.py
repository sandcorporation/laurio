"""에이전트 실행의 계정 쪽 거절 경보(#1058) — 공모전 채점·완성도·강의실 채점이 같은 자리(`run_agent_job`)에서 부른다.

- GlitchTip: 지문은 (벤더, 종류) 고정이라 제출마다 이슈가 따로 생기지 않는다. 같은 (벤더, 종류)는 한 시간에 한 번만
  보낸다. 이벤트에는 벤더·종류 이름만 있다 — 키 값도 응답 본문도 싣지 않는다.
- 마지막 거절(시각·벤더·종류)은 운영자 AI 채점 설정 화면이 읽는다. 보내지 않은 거절도 갱신한다.
저장은 `rate_limits` 캐시(배포는 공용 Redis, 시험은 프로세스 안)다 — 표·마이그레이션 없이 가장 작다. 캐시가 비면
「기록 없음」이고, 다음 거절이 다시 채운다. 경보 실패가 채점을 막으면 안 되므로 여기서 던지지 않는다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TypedDict

from django.core.cache import caches

from core.observability import capture_grouped_warning

logger = logging.getLogger(__name__)

ALERT_INTERVAL_SECONDS = 3600
_LAST_KEY = "agent-account-refusal:last"
_LAST_TTL_SECONDS = 30 * 24 * 3600


class AccountRefusalAlert(Exception):
    """GlitchTip 에 보내는 예외 — 문구에 벤더·종류 이름만 있다."""


class LastAccountRefusal(TypedDict):
    at: str  # ISO 8601 UTC
    vendor: str
    kind: str


def report_account_refusal(vendor: str, kind: str) -> None:
    try:
        cache = caches["rate_limits"]
        last: LastAccountRefusal = {"at": datetime.now(UTC).isoformat(), "vendor": vendor, "kind": kind}
        cache.set(_LAST_KEY, last, timeout=_LAST_TTL_SECONDS)
        if cache.add(f"agent-account-refusal:alert:{vendor}:{kind}", 1, timeout=ALERT_INTERVAL_SECONDS):
            capture_grouped_warning(
                AccountRefusalAlert(f"에이전트 벤더 계정 거절: {vendor} / {kind}"),
                fingerprint=["agent-account-refusal", vendor, kind],
                alert="agent-account-refusal",
                vendor=vendor,
                refusal_kind=kind,
            )
    except Exception:  # noqa: BLE001 - 경보 실패가 채점을 막으면 안 된다.
        logger.exception("계정 거절 경보를 남기지 못했다")


def last_account_refusal() -> LastAccountRefusal | None:
    try:
        value = caches["rate_limits"].get(_LAST_KEY)
    except Exception:  # noqa: BLE001 - 캐시 장애가 설정 화면을 막으면 안 된다.
        return None
    return value if isinstance(value, dict) else None  # type: ignore[return-value]  # 캐시 값은 우리가 쓴 모양이다
