"""「현재 점수」의 모양 — 정정이 있으면 최신 끝난 정정, 없으면 원래 `Score`(#1179, 스펙 #1178).

값은 `scoring.current.current_score` 가 만든다. 모양이 여기(아래 층) 있는 까닭은 그것을 받는 공모전·이의
앱이 `scoring` 을 import 하지 않기 때문이다(`contests.ports.CURRENT_SCORE` 로 받는다). 필드는 `Score` 의 판정
필드와 같은 이름이라 `OwnScoreOut`·`ScoreSnapshotOut` 이 원래 `Score` 를 읽던 그대로 돈다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Submission

#: JSON 컬럼에 담긴 값(`Score.reasoning`·`scored_assets`·`repository_reachability_check`)
JSON = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None


@dataclass(frozen=True)
class CurrentScore:
    submission: Submission
    percentage: Decimal
    model_version: str
    prompt: str
    reasoning: list[JSON]
    scored_assets: list[JSON]
    repository_reachability_check: list[JSON]
    # 원래 Score 를 만든 때 — 이의 창·화면이 「채점된 때」로 읽는 값이라 정정해도 바뀌지 않는다
    created_at: datetime
    # 끝난 정정이 있는가. 아래 셋은 정정됐을 때만 값이 있다.
    corrected: bool = False
    original_percentage: Decimal | None = None
    original_model_version: str | None = None
    correction_reason: str | None = None
