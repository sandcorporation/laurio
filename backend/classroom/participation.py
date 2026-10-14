"""참여 정책 모듈 — 「누가 이 클래스·문제에 무엇을 할 수 있나」를 한 곳에서
답한다(#438/#439, spec #432).

**강사 쪽 판정**(`assert_class_mutable`)은 이 클래스에 새 내용을 만들거나 바꿀 수
있는가이고, 보관되면 거절한다 — 보관은 **읽기 전용**이라는 뜻이다(CONTEXT.md
「클래스」). 막는 것: 문제 만들기·수정·열기·숨기기·다시 열기·삭제, 체크리스트
추가·수정·삭제·순서 바꾸기, 문제 순서 바꾸기, 템플릿 가져오기(대상 클래스 기준),
다른 클래스 문제 복사해 넣기(대상 클래스 기준). 가입·제출·이름 바꾸기는 이미 각
엔드포인트가 따로 막고 있어 이 함수를 거치지 않는다.

열어 두는 것(이 함수를 부르지 않는 곳): 읽기 전부, 클래스 설정(이름·강사 이름·키·
기본 모델), 보관 되돌리기, 복사해서 새로 열기, 클래스 삭제, 클래스 템플릿
공개, 보관된 클래스의 문제를 다른 진행 중 클래스로 가져가기(원본 기준으로는
막지 않는다 — 읽기는 보관 뒤에도 남는다).

**참여자 쪽 판정**(#439)은 볼 수 있나(`visible_problems_queryset`)와 낼 수 있나
(`participant_submit_blocked_reason`/`can_submit`)로 나뉜다. 낼 수 없는 이유는
하나만 돌려준다 — 우선순위는 **보관 → 내보냄 → 숨김**이다(강사가 학생 화면으로
보는 경우는 이 우선순위 밖이다: `viewing_as_instructor`는 아예 다른 사람 — 진짜
참여자가 아니다 — 이라 호출부가 따로 판단한다). 참여자 문제 목록 질의, 문제
상세, 제출 만들기, 이름 바꾸기, 강의실 소스 업로드 presign(`submissions.
resolvers.SubmissionTargetStateResolver`, 앱 경계 예외로 부른다)이 이 판정을
쓴다.
"""

from __future__ import annotations

from django.db.models import Q, QuerySet
from ninja.errors import HttpError

from .models import Class, ClassMember, ClassroomSubmission, Problem

#: 강사 전용 엔드포인트가 보관된 클래스에서 거절할 때 쓰는 공통 문구 —
#: 가입·제출이 이미 쓰는 것과 같은 형식(간결한 이유 한 문장)을 따른다.
CLASS_ARCHIVED_MESSAGE = "이 클래스는 보관되어 더 이상 바꿀 수 없습니다."


def assert_class_mutable(class_obj: Class) -> None:
    """이 클래스에 새 내용을 만들거나 바꿀 수 있는가 — 보관되면 403으로
    거절한다(#438). 대상이 강사 자신의 클래스인지는 호출부가
    `classroom.instructor_scope.class_scope`/`problem_scope`로 이미
    확인했다는 전제 위에 선다(#463) — 이 함수는 소유권이 아니라 보관
    여부만 보고, 그 두 함수가 `write=True`일 때만 이 함수를 부른다."""

    if class_obj.archived_at is not None:
        raise HttpError(403, CLASS_ARCHIVED_MESSAGE)


#: 참여자가 지금 이 클래스·문제에 새로 낼 수 없는 이유(#439) — 우선순위는
#: 보관 → 내보냄 → 숨김이다. 강사가 학생 화면으로 보는 경우("강사 보기")는
#: 이 셋과 겹치지 않는다 — 진짜 참여자가 아니므로 호출부(`classroom.api.
#: get_my_problem`)가 이 값들과 무관하게 직접 채운다.
SUBMIT_BLOCKED_ARCHIVED = "archived"
SUBMIT_BLOCKED_EXPELLED = "expelled"
SUBMIT_BLOCKED_HIDDEN = "hidden"
SUBMIT_BLOCKED_VIEWING_AS_INSTRUCTOR = "viewing_as_instructor"


