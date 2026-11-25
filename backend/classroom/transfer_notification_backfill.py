"""옛 「넘기려 합니다」 알림을 그 알림을 낳은 요청에 잇는다 (#1448 일부-6·②) — 데이터 마이그레이션
`classroom.0052` 가 부르고, 시험이 지금 모델로 부른다.

#1441 전의 요청 알림 `context` 에는 `transfer_id` 가 없다. 그 알림은 목록에서 상태를 물을 요청이 없고(그래서
「끝난 요청」, `gone`) 답해도 읽음 처리(`ownership_transfers._mark_request_read`)가 닿지 않는다.

**하나로 정해질 때만 잇는다.** 받는 사람·클래스가 같고, 요청 생성 시각이 알림 생성 시각 앞 `WINDOW` 안인 요청이
꼭 하나이고, 그 요청을 고른 옛 알림도 하나여야 한다. 알림은 요청을 커밋한 바로 뒤 같은 `Clock` 으로 만들어지므로
제 요청은 언제나 그 안에 있다. 클래스 번호만으로 이으면 같은 사람에게 거듭 보낸 요청이 섞인다 — 정하지 못한
알림은 그대로 두고 목록이 끝난 요청으로 보인다.

이은 요청이 이미 수락·거절됐으면 그 답의 시각으로 읽음 처리한다 — 지금 코드가 답할 때 하는 일과 같다. 취소·만료는
안 읽은 채로 둔다(받는 사람이 처리한 일이 아니다).
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

#: 요청 커밋과 알림 생성 사이 — 같은 요청 처리 안의 몇 밀리초다. 넉넉히 잡되 취소 뒤 다시 요청하는 간격보다는 짧게.
WINDOW = timedelta(minutes=1)

REQUESTED = "classroom_ownership_transfer_requested"


def link_legacy_request_notifications(Notification, OwnershipTransfer) -> int:
    """이은 알림 수를 돌려준다. 모델은 인자로 받는다 — 마이그레이션은 이력 모델을, 시험은 지금 모델을 준다."""

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

    picked: dict[int, object] = {}
    for notification in legacy:
        candidates = [
            t
            for t in OwnershipTransfer.objects.filter(
                recipient_id=notification.recipient_id,
                classroom_id=notification.context["class_id"],
                requested_at__gt=notification.created_at - WINDOW,
                requested_at__lte=notification.created_at,
            )
            if t.id not in already_linked
        ]
        if len(candidates) == 1:
            picked[notification.id] = candidates[0]

    claims = Counter(transfer.id for transfer in picked.values())
    linked = 0
    for notification in legacy:
        transfer = picked.get(notification.id)
        if transfer is None or claims[transfer.id] != 1:
            continue
        notification.context = {**notification.context, "transfer_id": transfer.id}
        fields = ["context"]
        answered_at = transfer.accepted_at or transfer.declined_at
        if notification.read_at is None and answered_at is not None:
            notification.read_at = answered_at
            fields.append("read_at")
        notification.save(update_fields=fields)
        linked += 1
    return linked
