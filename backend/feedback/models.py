"""건의·버그 제보 (#1237 스펙, #1238).

- `FeedbackPermission` — 계정별 「제보할 수 있다」의 지금 값. `contests.HostingPermission` 꼴이다 —
  계정마다 최대 한 행, 행이 없으면 꺼진 것과 같다. 「누가·언제·왜」는 append-only 인
  `FeedbackPermissionChange` 가 따로 남긴다.
- `FeedbackReport` — 제보 하나. 스크린샷은 PRIVATE 버킷의 키만 들고(`feedback.screenshots`),
  보관 기한이 지나면 키를 비운다 — 글은 남는다(#1239).
- `FeedbackStatusChange` — 상태가 바뀐 사건. 운영자가 바꾸면 `changed_by` 가, 대장이 관리 명령으로
  바꾸면 `changed_by` 없이 `actor_label` 만 남는다.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models

MAX_BODY_CHARS = 4000


class FeedbackPermission(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="feedback_permission", on_delete=models.CASCADE
    )
    is_granted = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"FeedbackPermission<{self.user_id}>({'on' if self.is_granted else 'off'})"


class FeedbackPermissionChange(models.Model):
    """부여·회수 둘 다 사유가 필수다. 계정·운영자 둘 다 PROTECT — 감사 기록이 주인을 잃지 않는다."""

    class Action(models.TextChoices):
        GRANTED = "granted", "부여"
        REVOKED = "revoked", "회수"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="feedback_permission_changes", on_delete=models.PROTECT
    )
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="feedback_permission_changes_made",
        on_delete=models.PROTECT,
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    reason = models.TextField()
    changed_at = models.DateTimeField()

    class Meta:
        ordering = ["-changed_at", "-id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"FeedbackPermissionChange({self.action}, user_id={self.user_id})"


class FeedbackReport(models.Model):
    class Kind(models.TextChoices):
        SUGGESTION = "suggestion", "건의"
        BUG = "bug", "버그"

    class App(models.TextChoices):
        CONTEST = "contest", "공모전"
        CLASSROOM = "classroom", "강의실"

    class Status(models.TextChoices):
        RECEIVED = "received", "접수"
        IN_PROGRESS = "in_progress", "작업 중"
        DEPLOYED = "deployed", "배포됨"
        DECLINED = "declined", "반려"

    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="feedback_reports", on_delete=models.PROTECT
    )
    kind = models.CharField(max_length=16, choices=Kind.choices)
    body = models.TextField()
    app = models.CharField(max_length=16, choices=App.choices)
    page_url = models.CharField(max_length=2048, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    screen_width = models.PositiveIntegerField(null=True, blank=True)
    screen_height = models.PositiveIntegerField(null=True, blank=True)
    # PRIVATE 버킷의 키. 없으면 빈 문자열 — 보내지 않았거나 보관 기한이 지나 지웠다.
    screenshot_key = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    resolution_note = models.TextField(blank=True)
    received_at = models.DateTimeField()
    # 배포됨·반려로 들어간 시각. 보관 기한(종결 30일)이 여기서 센다.
    closed_at = models.DateTimeField(null=True, blank=True)
    # 대장 전달(#1240): take 가 집은 시각과 전달을 마친 시각.
    taken_at = models.DateTimeField(null=True, blank=True)
    forwarded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-received_at", "-id"]
        indexes = [
            models.Index(fields=["reporter", "-received_at"], name="feedback_reporter_recent"),
            models.Index(fields=["status", "-received_at"], name="feedback_status_recent"),
        ]

    def __str__(self) -> str:  # pragma: no cover
        return f"FeedbackReport#{self.pk}({self.kind}, {self.status})"


class FeedbackStatusChange(models.Model):
    report = models.ForeignKey(FeedbackReport, related_name="status_changes", on_delete=models.CASCADE)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="feedback_status_changes_made",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
    )
    # 화면·명령에 보일 「누가」. 운영자면 그 계정 이름, 관리 명령이면 「대장(명령)」.
    actor_label = models.CharField(max_length=150)
    from_status = models.CharField(max_length=16, choices=FeedbackReport.Status.choices)
    to_status = models.CharField(max_length=16, choices=FeedbackReport.Status.choices)
    note = models.TextField(blank=True)
    changed_at = models.DateTimeField()

    class Meta:
        ordering = ["changed_at", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"FeedbackStatusChange(#{self.report_id} {self.from_status}->{self.to_status})"
