"""Contest 도메인 모델 (ADR-0001).

`Contest`가 단일 엔티티다 — 요구사항·`Requirement` 체크리스트·`Prize`·기한을 모두
담는다. 재개최는 복제 후 `source_contest`가 원본을 가리키는 방식으로 처리한다
(이 티켓은 draft 개최까지만 다루고, 재개최 자체는 만들지 않는다).

`Category`(산업·장르)와 `DeliverableType`(산출물 종류)은 다른 축이다. 섞지 않는다.
`DeliverableType`은 운영자가 배포 없이 조정할 수 있는 DB 테이블이고 최소 제안 상금을
컬럼으로 갖는다. 복수 선택 시 합산되며, `Prize`가 미달이면 배지가 서지만 등록은 막지
않는다.
"""

from __future__ import annotations
import uuid

from django.conf import settings
from django.db import models


class Category(models.Model):
    """Contest가 속한 산업·장르. DeliverableType과는 다른 축이다."""

    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class DeliverableType(models.Model):
    """만들어야 할 산출물의 종류. 최소 제안 상금을 갖고 복수 선택 시 합산된다.

    배포 없이 운영자가 admin에서 조정할 수 있는 DB 테이블이다.
    """

    name = models.CharField(max_length=100, unique=True)
    minimum_prize = models.PositiveIntegerField(help_text="최소 제안 상금(원)")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} (min {self.minimum_prize:,}원)"


