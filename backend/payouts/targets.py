"""Payout 의 지급 사유가 `get_or_create_payout` 에 주는 것 (#129).

Payout 은 Handover(Award 경로) 또는 DistributionShare(Distribution 경로) 중 정확히
하나를 가리킨다. 두 경로가 Payout 생성에 대해 다른 것은 셋뿐이다 — 어느 행을 잠그는가,
금액은 어디서 오는가, Payout 의 어느 FK 에 꽂히는가. 나머지 50줄(활성 조회 → 금액 계산
→ 세이브포인트 생성 → IntegrityError 재조회)은 같았는데 두 번 적혀 있었다. `Handover.payout_target()` 과
`payouts.distribution_payouts.share_payout_target` 이 이 셋을 주면 생성 경로는 하나가 된다.

모델을 import 하지 않는다 — handovers 가 이 모듈을 import 하므로 순환을 만들지 않기 위해서다.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PayoutTarget:
    # Payout 모델의 FK 필드 이름 — "handover" | "distribution_share".
    fk_name: str
    # `select_for_update` 로 잠근 사유 행을 돌려준다. 트랜잭션 안에서 부른다.
    lock: Callable[[], Any]
    # 잠근 행에서 지급할 Prize 금액(원)을 읽는다.
    prize_amount_of: Callable[[Any], int]


def handover_payout_target(handover) -> PayoutTarget:
    """이 Handover 를 지급 사유로 하는 Payout 생성에 필요한 것 (#129). #1086 에서 `Handover.payout_target()` 을
    여기로 옮겼다 — 인수인계 앱이 지급 앱을 부르지 않게."""

    from handovers.models import Handover

    return PayoutTarget(
        fk_name="handover",
        lock=lambda: Handover.objects.select_for_update().get(pk=handover.pk),
        prize_amount_of=lambda locked: locked.award.contest.prize,
    )
