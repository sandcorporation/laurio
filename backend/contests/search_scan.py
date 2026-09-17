"""공모전 검색 전체 재색인 스캔 (#450, 부모 #444 스펙).

Contest 단건 색인(`contests.tasks.index_contest`)은 저장·변경마다 그 공모전
하나만 맞추지만, 색인이 어긋날 길이 있다 — 태스크 유실, dev·CI처럼 워커가
아예 없는 환경(#40), 실물 어댑터를 켜기 전에 이미 있던 데이터. 그래서 매일
전체를 다시 만든다(부모 스펙) — `core.scans` 등록부에 올려 beat·
`/api/internal/tick`·`/api/internal/scans/contest-search-reindex`가 모두 같은
한 가지(`get_search_adapter().rebuild()`)를 부르게 한다.

**하루 한 번만 실제로 돈다 — 그리고 그 하루는 실제 벽시계다, 스캔의 `as_of`가
아니다.** `ContestSearchReindexState.last_reindexed_at`(`contests/models.py`
모듈 docstring이 이유를 설명한다)이 실제로 하루 전보다 최근이면 후보 자체가
비어 있다. `claim_transition`과 같은 조건부 UPDATE로 동시 tick 두 번이 와도
한 번만 `rebuild()`가 실행된다.

사람이 지금 당장 전체를 다시 만들고 싶을 때(부모 스펙 "필요하면 명령 하나로
전체를 다시 만들고 싶다")는 이 하루 제한을 보지 않는
`manage.py rebuild_contest_search_index`를 쓴다 — 그 명령은 이 스캔을 거치지
않고 `get_search_adapter().rebuild()`를 직접 부른다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from core.scans import ScanSpec

from .search import get_search_adapter

_DAILY = timedelta(days=1)

#: 항상 pk=1인 단일 행 — 없으면 만들어서 쓴다.
_STATE_PK = 1


def _rebuild_candidates(as_of: Any, ctx: dict) -> list[int]:
    from .models import ContestSearchReindexState

    state, _created = ContestSearchReindexState.objects.get_or_create(pk=_STATE_PK)
    if timezone.now() - state.last_reindexed_at < _DAILY:
        return []
    return [_STATE_PK]


def _rebuild_once(item: int, as_of: Any, ctx: dict) -> dict | None:
    from .models import ContestSearchReindexState

    now = timezone.now()
    # claim_transition과 같은 조건부 UPDATE — 이 조건에 아직도 걸리는 행만
    # 찜한다. rowcount가 0이면 동시에 들어온 다른 실행이 먼저 이겼다는 뜻이라
    # 아무것도 하지 않는다(뼈대가 이 행을 결과에 넣지 않는다).
    claimed = ContestSearchReindexState.objects.filter(
        pk=item, last_reindexed_at__lt=now - _DAILY
    ).update(last_reindexed_at=now)
    if claimed == 0:
        return None

    get_search_adapter().rebuild()
    return {"rebuilt": True}


CONTEST_SEARCH_REINDEX_SCAN = ScanSpec(
    name="contest-search-reindex",
    candidates=_rebuild_candidates,
    handle_row=_rebuild_once,
    batch_size=1,
    # beat 스케줄 자체는 하루 주기로 이 스캔을 부른다 — 위 실제 벽시계 찜 로직이
    # 그 사이 tick·beat 중복 호출에도 실제 재색인이 하루 한 번만 일어나게 한다.
    interval_seconds=int(_DAILY.total_seconds()),
)
