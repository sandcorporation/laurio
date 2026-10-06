"""공모전 검색 색인 Celery 태스크 (#450, 부모 #444 스펙, ADR-0003/0007).

`Contest`·그 카테고리·요구형태·개최자 표시 이름이 바뀌면 트랜잭션 커밋 뒤 이
태스크가 그 공모전 하나만 다시 색인한다 — `contests/indexing.py`의 신호
수신자가 `transaction.on_commit`으로 큐에 넣는다(`classroom.api`가 즉시 채점을
큐에 넣는 것과 같은 규율).

`core.tasks.backup_database`와 같은 모양이다 — 공유할 것이 없는 단순 멱등
갱신(같은 공모전을 두 번 색인해도 결과가 같다)이라 HTTP 경계를 하나 더 두는
비용을 낼 이유가 없다 — 워커 안에서 `contests.search.get_search_adapter()`를
직접 부른다.

dev·CI는 태스크가 eager 다(#582, `CELERY_TASK_ALWAYS_EAGER`) — `.delay()`
자리에서 그대로 색인한다(기본 검색 어댑터는 fake 다). 배포의 안전망은 매일 밤
전체 재색인 스캔(`contest-search-reindex`, `contests/apps.py`)이다.
"""

from __future__ import annotations

from celery import shared_task

from .search import ContestSearchUnavailable, get_search_adapter


@shared_task(
    name="contests.index_contest",
    ignore_result=True,
    # 배포 중 backend(=검색 어댑터가 붙는 이 워커 자신이 아니라 실물 OpenSearch)가
    # 잠깐 응답하지 않는 것은 사고가 아니다(`core.tasks.run_scan`과 같은 원칙) —
    # `ContestSearchUnavailable`(연결 실패·시간 초과)만 몇 번 물러서서 재시도한다.
    autoretry_for=(ContestSearchUnavailable,),
    retry_backoff=2,
    retry_backoff_max=30,
    retry_jitter=True,
    max_retries=3,
)
def index_contest(contest_id: int) -> None:
    """`Contest` 하나를 색인하거나(공개 상태) 지운다(초안·비공개·삭제됨).

    fake 어댑터로는 `contests.search.FakeContestSearchAdapter._indexed`의
    상태로 이 태스크의 효과를 관찰한다(`tests/test_contest_search_indexing.py`)
    — `core.tasks.backup_database`를 직접 불러 확인하는 것과 같은 관용구다.
    """

    get_search_adapter().index_or_remove(contest_id)
