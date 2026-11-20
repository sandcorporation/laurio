"""선정 앱이 위 앱(인수인계)에 맡기는 자리 — #1086, `core.registry.Slot` 꼴.

`handovers` 는 `awards.Award` 를 FK 로 가리키므로 선정 위에 선다. 선정이 Handover 를 import 해 만들면 둘이 한 순환이
된다. 그래서 `handovers.apps` 가 만드는 함수를 올리고 선정은 꺼내 부른다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING

from core.registry import Slot

if TYPE_CHECKING:
    from .models import Award

#: `handovers.services.open_handover` — 유료 공모전의 선정과 함께 인수인계를 연다(#14, #417). 같은 트랜잭션 안에서 부른다.
OPEN_HANDOVER: Slot[Callable[["Award", datetime], None]] = Slot("인수인계 열기", "handovers.apps")
