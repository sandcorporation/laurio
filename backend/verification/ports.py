"""본인확인 앱이 위 층에 묻는 자리 — 위 층 앱이 `AppConfig.ready()` 에서 올린다(#1102, `core.registry` 의 모양)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from core.registry import Slots

if TYPE_CHECKING:
    from django.db.models import Expression

#: 휴면 판정의 「마지막 행위 시각」 후보 — 앱 이름 → `Verification` 에서 걷는 식들(개최·제출 등). 앱 이름 차례로 붙인다.
LAST_ACTIVITY: Slots[Callable[[], "tuple[Expression, ...]"]] = Slots("마지막 행위 시각")


def last_activity_expressions() -> tuple[Expression, ...]:
    return tuple(e for _, make in sorted(LAST_ACTIVITY.as_dict().items()) for e in make())
