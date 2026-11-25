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


#: `classroom.notification_problem_status.transfer_states_for` — (받는 사람 pk, 이전 요청 pk 들) → 요청 pk 별 지금의
#: 상태(`pending`·`accepted`·`declined`·`cancelled`·`expired`, #1441). 그 사람 앞으로 온 요청만 답한다.
CLASSROOM_TRANSFER_STATES: Slot[Callable[[int, Collection[int]], Mapping[int, str]]] = Slot(
    "강의실 소유권 이전 요청의 지금 상태", "classroom.apps"
)


#: `classroom.notification_problem_status.classes_with_pending_transfer_for` — (받는 사람 pk, 클래스 pk 들) → 그 사람
#: 앞으로 지금 대기 중인 소유권 이전 요청이 있는 클래스 pk 들(#1459 ①). 요청에 잇지 못한 옛 알림이 「끝남」인지
#: 「모름」인지 가른다 — 대기 요청이 없으면 그 알림의 요청도 대기일 수 없다.
CLASSROOM_PENDING_TRANSFER_CLASSES: Slot[Callable[[int, Collection[int]], Collection[int]]] = Slot(
    "강의실 소유권 이전 요청이 대기 중인 클래스", "classroom.apps"
)
