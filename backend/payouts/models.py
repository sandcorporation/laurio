"""Payout 실행 도메인 모델 (#15, #50, ADR-0004, ADR-0008, ADR-0020).

`Payout`은 한 `Handover`(Escrow 해제)에 대해 실제로 돈을 내보내는 시도 하나를
나타낸다. `payments.models.Payment`와 같은 성격이다 — 토스 지급대행과의 대화
상태(요청됨/확정됨·Seller대기/확정됨·신원대기/확정됨/실패)만 들고, 확정으로
전이하는 순간에만 원장에 수수료·원천징수 공제 분개를 남긴다.

동시성·재전송에 안전한 이유는 `payouts.progress.advance`가
ADR-0003과 같은 조건부 `UPDATE ... WHERE status='requested'` 규율을 그대로
따르기 때문이다.

멱등키(`idempotency_key`)는 ADR-0008이 요구하는 "지급 요청에 멱등키를 붙인다"의
실체다 — `payments.Payment.order_id`와 같은 역할이지만, 토스 지급대행 API가
실제로 `Idempotency-Key` 헤더를 요구하는 개념이라 이름을 그대로 맞춘다.

`Seller`는 ADR-0020이 새로 들인 개념이다 — `Developer`가 지급대행사에 등록되는
수취인 신원. `CONFIRMED_IDENTITY_PENDING`("지급 확정 · 신원 대기", 주민등록번호를
기다림)과 `CONFIRMED_SELLER_PENDING`("지급 확정 · Seller 대기", 지급대행사의
수취인 등록을 기다림)은 서로 다른 것을 기다리는 별개 상태다 — 뭉치면 Operator가
어느 쪽을 처리해야 하는지 알 수 없다.
"""

from __future__ import annotations

import uuid

from django.db import models
from django.db.models import Q

from core.classification import Classification


class PayoutQuerySet(models.QuerySet):
    """Payout 의 지급 사유(Handover 또는 DistributionShare)에 따라 갈리는 조회를 한 곳에
    (#128). 불변식 `payout_exactly_one_target` 이 이 모델에 있으므로 「어느 경로로
    Contest·Developer 에 닿는가」도 여기서만 안다 — 호출자는 두 FK 중 어느 쪽인지 알 필요가
    없다.
    """

    def with_target(self):
        """`contest`·`developer` 속성이 추가 조회 없이 풀리도록 두 경로를 미리 붙인다."""

        return self.select_related(
            "handover__award__contest",
            "handover__award__submission__developer",
            "distribution_share__distribution__contest",
            "distribution_share__submission__developer",
        )

    def for_developer(self, developer):
        return self.filter(
            Q(handover__award__submission__developer=developer)
            | Q(distribution_share__submission__developer=developer)
        )

    def for_contest(self, contest_id):
        return self.filter(
            Q(handover__award__contest_id=contest_id)
            | Q(distribution_share__distribution__contest_id=contest_id)
        )

    def owned_by(self, user_id):
        return self.filter(
            Q(handover__award__submission__developer__user_id=user_id)
            | Q(distribution_share__submission__developer__user_id=user_id)
        )


class PayoutStatus(models.TextChoices):
    REQUESTED = "requested", "요청됨"
    # 토스가 지급을 확정했지만(payout.changed 성공), 주민등록번호가 아직
    # 없어 세무 처리를 마칠 수 없는 상태. 정식 상태다(ADR-0008) — 실패가
    # 아니고, 금액은 원장에 개발자 미지급금으로 계속 남는다.
    CONFIRMED_IDENTITY_PENDING = "confirmed_identity_pending", "지급 확정 · 신원 대기"
    # 지급이 확정됐지만 이 Developer의 Seller(지급대행사 수취인) 등록이 아직
    # 끝나지 않은 상태(ADR-0020). CONFIRMED_IDENTITY_PENDING과는 다른 것을
    # 기다린다 — 이건 주민등록번호(Laurio의 세무)가 아니라 지급대행사의
    # 수취인 등록을 기다린다. 한도 초과·심사 지연도 여기 머문다 — 실패가
    # 아니므로 금액은 그대로 원장에 개발자 미지급금으로 남는다.
    CONFIRMED_SELLER_PENDING = "confirmed_seller_pending", "지급 확정 · Seller 대기"
    CONFIRMED = "confirmed", "지급 확정"
    FAILED = "failed", "지급 실패"


