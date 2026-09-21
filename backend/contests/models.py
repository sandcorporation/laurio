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
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone

from core.classification import Classification
from core.clock import Clock

from payments.charges import ChargeBase
from submissions.models import Submission


class Category(models.Model):
    """Contest가 속한 산업·장르. DeliverableType과는 다른 축이다.

    운영자 앱이 `POST /operator/categories`(생성)·`POST /operator/categories/{id}`
    (이름 수정)·`POST /operator/categories/{id}/deactivate`(감추기)로 조정한다
    (#231, ADR-0023 준용). admin은 ADR-0019로 내려갔다. `DeliverableType`과 같은
    무게로 다룬다 — 최소 제안 상금 같은 정책값은 없지만, 공개 목록의 분류 축이고
    `Contest.category`가 PROTECT로 참조를 붙드는 것은 같다.

    지우지 않고 비활성화(`is_active=False`)만 하는 이유도 `DeliverableType`과
    같다 — 이미 이 Category로 열린 `Contest`가 있을 수 있어서다.
    """

    name = models.CharField(max_length=100, unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:  # pragma: no cover
        return self.name


class CategoryChange(models.Model):
    """`Category`에 대한 한 번의 변경 사건 — 누가·언제·무엇을·왜 (#231).

    `DeliverableTypeChange`와 같은 규율이다(ADR-0023 준용) — Category는
    공개 목록의 분류 축이고 Contest가 참조를 붙들고 있어 조용히 바뀌면
    안 되는 무게가 있다. `action`으로 생성·이름 수정·비활성화 세 가지를
    구별한다. `category`는 PROTECT다 — 이 이력이 참조를 잃지 않는다.
    """

    class Action(models.TextChoices):
        CREATED = "created", "생성"
        UPDATED = "updated", "수정"
        DEACTIVATED = "deactivated", "비활성화"

    category = models.ForeignKey(Category, related_name="changes", on_delete=models.PROTECT)
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="category_changes", on_delete=models.PROTECT
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    reason = models.TextField()
    before = models.JSONField()
    after = models.JSONField()
    changed_at = models.DateTimeField()

    class Meta:
        verbose_name = "카테고리 변경 이력"
        verbose_name_plural = "카테고리 변경 이력"
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"CategoryChange({self.action}, category_id={self.category_id})"


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


class HostingPermission(models.Model):
    """계정별 「무료 공모전 개최 권한」의 지금 상태 (#414, ADR-0048, CONTEXT.md
    「개최 권한」).

    유료 공모전에서는 결제가 개최를 걸러 준다 — 무료 공모전에는 그 문이 없으므로
    Operator가 계정별로 이 값을 켜고 끈다(예전 AssignmentPermission과 같은
    판단, ADR-0048 참고). 계정마다 최대 한 행이고 **지금 값**만 갖는다 — 「누가·
    언제·왜 바꿨는가」는 append-only인 `HostingPermissionChange`가 따로 남긴다
    (`PolicyChange`·`DeliverableTypeChange`와 같은 분리 — 현재값과 이력을 같은
    행에 두면 이력에 UPDATE가 생긴다).

    행이 아예 없는 계정은 권한이 없는 것과 같다 — `create`가 아니라 `get_or_
    create`로 다룬다(`hosting_permission_services.set_hosting_permission`).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="hosting_permission", on_delete=models.CASCADE
    )
    is_granted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"HostingPermission<{self.user_id}>({'on' if self.is_granted else 'off'})"


class HostingPermissionChange(models.Model):
    """`HostingPermission`에 대한 한 번의 변경 사건 — 누가·언제·누구를·왜 (#414,
    ADR-0023).

    `DeliverableTypeChange`·`CategoryChange`와 같은 규율이다 — 부여·회수 둘 다
    사유가 필수다. `user`는 권한이 바뀐 그 계정, `operator`는 바꾼 운영자다.
    둘 다 PROTECT — 계정이 지워져도(탈퇴는 `is_active=False`일 뿐 행 삭제가
    아니다, ADR-0025) 감사 기록이 주인을 잃지 않는다.
    """

    class Action(models.TextChoices):
        GRANTED = "granted", "부여"
        REVOKED = "revoked", "회수"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="hosting_permission_changes", on_delete=models.PROTECT
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="hosting_permission_changes_made",
        on_delete=models.PROTECT,
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    reason = models.TextField()
    changed_at = models.DateTimeField()

    class Meta:
        verbose_name = "개최 권한 변경 이력"
        verbose_name_plural = "개최 권한 변경 이력"
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"HostingPermissionChange({self.action}, user_id={self.user_id})"


class ContestQuerySet(models.QuerySet):
    """Contest 의 시간 창을 필터로 묻는 짝 (#143, #124). 파이썬 술어(`Contest.judging_window_open`
    등)와 이름이 같고 뜻이 같아야 한다 — 둘의 일치는 tests/test_contest_windows.py 가 경계값
    픽스처(직전·경계·직후)로 지킨다."""

    def judging_window_open(self, now):
        return self.filter(judging_ends_at__gt=now)

    def appeal_window_open(self, now):
        return self.filter(Q(judging_ends_at__isnull=True) | Q(judging_ends_at__gt=now))

    def distribution_due(self, as_of, policy):
        from distributions.services import distribution_due_q

        return self.filter(distribution_due_q(as_of, policy))


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
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)

    # 무료 공모전인가 (#415, ADR-0048) — 돈을 다루지 않는다. 결제·본인확인
    # 없이 개최 권한(`HostingPermission`)만으로 공개하고(`publish-free`
    # 전이, contests/transitions.py), 마감 뒤 Award는 만들되 Handover·
    # Escrow 해제·Distribution은 만들지 않는다(#417). `prize`는 무료
    # 공모전에서 항상 0이고 `required_minimum_prize`/`is_underfunded`도
    # 항상 0/False다 — 상금 개념 자체가 없다.
    is_free = models.BooleanField(default=False)

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

    # 누적 조회수 (#446, spec #444, `CONTEXT.md`의 ContestView). 이 칸 자체는
    # 요청마다 갱신되지 않는다 — Redis가 실시간으로 세고(`contests.view_tracking`),
    # 바뀐 공모전만 `contest-view-flush` 스캔이 10분마다 이리로 옮긴다
    # (`contests.view_flush`). 그래서 개최자 지표 화면·공개 목록·큐레이션이
    # 이 칸을 읽으면 서로 항상 같은 숫자를 보고(최대 10분 늦음), 서버 재시작·
    # 캐시 비움 뒤에도 0으로 돌아가지 않는다.
    view_count = models.PositiveIntegerField(default=0)

    # 알림 연결 (#19, ADR-0009/0010): 이 Contest에 대해 각 라이프사이클 알림을 이미
    # 보냈는지 표시한다. null이면 아직 안 보냈다는 뜻이고, 값이 차면 그 시각에
    # (조건부 UPDATE로) 정확히 한 번만 보냈다는 뜻이다 — 스캔이 몇 번 겹쳐 돌아도
    # 중복 발송을 막는 근거가 이 컬럼 자체다(core.transitions.claim_transition과
    # 같은 정신, contests.lifecycle_notifications의 각 스캔이 쓴다).
    deadline_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    judging_end_reminder_sent_at = models.DateTimeField(null=True, blank=True)
    distribution_final_warning_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            # 스캔 등록부(core.scans)의 두 Contest 스캔이 60초마다 도는데 그
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

    objects = ContestQuerySet.as_manager()

    def __str__(self) -> str:  # pragma: no cover
        return self.title

    @property
    def is_published(self) -> bool:
        return self.Status.SUBMITTABLE(self.status)

    # --- 시간 창 (#143, #124) — Contest 가 자기 시간 창을 안다 ---------------------------------
    #
    # 「이 사람이 지금 무엇을 해야 하는가」를 판정하는 번역기(sponsorship·participation)와 그 행위
    # 엔드포인트의 409/403 가드(awards.api·contests.api 연장)가 **같은 메서드**를 부른다 — 조건을
    # 두 벌로 쓰면 언젠가 갈라지고, 그때 화면은 시키는 대로 한 사용자에게 409 를 보여준다.
    # 경계는 스케줄러와 같다: `judging_ends_at <= as_of` 이면 CLOSED -> JUDGING_ENDED 로 옮기므로,
    # 심사 창은 now 가 judging_ends_at 과 같아지는 순간부터 이미 닫혀 있다(#13 리뷰 지적 7).

    def judging_window_open(self, now) -> bool:
        """Sponsor 가 Award·심사기간 연장을 할 수 있는 시간 창. 심사기간이 아직 없으면(CLOSED 전이가
        judging_ends_at 을 찍기 전) 닫혀 있다 — 행위 엔드포인트가 그렇게 거부해 왔고, 번역기도
        같은 답을 해야 「심사하세요」라고 해놓고 403 이 나는 일이 없다."""

        return self.judging_ends_at is not None and now < self.judging_ends_at

    def appeal_window_open(self, now) -> bool:
        """Developer 가 이의를 낼 수 있는 시간 창 = 심사 창의 끝과 같은 시각(#74) — 그래서 Sponsor 의
        유료 연장이 이의 창도 늘린다. 그 결합이 한 파일에 보이도록 여기 둔다. 심사기간이 없는
        Contest 는 창이 닫히지 않는다(`SubmissionDetailOut.appeal_deadline` 이 그렇게 약속한다) —
        심사 창과 다른 점이다.

        심사기간이 없는 Contest 는 창이 닫히지 않는다."""

        return self.judging_ends_at is None or now < self.judging_ends_at

    def distribution_due(self, as_of, policy) -> bool:
        """무응답 배분의 차례가 됐는가 — `distributions.services.distribution_due_q` 의 파이썬 짝."""

        return (
            self.Status.AWAITING_DISTRIBUTION(self.status)
            and self.judging_ends_at is not None
            and self.judging_ends_at <= as_of - timedelta(days=policy.distribution_wait_days)
            and getattr(self, "distribution", None) is None
        )



class HomeStatusAxis(models.TextChoices):
    """홈 큐레이션 버킷의 status 축 (#94, #141) — status 만으로 정해지는 부분. OPEN 은 마감 시각이
    마저 갈라 ONGOING·IMMINENT·IN_JUDGING 중 하나가 되고(`contests.curation.home_bucket_for`),
    HIDDEN 은 어느 묶음에도 들어가지 않는다."""

    OPEN = "open", "공개 중"
    IN_JUDGING = "in_judging", "심사중"
    COMPLETED = "completed", "완료"
    HIDDEN = "hidden", "숨김"


# --- Contest.Status 가 소유하는 분류 (#141, #121, #207) ----------------------------------------
#
# 질문마다 일곱 값 전부에 명시적으로 답한다. 집합은 여기서 파생되고(`.statuses`), 단일값 비교도
# 질문으로 한다 — 값이 하나 끼어들면(예: 심사 중 PAUSED) `== CLOSED` 자리들이 조용히 False 가
# 되는 것을 tests/test_status_classification.py 의 키 집합 단언이 막는다. 값 집합의 내용은 이관 전과
# 같다(#121 — 같은 질문에 다른 집합을 쓰는 곳은 없었다).
#
# ASSIGNMENT_OPEN·ASSIGNMENT_CLOSED(#207, ADR-0028)는 이 표(스펙 #197)를 그대로 옮긴 것이다 —
# 등록된 스캔 21개 중 19개가 이 선언만으로 Assignment 를 비켜간다. 상금·결제·Award·Escrow·
# Distribution·라이프사이클 알림·탈퇴 시 실명 보존, 그 무엇도 Assignment 에는 없으므로 그 전부를
# False 로 못 박는다 — 결제가 서 있던 자리를 Sponsor 의 명시적 「열기」가 대신할 뿐이다(EDITABLE·
# SUBMITTABLE 만 True).
_S = Contest.Status

# 마감(#11) 이후에도 계속 공개로 남는다 — CLOSED 뿐 아니라 AWARDED·JUDGING_ENDED 도(#13).
# Assignment 는 열려도 마감돼도 절대 나오지 않는다 — InviteCode 를 아는 사람만 본다(ADR-0028).
Contest.Status.PUBLICLY_VISIBLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: True,
        _S.CLOSED: True,
        _S.AWARDED: True,
        _S.JUDGING_ENDED: True,
    },
    question="공개 목록·상세에 보이는가",
)
# 결제로 공개됐거나(공모전) 명시적으로 열렸고(Assignment) 아직 마감 전이가 안 됐다 — 제출·수정의
# status 전제(시각은 따로 본다).
Contest.Status.SUBMITTABLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: True,
        _S.CLOSED: False,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="status 상 제출을 받는가",
)
# 라이프사이클 알림(마감 임박 등)을 보내는 status 인가 — 프리팩터(#205, ADR-0028)로 SUBMITTABLE 에서
# 떼어냈다. 「제출을 받는가」와 「통지를 보내는가」는 지금까지 우연히 같은 답이었을 뿐 같은 질문이
# 아니었고, Assignment 가 그 갈라짐의 실제 이유다 — Assignment 는 본인확인이 없어 연락처
# (`accounts.PhoneContact`)가 없는 수신자가 섞이므로(ADR-0029) 통지를 보내지 않아야 하지만,
# 제출은 받는다(위 SUBMITTABLE). ASSIGNMENT_OPEN 을 여기서 False 로 두지 않으면 dev·테스트에서는
# 안 보이고 프로덕션에서만 실패한 NotificationDispatch 가 제출자마다 쌓인다(ADR-0028 이 적어 둔
# 함정 그대로).
Contest.Status.SENDS_LIFECYCLE_NOTICES = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: True,
        _S.CLOSED: False,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="라이프사이클 알림을 보내는 status 인가",
)
# CLOSED 뿐 아니라 AWARDED·JUDGING_ENDED 도(#13) — Award 는 Score 를 기다리지 않으므로 채점이 끝나기
# 전에 CLOSED 를 벗어날 수 있다. CLOSED 만 보면 그 순간 미채점 Submission 이 영원히 빠진다.
# ASSIGNMENT_CLOSED 도 True — Assignment 의 채점은 이 상태로만 진입한다(Award 가 없어 갈아탈 다른
# 경로가 없다).
Contest.Status.SCOREABLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: False,
        _S.CLOSED: True,
        _S.AWARDED: True,
        _S.JUDGING_ENDED: True,
    },
    question="채점 스캔의 대상인가",
)
# 심사 창 안에서만 — 시각(judging_ends_at)은 따로 본다. Assignment 는 Award 자체가 없다.
Contest.Status.AWARDABLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: False,
        _S.CLOSED: True,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="status 상 Award 할 수 있는가",
)
# PUBLISHED·DRAFT 는 심사기간 자체가 없고, AWARDED·JUDGING_ENDED 는 더 늘릴 대상이 없다. Assignment
# 는 심사기간이라는 개념 자체가 없다 — judging_ends_at 을 영원히 null 로 둔다.
Contest.Status.JUDGING_EXTENDABLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: False,
        _S.CLOSED: True,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="심사기간을 연장할 수 있는가",
)
# 참여자 0명 전액 환불의 status 전제 — JUDGING_ENDED 도(#13 뒤 남아 있던 격차). 스케줄러가
# judging_ends_at 이 지나면 CLOSED -> JUDGING_ENDED 로 무조건 옮기므로, CLOSED 만 보면 그 순간부터
# Prize 가 Escrow 에 갇힌다. 참가자 없음·refund_disabled 는 payments 가 따로 본다. Assignment 에는
# Prize 도 Escrow 도 없다 — 환불할 것이 없다.
Contest.Status.REFUNDABLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: False,
        _S.CLOSED: True,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: True,
    },
    question="참여자 0명 환불의 status 전제를 만족하는가",
)
# 유찰된 Contest 의 재개최 — 같은 이유로 JUDGING_ENDED 도. 실제 판정 근거는 REFUNDED Payment 다.
# Assignment 에는 결제 자체가 없어 REFUNDED Payment 가 존재할 수 없다.
Contest.Status.REOPENABLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: False,
        _S.CLOSED: True,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: True,
    },
    question="재개최할 수 있는 status 인가",
)
# 결제 전이라 고칠 수 있고, 결제를 (다시) 시작할 수 있다 — 공모전은 DRAFT 뿐이다. Assignment 는
# ASSIGNMENT_OPEN 도 True — 「고칠 수 있다」의 절반이다(스펙 #197): 나머지 절반(제출 0건)은 #209 가
# 얹는 술어다. 문을 닫는 것은 결제가 아니라 첫 제출이라는 것이 ADR-0028 의 핵심이다.
Contest.Status.EDITABLE = Classification(
    {
        _S.DRAFT: True,
        _S.PUBLISHED: False,
        _S.CLOSED: False,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="초안으로서 고칠 수 있는가",
)
# 제출을 받는 동안(published)에도 브리프·요구사항을 고칠 수 있다(#473, ADR-0051) —
# `EDITABLE`(DRAFT뿐)과 다른 질문이다. 마감 뒤(CLOSED 이후)에는 채점 스냅샷(Score)이
# 이미 그 체크리스트를 근거로 만들어졌으므로 잠근다(ADR-0006). `prize`는 이 질문이
# 열어주는 대상이 아니다 — 결제·Escrow가 이미 확정한 금액이라 여기서 다시 열지
# 않는다(`contests.api._get_owned_content_editable_contest`가 이 질문을 쓰고,
# `update_contest`가 prize는 별도로 status==DRAFT 조건으로 다시 막는다).
Contest.Status.CONTENT_EDITABLE = Classification(
    {
        _S.DRAFT: True,
        _S.PUBLISHED: True,
        _S.CLOSED: False,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="제출을 받는 동안 개최자가 브리프·요구사항을 고칠 수 있는가",
)
# Assignment 는 결제 자체가 없다 — DRAFT 를 벗어나는 사건이 Sponsor 의 「열기」다.
Contest.Status.PAYABLE = Classification(
    {
        _S.DRAFT: True,
        _S.PUBLISHED: False,
        _S.CLOSED: False,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="Prize 결제를 시작할 수 있는가",
)
# 진행 중인 거래 — Sponsor 는 이 상태의 Contest 가 있으면 탈퇴할 수 없다(ADR-0025, #142 가 쓴다).
# Assignment 는 돈이 걸리지 않은 활동이라 계정을 붙잡지 않는다(스펙 #197 user story 19) — 열려
# 있어도 탈퇴를 막지 않는다.
Contest.Status.BLOCKS_SPONSOR_WITHDRAWAL = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: True,
        _S.CLOSED: True,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: False,
    },
    question="Sponsor 의 탈퇴를 막는 진행 중 거래인가",
)
# Award 가 이미 확정됐다 — 두 번째 Award 는 409 다. Assignment 에는 Award 자체가 없다.
Contest.Status.HAS_AWARD = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: False,
        _S.CLOSED: False,
        _S.AWARDED: True,
        _S.JUDGING_ENDED: False,
    },
    question="Award 가 이미 확정됐는가",
)
# 심사기간이 Award 없이 끝나 「무응답 N일」 카운트다운 중이다 — Distribution 의 대상 status.
# Assignment 에는 Distribution 자체가 없다.
Contest.Status.AWAITING_DISTRIBUTION = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: False,
        _S.CLOSED: False,
        _S.AWARDED: False,
        _S.JUDGING_ENDED: True,
    },
    question="Distribution 을 기다리는가",
)
# 탈퇴 후 실명·생년월일을 RetainedIdentity 로 보존할 법적 의무를 낳는 거래가 있었는가
# (전자상거래법상 거래기록 보존) — accounts.withdrawal._transaction_basis 의 유일한 소비처가
# 실제로 묻는 질문은 이것이다. 공모전은 "결제 확인"과 답이 같다 — Contest 가 DRAFT 를 벗어나는
# 유일한 경로가 결제 확인이기 때문이다. Assignment 는 결제 없이 DRAFT 를 벗어나므로 여기서 갈라진다
# — 과제만 연 사람은 실명을 보존할 의무가 없다(오히려 보존하면 과잉 보관이다, ADR-0028). 이름이
# "결제가 있었는가"가 아니라 이 질문을 말하는 이유가 바로 이것이다 — 이름을 그대로 뒀다면
# ASSIGNMENT_OPEN 을 True 로 적는 실수가 나기 쉬웠다.
Contest.Status.REQUIRES_IDENTITY_RETENTION = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: True,
        _S.CLOSED: True,
        _S.AWARDED: True,
        _S.JUDGING_ENDED: True,
    },
    question="탈퇴 후 실명 보존 의무를 낳는 거래가 있었는가",
)
# 홈 큐레이션의 status 축(#94). PUBLISHED 는 마감 시각이 마저 가른다. Assignment 는 어느 홈 묶음에도
# 들어가지 않는다 — DRAFT 와 같은 HIDDEN.
Contest.Status.HOME_AXIS = Classification(
    {
        _S.DRAFT: HomeStatusAxis.HIDDEN,
        _S.PUBLISHED: HomeStatusAxis.OPEN,
        _S.CLOSED: HomeStatusAxis.IN_JUDGING,
        _S.AWARDED: HomeStatusAxis.COMPLETED,
        _S.JUDGING_ENDED: HomeStatusAxis.COMPLETED,
    },
    question="홈의 어느 묶음 축에 속하는가",
)
# 제출 시 본인확인·자전거래 검사가 필요한가(#208) — `submissions.api`의 create_submission·
# update_submission이 쓴다. 이 질문이 실제로 갈리는 두 값은 SUBMITTABLE과 같은 PUBLISHED·
# ASSIGNMENT_OPEN뿐이지만(다른 값은 애초에 제출 자체가 막힌다, SUBMITTABLE 참고), 이
# Classification은 "질문마다 모든 값에 명시적으로 답한다"는 규율을 그대로 따른다 — 예전에
# `contest.status in ASSIGNMENT_STATUSES`(bare frozenset 멤버십)로 흩어져 있던 코드였는데,
# `core.classification`의 module docstring이 정확히 이 모양(호출부마다 손으로 쓴 집합)이
# 이 저장소에서 이미 세 번 회귀를 냈다고 적어 두고 있다 — 새 status가 생겨도 멤버십 검사
# 여러 곳 중 하나를 빠뜨리면 조용히 틀린다. 값 자체는 PUBLICLY_VISIBLE과 같은 네 값에서
# True다(공모전 계열 status 전부) — REQUIRES_IDENTITY_RETENTION과 마찬가지로 우연이다,
# 질문이 다르다.
Contest.Status.SUBMISSION_REQUIRES_VERIFICATION = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: True,
        _S.CLOSED: True,
        _S.AWARDED: True,
        _S.JUDGING_ENDED: True,
    },
    question="제출 시 본인확인·자전거래 검사가 필요한가",
)
# 본인 제출을 조회할 수 있는 status 인가(#208) — `submissions.api._get_viewable_contest_or_404`
# (GET .../submissions/me)가 쓴다. PUBLICLY_VISIBLE과 달리 두 Assignment status 도 True다 —
# 익명·타인에게는 계속 숨어 있어도(ADR-0028) 실제로 그 InviteCode 로 제출한 본인은 자기
# 제출을 마감 전후 가리지 않고 계속 읽을 수 있어야 한다. DRAFT 만 False 다 — 그 상태에서는
# 어느 종류든 Submission 이 존재할 수 없다(제출은 SUBMITTABLE 을 통과해야만 생긴다).
Contest.Status.OWN_SUBMISSION_VIEWABLE = Classification(
    {
        _S.DRAFT: False,
        _S.PUBLISHED: True,
        _S.CLOSED: True,
        _S.AWARDED: True,
        _S.JUDGING_ENDED: True,
    },
    question="본인 제출을 조회할 수 있는 status 인가",
)
del _S


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


class ContestChange(models.Model):
    """Contest 브리프·요구사항에 대한 한 번의 변경 사건 — 누가·언제·무엇을·무엇으로
    (#473, ADR-0051).

    `DeliverableTypeChange`·`CategoryChange`와 같은 규율(ADR-0023 준용)이다.
    **제출을 받는 동안(published)에 고친 것만 남긴다** — DRAFT는 아직 아무도
    그 조건을 보고 참가하지 않았으니 감사 흔적으로서의 무게가 없다
    (`contests.api._record_contest_change`가 이 조건을 본다). `action`이
    브리프 수정과 요구사항 추가·수정·삭제를 구별한다 — 브리프 수정의
    `before`/`after`는 바뀐 필드만 담는 dict이고, 요구사항 이벤트는 그
    요구사항 한 항목의 스냅샷(추가·수정은 `after`, 삭제는 `before`)을 담는다.

    `contest`는 CASCADE다 — `DeliverableType`과 달리 이 이력은 그 Contest를
    벗어나서는 뜻이 없고, e2e·데모 시드의 재시드 정리(`seed_e2e_contests`·
    `seed_demo_contests`가 이름 접두어로 걸러 `Contest.objects.filter(...).
    delete()`한다)가 그 Contest를 지울 때 함께 지워져야 한다. 「누가 바꿨는가」는
    별도 FK로 남기지 않는다 — 이 표면은
    소유자(`contests.api._get_owned_contest`)만 통과하므로 항상
    `contest.sponsor`와 같고, 감사 목적의 이중 기록이 아니라 중복이 된다.
    """

    class Action(models.TextChoices):
        UPDATED = "updated", "브리프 수정"
        REQUIREMENT_ADDED = "requirement_added", "요구사항 추가"
        REQUIREMENT_UPDATED = "requirement_updated", "요구사항 수정"
        REQUIREMENT_REMOVED = "requirement_removed", "요구사항 삭제"

    contest = models.ForeignKey(Contest, related_name="changes", on_delete=models.CASCADE)
    action = models.CharField(max_length=32, choices=Action.choices)
    before = models.JSONField()
    after = models.JSONField()
    changed_at = models.DateTimeField()

    class Meta:
        verbose_name = "공모전 변경 이력"
        verbose_name_plural = "공모전 변경 이력"
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ContestChange({self.action}, contest_id={self.contest_id})"


class ContestImage(models.Model):
    """Sponsor가 Contest에 붙이는 참고 이미지 (#234, ADR-0032). CONTEXT.md 「ContestImage」.

    `object_key`는 공개 이미지 버킷(`storage.adapters.base.Bucket.PUBLIC_IMAGES`)에
    사는 오브젝트를 가리킨다 — 브라우저가 presigned POST로 그 버킷에 직접 올린 뒤,
    이 행이 그 object_key를 기록해 Contest와 순서를 붙인다.

    **`thumbnail_key`·`detail_key`는 #235가 스캔으로 만드는 파생본이다(ADR-0031/
    0032).** 업로드 직후에는 둘 다 비어 있고, 그동안은 `url`/`thumbnail_url`
    프로퍼티가 원본으로 대신 답한다 — 화면이 "최적화됐는가"를 판정하지 않는다.
    **둘은 함께 성립한다.** `optimize_derivatives`(image_optimization.py)가 스캔
    한 회차 안에서 두 오브젝트를 쓴 뒤 두 필드를 **한 UPDATE**로 같이 채운다 — 한
    종만 성공한 중간 상태를 이 모델이 표현할 수 없게 한다. 파생본 object_key는
    원본 object_key에서 결정적으로 파생되므로(`{object_key}-thumbnail.webp` 등)
    재시도가 매번 같은 자리를 덮어써, 실패한 시도가 고아 오브젝트를 남기지 않는다.

    **`optimization_failed_at`이 채워지면 「최적화 불가」로 확정된 것이다**
    (#235, ADR-0031) — 실패가 `IMAGE_OPTIMIZATION_FAILURE_LIMIT`회에 이르고
    **동시에** `created_at` 이후 `IMAGE_OPTIMIZATION_FAILURE_GRACE`가 지나야
    확정된다(scoring의 `_scoring_cap_reached`와 같은 이유 — 스토리지가 잠깐
    흔들린 것만으로 되돌릴 수 없는 실패로 굳지 않는다). 확정된 뒤에도 원본은
    계속 보인다 — 이 행이 사라지지도, 원본 object_key가 지워지지도 않는다.
    `optimization_error`가 가장 최근 실패 사유를 들고 있어 나중에 "왜"에 답할
    수 있다. 시도 이력 자체는 `ContestImageOptimizationAttempt`에 쌓인다 — 카운터를
    이 행에 직접 두지 않는 이유는 `scoring.models.ScoringAttempt`와 같다: 카운터
    증가와 이력 생성이 갈리는 순간 진실이 둘이 된다. 이력이 유일한 원천이다.

    `created_at`은 `auto_now_add`가 아니라 `Clock.now()`를 기본값으로 쓴다(ADR-0003)
    — 실제 벽시계가 아니라 이 저장소의 주입 가능한 시계를 따라야, 위 유예 판정을
    테스트가 `ClockOverride`로 앞당길 수 있다(`changed_at=Clock.now()` 등 이
    저장소 전역의 관용구와 같다).

    편집 게이트는 Requirement와 똑같다 — `contests.api._get_owned_draft_contest`
    (소유자 + status==DRAFT)가 이미지 추가·순서 변경·제거를
    함께 지킨다. 이미지도 Contest의 조건이므로 결제가 문을 닫으면 더 이상 손댈 수
    없다(spec #225 "결제가 이미지도 닫는다").

    **빼는 것은 이 행만 지우는 일이다 — object_key가 가리키는 바이트는 지우지
    않는다.** 어댑터에 삭제 메서드가 없다(ADR-0005/0032가 의도적으로 뺐다). 재개최
    (#236)가 같은 object_key를 가리키는 새 행을 만들 수 있으므로, 실제로 오브젝트를
    지우면 원본 Contest의 이미지가 깨진다. 파생본도 같은 이유로 지우지 않는다.
    """

    contest = models.ForeignKey(Contest, related_name="images", on_delete=models.CASCADE)
    # 공개 이미지 버킷의 오브젝트 키. storage/api.py의 object_key 상한(600자
    # 이하 — "<target_ref>/<32자리 hex>")과 같은 여유를 둔다.
    object_key = models.CharField(max_length=600)
    order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=Clock.now)

    # #235, ADR-0031/0032 — 파생본 두 종. 비어 있으면(기본값) 아직 최적화되지
    # 않았다 — 위 클래스 docstring 참고.
    thumbnail_key = models.CharField(max_length=600, blank=True, default="")
    detail_key = models.CharField(max_length=600, blank=True, default="")
    # 확정된 「최적화 불가」 시각 — null이면 아직 후보다(스캔이 계속 재시도한다).
    optimization_failed_at = models.DateTimeField(null=True, blank=True)
    # 가장 최근 실패 사유. 확정 여부와 무관하게 실패할 때마다 갱신된다.
    optimization_error = models.TextField(blank=True, default="")

    class Meta:
        ordering = ["order", "id"]
        verbose_name = "공모전 이미지"
        verbose_name_plural = "공모전 이미지"

    def __str__(self) -> str:  # pragma: no cover
        return f"ContestImage(contest_id={self.contest_id}, object_key={self.object_key})"

    @property
    def is_optimized(self) -> bool:
        """썸네일·본문용 파생본이 둘 다 있는가 — 위 docstring의 "함께 성립" 규칙대로
        이 프로퍼티는 항상 「둘 다」거나 「둘 다 아니거나」다."""

        return bool(self.thumbnail_key) and bool(self.detail_key)

    @property
    def thumbnail_url(self) -> str:
        """목록용 URL. 최적화 전이거나 「최적화 불가」로 확정됐으면 원본을 그대로
        가리킨다 — 화면은 이 값이 파생본인지 원본인지 판정하지 않는다."""

        from storage.public import compose_public_image_url

        return compose_public_image_url(self.thumbnail_key or self.object_key)

    @property
    def url(self) -> str:
        """상세용 URL. thumbnail_url과 같은 원칙 — 최적화 전/실패 시 원본."""

        from storage.public import compose_public_image_url

        return compose_public_image_url(self.detail_key or self.object_key)


class ContestImageOptimizationAttempt(models.Model):
    """ContestImage 최적화 실패 이력 (#235, ADR-0031) — `scoring.models.ScoringAttempt`와
    같은 자리. Score와 달리 append-only일 필요는 없지만, 카운터를 `ContestImage`에
    직접 두지 않고 여기 쌓아 집계하는 이유는 같다 — 카운터 증가와 이력 생성이 갈리는
    순간 어느 쪽이 참인지 정할 방법이 없다.
    """

    contest_image = models.ForeignKey(
        ContestImage, related_name="optimization_attempts", on_delete=models.CASCADE
    )
    attempted_at = models.DateTimeField(auto_now_add=True)
    error = models.TextField()

    class Meta:
        ordering = ["-attempted_at"]
        verbose_name = "이미지 최적화 실패 이력"
        verbose_name_plural = "이미지 최적화 실패 이력"

    def __str__(self) -> str:  # pragma: no cover
        return f"ContestImageOptimizationAttempt(contest_image={self.contest_image_id}, at={self.attempted_at})"


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

        from .transitions import claim_contest_in_place_update

        contest = Contest.objects.select_for_update().get(pk=self.contest_id)
        if not Contest.Status.JUDGING_EXTENDABLE(contest.status) or contest.judging_ends_at is None:
            return

        new_count = contest.judging_extension_count + 1
        # 여기서 정책을 다시 읽지 않는다(#78 코드리뷰 지적 2) — extension_days 는
        # initiate 시점에 amount 와 함께 스냅샷된 값이다.
        new_judging_ends_at = contest.judging_ends_at + timedelta(days=self.extension_days)

        # 「judging-extension」으로 선언된 제자리 갱신(CLOSED -> CLOSED,
        # contests.transitions, #255)을 그대로 재사용한다 — 전이가 아니라 ① WHERE
        # status='closed' 조건부 UPDATE 규율을 한 번 더 지키고 ② auto_now 필드
        # (updated_at)를 이 메커니즘이 채워주기 위해서다(#13 리뷰 지적 6).
        claim_contest_in_place_update(
            "judging-extension",
            contest.pk,
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




class ContestSubmission(Submission):
    """공모전 자식 — `submissions.Submission`을 다중 테이블 상속으로 확장한다
    (#270, ADR-0039).

    부모와 테이블·pk를 나눠 갖는다 — 이 테이블에는 `contest`·`developer`
    두 컬럼과 `submission_ptr`(부모를 가리키는 pk)만 있다. 자료(`assets`)·근거
    (`requirement_responses`)는 부모 pk로 그대로 붙는다.

    **생성은 언제나 이 클래스를 통해서다** — `submissions.Submission`을 직접
    만들면 자식 없는 부모 행이 생긴다(이 자식이 없으면 어느 제품의 계약도
    만족하지 못한다). `contests.submission_api.create_submission`이 유일한
    HTTP 생성 경로이고, `Submission.user`는 언제나 `developer.user`와 같은
    값으로 맞춰 만든다 — 둘은 같은 사실(`DeveloperProfile.user`가 OneToOne)의
    두 표현이라 어긋나면 안 된다.
    """

    contest = models.ForeignKey(Contest, related_name="submissions", on_delete=models.CASCADE)
    developer = models.ForeignKey(
        "accounts.DeveloperProfile", related_name="submissions", on_delete=models.CASCADE
    )

    # 무료 공모전 전용 동의 시각 (#416, ADR-0048) — 「수상작의 소스는 개최자가
    # 볼 수 있습니다」에 언제 동의했는지. 무료 공모전이 아니면 항상 null이다 —
    # 유료 공모전은 본인확인이 그 자리를 대신한다. `contests.submission_api.
    # create_submission`/`update_submission`이 무료 공모전 제출마다 이 값을
    # 다시 찍는다(제출·수정 둘 다 동의를 다시 확인한다).
    source_access_consent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            # 한 Developer가 한 Contest에 낼 수 있는 Submission은 하나뿐이다. 두 번째
            # 제출은 새 행이 아니라 기존 행의 수정(PUT)이어야 한다 — #270 이전에는
            # 이 제약이 부모(`submissions.Submission`)에 있었다.
            models.UniqueConstraint(
                fields=["contest", "developer"], name="unique_submission_per_contest_developer"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"ContestSubmission(contest={self.contest_id}, developer={self.developer_id})"


class ContestSearchReindexState(models.Model):
    """전체 재색인 스캔(`contest-search-reindex`, #450)이 마지막으로 언제 돌았는지
    기억하는 단일 행.

    `core.scans.ScanSpec`은 "후보 행마다 조건부 UPDATE로 정확히 한 번 처리한다"는
    idempotency를 전제한다(ADR-0003) — 그런데 전체 재색인은 "언제나 할 일이
    있다"에 가까워, 이 마커 없이 tick·beat가 반복 호출하면 매번 다시 돈다. 그러면
    `/api/internal/tick`을 두 번 쏘면 스캔 결과 행 수가 두 배가 되는(다른 스캔은
    깨끗이 0으로 수렴하는) 비대칭이 생긴다(`tests/test_scheduler_tick.py`가 이미
    고정한 "tick 두 번 = 같은 결과" 계약). `contests.search_scan`이
    `last_reindexed_at`이 하루보다 최근이면 후보에서 빼고, `claim_transition`과
    같은 조건부 UPDATE로 이 행을 먼저 "찜한" 뒤에만 `rebuild()`를 부른다.

    **이 필드는 일부러 주입 가능한 `core.clock.Clock`이 아니라 실제 벽시계
    (`django.utils.timezone.now`)로 찍는다** — ADR-0003("시간은 주입 가능한
    의존성이다")의 명시적 예외다. 이 저장소의 다른 모든 시간 기반 테스트가
    `ClockOverride`로 몇 주씩 시계를 앞당기며 tick을 반복 호출하는데, 이 재색인
    "하루 주기"가 그 주입된 시계를 따라가면 검색과 무관한 테스트가 며칠을
    건너뛸 때마다 이 스캔이 덩달아 끼어들어 `rows` 개수를 흔든다. 실제
    OpenSearch 재색인 비용은 시뮬레이션 시간이 아니라 진짜 경과 시간에 매여
    있으므로, `core.backup_database`(스캔 등록부 밖에서 실제 Celery beat
    크론에 매인, 마찬가지로 주입된 시계를 보지 않는 작업)와 같은 원칙을 쓴다.

    사람이 즉시 전체를 다시 만들고 싶을 때는 이 마커를 보지 않는
    `manage.py rebuild_contest_search_index`를 쓴다 — 이 스캔은 "매일" 주기
    전용이고, 즉시 재색인은 별도 진입점이다(`contests/search_scan.py` 모듈
    docstring).
    """

    last_reindexed_at = models.DateTimeField(default=timezone.now)

    def __str__(self) -> str:  # pragma: no cover
        return f"ContestSearchReindexState(last_reindexed_at={self.last_reindexed_at})"
