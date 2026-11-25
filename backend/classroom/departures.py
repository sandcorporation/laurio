"""닫힌 참여자 행이 「나감」인가 「내보냄」인가(#1492-5, #1503 ①②).

새 코드는 닫을 때마다 `ClassMember.left_by_self` 에 확정 사유를 적는다 — 참(나감)·거짓(내보냄)
(`co_instructors.depart`·`api.expel_class_member`). 그 칸을 모르는 쓰기가 둘 있다 — 0054 가 칸을 더하기 전에
닫힌 행과, 이행 뒤 겹쳐 배포 중인 옛 서버나 코드만 되돌린 서버가 `expelled_at` 만 채운 행. 둘 다 칸이 NULL
(사유 불명)로 남는다. 일회성 행 채우기는 두 번째를 놓친다 — 그래서 불명인 행만 읽을 때마다 남은 흔적으로
판정한다. 확정 사유는 흔적이 무엇을 말하든 그대로다(#1509 ① — 공동 강사였던 사람이 참여자로 다시 들어와
탈퇴한 직후 내보내지면 흔적은 「나감」을 가리킨다).

흔적은 탈퇴뿐이다. 공동 강사의 떠나기와 소유자의 내보내기는 같은 쓰기라(공동 강사 줄을 지우고 행을 닫는다)
옛 코드가 처리했으면 가를 수 없어 「내보냄」으로 남는다. 탈퇴는 `accounts.Withdrawal` 이 남는다: 그 사람이 이
클래스의 공동 강사였고, 참여자 행이 탈퇴한 그 순간에 닫혔다면 탈퇴가 닫은 것이다
(`co_instructors.leave_all_on_withdrawal` 이 탈퇴 트랜잭션 안에서 닫는다 — `withdrawn_at` 은 그보다 먼저
잡힌다). 공동 강사였던 이력은 두 길로 남는다 — 수락한 공동 강사 초대, 그리고 초대 없이 넘긴 사람을 공동
강사로 앉히는 수락된 소유권 이전(`ownership_transfers.accept`)."""

from collections.abc import Iterable
from datetime import timedelta

from accounts.models import Withdrawal

from .models import ClassMember, CoInstructorInvite, OwnershipTransfer

#: 탈퇴 시각과 참여자 행이 닫힌 시각 사이 — 한 트랜잭션 안이라 넉넉히 잡아도 다른 길과 겹치지 않는다.
SAME_TRANSACTION = timedelta(minutes=1)


def left_member_ids(members: Iterable[ClassMember]) -> set[int]:
    """`members` 가운데 스스로 나간 행의 id. 사유 불명(NULL)인 닫힌 행이 있을 때만 쿼리를 낸다(많아야 셋)."""

    members = list(members)
    left = {m.id for m in members if m.expelled_at is not None and m.left_by_self is True}
    unsure = [m for m in members if m.expelled_at is not None and m.left_by_self is None]
    if not unsure:
        return left
    withdrawn_at = dict(
        Withdrawal.objects.filter(user_id__in={m.user_id for m in unsure}).values_list("user_id", "withdrawn_at")
    )
    unsure = [
        m
        for m in unsure
        if m.user_id in withdrawn_at
        and withdrawn_at[m.user_id] <= m.expelled_at <= withdrawn_at[m.user_id] + SAME_TRANSACTION
    ]
    if not unsure:
        return left
    user_ids = {m.user_id for m in unsure}
    classroom_ids = {m.classroom_id for m in unsure}
    co_taught = set(
        CoInstructorInvite.objects.filter(
            accepted_by_id__in=user_ids, classroom_id__in=classroom_ids, accepted_at__isnull=False
        ).values_list("classroom_id", "accepted_by_id")
    ) | set(
        OwnershipTransfer.objects.filter(
            requested_by_id__in=user_ids, classroom_id__in=classroom_ids, accepted_at__isnull=False
        ).values_list("classroom_id", "requested_by_id")
    )
    return left | {m.id for m in unsure if (m.classroom_id, m.user_id) in co_taught}


def is_left(member: ClassMember) -> bool:
    return member.id in left_member_ids([member])
