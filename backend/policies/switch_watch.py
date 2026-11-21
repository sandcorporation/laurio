"""운영 스위치 감시(#1221) — 바뀐 채 오래 남은 스위치를 찾고, 「이대로 둔다」를 기록한다.

완성도 리뷰 스위치를 끈 채 이틀을 알아채지 못했다(2026-11-19~21). 끈 값이 **기본값과 같아서** 「기본값과 다르면
알린다」만으로는 잡히지 않았다. 그래서 대상은 `switch` 설정 중 다음 둘 중 하나다.

- (가) 지금 값이 기본값과 다르다(`differs`).
- (나) 마지막 변경이 on → off, 곧 켜져 있던 것을 껐다(`turned_off`).

어느 쪽이든 **마지막 변경 뒤 N 일**(`SWITCH_ALERT_AFTER_DAYS`, 기본 2)이 지나야 알린다. 「이대로 둔다」(`ACK`)를 누르면
다음 변경까지 대상에서 빠진다 — 확인은 변경 이력(`RuntimeSettingChange`)에 누가·언제로 남고, 그 뒤에 새 변경(저장·지우기)이
오면 확인은 효력을 잃는다.

알림은 `ops_metrics.switch_alert` 가 기존 운영 경보 길(디스코드)로 하루 한 번 보낸다. 값·이름·이메일은 글에 없다 —
키·라벨·지금 값/기본값·언제부터·운영자 계정 id 뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction

from core.clock import Clock

from .runtime_settings import (
    _SWITCH_ON,
    DEFAULT_SWITCH_ALERT_AFTER_DAYS,
    SWITCH_ALERT_AFTER_DAYS,
    RuntimeSettingError,
    SettingView,
    _spec,
    describe_settings,
    setting_value,
)

Reason = Literal["differs", "turned_off"]


@dataclass(frozen=True)
class SwitchWatch:
    key: str
    label: str
    #: 지금 값·기본값 — 둘 다 「on」·「off」로 맞춘 값이다.
    value: str
    default: str
    #: 대상이 아니면 None.
    reason: Reason | None
    #: 마지막 변경(저장·지우기) 시각·운영자 id. 변경 이력이 없으면 None.
    changed_at: datetime | None
    changed_by_id: int | None
    #: 마지막 변경 뒤의 「이대로 둔다」. 없으면 None.
    confirmed_at: datetime | None
    confirmed_by: str | None

    @property
    def needs_confirm(self) -> bool:
        return self.reason is not None and self.confirmed_at is None


def _on_off(raw: str | None) -> str:
    return "on" if (raw or "").strip().lower() in _SWITCH_ON else "off"


def alert_after() -> timedelta:
    """대상이 되기까지의 기간 — 운영 설정 값, 읽을 수 없으면 기본값."""

    raw = setting_value(SWITCH_ALERT_AFTER_DAYS)
    try:
        days = float((raw or "").strip() or DEFAULT_SWITCH_ALERT_AFTER_DAYS)
    except ValueError:
        days = float(DEFAULT_SWITCH_ALERT_AFTER_DAYS)
    if days != days or days < 0:  # NaN·음수
        days = float(DEFAULT_SWITCH_ALERT_AFTER_DAYS)
    return timedelta(days=days)


def watches() -> dict[str, SwitchWatch]:
    """스위치마다 감시 상태 — 키 → `SwitchWatch`."""

    from .models import RuntimeSettingChange

    views: dict[str, SettingView] = {v.key: v for v in describe_settings() if v.kind == "switch"}
    last: dict[str, RuntimeSettingChange] = {}
    ack: dict[str, RuntimeSettingChange] = {}
    rows = (
        RuntimeSettingChange.objects.filter(key__in=views)
        .select_related("operator")
        .order_by("changed_at", "id")
    )
    for change in rows:
        if change.action == RuntimeSettingChange.Action.ACK:
            ack[change.key] = change
        else:
            last[change.key] = change
            ack.pop(change.key, None)  # 새 변경이 오면 앞의 확인은 효력을 잃는다.

    result: dict[str, SwitchWatch] = {}
    for key, view in views.items():
        value = _on_off(view.value if view.value is not None else view.default)
        default = _on_off(view.default)
        change = last.get(key)
        reason: Reason | None = None
        if change is not None:
            if value != default:
                reason = "differs"
            elif value == "off" and _on_off(change.before) == "on":
                reason = "turned_off"
        confirmed = ack.get(key)
        result[key] = SwitchWatch(
            key=key,
            label=view.label,
            value=value,
            default=default,
            reason=reason,
            changed_at=change.changed_at if change else None,
            changed_by_id=change.operator_id if change else None,
            confirmed_at=confirmed.changed_at if confirmed else None,
            confirmed_by=confirmed.operator.username if confirmed else None,
        )
    return result


def due(now: datetime) -> list[SwitchWatch]:
    """지금 알려야 할 스위치 — 대상이고, 확인되지 않았고, 마지막 변경 뒤 N 일이 지났다."""

    wait = alert_after()
    return [
        w
        for w in watches().values()
        if w.needs_confirm and w.changed_at is not None and now - w.changed_at >= wait
    ]


def confirm_switch(key: str, *, operator: AbstractBaseUser) -> bool:
    """「이대로 둔다」 — 대상이고 아직 확인하지 않은 스위치만 기록한다. 기록하면 `True`."""

    from .models import RuntimeSettingChange

    if _spec(key).kind != "switch":
        raise RuntimeSettingError("스위치 설정만 확인할 수 있습니다.", "not_switch")
    with transaction.atomic():
        watch = watches()[key]
        if not watch.needs_confirm:
            return False
        RuntimeSettingChange.objects.create(
            operator=operator,
            key=key,
            action=RuntimeSettingChange.Action.ACK,
            before=watch.value,
            after=watch.value,
            changed_at=Clock.now(),
        )
    return True