class Contest(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "초안"
        # PUBLISHED 는 #9(결제/Escrow)가 결제 확인 후 이 상태로 전이시킨다.
        PUBLISHED = "published", "공개"
        # CLOSED 는 #11이 core.transitions 레지스트리에 등록한 전이다 — 스케줄러
        # 틱이 deadline_at 이 지난 PUBLISHED Contest 를 조건부 UPDATE 로 옮긴다
        # (ADR-0003). 데모·영상 전면 공개는 이 상태를 기다리지 않고
        # submissions.resolvers 가 deadline_at 을 직접 비교해 이미 판정한다 — 이
        # 상태는 "채점(#12)을 정확히 1회 시작할 지점"과 "운영자가 마감된 Contest를
        # 식별하는 지점"으로 쓰인다. CLOSED에 들어서는 같은 조건부 UPDATE가
        # judging_ends_at(마감 + 7일)도 함께 찍는다(#13) — 심사기간이 여기서 시작된다.
        CLOSED = "closed", "마감"
        # AWARDED 는 #13 — Sponsor가 심사기간(judging_ends_at 이전) 중에 Submission
        # 하나를 Award하면 CLOSED에서 여기로 조건부 UPDATE로 옮긴다. Handover·Escrow
        # 해제·Payout(#14/#15)이 이 상태를 다음 단계의 시작점으로 쓴다.
        AWARDED = "awarded", "선정 완료"
        # JUDGING_ENDED 는 #13이 core.transitions 레지스트리에 등록한 두 번째 전이다
        # — judging_ends_at 이 지날 때까지 아무도 Award하지 않은 CLOSED Contest를
        # 스케줄러 틱이 옮긴다. Award된 Contest는 이미 AWARDED라 이 전이의 from_state
        # 조건(CLOSED)에 걸리지 않는다. Distribution(#16)이 "무응답 14일" 카운트다운의
        # 시작점으로 이 상태를 쓴다.
        JUDGING_ENDED = "judging_ended", "심사기간 종료"

    sponsor = models.ForeignKey(
        "accounts.SponsorProfile", related_name="contests", on_delete=models.CASCADE
    )
    # ledger.JournalEntry.contest_id 는 (#8보다 먼저 만들어진) 불투명 UUID다 — ledger
    # 앱은 손대지 않고(#9의 범위 밖, 이미 리뷰·검증됨) 이 필드로 Contest의 정수 PK와
    # 원장의 UUID 세계를 잇는다. #9가 결제 웹훅을 원장에 분개로 남길 때 이 값을
    # contest_id로 쓴다.
    ledger_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    title = models.CharField(max_length=200)
    category = models.ForeignKey(Category, related_name="contests", on_delete=models.PROTECT)
    deliverable_types = models.ManyToManyField(DeliverableType, related_name="contests")
    description = models.TextField(blank=True)
    prize = models.PositiveIntegerField()
    deadline_at = models.DateTimeField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT)

    # 심사기간 종료 시각 (#13, ADR-0003). CLOSED 전이가 일어나는 조건부 UPDATE 안에서
    # deadline_at + JUDGING_PERIOD_DAYS 로 함께 채워진다. 유료 연장은 이 컬럼만
    # 갱신한다 — 예약된 스캔 규칙(core.transitions 레지스트리)은 그대로 두고 값만
    # 바뀐다. CLOSED로 전이하기 전에는 null이다.
    judging_ends_at = models.DateTimeField(null=True, blank=True)
    # 지금까지 유료로 연장된 횟수. 2회 이상(즉 이 값이 2 이상)이 되는 순간
    # refund_disabled가 영구히 True로 확정된다 — 이 카운트 자체는 감사용으로 계속
    # 늘어난다.
    judging_extension_count = models.PositiveIntegerField(default=0)
    # 2회 이상 연장되면 영구히 True로 확정되는 환불 불가 플래그. 한 번 True가 되면
    # 다시 False로 되돌리는 코드 경로는 없다 — "영구히"의 실제 구현이다.
    refund_disabled = models.BooleanField(default=False)

    # ADR-0001: 재개최는 복제 후 원본을 가리킨다. 이 티켓은 필드만 마련해 두고
    # 재개최 플로우 자체는 만들지 않는다(범위 밖).
    source_contest = models.ForeignKey(
        "self", null=True, blank=True, related_name="reopenings", on_delete=models.SET_NULL
    )

    # 개최 시점의 최소 제안 상금 합계 스냅샷. 이후 운영자가 DeliverableType의
    # 최소 상금을 바꿔도 이미 개최된 Contest의 배지 판단은 흔들리지 않는다.
    required_minimum_prize = models.PositiveIntegerField(default=0)
    is_underfunded = models.BooleanField(default=False)

    # 알림 연결 (#19, ADR-0009/0010): 이 Contest에 대해 각 라이프사이클 알림을 이미
    # 보냈는지 표시한다. null이면 아직 안 보냈다는 뜻이고, 값이 차면 그 시각에
    # (조건부 UPDATE로) 정확히 한 번만 보냈다는 뜻이다 — 스캔이 몇 번 겹쳐 돌아도
    # 중복 발송을 막는 근거가 이 컬럼 자체다(core.transitions.claim_transition과
    # 같은 정신, notifications.lifecycle의 각 send_due_* 스캔이 쓴다).
    deadline_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    judging_end_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    distribution_final_warning_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return self.title

    @property
    def is_published(self) -> bool:
        return self.status == self.Status.PUBLISHED


class Requirement(models.Model):
    """Contest의 심사 체크리스트를 이루는 검증 가능한 한 항목."""

    class Grade(models.TextChoices):
        REQUIRED = "required", "필수"
        OPTIONAL = "optional", "선택"

    contest = models.ForeignKey(Contest, related_name="requirements", on_delete=models.CASCADE)
    text = models.CharField(max_length=500)
    grade = models.CharField(max_length=16, choices=Grade.choices)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return self.text


