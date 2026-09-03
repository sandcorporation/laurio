"""Payout 의 지급 사유가 `get_or_create_payout` 에 주는 것 (#129).

Payout 은 Handover(Award 경로) 또는 DistributionShare(Distribution 경로) 중 정확히
하나를 가리킨다. 두 경로가 Payout 생성에 대해 다른 것은 셋뿐이다 — 어느 행을 잠그는가,
금액은 어디서 오는가, Payout 의 어느 FK 에 꽂히는가. 나머지 50줄(활성 조회 → 금액 계산
→ 세이브포인트 생성 → IntegrityError 재조회)은 같았는데 두 번 적혀 있었다. 각 모델이
`payout_target()` 으로 이 셋을 주면 생성 경로는 하나가 된다.

모델을 import 하지 않는다 — handovers·distributions 양쪽이 이 모듈을 import 하므로
순환을 만들지 않기 위해서다.
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
