"""운영팀 알림을 보내는 도메인 함수 (#418, CONTEXT.md 「운영자 알림」).

`services.create_notification`이 이미 옵트인·야간 연기·internal_only 판정을
갖고 있으므로 이 함수는 그 위에 `OperatorNotice`(제목·본문·보낸 운영자)를
한 번의 요청 안에서 함께 커밋하는 것만 더한다. 수정·삭제 함수는 없다
(append-only) — 잘못 보냈으면 이 함수를 다시 불러 새 알림을 만든다.
"""

from __future__ import annotations

from django.db import transaction

from .models import Notification, NotificationType, OperatorNotice
from .services import create_notification


def send_operator_notice(
    *, sender, recipient, title: str, body: str = "", image_object_key: str = ""
) -> Notification:
    """`sender`(Operator)가 `recipient`에게 운영팀 알림 한 건을 보낸다.

    `create_notification`이 이미 `is_internal_only` 유형이라 채널을 시도하지
    않는다 — 이 함수는 그 결과 위에 `OperatorNotice` 행을 얹을 뿐이다. 둘을
    한 트랜잭션으로 묶어, `OperatorNotice` 생성이 실패했는데 `Notification`만
    남는 반쪽짜리 상태를 만들지 않는다.

    `image_object_key`의 소유권 확인(#419, 이 요청을 보낸 운영자가 실제로
    올린 키인지)은 호출부(`notifications.operator_api.send_notice`)가 이미
    끝낸 뒤에만 여기로 온다 — 이 함수는 그 값을 그대로 저장할 뿐이다.
    """

    with transaction.atomic():
        notification = create_notification(
            recipient=recipient, notification_type=NotificationType.OPERATOR_NOTICE, context={}
        )
        OperatorNotice.objects.create(
            notification=notification,
            title=title,
            body=body,
            sent_by=sender,
            image_object_key=image_object_key,
        )
    return notification
