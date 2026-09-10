"""Award 조회 헬퍼 — Handover(#14)가 접근 판정에 재사용한다.

`awards.models.Award`는 이미 "이 Contest가 Award됐는지, 어느 Submission이
선정됐는지"를 담고 있다(`awards.models.Award` 독스트링) — 이 모듈은 그 사실을
"이 Contest에서 이 Developer가 선정됐는가"라는 질문으로 뒤집어 재사용하기 쉽게
만들 뿐, 새 상태를 만들지 않는다.
"""

from __future__ import annotations

from .models import Award


def sponsor_user_id_if_awarded(contest_id: int, developer_user_id: int) -> int | None:
    """이 Contest에서 이 Developer의 Submission이 Award됐다면 Sponsor의 User pk를,
    아니면 None을 돌려준다.
    """

    award = (
        Award.objects.filter(
            contest_id=contest_id,
            submission__contestsubmission__developer__user_id=developer_user_id,
        )
        .select_related("contest__sponsor")
        .first()
    )
    if award is None:
        return None
    return award.contest.sponsor.user_id