# --- Payout.Status 가 소유하는 분류 (#142, #121) ---------------------------------------------
#
# 다섯 값 전부에 명시적으로 답한다(tests/test_status_classification.py 가 강제). CONFIRMED_SELLER_PENDING 이
# 생겼을 때 distributions 의 SETTLED 집합에 빠져 배치 슬롯을 낭비한 사고(#50)가 이 모양의 이유다.
_P = PayoutStatus

# "아직 실패로 끝나지 않은" 시도 — FAILED 만 빠진다. 그래야 실패한 시도 뒤에 새 REQUESTED 를 만들 수
# 있다. CONFIRMED_SELLER_PENDING 도 활성이다 — Seller 등록이 안 끝났을 뿐 지급 자체는 이미 확정되어
# 원장에 분개가 남아 있다(#50). 아래 Payout.Meta 의 부분 유니크 제약 둘이 이 질문에서 파생된다 — DB
# 레벨 최후 방어선과 애플리케이션 레벨 조회 기준이 한 집합이다.
PayoutStatus.ACTIVE = Classification(
    {_P.REQUESTED: True, _P.CONFIRMED_IDENTITY_PENDING: True, _P.CONFIRMED_SELLER_PENDING: True, _P.CONFIRMED: True, _P.FAILED: False},
    question="활성(실패로 끝나지 않은) 시도인가",
)
# 「이 몫은 더 이상 지급을 기다리지 않는다」 — 지급 자체(원장 분개)가 확정된 상태들. 몫 지급 스캔이
# 다시 시도하지 않는 기준이고, `contests.sponsorship` 이 개최자에게 「완료」라고 말해도 되는지도
# 같은 기준이어야 한다(#81).
PayoutStatus.SETTLED = Classification(
    {_P.REQUESTED: False, _P.CONFIRMED_IDENTITY_PENDING: True, _P.CONFIRMED_SELLER_PENDING: True, _P.CONFIRMED: True, _P.FAILED: False},
    question="지급이 확정되어 더 이상 기다리지 않는가",
)
# ADR-0025 "지급이 끝나기 전에는 탈퇴할 수 없다"(User Story 6). CONFIRMED 는 지급이 실제로 끝난
# 상태이고(TransferStatus 가 COMPLETED 일 때만 여기로 전진한다), FAILED 는 그 시도 자체가 끝난 상태다 —
# 재시도는 새 REQUESTED 행으로 남으므로(#57) FAILED 행 하나가 "미지급 상태"를 뜻하지 않는다.
PayoutStatus.BLOCKS_DEVELOPER_WITHDRAWAL = Classification(
    {_P.REQUESTED: True, _P.CONFIRMED_IDENTITY_PENDING: True, _P.CONFIRMED_SELLER_PENDING: True, _P.CONFIRMED: False, _P.FAILED: False},
    question="Developer 의 탈퇴를 막는 진행 중 지급인가",
)
del _P

# 부분 유니크 제약의 조건 — ACTIVE 질문에서 파생한 문자열 리스트(enum 정의 순서, 마이그레이션 상태와
# 같은 순서).
_ACTIVE_PAYOUT_STATUS_VALUES = [status.value for status in PayoutStatus if PayoutStatus.ACTIVE(status)]


