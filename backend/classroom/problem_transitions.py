"""Problem 상태 전이 표 — 초안 → 열림, 열림 → 숨김, 숨김 → 열림 하나씩,
그리고 그 표가 전이를 직접 실행한다 (#440·#468, spec #432/#461,
`contests.transitions`(#255)와 같은 모양의 선언).

**Contest 표의 무게를 그대로 옮기지 않는다.** Problem 에는 시간 기반 스캔
전이가 없다 — 셋 다 강사의 명시적 행위(`POST .../open`·`.../hide`·
`.../reopen`, 문제 만들기의 "바로 연다")로만 일어난다. 그래서
`ScanContestTransition`/스캔 등록부 검증/mermaid 다이어그램 같은 장치는
여기 없다 — 이 표가 답하는 것은 「지금 이 전이를 부를 수 있는가, 아니라면
왜 막혔는가」뿐이다.

**막힌 이유는 우선순위가 있다** — 보관 → 필수 항목 없음. 클래스가 보관되면
그 자체로 아무 전이도 못 하므로(`classroom.instructor_scope.problem_scope`,
#463) 필수 항목이 있고 없고는 뜻이 없어진다. **다만 이 우선순위는
`available_transitions`(화면이 미리 읽는 자리)만의 것이다** — `execute_transition`
은 보관을 아예 모른다: 그 확인은 라우트 첫 줄의 강사 범위 호출이 이미 끝내고
왔다는 전제 위에 선다. 그래서 실행이 실제로 거절하는 이유(상태·필수 항목)와
화면이 미리 보여준 이유가 갈릴 자리가 없다 — 둘 다 `PROBLEM_TRANSITIONS`
하나를 읽는다.

**표가 전이를 직접 실행한다(#468).** 예전에는 호출부(`classroom.api`)가
`assert_transition_from_state`·`assert_has_required_item`을 따로 부른 뒤
`problem.status = edge.to_state; problem.save(...)`를 열기·숨기기·다시 열기
세 라우트에 각각 다시 적었다. 지금은 `execute_transition(name, problem)`
하나가 상태 확인 → 필수 항목 확인 → 상태 쓰기 → 저장까지 끝내고, 거절
문구도 간선(`ProblemTransition.wrong_state_message`)에 있다 — 라우트는
문구를 다시 타이핑하지 않는다.

**전이를 하나 더할 때 고칠 곳은 딱 둘이다 — 표 한 줄과 라우트 하나.**
① `PROBLEM_TRANSITIONS`에 간선(`from_state`·`to_state`, 필요하면
`requires_required_item`과 `wrong_state_message`)을 하나 적는다. ②
`classroom.api`에 `POST .../{그 이름}` 라우트를 하나 더해 첫 줄에서 강사
범위(`instructor_scope.problem_scope(..., write=True)`)를 열고
`execute_transition("그 이름", problem)`을 부른다. `execute_transition`
자신도 `available_transitions`도 고치지 않는다 — 둘 다 표를 읽을 뿐이라
새 간선을 저절로 안다.

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

#: 필수 항목이 하나도 없는 문제를 열려고 할 때의 문구 — 문제 만들기의
#: "바로 연다"(`classroom.api.create_problem`)와 `execute_transition`의
#: open·reopen 두 자리가 예전에는 이 문장을 각자 들고 있었다(#468 AC "여러
#: 곳에 복사돼 있던 것도 한 곳이 된다").
NO_REQUIRED_ITEM_MESSAGE = "필수 항목이 하나도 없는 문제는 열 수 없습니다."


@dataclass(frozen=True)
class ProblemTransition:
    name: str
    from_state: str
    to_state: str
    #: 이 전이가 필수 체크리스트 항목을 요구하는가 — OPEN으로 가는 두 전이
    #: (초안→열림, 숨김→열림)만 그렇다. HIDDEN으로 가는 전이(열림→숨김)는
    #: 요구하지 않는다 — 이미 있던 항목을 그대로 들고 숨는 것뿐이다.
    requires_required_item: bool = False
    #: 지금 상태에서 부를 수 없을 때(`from_state`가 안 맞을 때) 낼 문구 —
    #: `execute_transition`이 그대로 싣는다.
    wrong_state_message: str = ""


#: 이름 → 간선. 지금 그래프는 상태마다 나가는 간선이 정확히 하나씩이라
#: (초안은 열림으로만, 열림은 숨김으로만, 숨김은 열림으로만) 상태 하나를
#: 넣으면 `available_transitions`가 언제나 원소 하나짜리 목록을 돌려준다 —
#: 갈래가 늘어도 이 표만 고치면 된다.
PROBLEM_TRANSITIONS: dict[str, ProblemTransition] = {
    "open": ProblemTransition(
        name="open",
        from_state=Problem.Status.DRAFT,
        to_state=Problem.Status.OPEN,
        requires_required_item=True,
        wrong_state_message="초안만 열 수 있습니다.",
    ),
    "hide": ProblemTransition(
        name="hide",
        from_state=Problem.Status.OPEN,
        to_state=Problem.Status.HIDDEN,
        wrong_state_message="열린 문제만 숨길 수 있습니다.",
    ),
    "reopen": ProblemTransition(
        name="reopen",
        from_state=Problem.Status.HIDDEN,
        to_state=Problem.Status.OPEN,
        requires_required_item=True,
        wrong_state_message="숨긴 문제만 다시 열 수 있습니다.",
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


def execute_transition(name: str, problem: Problem) -> Problem:
    """`name` 전이를 지금 상태에서 실행한다 — 상태 확인 → 필수 항목 확인 →
    상태 쓰기 → 저장까지 표가 갖는다(#468). 호출부(`classroom.api`)는 강사
    범위(`instructor_scope.problem_scope(..., write=True)`)로 보관 확인까지
    끝낸 뒤 이 함수 하나만 부른다 — 그 뒤로 거절 문구의 유일한 출처는
    `PROBLEM_TRANSITIONS`다.

    보관을 이 함수가 다시 보지 않는 이유는 모듈 docstring에 있다 — 화면이
    미리 읽는 `available_transitions`와 실행이 같은 표를 읽으므로 "지금 막힌
    이유"와 "실제로 거절하는 이유"가 갈릴 수 없다."""

    edge = PROBLEM_TRANSITIONS[name]
    if problem.status != edge.from_state:
        raise HttpError(400, edge.wrong_state_message)
    if edge.requires_required_item and not has_required_item(problem):
        raise HttpError(400, NO_REQUIRED_ITEM_MESSAGE)

    problem.status = edge.to_state
    problem.save(update_fields=["status", "updated_at"])
    return problem


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
