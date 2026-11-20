"""「크기 초과」 채점 보류의 판별(#989 A2) — 채점(`scoring`)·이의(`appeals`)·참가자 화면이 같은 판정을 쓴다.

`appeals` 는 `scoring` 을 import 하지 않는다(재채점을 하지 않는다는 경계) — 그래서 표식과 판정을
두 앱이 다 기대는 여기에 둔다. 보류 기록은 `scoring.ScoringAttempt.error` 의 머리다.
"""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

#: 채점 보류 표식(#986) — 앱 코드·채점 요청이 모델 컨텍스트에 다 들어가지 않는 제출의
#: `ScoringAttempt.error` 머리. `release_scoring_hold` 가 풀면 머리가 바뀌어 더는 보류가 아니다.
SIZE_HOLD_ERROR_PREFIX = "SourceOverBudgetHold:"


def size_held_filter() -> Q:
    """`ContestSubmission` 쿼리에 거는 「지금 크기 초과 보류」 조건 — Score 가 없고 풀리지 않은 보류 기록이 있다."""

    # 보류 기록(`ScoringAttempt`)은 scoring 이 가진다 — `scoring.apps` 가 올린 조건을 꺼낸다(#1086, `contests.ports`).
    from .ports import SIZE_HELD_FILTER

    return SIZE_HELD_FILTER.get()()


def is_size_held(submission) -> bool:
    """이 제출이 지금 「크기 초과」 보류인가."""

    if hasattr(submission, "score"):
        return False
    return submission.scoring_attempts.filter(error__startswith=SIZE_HOLD_ERROR_PREFIX).exists()
