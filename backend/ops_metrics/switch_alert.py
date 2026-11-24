"""운영 스위치 경보(#1221) — 바뀐 채 오래 남은 스위치를 하루 한 번 운영 경보 길로 알린다.

대상·기준은 `policies.switch_watch` 가 정한다. 보내는 길은 #830 과 같다 — `OPS_ALERT_DISCORD_WEBHOOK_URL`(값은 읽어 쓰기만 하고
어디에도 내지 않는다) → `alerts.post_webhook`. 웹훅이 비어 있으면 조용히 넘어간다. 보내지 못해도 다음 날 다시 대상이다.
글에는 키·라벨·지금 값/기본값·마지막 변경 시각·운영자 계정 id 만 있다 — 이름·이메일은 없다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings

from policies.switch_watch import SwitchWatch, due

from . import alerts

logger = logging.getLogger(__name__)

_SEOUL = ZoneInfo("Asia/Seoul")


def line(watch: SwitchWatch) -> str:
    since = watch.changed_at.astimezone(_SEOUL).strftime("%Y-%m-%d %H:%M") if watch.changed_at else "—"
    who = f"운영자 #{watch.changed_by_id}" if watch.changed_by_id is not None else "—"
    return f"· {watch.label}({watch.key}) {watch.value} (기본 {watch.default}) — {since} 부터, {who}"


def message(watches: list[SwitchWatch]) -> str:
    text = "⚠️ [Codemit] 운영 스위치가 바뀐 채 남아 있다\n" + "\n".join(line(w) for w in watches)
    origin = settings.OPERATOR_WEB_ORIGIN.rstrip("/")
    return f"{text}\n{origin}/settings?tab=ai" if origin else text


def check_daily(*, now: datetime) -> list[str]:
    """알릴 스위치의 키들 — 웹훅이 없거나 보내지 못해도 키는 돌려준다."""

    targets = due(now)
    if not targets:
        return []
    text = message(targets)
    alerts.post_notice(text)
    url = settings.OPS_ALERT_DISCORD_WEBHOOK_URL
    if url:
        try:
            alerts.post_webhook(url, text)
        except Exception as exc:  # noqa: BLE001 - 다음 날 다시 대상이다
            # 주소가 예외 문장에 섞일 수 있어 종류만 남긴다.
            logger.warning("운영 스위치 경보를 보내지 못했다: %s", type(exc).__name__)
    return [w.key for w in targets]
