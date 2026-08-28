"""Appeal 도메인 모델 (#21, ADR-0004, ADR-0006).

Developer가 자신의 불변 `Score` 스냅샷에 이의를 제기하고, 운영자가 그 스냅샷의
근거(점수·reasoning·prompt·model_version)와 함께 검토해 심판한다. `Score`는
append-only라 이 앱은 그것을 절대 건드리지 않는다 — 재채점 경로는 존재하지
않는다(ADR-0006). 인용(UPHELD)되면 `ledger`에 정정 분개가 새로 추가될 뿐, 기존
분개는 그대로 남는다.

Submission 하나에 이의제기는 하나만 허용한다(`OneToOneField`) — 재이의는 이
티켓 범위 밖이다.
"""

from __future__ import annotations

from django.db import models


class Appeal(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "검토 대기"
        UPHELD = "upheld", "인용"
        REJECTED = "rejected", "기각"

    submission = models.OneToOneField(
        "submissions.Submission", related_name="appeal", on_delete=models.CASCADE
    )
    reason = models.TextField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)

    # 운영자 심판 결과. PENDING 동안은 전부 비어 있다.
    ruling_note = models.TextField(blank=True)
    # 인용 시에만 채워진다 — 운영자가 근거를 검토해 직접 정하는 정정 금액이다.
    # 자동으로 재계산되지 않는다(재채점 경로가 없는 것과 같은 이유 — 이 값은
    # 항상 사람의 판단이다).
    correction_amount = models.PositiveIntegerField(null=True, blank=True)
    # 인용 시 원장에 남긴 정정 분개. 성공 시 정확히 한 번만 채워진다
    # (payouts.models.Payout.journal_entry_id와 같은 원칙).
    correction_journal_entry_id = models.PositiveIntegerField(null=True, blank=True)
    ruled_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Appeal(submission={self.submission_id}, status={self.status})"
