"""「지금 크기 초과 보류」 조건의 본문 — `contests.scoring_hold.size_held_filter` 가 `contests.ports.SIZE_HELD_FILTER`
로 꺼내 쓴다(#986, #1086). 보류 기록(`ScoringAttempt`)이 이 앱에 있어서 여기 둔다."""

from __future__ import annotations

from django.db.models import Exists, OuterRef, Q

from contests.scoring_hold import SIZE_HOLD_ERROR_PREFIX

from .models import ScoringAttempt


def size_held_q() -> Q:
    return Q(score__isnull=True) & Exists(
        ScoringAttempt.objects.filter(submission_id=OuterRef("pk"), error__startswith=SIZE_HOLD_ERROR_PREFIX)
    )
