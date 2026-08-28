"""PG 웹훅 서명 (ADR-0007, #9 리뷰 지적 2).

`/api/payments/webhook`은 인증 없는 내부 엔드포인트다 — 그런데 인증이 없다는 것과
아무 검증도 없다는 것은 다르다. Sponsor가 자신의 결제 `order_id`(자기 201 응답에
그대로 찍혀 있다)를 들고 직접 이 엔드포인트에 `{"status": "paid"}`를 쏘면, 서명
검증이 없을 경우 실제로 돈이 오가지 않아도 원장에 예치 분개가 남고 Contest가
공개된다 — 원장은 append-only라 정정(반대 분개)은 가능해도 위조된 분개 자체를
지울 수는 없다.

그래서 이 엔드포인트에 도달하는 모든 웹훅은 PG(Fake PG 포함)만 계산할 수 있는
서명을 달아야 하고, 서버는 그 서명을 재계산해 대조한다. Fake PG는 dev/test에서
`PAYMENT_WEBHOOK_SECRET`을 알고 있다는 전제로 서명을 만든다 — 실제 토스 연동
(#23)은 이 서명 스킴을 토스가 제공하는 실제 웹훅 서명 방식으로 바꿔 끼우기만
하면 되고, `payments.api`의 검증 지점은 그대로 유지된다.
"""

from __future__ import annotations

import hashlib
import hmac


def _canonical_payload(*, webhook_id: str, order_id: str, status: str) -> bytes:
    return f"{webhook_id}:{order_id}:{status}".encode("utf-8")


def sign_webhook(*, webhook_id: str, order_id: str, status: str, secret: str) -> str:
    """PG(Fake PG 포함)가 웹훅을 보낼 때 계산하는 서명. HMAC-SHA256 hex digest."""

    return hmac.new(
        secret.encode("utf-8"),
        _canonical_payload(webhook_id=webhook_id, order_id=order_id, status=status),
        hashlib.sha256,
    ).hexdigest()


def verify_webhook_signature(
    *, webhook_id: str, order_id: str, status: str, signature: str | None, secret: str
) -> bool:
    """서명이 없거나(`signature` falsy) 틀리면 False.

    `hmac.compare_digest`로 비교해 타이밍 공격으로 서명을 한 글자씩 추측당하는
    경로를 막는다.
    """

    if not signature:
        return False

    expected = sign_webhook(webhook_id=webhook_id, order_id=order_id, status=status, secret=secret)
    return hmac.compare_digest(expected, signature)
