"""공동 강사 초대 — 만들고, 미리 보고, 수락한다 (#561, spec #558, ADR-0055).

`CONTEXT.md` 「공동 강사」·「공동 강사 초대」가 낱말의 뜻이다. 이 모듈은 화면 API
(`classroom.api`)가 부르는 일만 든다 — 연결된 앱(MCP)에는 초대 도구가 없다(ADR-0055
「결과」: 초대 링크는 권한 그 자체라 AI 도구가 만들지 않게 한다).

**초대는 1회용이다.** 수락은 한 트랜잭션에서 초대 행을 잠그고(`select_for_update`)
「아직 대기인가」를 다시 확인한 뒤에야 공동 강사 행을 만든다 — 같은 링크를 두 사람이
동시에 눌러도 한 사람만 공동 강사가 된다. 이미 그 클래스의 강사인 사람(소유자 포함)의
수락은 409 이고 초대는 쓰이지 않는다 — 다른 사람에게 줄 수 있게 남는다.

**보관과 무관하다.** 사람을 들이는 일은 클래스의 존폐 쪽이라 보관된 클래스에서도
만들고 수락한다(`CONTEXT.md` 「공동 강사」).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from ninja.errors import HttpError

from core.clock import Clock

from .class_authoring import reject_banned_name
from .instructors import is_instructor
from .models import CO_INSTRUCTOR_INVITE_TTL_DAYS, Class, ClassCoInstructor, CoInstructorInvite

#: 이미 그 클래스의 강사인 사람이 수락하려 할 때 — 미리보기 화면도 같은 말을 쓴다.
ALREADY_INSTRUCTOR_MESSAGE = "이미 이 클래스의 강사입니다."

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
