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

from payments.charges import ChargeBase


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

    상위 등급 Operator가 `POST /api/operator/deliverable-types`(생성)·
    `POST /api/operator/deliverable-types/{id}`(최소 제안 상금 수정)·
    `POST /api/operator/deliverable-types/{id}/deactivate`(비활성화)로 조정한다
    (#80). admin은 ADR-0019로 내려갔다 — 여기서 "admin에서 조정한다"고 말하던
    시절의 흔적은 이 문장이 마지막이다.

    `PlatformPolicy`(#75~#79)와 달리 단일 행에 들어갈 수 없다 — 종류마다 값이
    다르고 종류 자체가 추가·삭제(정확히는 비활성화)되기 때문이다(ADR-0023).
    지우지 않고 비활성화만 하는 이유는 이미 이 종류로 만들어진 `Contest`가
    있을 수 있어서다 — `Contest.deliverable_types`가 이 행을 참조하는 한 지우면
    그 Contest들의 산출물 종류가 깨진다.
    """

    name = models.CharField(max_length=100, unique=True)
    minimum_prize = models.PositiveIntegerField(help_text="최소 제안 상금(원)")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover
        return f"{self.name} (min {self.minimum_prize:,}원)"


class DeliverableTypeChange(models.Model):
    """`DeliverableType`에 대한 한 번의 변경 사건 — 누가·언제·무엇을·왜 (#80).

    `policies.models.PolicyChange`와 같은 규율이다 — 최소 제안 상금은 "상금미달"
    배지 판정에 그대로 쓰이므로, 그 값을 바꾸는 것도 근거 없이 이루어지면 안
    되는 판단이다. `action`으로 생성·수정·비활성화 세 가지를 구별한다 — 생성은
    `before`가 비어 있고(그 전엔 이 종류 자체가 없었다), 비활성화는 `is_active`
    한 필드만 바뀐다.

    `deliverable_type`은 PROTECT다 — `DeliverableType`은 지워지지 않고
    비활성화만 되므로 이 참조가 끊길 일은 정상 경로에 없지만, `PolicyChange.
    operator`·`AppealRuling.ruled_by`와 같은 원칙을 그대로 지킨다. `operator`도
    PROTECT — 바꾼 계정을 지워도 감사 기록이 주인을 잃지 않는다.
    """

    class Action(models.TextChoices):
        CREATED = "created", "생성"
        UPDATED = "updated", "수정"
        DEACTIVATED = "deactivated", "비활성화"

    deliverable_type = models.ForeignKey(
        DeliverableType, related_name="changes", on_delete=models.PROTECT
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="deliverable_type_changes", on_delete=models.PROTECT
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    reason = models.TextField()
    before = models.JSONField()
    after = models.JSONField()
    changed_at = models.DateTimeField()

    class Meta:
        verbose_name = "산출물 종류 변경 이력"
        verbose_name_plural = "산출물 종류 변경 이력"
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"DeliverableTypeChange({self.action}, deliverable_type_id={self.deliverable_type_id})"


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
    # deadline_at + PlatformPolicy.judging_period_days(#78/ADR-0023)로 함께
    # 채워진다. 유료 연장은 이 컬럼만
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
        indexes = [
            # 스케줄러 틱(core.transitions.run_due_transitions)이 60초마다 도는 두
            # 스캔의 WHERE 절이 그대로 타는 인덱스다. 규칙은 contests/apps.py 가
            # 등록하고, 각각 (status, deadline_at) 과 (status, judging_ends_at) 을
            # 함께 건다.
            #
            # 인덱스가 없으면 그 둘이 매 틱마다 전체 테이블 순차 스캔이 된다 —
            # `EXPLAIN` 으로 실제로 확인했다(Seq Scan on contests_contest). 지금
            # 규모에서는 수 ms 라 아프지 않지만, transitions.py 가 배치 상한을
            # 두면서 남긴 주석("인덱스가 있어도 무제한 스캔은 …")은 인덱스가
            # 있다는 전제로 쓰였는데 실제로는 없었다. notifications 는 같은 모양의
            # 주기 스캔에 대해 이미 이 인덱스를 갖고 있다(notif_status_sched_idx)
            # — 여기서 그 관용구를 맞춘다.
            models.Index(fields=["status", "deadline_at"], name="contest_status_deadline_idx"),
            models.Index(
                fields=["status", "judging_ends_at"], name="contest_status_judgeend_idx"
            ),
        ]

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


class JudgingExtensionPayment(ChargeBase):
    """심사기간 유료 연장 결제 시도 하나 (#13, #126, ADR-0004/0007/0008).

    Charge(CONTEXT.md)의 한 종류다 — `payments.models.Payment`(Prize 예치+개최비)와
    같은 뼈대(`payments.charges.ChargeBase`)를 상속하고, 이 종류에 고유한 둘만 준다:
    분개의 줄(`journal`)과 확정에 딸려오는 부모 전이(`on_paid` — 심사기간 연장). `Payment`
    를 그대로 재사용하지 않는 이유: `Payment.unique_active_payment_per_contest`는 Contest
    당 결제가 평생 한 번(최초 예치)이라는 전제로 걸려 있는데, 연장은 같은 Contest에 대해
    여러 번 반복될 수 있는 별개의 결제 종류다.

    동시성·재전송에 안전한 이유는 `payments.charges.apply_vendor_outcome` 이 조건부
    `UPDATE ... WHERE status='requested'` 규율(ADR-0003)로 딱 한 번만 이기기 때문이다.
    """

    contest = models.ForeignKey(
        "contests.Contest", related_name="judging_extension_payments", on_delete=models.CASCADE
    )

    # 결제 시점의 스냅샷 — PlatformPolicy.judging_extension_fee(#78/ADR-0023)가
    # 나중에 바뀌어도 이미 요청된 결제 금액은 흔들리지 않는다(Payment.prize_amount와
    # 같은 원칙).
    amount = models.PositiveIntegerField()
    # 결제 시점(initiate)의 PlatformPolicy.judging_extension_days 스냅샷
    # (#78 코드리뷰 지적 2) — amount와 짝을 이루는 값. initiate와 confirm 사이에
    # 운영자가 judging_extension_days를 바꾸면 amount는 옛 금액 그대로 청구되는데
    # 심사기간은 새 값만큼만 늘어나는 불일치가 생긴다 — Sponsor가 낸 돈과 실제로
    # 받는 연장 길이가 항상 같은 시점의 정책을 가리키도록 이 필드가 그 값을
    # initiate 시점에 확정한다.
    extension_days = models.PositiveIntegerField()
    # 이 결제가 성공하면 몇 번째 연장이 되는지의 스냅샷(감사·원장 메모용). 정확한
    # 카운트는 여전히 Contest.judging_extension_count가 조건부 UPDATE로 늘리는
    # 값이 유일한 진실이다 — 이 필드는 그 값을 미리 찍어두는 라벨일 뿐이다.
    extension_number = models.PositiveIntegerField()

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

    @property
    def charged_amount(self) -> int:
        return self.amount

    def journal(self):
        from ledger.models import Account, EntrySide
        from ledger.services import LineInput

        return (
            self.contest.ledger_id,
            (
                f"Contest #{self.contest_id} 심사기간 연장 {self.extension_number}회차 — "
                f"{self.amount:,}원"
            ),
            [
                LineInput(account=Account.SPONSOR_DEPOSIT, side=EntrySide.DEBIT, amount=self.amount),
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE, side=EntrySide.CREDIT, amount=self.amount
                ),
            ],
        )

    def on_paid(self) -> None:
        """이겼을 때만, 분개와 같은 트랜잭션 안에서 심사기간을 늘린다.

        결제가 확정되는 사이(initiate → confirm) Award되었거나 이미 심사기간이
        종료됐다면 더 늘릴 대상이 없다. 그 경우에도 분개는 그대로 남는다 — Sponsor가 낸
        돈이 대사 가능한 흔적으로 남아야 하기 때문이다(#13 리뷰 지적 1). 그 돈의 처리
        (환불 등)는 별도다(#17/#22).
        """

        from datetime import timedelta

        from core.clock import Clock
        from core.transitions import claim_transition

        contest = Contest.objects.select_for_update().get(pk=self.contest_id)
        if contest.status != Contest.Status.CLOSED or contest.judging_ends_at is None:
            return

        new_count = contest.judging_extension_count + 1
        # 여기서 정책을 다시 읽지 않는다(#78 코드리뷰 지적 2) — extension_days 는
        # initiate 시점에 amount 와 함께 스냅샷된 값이다.
        new_judging_ends_at = contest.judging_ends_at + timedelta(days=self.extension_days)

        # claim_transition을 그대로 재사용한다 — from/to 가 둘 다 CLOSED인 "제자리"
        # 전이이지만, ① WHERE status='closed' 조건부 UPDATE 규율을 한 번 더 지키고
        # ② auto_now 필드(updated_at)를 이 메커니즘이 채워준다(#13 리뷰 지적 6).
        claim_transition(
            Contest,
            contest.pk,
            from_state=Contest.Status.CLOSED,
            to_state=Contest.Status.CLOSED,
            state_field="status",
            now=Clock.now(),
            extra_fields={
                "judging_ends_at": new_judging_ends_at,
                "judging_extension_count": new_count,
                "refund_disabled": contest.refund_disabled or new_count >= 2,
                # 심사기간 종료 임박 알림(#19)이 이미 발송된 뒤에 연장되면 이 표식을
                # 비워야 새 종료일이 다가올 때 다시 알릴 수 있다(#19 리뷰 지적 1).
                "judging_end_reminder_sent_at": None,
            },
        )


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
