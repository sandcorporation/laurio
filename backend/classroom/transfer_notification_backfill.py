"""옛 「넘기려 합니다」 알림을 그 알림을 낳은 요청에 잇는다 (#1448 일부-6·②) — 데이터 마이그레이션
`classroom.0052` 가 부르고, 시험이 지금 모델로 부른다.

#1441 전의 요청 알림 `context` 에는 `transfer_id` 가 없다. 그 알림은 목록에서 상태를 물을 요청이 없고
답해도 읽음 처리(`ownership_transfers._mark_request_read`)가 닿지 않는다.

**하나로 정해질 때만 잇는다.** 받는 사람·클래스가 같고, 요청 생성 시각이 알림 생성 시각 앞 `WINDOW` 안인 요청이
꼭 하나이고, 그 요청을 고른 옛 알림도 하나여야 한다. 알림은 요청을 커밋한 바로 뒤 같은 `Clock` 으로 만들어지므로
제 요청은 언제나 그 안에 있다. 클래스 번호만으로 이으면 같은 사람에게 거듭 보낸 요청이 섞인다 — 정하지 못한
알림은 그대로 둔다 — 목록은 그 클래스에 그 사람 앞 대기 요청이 있으면 「모름」(`unknown`), 없으면 「끝남」(`gone`)으로
보인다(`notifications.api._transfer_status`, #1459 ①).

이은 요청이 이미 수락·거절됐으면 그 답의 시각으로 읽음 처리한다 — 지금 코드가 답할 때 하는 일과 같다. 취소·만료는
안 읽은 채로 둔다(받는 사람이 처리한 일이 아니다). 연결과 읽음 보정은 따로 쓴다 — 읽음은 DB 에서 아직 안 읽음인 행에만
채워, 이행이 읽은 뒤 받는 사람이 읽음 처리한 것을 덮지 않는다(#1471 ⑤).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta

from django.db.models import Case, Value, When

#: 요청 커밋과 알림 생성 사이 — 같은 요청 처리 안의 몇 밀리초다. 넉넉히 잡되 취소 뒤 다시 요청하는 간격보다는 짧게.
WINDOW = timedelta(minutes=1)

REQUESTED = "classroom_ownership_transfer_requested"


def link_legacy_request_notifications(Notification, OwnershipTransfer) -> int:
    """이은 알림 수를 돌려준다. 모델은 인자로 받는다 — 마이그레이션은 이력 모델을, 시험은 지금 모델을 준다.

    질의 수는 알림 수와 무관하다(#1459 ②): 요청 알림 읽기 하나, 후보 요청 읽기 하나, 이은 알림 `bulk_update`
    (연결만) 하나, 답한 요청의 알림이 있으면 읽음 보정 조건부 `UPDATE` 하나(#1471 ⑤)."""

    requested = list(Notification.objects.filter(notification_type=REQUESTED))
    already_linked = {
        n.context.get("transfer_id")
        for n in requested
        if isinstance(n.context, dict) and isinstance(n.context.get("transfer_id"), int)
    }
    legacy = [
        n
        for n in requested
        if isinstance(n.context, dict)
        and not isinstance(n.context.get("transfer_id"), int)
        and isinstance(n.context.get("class_id"), int)
    ]
    if not legacy:
        return 0

    # (받는 사람, 클래스) 묶음의 요청을 한 번에 읽는다 — 두 `__in` 의 곱이 묶음보다 넓을 수 있어 아래에서 묶음으로 거른다.
    pairs = {(n.recipient_id, n.context["class_id"]) for n in legacy}
    by_pair: dict[tuple[int, int], list] = defaultdict(list)
    for transfer in OwnershipTransfer.objects.filter(
        recipient_id__in={recipient for recipient, _ in pairs},
        classroom_id__in={classroom for _, classroom in pairs},
    ):
        pair = (transfer.recipient_id, transfer.classroom_id)
        if pair in pairs and transfer.id not in already_linked:
            by_pair[pair].append(transfer)

    picked: dict[int, object] = {}
    for notification in legacy:
        candidates = [
            t
            for t in by_pair.get((notification.recipient_id, notification.context["class_id"]), ())
            if notification.created_at - WINDOW < t.requested_at <= notification.created_at
        ]
        if len(candidates) == 1:
            picked[notification.id] = candidates[0]

    claims = Counter(transfer.id for transfer in picked.values())
    linked = []
    answered: dict[int, object] = {}
    for notification in legacy:
        transfer = picked.get(notification.id)
        if transfer is None or claims[transfer.id] != 1:
            continue
        notification.context = {**notification.context, "transfer_id": transfer.id}
        linked.append(notification)
        answered_at = transfer.accepted_at or transfer.declined_at
        if answered_at is not None:
            answered[notification.id] = answered_at
    if linked:
        # 연결만 쓴다 — `read_at` 은 위에서 읽은 뒤 받는 사람이 바꿨을 수 있다(#1471 ⑤).
        Notification.objects.bulk_update(linked, ["context"])
    if answered:
        # 읽음 보정은 DB 가 아직 안 읽음인 행에만 — 읽음 API(`notifications.api.mark_one_read`)와 같은 조건부
        # 갱신이라, 그 사이 사용자가 읽은 시각을 덮지 않는다. 행마다 시각이 달라도 질의 하나다.
        Notification.objects.filter(pk__in=answered, read_at__isnull=True).update(
            read_at=Case(*(When(pk=pk, then=Value(at)) for pk, at in answered.items()))
        )
    return len(linked)