def participant_membership_blocked_reason(class_obj: Class, member: ClassMember) -> str | None:
    """가입 자체는 살아 있지만(`ClassMember` 행이 있지만) 더 이상 이 클래스에
    새로 낼 수 없는 이유 — 보관 → 내보냄 순서다. 문제 하나를 특정하지 않는
    자리(이름 바꾸기)가 쓴다. `participant_submit_blocked_reason`이 이 함수
    위에 「숨김」 한 단계를 더 얹는다."""

    if class_obj.archived_at is not None:
        return SUBMIT_BLOCKED_ARCHIVED
    if member.expelled_at is not None:
        return SUBMIT_BLOCKED_EXPELLED
    return None


def participant_submit_blocked_reason(
    class_obj: Class, member: ClassMember, problem: Problem
) -> str | None:
    """참여자가 지금 이 문제에 새로 낼 수 없는 이유 하나, 없으면 `None`(#439).
    순서는 보관 → 내보냄 → 숨김이다 — 스캔 후보·채점 직전 확인처럼 문제
    하나에 대한 판정이 아니라 화면·업로드 게이트가 쓰는 자리다."""

    reason = participant_membership_blocked_reason(class_obj, member)
    if reason is not None:
        return reason
    if problem.status == Problem.Status.HIDDEN:
        return SUBMIT_BLOCKED_HIDDEN
    return None


def instructor_can_submit(class_obj: Class, problem: Problem) -> bool:
    """그 클래스의 **강사**가 지금 이 문제에 낼 수 있는가(2026-09-17, #429 개정).

    참여자 판정과 갈라 두는 이유: 강사에게는 「내보냄」이 없고, 참여자 행이 아직
    없을 수도 있다(첫 제출이 그 자리에서 만든다 — `classroom.api.
    _get_submitting_member_or_404`).

    **상태는 보지 않는다**(2026-09-17) — 초안·열림·숨김 어디서든 강사는 자기
    문제를 내 본다(문제를 만들며 시험해 보는 것이 정상 절차다, #431이 이미 그
    전제 위에 서 있다). 막는 것은 **보관된 클래스** 하나뿐이다 — 보관은 읽기
    전용이라는 뜻이고(CONTEXT.md 「클래스」, #294/#438), 그 규칙은 강사에게도
    같다. 참여자 규칙은 한 글자도 바뀌지 않는다: 초안은 404, 숨김은 403이다."""

    del problem  # 상태를 보지 않는다 — 인자는 호출부의 읽기 흐름을 위해 남긴다
    return class_obj.archived_at is None


def can_submit(class_obj: Class, member: ClassMember, problem: Problem) -> bool:
    return participant_submit_blocked_reason(class_obj, member, problem) is None


def visible_problems_queryset(class_id: int, member: ClassMember) -> QuerySet[Problem]:
    """이 참여자에게 존재하는 문제들 — 열린 문제 전부 + 이 참여자가 한 번이라도
    낸 숨긴 문제(#405). 참여자 문제 목록(`list_my_problems`)과 문제 상세 존재
    판정(`_get_visible_problem_for_participant_or_404`)이 같은 질의를 써야
    「목록에 보이는 문제와 열어서 볼 수 있는 문제가 언제나 같다」(#439 AC)가
    성립한다 — 두 자리가 각자 조건을 다시 적으면 그 사이가 갈릴 수 있다."""

    submitted_problem_ids = ClassroomSubmission.objects.filter(member=member).values_list(
        "problem_id", flat=True
    )
    return Problem.objects.filter(classroom_id=class_id).filter(
        Q(status=Problem.Status.OPEN) | Q(status=Problem.Status.HIDDEN, id__in=submitted_problem_ids)
    )
