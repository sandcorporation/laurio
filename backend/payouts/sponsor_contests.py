"""개최자 공모전 목록이 행마다 판정할 사실을 한 질의로 붙인다(#81) — 채점·이의·지급·배분을 다 보므로 이 가족의 맨
위(지급)에 둔다. `contests.api` 는 `contests.ports.SPONSORED_CONTEST_QUERYSET` 으로 부른다(#1086 에서
`contests.sponsorship` 에서 옮겼다). 판정 자체(`sponsor_next_action_for`)는 그대로 `contests.sponsorship` 에 있다.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Case, Count, Exists, OuterRef, Q, Value, When

from appeals.models import Appeal
from contests.models import distribution_due_q
from distributions.models import DistributionShare
from scoring.models import Score

from .models import Payout


def sponsored_contest_queryset(base, *, as_of, policy):
    """판정에 필요한 사실을 **한 질의로** 붙인다 (#81).

    전부 `Exists` 서브쿼리다 — `Count` 로 하면 조인이 곱해져 행이 늘고,
    `distinct=True` 로 막아도 질의가 무거워진다. 실제 조인은
    `submission_count` 하나뿐이다.
    """

    return base.select_related("award__handover", "distribution").annotate(
        submission_count=Count("submissions", distinct=True),
        has_any_score=Exists(
            Score.objects.filter(submission__contestsubmission__contest=OuterRef("pk"))
        ),
        has_pending_appeal=Exists(
            Appeal.objects.filter(
                submission__contestsubmission__contest=OuterRef("pk"), status=Appeal.Status.PENDING
            )
        ),
        # transfer_status가 FAILED면 CONFIRMED라도 실이체가 실제로는 아직
        # 안 나간 것이다(#57 코드리뷰 지적 4/7/8, 3차의 결과로 생긴
        # Payout.transfer_status 축 — status는 원장 확정 사실이라 되돌리지
        # 않지만(ADR-0004), 이 축을 안 보면 뒤늦게 실이체가 실패로 확인된
        # Contest도 "완료"라고 말하게 된다). Sponsor에게 지급 상세를 보여주지
        # 않는다는 설계 의도(위 주석)는 그대로 지키되, "완료"라는 판정 자체는
        # 진실이어야 한다.
        has_confirmed_payout=Exists(
            Payout.objects.filter(
                handover__award__contest=OuterRef("pk"), status=Payout.Status.CONFIRMED
            ).exclude(transfer_status=Payout.TransferStatus.FAILED)
        ),
        # 배분은 만들어졌는데 아직 정산되지 않은 몫이 남아 있는가. 「배분 행이
        # 생겼다」와 「돈이 실제로 갔다」는 다르다 — 지급이 전부 실패해 매 스캔
        # 재시도되는 중에도 앞의 조건은 참이다.
        #
        # `payouts__status__in=Payout.Status.SETTLED.statuses`만으로는 CONFIRMED인데
        # transfer_status가 FAILED인 Payout도 "정산됨"으로 잡는다(코드리뷰
        # 지적 7, 4차 — 지난 라운드에 Award 경로(has_confirmed_payout)만
        # 고치고 이 배분 경로는 놓쳤다). 두 조건을 하나의 Q로 묶어 **같은
        # 관련 Payout 행**에 함께 걸어야 한다 — exclude를 두 번 나눠 걸면
        # 서로 다른 Payout 행에 각각 적용될 수 있어 원하는 "정산됨 AND
        # 실이체 실패 아님"이라는 단일 행의 조건이 되지 않는다.
        has_unsettled_share=Exists(
            DistributionShare.objects.filter(
                distribution__contest=OuterRef("pk")
            ).exclude(
                Q(payouts__status__in=Payout.Status.SETTLED.statuses)
                & ~Q(payouts__transfer_status=Payout.TransferStatus.FAILED)
            )
        ),
        # 배분 시각이 왔는가. 스캔·이의 큐가 쓰는 것과 **같은 조건**이다
        # (`distribution_due_q`) — 세 벌로 쓰면 개최자 화면은 보류라는데 이의
        # 큐는 아니라고 하는 날이 온다.
        is_distribution_due=Case(
            When(distribution_due_q(as_of, policy), then=Value(True)),
            default=Value(False),
            output_field=models.BooleanField(),
        ),
    )
