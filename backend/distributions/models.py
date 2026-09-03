"""Distribution 도메인 모델 (#16, CONTEXT.md, ADR-0003/0004/0006).

`Distribution`은 "Sponsor가 기한 내 Award하지 않아, Score 컷라인을 통과한
Submission들에게 Prize를 1/N로 나누는 것"이다(CONTEXT.md). Contest 하나에 최대
하나만 존재한다(`OneToOneField`) — 스캔이 두 번 돌아도 두 번째는 이미 존재하는
Distribution을 보고 아무 것도 다시 만들지 않는다(#16 AC "틱을 연속 두 번 쏴도
한 번만 실행된다").

컷라인은 상수가 아니라 DB 조정 가능한 운영 파라미터다(#16 AC) —
`policies.PlatformPolicy.distribution_cutline_percentage`에 산다(#79, ADR-0023).
이 모델이 예전에 직접 담던 `DistributionCutline`을 그 단일 행이 흡수했다 — 정책이
여러 테이블로 흩어지지 않도록 하기 위해서다. 값을 바꾸는 것은 상위 등급
Operator만 할 수 있는 운영자 API의 몫이다(#76) — 지금은 `manage.py shell`로만
바뀐다. `Distribution.cutline_percentage`는 실제로 적용된 값의 스냅샷이다 —
나중에 운영자가 컷라인을 바꿔도 이미 배분된 Distribution의 판정 근거는 흔들리지
않는다(`payouts.Payout.prize_amount`가 지급 요청 시점 스냅샷인 것과 같은 원칙).
"""

from __future__ import annotations

from django.db import models


class Distribution(models.Model):
    """Contest 하나에 대한 1/N 배분 한 건. 정확히 한 번만 만들어진다."""

    contest = models.OneToOneField(
        "contests.Contest", related_name="distribution", on_delete=models.CASCADE
    )
    # 판정에 실제로 쓰인 컷라인 스냅샷(그 시점의 DistributionCutline 값).
    cutline_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    total_prize = models.PositiveIntegerField()
    qualifying_count = models.PositiveIntegerField()
    # floor(total_prize / qualifying_count). DistributionShare.amount의 합 + 이
    # 값과 무관하다 — 나머지는 아래 remainder_amount로 별도 관리한다.
    share_amount = models.PositiveIntegerField()
    # 1/N 나머지(ADR-0004의 "단수처리"). 사라지지 않고 명시적으로 분개된다.
    remainder_amount = models.PositiveIntegerField(default=0)
    remainder_journal_entry_id = models.PositiveIntegerField(null=True, blank=True)
    # 컷라인을 통과한 Submission이 하나도 없어(하지만 참여자는 있어) 컷라인을
    # 무시하고 전원에게 배분한 경우 True. Escrow의 "참여자가 한 명이라도 있으면
    # Sponsor에게 되돌아가지 않는다"는 원칙이 컷라인보다 우선한다(REQUEST.md
    # "핵심 원칙").
    cutline_waived = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Distribution(contest={self.contest_id}, N={self.qualifying_count})"


class DistributionShare(models.Model):
    """Distribution 한 건이 특정 Submission에 배분한 몫 하나.

    `payouts.Payout.distribution_share`가 이 행을 가리켜 실제 지급을 실행한다 —
    `handovers.Handover`가 Award 경로의 지급 대상이듯, 이 모델이 무응답 배분
    경로의 지급 대상이다(#16, "기존 Payout 경로를 재사용한다").
    """

    distribution = models.ForeignKey(
        Distribution, related_name="shares", on_delete=models.CASCADE
    )
    # Contest 당 Submission은 Developer 당 하나뿐이고, Distribution도 Contest 당
    # 하나뿐이므로 Submission 당 몫도 하나뿐이다.
    submission = models.OneToOneField(
        "submissions.Submission", related_name="distribution_share", on_delete=models.PROTECT
    )
    # Distribution.share_amount의 스냅샷 — 원 단위 정수(ADR-0004).
    amount = models.PositiveIntegerField()

    # 결과 알림(notifications.lifecycle.notify_distribution_shares) 완료
    # 표식(#19 리뷰 지적 3) — awards.Award.result_notice_sent_at과 같은 이유·
    # 같은 패턴. Distribution 생성 직후 즉시 경로가 성공적으로 시도한 뒤에만
    # 채워지고, 비어 있는 채로 남은 몫은
    # `notifications.lifecycle.send_pending_distribution_share_result_notices`
    # 가 다시 찾아 마저 알린다.
    result_notice_sent_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def payout_target(self):
        """이 몫을 지급 사유로 하는 Payout 생성에 필요한 것 (#129)."""

        from payouts.targets import PayoutTarget

        return PayoutTarget(
            fk_name="distribution_share",
            lock=lambda: DistributionShare.objects.select_for_update().get(pk=self.pk),
            prize_amount_of=lambda locked: locked.amount,
        )

    class Meta:
        ordering = ["id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"DistributionShare(submission={self.submission_id}, amount={self.amount})"
