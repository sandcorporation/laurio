"""소유권 이전 — 소유자가 요청하고, 받는 공동 강사가 수락하거나 거절한다 (#564, spec #558,
ADR-0055, `CONTEXT.md` 「소유권 이전」).

**받는 사람이 수락해야 넘어간다.** 수락은 한 트랜잭션이다(`accept`):

1. `Class.instructor` 가 받는 사람으로 바뀐다.
2. 받는 사람의 공동 강사 자리가 사라지고 넘긴 사람이 공동 강사가 된다 — 강사 이름은 각자의
   것을 들고 자리만 바꾼다(넘긴 사람의 `instructor_display_name` 이 그 사람의 공동 강사
   `display_name` 이 되고, 받는 사람의 공동 강사 이름이 `instructor_display_name` 이 된다).
   줄은 고쳐 쓰지 않고 새로 만든다 — 넘긴 사람이 옛 줄 id 로 겹쳐 보낸 내보내기가 자기 자신을
   가리키게 되지 않도록.
3. 채점 키(암호문·끝 네 자리·상태)를 비운다 — 키는 넘긴 사람의 비용이다. 예산·사용량·경고
   시각은 클래스의 기록이라 그대로다. 키가 빈 동안 낸 시도는 채점 대기 사유 「키」로 기다리다
   새 소유자가 키를 넣으면 채점된다(`classroom.pending_scoring`).

연결된 앱(ConnectedApp)은 계정의 것이라 건드리지 않는다 — 넘긴 사람의 앱은 그 사람이 이제
공동 강사로 할 수 있는 만큼만 한다.

**잠금 순서는 하나다 — 공동 강사 줄 → 이전 요청 → 클래스.** 수락은 받는 사람의 공동 강사
줄을 먼저 잠그고, 떠나기의 정리(`co_instructors.depart`)도 그 줄을 먼저 잠근 뒤 대기 요청을
지운다. 그래서 수락과 「받는 사람이 떠난다」가 겹쳐도 교착 없이 한쪽만 이긴다. 거절·취소는
요청 행 하나만 잠그고, 요청은 클래스 행을 잠가 「대기 하나」를 지킨다.

**보관과 무관하다** — 사람을 들이고 내보내고 넘기는 일은 클래스의 존폐 쪽이다.

**요청·수락·거절은 당사자에게 알린다**(#575) — 요청은 받는 사람에게, 수락·거절은 요청한 사람에게.
취소·만료는 알리지 않는다. 알림은 트랜잭션이 끝난(커밋된) 뒤 `notify_safely` 로 보낸다 — 알림이
실패해도 이전은 그대로이고, 롤백된 요청이 알림을 남기지도 않는다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from ninja.errors import HttpError

from core.clock import Clock
from notifications.models import NotificationType
from notifications.services import notify_safely

from .instructor_scope import OWNER_ONLY_MESSAGE
from .instructors import is_owner
from .models import OWNERSHIP_TRANSFER_TTL_DAYS, Class, ClassCoInstructor, OwnershipTransfer

ALREADY_PENDING_MESSAGE = "이미 대기 중인 소유권 이전 요청이 있습니다. 그 요청을 취소한 뒤 다시 요청하세요."
NOT_RECIPIENT_MESSAGE = "이 소유권 이전 요청을 받은 공동 강사만 할 수 있습니다."
NO_SUCH_CO_INSTRUCTOR_MESSAGE = "이 클래스에 그런 공동 강사가 없습니다."
NO_SUCH_TRANSFER_MESSAGE = "이 클래스에 그런 소유권 이전 요청이 없습니다."

_NOT_PENDING_MESSAGES = {
    OwnershipTransfer.Status.ACCEPTED: "이미 수락된 소유권 이전 요청입니다.",
    OwnershipTransfer.Status.DECLINED: "거절된 소유권 이전 요청입니다.",
    OwnershipTransfer.Status.CANCELLED: "취소된 소유권 이전 요청입니다.",
    OwnershipTransfer.Status.EXPIRED: "만료된 소유권 이전 요청입니다.",
}


def pending_q(now) -> Q:
    """대기 중인 요청 — 끝나지 않았고 만료되지 않았다(`status_at` 의 대기와 같다)."""

    return Q(accepted_at__isnull=True, declined_at__isnull=True, cancelled_at__isnull=True, expires_at__gt=now)


def pending_for(class_obj: Class) -> tuple[OwnershipTransfer, ClassCoInstructor | None] | None:
    """이 클래스의 대기 중 요청과 받는 사람의 공동 강사 줄 — 없으면 `None`. 클래스 화면이 싣는다."""

    transfer = class_obj.ownership_transfers.filter(pending_q(Clock.now())).first()
    if transfer is None:
        return None
    row = ClassCoInstructor.objects.filter(classroom_id=class_obj.id, user_id=transfer.recipient_id).first()
    return transfer, row


def _raise_unless_pending(transfer: OwnershipTransfer) -> None:
    message = _NOT_PENDING_MESSAGES.get(transfer.status_at(Clock.now()))
    if message is not None:
        raise HttpError(409, message)


def request(class_obj: Class, owner_id: int, co_instructor_id: int) -> OwnershipTransfer:
    """소유자가 공동 강사 줄 하나를 골라 이전을 요청한다. 이 클래스의 공동 강사 줄이 아니면
    404, 대기 중인 요청이 이미 있으면 409. 문(`class_scope(owner=True)`)을 지난 뒤에도 클래스
    행을 잠그고 소유자인지 다시 본다 — 겹친 수락으로 방금 소유자가 바뀌었을 수 있다."""

    now = Clock.now()
    with transaction.atomic():
        locked = Class.objects.select_for_update().get(id=class_obj.id)
        if not is_owner(locked, owner_id):
            raise HttpError(403, OWNER_ONLY_MESSAGE)
        # 받는 사람을 함께 읽어 둔다 — 커밋 뒤의 알림이 따로 조회하다 실패해 응답을 깨지 않게.
        row = (
            ClassCoInstructor.objects.select_related("user")
            .filter(classroom_id=locked.id, id=co_instructor_id)
            .first()
        )
        if row is None:
            raise HttpError(404, NO_SUCH_CO_INSTRUCTOR_MESSAGE)
        if locked.ownership_transfers.filter(pending_q(now)).exists():
            raise HttpError(409, ALREADY_PENDING_MESSAGE)
        transfer = OwnershipTransfer.objects.create(
            classroom=locked,
            requested_by_id=owner_id,
            recipient_id=row.user_id,
            requested_at=now,
            expires_at=now + timedelta(days=OWNERSHIP_TRANSFER_TTL_DAYS),
        )
    notify_safely(
        recipient=row.user,
        notification_type=NotificationType.CLASSROOM_OWNERSHIP_TRANSFER_REQUESTED,
        context={
            "class_id": locked.id,
            "class_name": locked.name,
            "requester_display_name": locked.instructor_display_name,
            "expires_at": transfer.expires_at.isoformat(),
        },
    )
    return transfer


def _transfer_or_404(class_obj: Class, transfer_id: int, *, lock: bool) -> OwnershipTransfer:
    # 요청한 사람을 함께 읽어 둔다(수락·거절 알림의 수신자) — 잠그는 것은 요청 행 하나뿐이다.
    qs = OwnershipTransfer.objects.select_related("requested_by").filter(classroom_id=class_obj.id, id=transfer_id)
    transfer = (qs.select_for_update(of=("self",)) if lock else qs).first()
    if transfer is None:
        raise HttpError(404, NO_SUCH_TRANSFER_MESSAGE)
    return transfer


def cancel(class_obj: Class, owner_id: int, transfer_id: int) -> None:
    """소유자가 대기 중인 요청을 취소한다. 끝난 요청이면 409."""

    with transaction.atomic():
        transfer = _transfer_or_404(class_obj, transfer_id, lock=True)
        # 잠근 뒤 다시 본다 — 겹친 수락으로 이미 소유자가 아니면 그 수락이 끝낸 요청이다.
        _raise_unless_pending(transfer)
        if not is_owner(Class.objects.get(id=class_obj.id), owner_id):
            raise HttpError(403, OWNER_ONLY_MESSAGE)
        transfer.cancelled_at = Clock.now()
        transfer.save(update_fields=["cancelled_at"])


def decline(class_obj: Class, user_id: int, transfer_id: int) -> None:
    """받는 사람이 거절한다. 받는 사람이 아니면 403, 끝난 요청이면 409."""

    with transaction.atomic():
        transfer = _transfer_or_404(class_obj, transfer_id, lock=True)
        if transfer.recipient_id != user_id:
            raise HttpError(403, NOT_RECIPIENT_MESSAGE)
        _raise_unless_pending(transfer)
        transfer.declined_at = Clock.now()
        transfer.save(update_fields=["declined_at"])
        locked = Class.objects.get(id=class_obj.id)
        row = ClassCoInstructor.objects.filter(classroom_id=locked.id, user_id=user_id).first()
    _notify_requester(
        transfer,
        locked,
        NotificationType.CLASSROOM_OWNERSHIP_TRANSFER_DECLINED,
        recipient_display_name=row.display_name if row is not None else "",
    )


def accept(class_obj: Class, user_id: int, transfer_id: int) -> Class:
    """받는 사람이 수락한다 — 모듈 docstring 의 한 트랜잭션. 받는 사람이 아니면 403, 끝난
    요청이면 409, 그 사이 받는 사람이 떠나 요청이 사라졌으면 404."""

    if _transfer_or_404(class_obj, transfer_id, lock=False).recipient_id != user_id:
        raise HttpError(403, NOT_RECIPIENT_MESSAGE)

    now = Clock.now()
    with transaction.atomic():
        # 잠금 순서: 공동 강사 줄 → 요청 → 클래스(모듈 docstring).
        recipient_row = (
            ClassCoInstructor.objects.select_for_update().filter(classroom_id=class_obj.id, user_id=user_id).first()
        )
        transfer = _transfer_or_404(class_obj, transfer_id, lock=True)
        _raise_unless_pending(transfer)
        if recipient_row is None:  # 떠나면 요청도 함께 사라지므로 닿지 않는다(depart) — 방어선.
            raise HttpError(404, NO_SUCH_TRANSFER_MESSAGE)
        locked = Class.objects.select_for_update().get(id=class_obj.id)

        giver_id = locked.instructor_id
        giver_name = locked.instructor_display_name
        recipient_row.delete()
        ClassCoInstructor.objects.create(
            classroom=locked, user_id=giver_id, display_name=giver_name, accepted_at=now
        )
        locked.instructor_id = user_id
        locked.instructor_display_name = recipient_row.display_name
        locked.openai_api_key_encrypted = ""
        locked.openai_api_key_last4 = ""
        locked.openai_api_key_status = Class.ScoringKeyStatus.UNVERIFIED
        locked.scoring_quota_exhausted_at = None
        # 호환 서버(#601)도 넘긴 사람의 것이다 — 인증 값만 지우고 주소를 남기면 새 소유자의
        # 채점이 넘긴 사람의 서버로 계속 나간다.
        locked.scoring_connection_kind = Class.ScoringConnectionKind.OPENAI_KEY
        locked.scoring_server_url = ""
        locked.save(
            update_fields=[
                "instructor",
                "instructor_display_name",
                "openai_api_key_encrypted",
                "openai_api_key_last4",
                "openai_api_key_status",
                "scoring_quota_exhausted_at",
                "scoring_connection_kind",
                "scoring_server_url",
            ]
        )
        transfer.accepted_at = now
        transfer.save(update_fields=["accepted_at"])
    _notify_requester(
        transfer,
        locked,
        NotificationType.CLASSROOM_OWNERSHIP_TRANSFER_ACCEPTED,
        recipient_display_name=locked.instructor_display_name,
    )
    return locked


def _notify_requester(
    transfer: OwnershipTransfer, class_obj: Class, notification_type: str, *, recipient_display_name: str
) -> None:
    """요청한(넘긴) 사람에게 받는 사람의 답을 알린다 — 트랜잭션이 끝난 뒤에 부른다."""

    notify_safely(
        recipient=transfer.requested_by,
        notification_type=notification_type,
        context={
            "class_id": class_obj.id,
            "class_name": class_obj.name,
            "recipient_display_name": recipient_display_name,
        },
    )
