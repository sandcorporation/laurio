"""강의실 모양 target_ref(`"classroom-submission:<problem_id>:<user_id>:<슬롯>"`)의 가시성 판정 — `submissions.resolvers` 에
등록한다(#1085). 공유층(`submissions`)이 강의실을 최상단에서 import 하지 않도록 강의실 앱이 이 판정을 들고 올린다.
"""

from __future__ import annotations

from storage.policy import TargetState, Visibility
from submissions.resolvers import DENY_TARGET
from submissions.target_refs import SOURCE_SLOT

from .instructors import is_instructor
from .models import ClassMember, Problem as ClassroomProblem
from .participation import can_submit, instructor_can_submit


def resolve_classroom_submission(parts: list[str]) -> TargetState:
    """강의실 모양(#286) — 마감도 Award도 Sponsor도 없어 "본인만"이 끝이다.

    `SOURCE_SLOT` 뿐이라 시연 영상·스크린샷·빌드 자산 분기가 아예 없다.
    Problem 존재를 확인하는 이유는 공모전 분기의 `Contest.objects.filter(...)`와
    같다 — 형식만 맞고 가리키는 대상이 없는 target_ref는 소유자 없는
    private로 fail-closed한다.

    **낼 수 있는 사람만 업로드 주소를 받는다**(#439) — Problem이 있어도
    그 사람이 지금 이 클래스·문제에 새로 낼 수 없으면(보관·내보냄·숨김,
    `classroom.participation.can_submit`) 같은 이유로 fail-closed한다.
    참여자가 아니면(`ClassMember` 행이 없으면) 애초에 판정할 자격이 없어
    역시 거절한다 — **다만 그 클래스의 강사는 예외다**(2026-09-17, #429
    개정): 강사는 상태(초안·열림·숨김)와 무관하게 자기 문제를 내 보므로,
    참여자 행이 아직 없어도(첫 제출이 그때 만든다) 업로드 주소를 받는다.
    보관된 클래스만 막는다. 안 그러면 소스 형식 문제에만 강사가 못 내는
    비대칭이 생긴다."""

    _, problem_id_raw, user_id_raw, slot = parts
    if slot != SOURCE_SLOT:
        return DENY_TARGET

    try:
        problem_id = int(problem_id_raw)
        user_id = int(user_id_raw)
    except ValueError:
        return DENY_TARGET

    problem = ClassroomProblem.objects.select_related("classroom").filter(id=problem_id).first()
    if problem is None:
        return DENY_TARGET

    if is_instructor(problem.classroom, user_id):
        # 강사는 참여자 행이 있든 없든 강사 기준으로 본다(2026-09-17) —
        # 상태(초안·열림·숨김)는 보지 않고 보관만 막는다. 행이 있다고
        # 참여자 규칙(숨김 403)에 걸리면 같은 사람이 같은 문제에 대해
        # 어제와 오늘 다른 답을 받는다.
        if not instructor_can_submit(problem.classroom, problem):
            return DENY_TARGET
    else:
        member = ClassMember.objects.filter(
            classroom=problem.classroom, user_id=user_id
        ).first()
        if member is None or not can_submit(problem.classroom, member, problem):
            return DENY_TARGET

    return TargetState(visibility=Visibility.PRIVATE, owner_id=user_id)
