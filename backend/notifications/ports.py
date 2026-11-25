"""알림 앱(공유층)이 기능 앱에 묻는 자리 — 기능 앱이 `AppConfig.ready()` 에서 올린다(`core.registry`).

알림의 `context` 는 만든 때의 사실이다. 목록 화면이 「지금」을 말해야 하는 값은 그 일을 아는 앱만 알고,
공유층은 그 앱을 import 하지 않고 여기 자리만 둔다.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping
from dataclasses import dataclass

from core.registry import Slot


@dataclass(frozen=True)
class ProblemStatus:
    """한 사람이 한 강의실 문제에서 지금 서 있는 자리."""

    passed: bool
    attempt_count: int


#: `classroom.notification_problem_status.problem_statuses_for` — (받는 사람 pk, 문제 pk 들) → 문제 pk 별 상태.
#: **그 사람 자신의 시도가 있는 문제만** 답한다 — 나머지는 키 자체가 없다.
CLASSROOM_PROBLEM_STATUSES: Slot[Callable[[int, Collection[int]], Mapping[int, ProblemStatus]]] = Slot(
    "강의실 문제의 지금 상태", "classroom.apps"
)


#: `classroom.notification_problem_status.transfer_pending_class_ids` — (받는 사람 pk, 클래스 pk 들) → 그 사람 앞으로
#: **지금 답을 기다리는** 소유권 이전 요청이 있는 클래스 pk 들(#1435).
CLASSROOM_TRANSFER_PENDING: Slot[Callable[[int, Collection[int]], Collection[int]]] = Slot(
    "강의실 소유권 이전 요청의 지금 상태", "classroom.apps"
)
