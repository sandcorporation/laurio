"""공동 강사 초대 — 만들고, 미리 보고, 수락한다 (#561, spec #558, ADR-0055).

`CONTEXT.md` 「공동 강사」·「공동 강사 초대」가 낱말의 뜻이다. 이 모듈은 화면 API
(`classroom.api`)가 부르는 일만 든다 — 연결된 앱(MCP)에는 초대 도구가 없다(ADR-0055
「결과」: 초대 링크는 권한 그 자체라 AI 도구가 만들지 않게 한다).

**초대는 1회용이다.** 수락은 한 트랜잭션에서 초대 행을 잠그고(`select_for_update`)
「아직 대기인가」를 다시 확인한 뒤에야 공동 강사 행을 만든다 — 같은 링크를 두 사람이
동시에 눌러도 한 사람만 공동 강사가 된다. 이미 그 클래스의 강사인 사람(소유자 포함)의
수락은 409 이고 초대는 쓰이지 않는다 — 다른 사람에게 줄 수 있게 남는다.

**보관과 무관하다.** 사람을 들이는 일은 클래스의 존폐 쪽이라 보관된 클래스에서도
만들고, 보고, 취소하고, 수락한다(`CONTEXT.md` 「공동 강사」).

**보는 것과 취소도 강사 누구나다**(#562) — 클래스 관리의 「강사」 영역이 강사 목록
(`roster`)과 대기 중인 초대(`pending_invites`)를 보여 주고, 누가 만든 초대든 취소한다
(`cancel_invite`). 취소는 행을 지우지 않고 시각을 찍는다 — 링크를 연 사람이 「취소된
초대」라는 사실을 볼 수 있어야 해서다.

**떠나는 길은 셋이고 정리는 하나다**(#563). 공동 강사가 스스로 떠나기(`leave`), 소유자의
내보내기(`remove_by_owner`), 탈퇴(`leave_all_on_withdrawal`, `accounts.signals.user_withdrawn`)
모두 `depart` 하나를 한 트랜잭션에서 탄다 — 공동 강사 자리를 지우고, 그 사람의 참여자 행이
있으면 내보낸 참여자로 표시하고(점검용 시도가 달성률에 섞이지 않게, 그 시도는 문제 삭제를
막는다 — ADR-0050), 그 사람이 만든 대기 중 초대를 취소하고, 그 사람에게 온 대기 중 소유권 이전
요청을 지운다(#564). 소유자는 떠날 수 없다(넘기거나 보관·삭제한다). 보관과 무관하다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Q
from ninja.errors import HttpError

from core.clock import Clock

from .class_authoring import reject_banned_name
from .instructors import is_instructor, is_owner
from .models import (
    CO_INSTRUCTOR_INVITE_TTL_DAYS,
    Class,
    ClassCoInstructor,
    ClassMember,
    CoInstructorInvite,
    OwnershipTransfer,
)
from .ownership_transfers import pending_q as ownership_pending_q

#: 이미 그 클래스의 강사인 사람이 수락하려 할 때 — 미리보기 화면도 같은 말을 쓴다.
ALREADY_INSTRUCTOR_MESSAGE = "이미 이 클래스의 강사입니다."

#: 소유자가 떠나려 할 때 — 화면이 같은 안내를 미리 보여 준다.
OWNER_CANNOT_LEAVE_MESSAGE = (
    "소유자는 클래스를 떠날 수 없습니다. 공동 강사에게 소유권을 넘기면 공동 강사가 되어 떠날 수 있고, "
    "수업을 끝내려면 클래스를 보관하거나 삭제하세요."
)

#: 쓸 수 없는 초대의 상태별 문장 — 초대한 사람에게 새 링크를 부탁하라고 말한다.
_NOT_PENDING_MESSAGES = {
    CoInstructorInvite.Status.ACCEPTED: "이미 쓰인 초대입니다. 초대한 강사에게 새 링크를 부탁하세요.",
    CoInstructorInvite.Status.EXPIRED: "만료된 초대입니다. 초대한 강사에게 새 링크를 부탁하세요.",
    CoInstructorInvite.Status.CANCELLED: "취소된 초대입니다. 초대한 강사에게 새 링크를 부탁하세요.",
}


def create_invite(class_obj: Class, created_by_id: int) -> CoInstructorInvite:
    """강사(소유자 또는 공동 강사)가 초대를 하나 만든다 — 여러 개가 동시에 열려 있어도 된다."""

    now = Clock.now()
    return CoInstructorInvite.objects.create(
        classroom=class_obj,
        created_by_id=created_by_id,
        created_at=now,
        expires_at=now + timedelta(days=CO_INSTRUCTOR_INVITE_TTL_DAYS),
    )


def invite_or_404(token: str) -> CoInstructorInvite:
    try:
        return CoInstructorInvite.objects.select_related("classroom").get(token=token)
    except CoInstructorInvite.DoesNotExist as exc:
        raise HttpError(404, "이 초대 링크는 없는 주소입니다.") from exc


def not_pending_message(status: str) -> str | None:
    return _NOT_PENDING_MESSAGES.get(status)


def instructor_names(class_obj: Class) -> list[str]:
    """미리보기가 보여 줄 강사 이름들 — 소유자 먼저, 그다음 공동 강사를 수락한 순서로.
    빈 이름은 뺀다(소유자 이름이 생기기 전에 만든 클래스)."""

    names = [class_obj.instructor_display_name]
    names += list(class_obj.co_instructors.values_list("display_name", flat=True))
    return [name for name in names if name]


def roster(class_obj: Class, viewer_id: int) -> list[dict]:
    """강사 목록 — 줄마다 강사 이름·역할·수락한 때·부른 사람 자신인가. 소유자 먼저(수락한 때
    없음), 그다음 공동 강사를 수락한 순서로. 소유자의 이름이 비어 있으면 빈 문자열 그대로다 —
    화면이 고른다."""

    rows = [
        {
            "display_name": class_obj.instructor_display_name,
            "role": "owner",
            "accepted_at": None,
            "is_me": is_owner(class_obj, viewer_id),
        }
    ]
    rows += [
        {
            "co_instructor_id": row.id,
            "display_name": row.display_name,
            "role": "co_instructor",
            "accepted_at": row.accepted_at,
            "is_me": row.user_id == viewer_id,
        }
        for row in class_obj.co_instructors.all()
    ]
    return rows


def _pending_q(now):
    """대기 중인 초대 — 수락되지 않았고, 취소되지 않았고, 만료되지 않았다(`status_at` 의 대기와 같다)."""

    return Q(accepted_at__isnull=True, cancelled_at__isnull=True, expires_at__gt=now)


def pending_invites(class_obj: Class) -> list[tuple[CoInstructorInvite, str]]:
    """아직 쓰이지 않은 초대와 만든 사람의 강사 이름 — 새것 먼저. 수락·취소·만료는 빠진다."""

    now = Clock.now()
    invites = class_obj.co_instructor_invites.filter(_pending_q(now))
    # 만든 사람의 이름은 강사 목록에서 한 번에 찾는다 — 초대마다 묻지 않는다.
    names = dict(class_obj.co_instructors.values_list("user_id", "display_name"))

    def name_of(user_id: int) -> str:
        return class_obj.instructor_display_name if is_owner(class_obj, user_id) else names.get(user_id, "")

    return [(invite, name_of(invite.created_by_id)) for invite in invites]


def cancel_invite(class_obj: Class, invite_id: int) -> None:
    """대기 중인 초대를 취소한다. 이 클래스의 초대가 아니면 404, 이미 쓰였거나 만료·취소됐으면
    409(그 상태의 문장) — 수락과 같은 행 잠금으로, 수락과 취소가 겹쳐도 한쪽만 이긴다."""

    with transaction.atomic():
        invite = (
            CoInstructorInvite.objects.select_for_update()
            .filter(classroom_id=class_obj.id, id=invite_id)
            .first()
        )
        if invite is None:
            raise HttpError(404, "이 클래스에 그런 초대가 없습니다.")
        message = not_pending_message(invite.status_at(Clock.now()))
        if message is not None:
            raise HttpError(409, message)
        invite.cancelled_at = Clock.now()
        invite.save(update_fields=["cancelled_at"])


def accept_invite(token: str, user_id: int, display_name: str) -> Class:
    """초대를 쓰고 공동 강사가 된다. 거절 사유는 404(없는 토큰)·409(이미 강사)·
    410(쓰였거나 만료·취소)이다."""

    reject_banned_name(display_name)
    with transaction.atomic():
        try:
            invite = (
                CoInstructorInvite.objects.select_for_update()
                .select_related("classroom")
                .get(token=token)
            )
        except CoInstructorInvite.DoesNotExist as exc:
            raise HttpError(404, "이 초대 링크는 없는 주소입니다.") from exc

        now = Clock.now()
        message = not_pending_message(invite.status_at(now))
        if message is not None:
            raise HttpError(410, message)

        class_obj = invite.classroom
        if is_instructor(class_obj, user_id):
            raise HttpError(409, ALREADY_INSTRUCTOR_MESSAGE)

        try:
            # 같은 사람이 같은 클래스의 다른 초대 둘을 동시에 수락하면 위 확인을 둘 다
            # 지날 수 있다 — 유일 제약이 마지막 문이다. 저장점 안에서 만들어 실패해도
            # 이 트랜잭션(초대 잠금)은 그대로 409 로 끝난다.
            with transaction.atomic():
                ClassCoInstructor.objects.create(
                    classroom=class_obj, user_id=user_id, display_name=display_name, accepted_at=now
                )
        except IntegrityError as exc:
            raise HttpError(409, ALREADY_INSTRUCTOR_MESSAGE) from exc

        invite.accepted_by_id = user_id
        invite.accepted_at = now
        invite.save(update_fields=["accepted_by", "accepted_at"])
    return class_obj


# --- 떠나기 (#563) -----------------------------------------------------------------


def depart(row: ClassCoInstructor) -> bool:
    """공동 강사 한 사람이 클래스에서 빠진다 — 세 길(떠나기·내보내기·탈퇴)이 모두 이 함수를
    탄다. 한 트랜잭션에서:

    1. 공동 강사 자리를 지운다 — 그 순간부터 「강사인가」가 거짓이라 강사 라우트가 404 다.
    2. 그 사람의 참여자 행이 있으면 내보낸 참여자로 표시한다(이미 내보냈으면 그대로). 강사일
       때 집계에서 빠지던 점검용 시도가 「지금 배우는 사람」으로 돌아오지 않게 하고, 그 시도는
       내보낸 참여자의 시도로 남아 문제 삭제를 막는다(ADR-0050).
    3. 그 사람이 만든 대기 중 초대를 취소한다 — 더 믿지 않는 사람이 나눠 준 링크로 누가
       들어오지 않게. 수락과 같은 행을 `UPDATE` 가 잠그므로 겹친 수락은 한쪽만 이긴다.
    4. 그 사람에게 온 대기 중 소유권 이전 요청을 지운다(#564) — 받는 사람이 떠나면 요청이
       사라진다(`CONTEXT.md` 「소유권 이전」).

    공동 강사 줄을 먼저 잠근다 — 이전 수락(`ownership_transfers.accept`)과 같은 잠금 순서라
    둘이 겹쳐도 한쪽만 이긴다. 줄이 이미 없으면(겹친 수락이 줄을 바꿨거나 먼저 떠났다) 아무것도
    하지 않고 거짓을 돌려준다."""

    now = Clock.now()
    with transaction.atomic():
        if ClassCoInstructor.objects.select_for_update().filter(id=row.id).first() is None:
            return False
        OwnershipTransfer.objects.filter(
            ownership_pending_q(now), classroom_id=row.classroom_id, recipient_id=row.user_id
        ).delete()
        ClassCoInstructor.objects.filter(id=row.id).delete()
        ClassMember.objects.filter(
            classroom_id=row.classroom_id, user_id=row.user_id, expelled_at__isnull=True
        ).update(expelled_at=now)
        CoInstructorInvite.objects.filter(
            _pending_q(now), classroom_id=row.classroom_id, created_by_id=row.user_id
        ).update(cancelled_at=now)
    return True


def leave(class_obj: Class, user_id: int) -> None:
    """부른 강사가 스스로 떠난다. 소유자는 409 — 넘기거나 보관·삭제한다."""

    if is_owner(class_obj, user_id):
        raise HttpError(409, OWNER_CANNOT_LEAVE_MESSAGE)
    row = ClassCoInstructor.objects.filter(classroom_id=class_obj.id, user_id=user_id).first()
    if row is not None:
        depart(row)


def remove_by_owner(class_obj: Class, co_instructor_id: int) -> None:
    """소유자가 공동 강사 한 사람을 내보낸다. 이 클래스의 공동 강사 줄이 아니면 404."""

    row = ClassCoInstructor.objects.filter(classroom_id=class_obj.id, id=co_instructor_id).first()
    if row is None or not depart(row):
        raise HttpError(404, "이 클래스에 그런 공동 강사가 없습니다.")


def leave_all_on_withdrawal(sender, user, **kwargs) -> None:
    """탈퇴하면 공동 강사인 클래스 전부에서 빠진다(`accounts.signals.user_withdrawn`). 탈퇴
    트랜잭션 안에서 불린다 — 여기서 실패하면 탈퇴도 되돌아간다. 소유한 클래스는 건드리지
    않는다(보관하지 않은 소유 클래스는 탈퇴를 막고, 보관한 것은 소유자에게 남는다)."""

    for row in ClassCoInstructor.objects.filter(user_id=user.id):
        depart(row)
