"""Problem 상태 전이 표 — 초안 → 열림, 열림 → 숨김, 숨김 → 열림 하나씩
(#440, spec #432, `contests.transitions`(#255)와 같은 모양의 선언).

**Contest 표의 무게를 그대로 옮기지 않는다.** Problem 에는 시간 기반 스캔
전이가 없다 — 셋 다 강사의 명시적 행위(`POST .../open`·`.../hide`·
`.../reopen`, 문제 만들기의 "바로 연다")로만 일어난다. 그래서
`ScanContestTransition`/스캔 등록부 검증/mermaid 다이어그램 같은 장치는
여기 없다 — 이 표가 답하는 것은 「지금 이 전이를 부를 수 있는가, 아니라면
왜 막혔는가」뿐이다.

**막힌 이유는 우선순위가 있다** — 보관 → 필수 항목 없음. 클래스가 보관되면
그 자체로 아무 전이도 못 하므로(`classroom.participation.
assert_class_mutable`, #438) 필수 항목이 있고 없고는 뜻이 없어진다.

**전이가 아니라 불변식도 하나 있다.** 열린·숨긴 문제는 필수 항목을 하나
이상 유지해야 한다 — 마지막 필수 항목을 지우거나 필수를 해제하면 그 순간
통과가 정의되지 않아 모든 참여자의 통과가 사라진다. 이것은 상태를 바꾸는
전이가 아니라 체크리스트 변경(`update_checklist_item`·`delete_checklist_item`)에
거는 가드라 이 표의 간선이 아니라 별도 함수(`assert_required_item_floor`)로
둔다 — Contest 표의 「생성은 그래프 밖이다」와 같은 종류의 경계다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ninja.errors import HttpError

from .models import Class, Problem

#: 전이가 막혔을 때의 이유 — 강사용 문제 응답의 `available_transitions`와
#: 참여 정책 모듈의 `SUBMIT_BLOCKED_ARCHIVED`가 같은 문자열("archived")을
#: 쓴다 — 화면이 이미 아는 뜻을 새로 배우지 않는다.
BLOCKED_ARCHIVED = "archived"
BLOCKED_NO_REQUIRED_ITEM = "no_required_item"


@dataclass(frozen=True)
class ProblemTransition:
    name: str
    from_state: str
    to_state: str
    #: 이 전이가 필수 체크리스트 항목을 요구하는가 — OPEN으로 가는 두 전이
    #: (초안→열림, 숨김→열림)만 그렇다. HIDDEN으로 가는 전이(열림→숨김)는
    #: 요구하지 않는다 — 이미 있던 항목을 그대로 들고 숨는 것뿐이다.
    requires_required_item: bool = False


#: 이름 → 간선. 지금 그래프는 상태마다 나가는 간선이 정확히 하나씩이라
#: (초안은 열림으로만, 열림은 숨김으로만, 숨김은 열림으로만) 상태 하나를
#: 넣으면 `available_transitions`가 언제나 원소 하나짜리 목록을 돌려준다 —
#: 갈래가 늘어도 이 표만 고치면 된다.
PROBLEM_TRANSITIONS: dict[str, ProblemTransition] = {
    "open": ProblemTransition(
        name="open", from_state=Problem.Status.DRAFT, to_state=Problem.Status.OPEN, requires_required_item=True
    ),
    "hide": ProblemTransition(name="hide", from_state=Problem.Status.OPEN, to_state=Problem.Status.HIDDEN),
    "reopen": ProblemTransition(
        name="reopen", from_state=Problem.Status.HIDDEN, to_state=Problem.Status.OPEN, requires_required_item=True
    ),
}

_renamed = {key: edge.name for key, edge in PROBLEM_TRANSITIONS.items() if edge.name != key}
if _renamed:
    # contests.transitions의 같은 가드와 같은 이유 — 키와 name이 갈리면
    # 오류 메시지·화면이 서로 다른 이름을 말하게 된다.
    raise RuntimeError(f"PROBLEM_TRANSITIONS의 키와 name이 다르다: {_renamed}")


def has_required_item(problem: Problem) -> bool:
    return problem.checklist_items.filter(required=True).exists()


@dataclass(frozen=True)
class TransitionAvailability:
    name: str
    to_state: str
    #: `None`이면 지금 바로 부를 수 있다. 아니면 "archived"|"no_required_item".
    blocked_reason: str | None = None


def _blocked_reason(edge: ProblemTransition, *, problem: Problem, class_obj: Class) -> str | None:
    if class_obj.archived_at is not None:
        return BLOCKED_ARCHIVED
    if edge.requires_required_item and not has_required_item(problem):
        return BLOCKED_NO_REQUIRED_ITEM
    return None


def available_transitions(problem: Problem, class_obj: Class) -> list[TransitionAvailability]:
    """이 문제가 지금 상태에서 나갈 수 있는 전이들과 각자 막힌 이유(#440) —
    강사용 문제 응답이 그대로 싣는다. 수정 화면은 이 목록으로 버튼과 안내를
    그리고, 화면 안에서 상태별 버튼을 다시 계산하지 않는다."""

    return [
        TransitionAvailability(
            name=name, to_state=edge.to_state, blocked_reason=_blocked_reason(edge, problem=problem, class_obj=class_obj)
        )
        for name, edge in PROBLEM_TRANSITIONS.items()
        if edge.from_state == problem.status
    ]


def assert_transition_from_state(name: str, problem: Problem, *, wrong_state_message: str) -> None:
    """`name` 전이가 지금 상태에서 부를 수 있는 것인지 확인한다 — 아니면
    `wrong_state_message`로 400. 실제 문구는 호출부(`classroom.api`)가 이미
    참여자에게 보여 온 것을 그대로 넘긴다 — 이 표는 from_state만 판정한다."""

    edge = PROBLEM_TRANSITIONS[name]
    if problem.status != edge.from_state:
        raise HttpError(400, wrong_state_message)


def assert_has_required_item(problem: Problem, *, message: str) -> None:
    if not has_required_item(problem):
        raise HttpError(400, message)


def required_item_floor_message(status: str) -> str:
    label = "열린" if status == Problem.Status.OPEN else "숨긴"
    return f"{label} 문제는 필수 항목이 하나 이상 있어야 합니다."


def assert_required_item_floor(problem: Problem, *, remaining_required_count: int) -> None:
    """열린·숨긴 문제가 필수 항목을 전부 잃는 변경을 거절한다(#440 AC) —
    초안은 아직 아무도 안 보므로 자유롭게 비울 수 있다."""

    if problem.status == Problem.Status.DRAFT:
        return
    if remaining_required_count > 0:
        return
    raise HttpError(422, required_item_floor_message(problem.status))