class Payout(models.Model):
    # 값 자리는 `Payout.Status.X` 그대로다 — 클래스 바깥에 둔 이유는 Meta 의 제약 조건이 클래스 생성
    # 중에 이 enum 의 분류를 읽어야 하기 때문이다.
    Status = PayoutStatus

    class TransferStatus(models.TextChoices):
        """실제 벤더 이체(토스 실물 어댑터가 부르는 `POST /v2/payouts`)의 진행
        상태 — `status`(두 대기가 풀렸는가)와는 다른 축이다(코드리뷰 지적 1/4/8,
        #57). `status`가 "Laurio가 내부적으로(원장상) 확정했는가"를 답하는
        반면, 이 필드는 "그 확정된 금액이 실제로 벤더에게 이체 요청됐고 그
        결과가 무엇인가"를 답한다. 둘을 하나로 뭉치면 "Seller가 막 준비됐는데
        실이체가 벤더 쪽 한도로 거절된" 경우를 표현할 자리가 없어, 확정
        상태(status)가 실이체 실패를 덮어써 "지급 완료"라고 잘못 말하게 된다.

        REQUESTED/COMPLETED/FAILED 어느 쪽으로도 `status`를 되돌리지 않는다 —
        원장 분개는 이미 남아 있고(ADR-0004), 이 필드는 오직 "실이체 자체가
        어디까지 갔는가"만 기록한다. `status`를 CONFIRMED로 전진시킬지는
        `payouts.services`의 호출자들이 이 필드가 COMPLETED일 때만 결정한다.
        """

        # Seller가 아직 지급 가능 상태가 아니어서 실이체 자체를 시도하지
        # 않았다(기본값). 두 대기 중 Seller 대기가 남아 있다는 뜻이다.
        NOT_REQUESTED = "not_requested", "실이체 요청 전"
        # 벤더에 실이체를 요청했지만 아직 결과가 확정되지 않았다(타임아웃 뒤
        # query_status로도 아직 pending, 또는 웹훅을 기다리는 중).
        REQUESTED = "requested", "실이체 확인 대기"
        COMPLETED = "completed", "실이체 완료"
        # 벤더가 실이체를 명시적으로 거절했다(예: 실이체 시점의 한도 초과).
        # **실패로 종결하지 않는다** — 원장의 금액은 그대로이고, Seller가
        # 이미 준비된 상태이므로 재시도(POST /payouts/{key}/seller-registration,
        # 실질적으로는 실이체 재시도)로 회복한다(코드리뷰 지적 1).
        FAILED = "failed", "실이체 실패"

    # OneToOneField가 아니라 ForeignKey다 — FAILED로 끝난 시도가 재시도를 영구히
    # 막으면 안 된다(토스가 거절해도 Escrow에 갇힌 상금을 꺼낼 길이 있어야 한다).
    # 동시에 하나의 Handover에 "진행 중이거나 이미 성사된" 시도가 두 개 이상
    # 생기는 걸 막는 건 아래 unique_active_payout_per_handover다 —
    # payments.models.Payment.unique_active_payment_per_contest와 같은 부분
    # 유니크 인덱스로, failed는 조건에서 뺀다.
    #
    # handover/distribution_share 둘 다 null=True다 — Payout은 두 가지 서로 다른
    # 지급 사유 중 정확히 하나에 연결된다(#16). Award 경로는 Handover(Escrow
    # 해제)를, 무응답 1/N 배분 경로는 DistributionShare를 가리킨다. "Distribution도
    # 기존 Payout 경로를 재사용한다"는 #16의 요구를 새 Payout 구현을 만들지 않고
    # 만족시키는 방법이 이 두 FK를 나란히 두는 것이다 — 아래 CheckConstraint가
    # 정확히 하나만 채워지도록 강제한다.
    handover = models.ForeignKey(
        "handovers.Handover", related_name="payouts", on_delete=models.CASCADE, null=True, blank=True
    )
    distribution_share = models.ForeignKey(
        "distributions.DistributionShare",
        related_name="payouts",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    idempotency_key = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # 지급 요청 시점의 스냅샷(원 단위 정수, ADR-0004). Contest.prize나 수수료율이
    # 나중에 바뀌어도 이미 요청된 지급 금액은 흔들리지 않는다
    # (payments.models.Payment.prize_amount와 같은 원칙).
    prize_amount = models.PositiveIntegerField()
    platform_fee_amount = models.PositiveIntegerField()
    withholding_tax_amount = models.PositiveIntegerField()
    net_amount = models.PositiveIntegerField()

    # 이 금액을 계산할 때 실제로 쓴 요율의 스냅샷(#75, ADR-0023) — 1/10000(bp) 단위
    # 정수. `distributions.Distribution.cutline_percentage`와 같은 이유: 값이
    # 바뀔 수 있게 되는 순간 "왜 이만큼 뗐는가"에 답하려면 금액만이 아니라 그때
    # 쓴 요율 자체가 남아야 한다 — 상금이 다르면 금액에서 요율을 역산할 수 없다.
    # `policies.PlatformPolicy`가 지금 어떤 값이든, 이 두 필드는 이 Payout이 만들어진
    # 순간의 값에 영구히 고정된다(정책이 나중에 바뀌어도 흔들리지 않는다).
    #
    # withholding_tax_bps는 "실제로 적용된" 요율이다(코드리뷰 지적 2) — 과세최저한
    # 면제로 withholding_tax_amount가 0원이면 이 필드도 0을 기록한다. 정책의
    # 명목 요율(예: 440)을 그대로 남기면 "4.4%를 적용했다"는 기록과 "0원 뗐다"는
    # 금액이 서로 모순돼, 이 스냅샷으로 나중에 원천징수 명세를 만들면 뗀 적 없는
    # 세금을 보고하게 된다. withholding_exempt가 그 모순 없는 기록을 "왜"까지
    # 답하게 한다 — bps=0이 "요율이 0으로 정책됐다"인지 "면제됐다"인지는
    # withholding_exempt로만 구별된다.
    platform_fee_bps = models.PositiveIntegerField()
    withholding_tax_bps = models.PositiveIntegerField()
    withholding_exempt = models.BooleanField(default=False)

    status = models.CharField(max_length=32, choices=Status.choices, default=Status.REQUESTED)
    transfer_status = models.CharField(
        max_length=16, choices=TransferStatus.choices, default=TransferStatus.NOT_REQUESTED
    )
    # 벤더(토스)가 실이체 요청 응답으로 돌려준 자신의 식별자(코드리뷰 지적 8) —
    # 우리 idempotency_key(refPayoutId)와 다르다. POST 응답의 `id`를 여기 저장해
    # 두지 않으면, 확인(query_status)이 우리 키로 GET을 시도해 항상 404가
    # 되어 "타임아웃 뒤 조회로 확정"하는 경로 자체가 성립하지 않는다.
    vendor_payout_id = models.CharField(max_length=100, blank=True)
    # 실이체를 벤더에 실제로 요청(POST)한 횟수(코드리뷰 지적 4, 4차 — 실행
    # 재현 완료). `idempotency_key` 하나를 모든 재시도에 그대로 재사용하면,
    # 벤더가 "이미 처리한 요청"으로 보고 예전 FAILED 응답을 그대로 재생한다
    # — 진짜 새 시도가 아니라 캐시된 실패를 돌려받으므로 실운영에서 영구히
    # 복구 불가능하다. `TossPayoutAdapter`는 벤더에 보내는 refPayoutId/
    # Idempotency-Key를 `f"{idempotency_key}-{transfer_attempt}"`로 만들어
    # 매 시도가 벤더에게는 새 요청으로 보이게 한다 — 우리 쪽 DB 조회·웹훅
    # 매칭은 여전히 `idempotency_key`(변하지 않는 값)로만 한다.
    transfer_attempt = models.PositiveIntegerField(default=0)
    # 이 시도(transfer_attempt)를 선점한 시각(코드리뷰 지적 6, 5차) —
    # notifications.models.Notification.claimed_at과 같은 관용구다. 벤더에
    # 닿기도 전에 끊긴 요청(ConnectionError 등)은 query_status로도 절대 풀리지
    # 않는다 — 벤더는 그 시도 자체를 모르기 때문이다. 이 값이 없으면
    # transfer_status=REQUESTED로 영구히 멈춘 Payout을 되찾을 방법이 없다.
    # `TossPayoutAdapter._claim_transfer_attempt`가 새 시도를 선점할 때마다
    # 갱신하고, 이 값이 오래되면(임계값 초과) REQUESTED에서도 재선점을 허용한다.
    transfer_claimed_at = models.DateTimeField(null=True, blank=True)

    # 확정(CONFIRMED_IDENTITY_PENDING 진입) 시 원장에 남긴 수수료·원천징수 공제
    # 분개. 성공 시 정확히 한 번만 채워진다.
    journal_entry_id = models.PositiveIntegerField(null=True, blank=True)
    # 실패로 전이하며 위 분개를 취소한 반대 분개(있을 때만). 확정 후 실패라는
    # 뒤로 가는 상태 전이는 없지만("A backward state edge... 정정은 반대 분개로"),
    # REQUESTED에서 곧바로 FAILED로 가는 정상 실패 경로에는 애초에 분개가 없으므로
    # 이 필드가 채워질 일이 없다 — 감사용으로 자리만 남겨둔다.
    reversal_journal_entry_id = models.PositiveIntegerField(null=True, blank=True)

    objects = PayoutQuerySet.as_manager()

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # 진행 중이거나 이미 확정된 지급 시도는 Handover 당 정확히 하나여야
            # 한다(payments.Payment.unique_active_payment_per_contest와 같은
            # 이유 — 락 없는 조회-후-생성 경합이 같은 Handover에 활성 Payout을
            # 두 개 만들면 수수료·원천징수 분개가 두 번 남는다). failed는 제외해
            # 재시도(새 REQUESTED)를 막지 않는다 — 부분 인덱스라서 status=
            # 'failed'인 행끼리는 이 제약에 걸리지 않는다.
            models.UniqueConstraint(
                fields=["handover"],
                condition=models.Q(status__in=_ACTIVE_PAYOUT_STATUS_VALUES),
                name="unique_active_payout_per_handover",
            ),
            # distribution_share 쪽도 같은 이유로 같은 모양의 부분 유니크 제약을
            # 둔다 — 같은 몫에 동시에 두 개의 활성 Payout이 생기면 그 몫의
            # 수수료·원천징수 분개가 두 번 남는다.
            models.UniqueConstraint(
                fields=["distribution_share"],
                condition=models.Q(status__in=_ACTIVE_PAYOUT_STATUS_VALUES),
                name="unique_active_payout_per_distribution_share",
            ),
            # 정확히 하나의 지급 사유만 채워져야 한다 — 둘 다 비었거나 둘 다
            # 채워진 Payout은 어느 쪽 경로의 지급인지 판정할 수 없어 원장 분개의
            # 근거(contest·memo)를 만들 수 없다.
            models.CheckConstraint(
                condition=(
                    models.Q(handover__isnull=False, distribution_share__isnull=True)
                    | models.Q(handover__isnull=True, distribution_share__isnull=False)
                ),
                name="payout_exactly_one_target",
            ),
        ]

    # ---- 지급 사유 해석 (#128) — 두 FK 중 정확히 하나가 채워져 있다(payout_exactly_one_target).
    @property
    def contest(self):
        if self.handover_id is not None:
            return self.handover.award.contest
        return self.distribution_share.distribution.contest

    @property
    def developer(self):
        """이 Payout 을 받을 `accounts.DeveloperProfile`. Seller 는 이 단위로 등록된다 —
        한 Developer 가 여러 Contest 를 이겨도 등록은 한 번."""

        if self.handover_id is not None:
            return self.handover.award.submission.developer
        return self.distribution_share.submission.developer

    @property
    def seller(self):
        """이 Payout 의 수취인 Seller. 아직 등록이 시작되지 않았으면 None."""

        return Seller.objects.filter(developer=self.developer).first()

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


