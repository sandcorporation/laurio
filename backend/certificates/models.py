"""공모전 상장(스펙 #1071 「데이터」) — 발급본 한 장이 한 행이다.

발급본은 바뀌지 않는다. 고치려면 취소하고 새 번호로 다시 발급한다(`replaced_by` 가 새 행을
가리킨다). 한 공모전에서 한 사람은 **취소되지 않은 상장을 하나만** 가진다(부분 유니크 제약).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Certificate(models.Model):
    # 발급본은 공개 확인 주소가 걸린 기록이라 공모전·제출이 지워질 때 따라 사라지지 않는다 —
    # `scoring.Score.submission` 과 같은 PROTECT(#240). 공모전을 지우는 시드는 상장을 먼저 지운다.
    contest = models.ForeignKey("contests.Contest", on_delete=models.PROTECT, related_name="certificates")
    submission = models.ForeignKey(
        "contests.ContestSubmission", on_delete=models.PROTECT, related_name="certificates"
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="certificates_received"
    )

    #: `YYYY-CCCC-NNN` — 발급 연도·공모전 id 네 자리·그 공모전 안의 일련번호. 공개 값이다.
    number = models.CharField(max_length=32, unique=True)
    #: 확인 주소 `/c/{token}` 의 값 — `secrets.token_urlsafe(16)`(22자).
    token = models.CharField(max_length=32, unique=True)

    award_name = models.CharField(max_length=20)
    recipient_name = models.CharField(max_length=20, blank=True)
    body = models.CharField(max_length=120, blank=True)
    giver_name = models.CharField(max_length=30)
    giver_title = models.CharField(max_length=30, blank=True)
    award_date = models.DateField()

    pdf_object_key = models.CharField(max_length=255)

    issued_at = models.DateTimeField()
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="certificates_issued"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="certificates_cancelled",
    )
    replaced_by = models.OneToOneField(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="replaces"
    )
    #: 받는 사람이 확인 페이지를 닫은 때(#1130). 탈퇴하면 이 값이 차고 이름이 비워진다.
    recipient_hidden_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [
            models.UniqueConstraint(
                fields=["contest", "recipient"],
                condition=models.Q(cancelled_at__isnull=True),
                name="unique_valid_certificate_per_contest_recipient",
            ),
        ]

    def __str__(self) -> str:
        return self.number

    @property
    def is_valid(self) -> bool:
        return self.cancelled_at is None
