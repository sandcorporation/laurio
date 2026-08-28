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
        # 식별하는 지점"으로 쓰인다.
        CLOSED = "closed", "마감"

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

    # ADR-0001: 재개최는 복제 후 원본을 가리킨다. 이 티켓은 필드만 마련해 두고
    # 재개최 플로우 자체는 만들지 않는다(범위 밖).
    source_contest = models.ForeignKey(
        "self", null=True, blank=True, related_name="reopenings", on_delete=models.SET_NULL
    )

    # 개최 시점의 최소 제안 상금 합계 스냅샷. 이후 운영자가 DeliverableType의
    # 최소 상금을 바꿔도 이미 개최된 Contest의 배지 판단은 흔들리지 않는다.
    required_minimum_prize = models.PositiveIntegerField(default=0)
    is_underfunded = models.BooleanField(default=False)

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