class Seller(models.Model):
    """`Developer`가 지급대행사(토스)에 등록된 수취인 신원 (#50, ADR-0020).

    가입·제출 시점이 아니라 **Payout이 확정된 뒤**에만 등록이 시작된다 —
    `verification.models.Verification`을 행위 시점으로 미룬 것(ADR-0011)과 같은
    원칙이다. 구경하거나 떨어진 Developer가 지급대행사에 신원 정보를 넘길
    이유가 없다.

    `Developer`(accounts.DeveloperProfile)와 1:1이다 — 한 Developer는 Contest를
    여러 번 이길 수 있지만 지급대행사 등록은 한 번만 하면 된다. `seller_id`가
    한 번 채워지면(PARTIALLY_APPROVED) 두 번째 Payout부터는 재등록하지 않는다
    (`payouts.services.ensure_seller_registered`).
    """

    class Status(models.TextChoices):
        # 아직 등록을 시도하지 않았거나, 시도했지만 지급대행사 응답을 아직
        # 받지 못한 상태. 사실상 과도기 값이다 — FakeSellerAdapter는 항상
        # 동기로 응답하므로 이 값이 DB에 오래 머무는 일은 없지만, 실물
        # 어댑터(#57)는 이메일·실명·전화번호 중 하나라도 아직 없으면 벤더를
        # 부르지 않고 이 값에 머문다(등록 자체를 아직 시도하지 않은
        # 경우) — `TossSellerAdapter.register` 참고.
        PENDING = "pending", "등록 대기"
        # 토스에 재확인한 실제 상태 흐름(ADR-0020)의 첫 단계 — 등록은
        # 접수됐고(seller_id를 받는다) 토스가 발송한 본인인증 문자로 Developer가
        # 본인인증을 마쳐야 다음 단계(PARTIALLY_APPROVED)로 넘어간다. **PENDING과
        # 다르다** — PENDING은 "아무도 할 일이 없다"(우리가 응답을 기다린다)이고,
        # 이 상태는 "Developer가 할 일이 있다"(사람의 차례)다. 이 구별이 없으면
        # 화면이 "처리 중"이라고만 말해 Developer가 자기 차례인 줄 모르고
        # 기다린다 — ADR-0020이 "침묵은 상금이 사라진 것으로 읽힌다"고 경고한
        # 바로 그 상태다.
        APPROVAL_REQUIRED = "approval_required", "본인인증 대기"
        # 본인인증을 마치고 지급대행사가 승인한 상태 — 주간 한도 안에서는
        # 곧바로 지급받을 수 있다(ADR-0020).
        PARTIALLY_APPROVED = "partially_approved", "부분 승인"
        # 주간 한도 초과, 또는 지급대행사가 추가 서류·확인을 요구하는 상태.
        # **실패가 아니다** — 짧은 기간에 여러 Contest에서 수상한 Developer를
        # 성공했다는 이유로 막지 않는다(ADR-0020). 시간이 지나면(또는 재시도로)
        # PARTIALLY_APPROVED로 넘어갈 수 있다.
        UNDER_REVIEW = "under_review", "심사 대기"
        # KYC 심사를 마쳐 주간 한도 자체가 없어진 상태(ADR-0020 토스 재확인
        # 결과) — PARTIALLY_APPROVED와 마찬가지로 곧바로 지급받을 수 있다.
        # 한도를 푼 Developer가 계속 PARTIALLY_APPROVED로 잘못 남지 않도록
        # 별도 값을 둔다.
        APPROVED = "approved", "승인 완료"
        # 지급대행사가 등록을 거절했다. 이것도 Payout을 FAILED로 되돌리지
        # 않는다 — 확정된 금액은 원장에 개발자 미지급금으로 그대로 남고
        # (ADR-0004), 재시도(운영 처리 후 재등록)로 회복할 여지를 남긴다.
        REJECTED = "rejected", "거절"

    # 지급이 준비 완료로 취급되는(=Payout이 다음 단계로 넘어갈 수 있는) 상태
    # 집합 — `payouts.services`의 여러 지점이 "Seller가 준비됐는가"를 같은
    # 기준으로 판정해야 한다(#57). PARTIALLY_APPROVED(주간 한도 있음)와
    # APPROVED(한도 없음) 둘 다 지급 가능 상태이고, 한도 자체는 지급 시점에
    # 별도로 확인할 문제이지 Seller 준비 여부의 판정 기준이 아니다.
    READY_STATUSES = (Status.PARTIALLY_APPROVED, Status.APPROVED)

    developer = models.OneToOneField(
        "accounts.DeveloperProfile", related_name="seller", on_delete=models.CASCADE
    )
    # 지급대행사가 발급한 등록 식별자. 등록 시도 자체가 아직 없었거나(PENDING)
    # 거절되어(REJECTED) 식별자를 못 받았으면 빈 문자열일 수 있다.
    seller_id = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=32, choices=Status.choices, default=Status.PENDING)
    # PARTIALLY_APPROVED일 때만 의미가 있는 주간 지급 한도(원 단위 정수,
    # ADR-0004). 그 외 상태에서는 null이다.
    weekly_limit_amount = models.PositiveIntegerField(null=True, blank=True)
    # 토스 셀러 등록(businessType=INDIVIDUAL)의 individual 객체가 요구하는
    # 전화번호(#57) — 가입 시점에는 어디에도 없어 Payout이 확정된 뒤 별도로
    # 제출받는다(`POST /payouts/{idempotency_key}/seller-contact`). TaxIdentity.
    # resident_registration_number_encrypted와 같은 이유로 암호화해 저장한다.
    # 아직 제출되지 않았으면 빈 문자열이고, 그동안 실물 어댑터는 벤더를 부르지
    # 않고 PENDING에 머문다(register()가 스스로 판단한다) — Fake 어댑터는 이
    # 값을 쓰지 않는다(기존 시나리오 동작을 바꾸지 않는다).
    phone_number_encrypted = models.CharField(max_length=500, blank=True)
    # 지급용 이메일(#168) — 로그인 계정의 이메일과 별개의 값이다. 소셜 로그인이
    # 이메일 동의를 주지 않으면(#49 유저스토리 12) 계정 이메일이 빈 문자열일 수
    # 있는데, 토스 셀러 등록은 이메일을 필수로 요구한다. 화면은 계정 이메일을
    # 기본값으로 보여주되 저장은 여기(Seller)에만 한다 — 로그인 제공자를
    # 바꾸거나 계정 이메일이 바뀌어도 지급 경로가 흔들리지 않고, 카카오 계정
    # 주소로 지급 안내를 받고 싶지 않은 Developer 에게 선택지가 남는다.
    # 전화번호와 달리 평문으로 둔다 — 같은 종류의 값(계정 이메일)이 저장소에
    # 따라 다른 취급(암호화 여부)을 받으면 파기 규칙이 갈린다(#168).
    email = models.EmailField(max_length=254, blank=True)

    # 등록 시도가 벤더 오류(어댑터가 예기치 못하게 실패한 경우, `SellerError`)로
    # 접수조차 되지 못한 연속 횟수(#178) — 한도 초과·심사·거절 같은 **정상 응답**은
    # 여기 안 들어간다(그것들은 이미 자기 상태를 가진다). 자력 회복 스캔
    # (`payouts.recovery`)이 이 값을 올리고, 등록이 정상 응답(성공이든 거절이든
    # 무엇이든)을 받으면 0으로 되돌아간다. 상한(`payouts.progress.
    # MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS`)에 이르면 스캔이 재시도를 멈추고
    # Hold 판정이 Operator 의 차례로 넘긴다 — 벤더에 같은 요청을 무한히 쏘지
    # 않기 위해서다.
    registration_error_count = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Seller(developer={self.developer_id}, status={self.status})"

    # --- 암호화된 필드 접근자 (verification.models.Verification과 같은 패턴) ----
    @property
    def phone_number(self) -> str:
        from verification.crypto import decrypt

        if not self.phone_number_encrypted:
            return ""
        return decrypt(self.phone_number_encrypted)

    @phone_number.setter
    def phone_number(self, value: str) -> None:
        from verification.crypto import encrypt

        self.phone_number_encrypted = encrypt(value) if value else ""

    def erase_contact(self) -> None:
        """연락처(전화번호·이메일)를 비운다(#171, Withdrawal) — 등록 식별자
        (`seller_id`)와 `status`는 건드리지 않는다. 지급이 끝나야 탈퇴할 수
        있으므로(`Payout.Status.BLOCKS_DEVELOPER_WITHDRAWAL`) 이 값들은 이미
        목적을 다한 개인정보다.

        지울 필드 집합을 이 모델이 소유한다 — 호출부(`accounts.withdrawal`)가
        필드 이름을 손으로 나열하면, 나중에 연락처 성격의 필드가 하나 늘어도
        (예: 우편 주소) 그 호출부를 고치는 것을 잊을 수 있다. `updated_at`
        을 `update_fields` 에 명시한다 — `auto_now`는 `update_fields`에 없는
        필드는 갱신하지 않으므로, 여기서 빠뜨리면 연락처가 지워진 사실이
        `updated_at`에 남지 않는다."""

        self.phone_number_encrypted = ""
        self.email = ""
        self.save(update_fields=["phone_number_encrypted", "email", "updated_at"])