class JudgingExtensionPayment(models.Model):
    """심사기간 유료 연장 결제 시도 하나 (#13, ADR-0004/0007/0008).

    `payments.models.Payment`와 같은 성격의 모델이다 — PG와의 대화 상태(요청됨/
    완료/실패)만 들고, 완료로 전이하는 순간에만 원장에 분개를 남긴다. `Payment`를
    그대로 재사용하지 않는 이유: `Payment.unique_active_payment_per_contest`는
    Contest 당 결제가 평생 한 번(최초 예치)이라는 전제로 걸려 있는데, 연장은 같은
    Contest에 대해 여러 번 반복될 수 있는 별개의 결제 종류다.

    동시성·재전송에 안전한 이유는 `contests.services.mark_extension_paid`/
    `mark_extension_failed`가 `payments.services.mark_paid`/`mark_failed`와 똑같은
    조건부 `UPDATE ... WHERE status='requested'` 규율을 따르기 때문이다.
    """

    class Status(models.TextChoices):
        REQUESTED = "requested", "요청됨"
        PAID = "paid", "결제완료"
        FAILED = "failed", "결제실패"

    contest = models.ForeignKey(
        "contests.Contest", related_name="judging_extension_payments", on_delete=models.CASCADE
    )
    # PG에 전달하는 주문 참조값.
    order_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # 결제 시점의 스냅샷 — settings.CONTEST_EXTENSION_FEE가 나중에 바뀌어도 이미
    # 요청된 결제 금액은 흔들리지 않는다(Payment.prize_amount와 같은 원칙).
    amount = models.PositiveIntegerField()
    # 이 결제가 성공하면 몇 번째 연장이 되는지의 스냅샷(감사·원장 메모용). 정확한
    # 카운트는 여전히 Contest.judging_extension_count가 조건부 UPDATE로 늘리는
    # 값이 유일한 진실이다 — 이 필드는 그 값을 미리 찍어두는 라벨일 뿐이다.
    extension_number = models.PositiveIntegerField()

    status = models.CharField(max_length=16, choices=Status.choices, default=Status.REQUESTED)

    # 이 결제가 원장에 남긴 분개. 성공 시 정확히 한 번만 채워진다(Payment.journal_
    # entry_id와 같은 원칙).
    journal_entry_id = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # 진행 중인(REQUESTED) 연장 결제는 Contest 당 동시에 하나뿐이어야
            # 한다 — 그렇지 않으면 더블클릭·재요청이 같은 연장을 두 번 결제하게
            # 만든다(Payment.unique_active_payment_per_contest와 같은 방어,
            # #13 리뷰 지적). PAID는 조건에서 뺀다 — Payment와 달리 연장은 한
            # Contest에 여러 번 반복될 수 있는 결제라, 이전 연장이 PAID로 남아
            # 있어도 다음 연장의 새 REQUESTED 생성을 막으면 안 된다.
            models.UniqueConstraint(
                fields=["contest"],
                condition=models.Q(status="requested"),
                name="unique_pending_judging_extension_payment_per_contest",
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"JudgingExtensionPayment(order_id={self.order_id}, status={self.status})"


class RequirementChatMessage(models.Model):
    """AI grill 대화 이력 한 턴 (#20).

    Sponsor가 무엇을 적어야 할지 모르는 상태에서 시작해 여러 턴에 걸쳐 요구사항을
    구체화하는 대화의 원문이다. 이 자체는 확정된 체크리스트가 아니다 — 대화가
    제안한 항목을 Sponsor가 받아들여야 비로소 `Requirement` 행으로 만들어진다
    (`contests.api`의 requirement CRUD 엔드포인트). Contest가 DRAFT를 벗어나면
    더 이상 새 턴을 만들지 않는다(공개된 뒤에는 체크리스트가 흔들리면 안 된다).
    """

    class Role(models.TextChoices):
        SPONSOR = "sponsor", "발주자"
        ASSISTANT = "assistant", "AI"

    contest = models.ForeignKey(
        Contest, related_name="requirement_chat_messages", on_delete=models.CASCADE
    )
    role = models.CharField(max_length=16, choices=Role.choices)
    content = models.TextField()
    # ASSISTANT 턴에만 채워진다 — 그 응답을 만들 때 LLM에 실제로 보낸(또는 보낼)
    # 프롬프트 감사 기록이다. scoring.models.Score.prompt와 같은 목적: Sponsor가
    # 입력한 신뢰할 수 없는 텍스트가 프롬프트 경계 마커를 무력화한 채로 실렸는지
    # 사후에 확인할 수 있다(ADR-0006과 같은 정신의 감사 흔적, 다만 이 대화는
    # append-only 스냅샷은 아니다).
    prompt = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"[{self.role}] {self.content[:30]}"
