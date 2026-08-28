"""Payout 실행 도메인 모델 (#15, ADR-0004, ADR-0008).

`Payout`은 한 `Handover`(Escrow 해제)에 대해 실제로 돈을 내보내는 시도 하나를
나타낸다. `payments.models.Payment`와 같은 성격이다 — 토스 지급대행과의 대화
상태(요청됨/확정됨·신원대기/확정됨/실패)만 들고, 확정으로 전이하는 순간에만
원장에 수수료·원천징수 공제 분개를 남긴다.

동시성·재전송에 안전한 이유는 `payouts.services.mark_confirmed`/`mark_failed`가
ADR-0003과 같은 조건부 `UPDATE ... WHERE status='requested'` 규율을 그대로
따르기 때문이다.

멱등키(`idempotency_key`)는 ADR-0008이 요구하는 "지급 요청에 멱등키를 붙인다"의
실체다 — `payments.Payment.order_id`와 같은 역할이지만, 토스 지급대행 API가
실제로 `Idempotency-Key` 헤더를 요구하는 개념이라 이름을 그대로 맞춘다.
"""

from __future__ import annotations

import uuid

from django.db import models


class Payout(models.Model):
    class Status(models.TextChoices):
        REQUESTED = "requested", "요청됨"
        # 토스가 지급을 확정했지만(payout.changed 성공), 주민등록번호가 아직
        # 없어 세무 처리를 마칠 수 없는 상태. 정식 상태다(ADR-0008) — 실패가
        # 아니고, 금액은 원장에 개발자 미지급금으로 계속 남는다.
        CONFIRMED_IDENTITY_PENDING = "confirmed_identity_pending", "지급 확정 · 신원 대기"
        CONFIRMED = "confirmed", "지급 확정"
        FAILED = "failed", "지급 실패"

    handover = models.OneToOneField(
        "handovers.Handover", related_name="payout", on_delete=models.CASCADE
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # 지급 요청 시점의 스냅샷(원 단위 정수, ADR-0004). Contest.prize나 수수료율이
    # 나중에 바뀌어도 이미 요청된 지급 금액은 흔들리지 않는다
    # (payments.models.Payment.prize_amount와 같은 원칙).
    prize_amount = models.PositiveIntegerField()
    platform_fee_amount = models.PositiveIntegerField()
    withholding_tax_amount = models.PositiveIntegerField()
    net_amount = models.PositiveIntegerField()

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.REQUESTED)

    # 확정(CONFIRMED_IDENTITY_PENDING 진입) 시 원장에 남긴 수수료·원천징수 공제
    # 분개. 성공 시 정확히 한 번만 채워진다.
    journal_entry_id = models.PositiveIntegerField(null=True, blank=True)
    # 실패로 전이하며 위 분개를 취소한 반대 분개(있을 때만). 확정 후 실패라는
    # 뒤로 가는 상태 전이는 없지만("A backward state edge... 정정은 반대 분개로"),
    # REQUESTED에서 곧바로 FAILED로 가는 정상 실패 경로에는 애초에 분개가 없으므로
    # 이 필드가 채워질 일이 없다 — 감사용으로 자리만 남겨둔다.
    reversal_journal_entry_id = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Payout(idempotency_key={self.idempotency_key}, status={self.status})"


class PayoutWebhookDelivery(models.Model):
    """토스(혹은 Fake)가 보낸 payout.changed 웹훅 전달 시도 하나. 감사 로그용.

    `payments.models.WebhookDelivery`와 같은 이유로 unique 제약을 걸지 않는다 —
    멱등성의 실제 방어선은 `Payout.status`의 조건부 UPDATE다. 이 테이블은 "정말로
    같은 webhook_id가 두 번 왔는가"를 사람이 나중에 확인할 수 있게 남기는 용도다.
    """

    payout = models.ForeignKey(
        Payout, related_name="webhook_deliveries", on_delete=models.CASCADE, null=True, blank=True
    )
    webhook_id = models.CharField(max_length=64)
    idempotency_key = models.UUIDField()
    event_status = models.CharField(max_length=16)
    received_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["received_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"PayoutWebhookDelivery(webhook_id={self.webhook_id})"


class TaxIdentity(models.Model):
    """세무 목적으로만 쓰이는 주민등록번호 저장소 (ADR-0008).

    가입 시점이 아니라 Payout이 확정된 시점에만 수집하고, 다른 어떤 테이블과도
    분리된 별도 암호화 테이블에 둔다 — `verification.models.Verification`이
    실명·생년월일·CI/DI를 두는 것과 물리적으로도 같은 테이블에 섞지 않는다(용도가
    다르다: Verification은 신원 확인, 이건 세무 신고용).

    암호화는 `verification.crypto`의 Fernet 헬퍼를 그대로 재사용한다 — 이 필드가
    다루는 값도 "저장 전 암호화해야 하는 개인식별정보"라는 점에서 같은 요구사항이고,
    두 번째 암호화 구현을 새로 만들 이유가 없다.
    """

    payout = models.OneToOneField(
        Payout, related_name="tax_identity", on_delete=models.CASCADE
    )
    resident_registration_number_encrypted = models.CharField(max_length=500)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"TaxIdentity(payout={self.payout_id})"
