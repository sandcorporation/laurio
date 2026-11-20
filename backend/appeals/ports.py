"""이의 앱이 위 층에 묻는 자리 — 위 층 앱이 `AppConfig.ready()` 에서 올린다(#1086, `core.registry` 의 모양).

`distributions` 는 배분을 막는 이의(`Appeal`)를 읽는다. 이의 화면이 「이 이의가 배분을 막고 있나」를 묻으려고
`distributions` 를 import 하면 둘이 한 순환이 된다. 그래서 판정은 `distributions.apps` 가 이 자리에 올린다.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from core.registry import Slot

if TYPE_CHECKING:
    from appeals.models import Appeal

#: `distributions.services.is_holding_distribution`
DISTRIBUTION_HOLD: Slot[Callable[["Appeal"], bool]] = Slot("배분 보류 판정", "distributions.apps")


def is_holding_distribution(appeal: Appeal) -> bool:
    return DISTRIBUTION_HOLD.get()(appeal)
