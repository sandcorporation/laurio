"""Submission 도메인 모델 (CONTEXT.md, ADR-0014).

`Submission`은 한 Developer가 한 Contest에 낸 결과물 일체다. 전체 소스코드는
필수다 — 플랫폼의 "강제하지 않고 배지로 신호한다" 원칙에서 유일한 예외다(ADR-0014).
그 강제는 API 레이어(submissions.api)에서 하고, 여기 모델은 그 결과를 담는 그릇이다.

시연 영상·데모 URL·테스트 계정은 선택이며 완성도 지표로만 쓰인다. 각 `Requirement`
자가 응답(`RequirementResponse`)에는 `Evidence`를 연결할 수 있다 — 연결되지 않아도
제출 자체는 거부되지 않고, "미연결"로 표시될 뿐이다(#12가 채점에서 미달로 본다).
"""

from __future__ import annotations

from django.db import models


class Submission(models.Model):
    contest = models.ForeignKey(
        "contests.Contest", related_name="submissions", on_delete=models.CASCADE
    )
    developer = models.ForeignKey(
        "accounts.DeveloperProfile", related_name="submissions", on_delete=models.CASCADE
    )

    # storage.api가 발급한 object_key("<target_ref>/<32자리 hex>"). 소스는 필수라
    # blank=False로 방어선을 하나 더 둔다 — 실제 강제는 API가 한다.
    source_object_key = models.CharField(max_length=600)

    demo_video_object_key = models.CharField(max_length=600, blank=True)
    demo_url = models.CharField(max_length=2000, blank=True)
    test_account = models.CharField(max_length=500, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # 한 Developer가 한 Contest에 낼 수 있는 Submission은 하나뿐이다. 두 번째
            # 제출은 새 행이 아니라 기존 행의 수정(PUT)이어야 한다.
            models.UniqueConstraint(
                fields=["contest", "developer"], name="unique_submission_per_contest_developer"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"Submission(contest={self.contest_id}, developer={self.developer_id})"


class RequirementResponse(models.Model):
    """한 Requirement에 대한 Developer의 자가 응답."""

    submission = models.ForeignKey(
        Submission, related_name="requirement_responses", on_delete=models.CASCADE
    )
    requirement = models.ForeignKey(
        "contests.Requirement", related_name="responses", on_delete=models.CASCADE
    )
    is_met = models.BooleanField(default=False)
    note = models.CharField(max_length=1000, blank=True)

    class Meta:
        ordering = ["requirement__order", "requirement_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["submission", "requirement"], name="unique_response_per_requirement"
            ),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"RequirementResponse(submission={self.submission_id}, requirement={self.requirement_id})"


class Evidence(models.Model):
    """자가 응답 하나를 뒷받침하는 근거 (CONTEXT.md의 Evidence)."""

    class Kind(models.TextChoices):
        VIDEO_TIMESTAMP = "video_timestamp", "영상 타임스탬프"
        SCREENSHOT = "screenshot", "스크린샷"
        DEMO_PATH = "demo_path", "데모 내 경로"
        SOURCE_LOCATION = "source_location", "소스 위치"

    response = models.ForeignKey(
        RequirementResponse, related_name="evidence_items", on_delete=models.CASCADE
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    value = models.CharField(max_length=500)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Evidence({self.kind}={self.value!r})"
