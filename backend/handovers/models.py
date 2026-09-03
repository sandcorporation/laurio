"""Handover 도메인 모델 (#14, CONTEXT.md, ADR-0004, ADR-0005/0014).

`Handover`는 "Award 이후 Developer가 소스코드와 빌드 자산을 Sponsor에게 넘기는
행위"다(CONTEXT.md) — 다만 소스코드는 이미 제출 시점에 스토리지에 있으므로(#10,
ADR-0014), 여기서 실제로 "넘어가는" 것은 접근 권한뿐이다. `submissions.resolvers`가
이 앱의 존재(`Award` 유무)를 근거로 그 접근 권한을 판정한다.

`Handover`는 Award 하나에 정확히 하나만 존재한다 — Award 자체가 Contest 당 하나뿐이므로
(`awards.models.Award.contest`가 OneToOneField) 자연스럽게 Contest 당 Handover도
하나다. `awards.api.award_submission`이 Award 생성과 같은 트랜잭션에서 이 행을 만든다.
"""

from __future__ import annotations

from django.db import models


class Handover(models.Model):
    class Status(models.TextChoices):
        PENDING_ACCEPTANCE = "pending_acceptance", "인수 대기"
        RELEASED = "released", "Escrow 해제됨"

    class ReleasedVia(models.TextChoices):
        SPONSOR_ACCEPTED = "sponsor_accepted", "Sponsor 인수 확인"
        TIMEOUT = "timeout", "정해진 기간 경과"

    award = models.OneToOneField(
        "awards.Award", related_name="handover", on_delete=models.CASCADE
    )
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.PENDING_ACCEPTANCE
    )
    # Award 시각 + PlatformPolicy.handover_acceptance_period_days(#78/ADR-0023).
    # Sponsor가 침묵해도 이 시각이 지나면 틱이 Escrow를 해제한다 — Sponsor의
    # 침묵이 Developer를 인질로 잡지 못한다(#14 AC).
    release_deadline_at = models.DateTimeField()

    released_via = models.CharField(max_length=20, choices=ReleasedVia.choices, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)

    # 이 Handover의 Escrow 해제가 원장에 남긴 분개. 성공 시 정확히 한 번만
    # 채워진다(payments.models.Payment.journal_entry_id와 같은 원칙).
    escrow_release_journal_entry_id = models.PositiveIntegerField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def payout_target(self):
        """이 Handover 를 지급 사유로 하는 Payout 생성에 필요한 것 (#129)."""

        from payouts.targets import PayoutTarget

        return PayoutTarget(
            fk_name="handover",
            lock=lambda: Handover.objects.select_for_update().get(pk=self.pk),
            prize_amount_of=lambda locked: locked.award.contest.prize,
        )

    def __str__(self) -> str:  # pragma: no cover
        return f"Handover(award={self.award_id}, status={self.status})"


class BuildAsset(models.Model):
    """Award된 Submission에 Developer가 추가로 올리는 빌드 자산 하나.

    ADR가 예로 드는 것: 빌드 설정·서명키·스토어 메타데이터·실행 문서. 실제 스토어
    배포는 Handover 범위 밖이다(#14 AC) — 이 모델은 그 배포에 필요한 자산을
    Sponsor가 내려받을 수 있게 참조만 담을 뿐, 배포 자체를 수행하지 않는다.
    """

    class Kind(models.TextChoices):
        BUILD_CONFIG = "build_config", "빌드 설정"
        SIGNING_KEY = "signing_key", "서명키"
        STORE_METADATA = "store_metadata", "스토어 메타데이터"
        RUN_DOCS = "run_docs", "실행 문서"
        OTHER = "other", "기타"

    submission = models.ForeignKey(
        "submissions.Submission", related_name="build_assets", on_delete=models.CASCADE
    )
    kind = models.CharField(max_length=20, choices=Kind.choices)
    # storage.api가 발급한 object_key("<target_ref>/<32자리 hex>").
    object_key = models.CharField(max_length=600)
    label = models.CharField(max_length=200, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"BuildAsset(submission={self.submission_id}, kind={self.kind})"
