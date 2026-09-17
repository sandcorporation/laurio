"""조회수 옮기기 스캔 — 「바뀐 공모전」만 Redis에서 DB로 (#446, spec #444).

`contests.view_tracking`이 Redis에 실시간으로 쌓는 조회수는 그 자체로는 DB에 영구히
남지 않는다. 이 스캔이 10분마다 그 격차를 메운다: `contests.view_flush_store`가 관리하는
「바뀐 공모전 id」 집합을 후보 단계에서 원자적으로 통째로 떼어 내고, 그 id들의 지금 값을
한 번에 읽어(`contests.view_tracking.get_view_counts`) `Contest.view_count`를 한 SQL문
(`bulk_update`)으로만 고친다 — 후보에 없는 Contest는 건드리지 않으므로 DB 전체를 훑지
않는다.

**행 하나 = 이번에 떼어 낸 id 전체(리스트 하나)다.** `core.scans`의 뼈대는 "후보 하나하나를
따로 처리하고 하나가 실패해도 나머지는 계속한다"를 기본으로 삼지만(poison pill 격리), 이
스캔은 그 반대를 원한다 — id마다 따로 읽고 따로 쓰면 "한 번에 읽어 한 번에 고친다"는
인수조건이 깨지고, 왕복 수가 배치 크기만큼 늘어난다. 그래서 후보를 미리 다 모아 하나의
리스트로 감싸 넘긴다(`_batch`가 두 번째로 자르지 못하게, 후보 수는 언제나 1이다).

**실패하면 떼어 낸 id를 전부 되돌린다.** DB 쓰기가 실패하면(연결 끊김 등) 그 리스트의 id를
`mark_changed`로 다시 집합에 넣은 뒤 예외를 그대로 올린다 — `core.scans.run_scan`이 그
예외를 `failed`에 기록하고 다음 실행으로 넘긴다. 숫자를 잃는 유일한 경로는 이 되돌리기
자체가 실패하는 것뿐인데, 그건 같은 Redis가 애초에 죽어 있었다는 뜻이라 이 스캔이 통째로
도는 것 자체가 불가능했을 상황이다.
"""

from __future__ import annotations

from core.scans import ScanSpec

from .models import Contest
from .view_flush_store import get_changed_contests_store
from .view_tracking import get_view_counts

SCAN_NAME = "contest-view-flush"

# 10분 — spec #444, 티켓 #446의 인수조건("최대 10분 늦음")이 곧 이 값이다.
_FLUSH_INTERVAL_SECONDS = 600.0


def _candidates(as_of, ctx) -> list[list[int]]:
    changed_ids = get_changed_contests_store().pop_all()
    # 빈 리스트를 후보로 감싸 넘기면 handle_row가 빈 배치를 "처리"한 것으로 세어
    # rows에 쓸모없는 행이 하나 생긴다 — 아무것도 없으면 아예 후보가 없는 것으로 만든다.
    return [changed_ids] if changed_ids else []


def _handle_row(contest_ids: list[int], as_of, ctx) -> dict:
    store = get_changed_contests_store()
    try:
        counts = get_view_counts(contest_ids)
        contests = list(Contest.objects.filter(id__in=contest_ids).only("id", "view_count"))
        for contest in contests:
            # `counts`에 없는 id는 손대지 않는다(값을 못 읽었다고 0으로 되돌리지 않는다) —
            # `contests.view_tracking.get_view_counts`의 계약이 그렇다.
            contest.view_count = counts.get(contest.id, contest.view_count)
        Contest.objects.bulk_update(contests, ["view_count"])
    except Exception:
        # 되돌린다 — 다음 회차가 같은 id를 다시 줍는다. 되돌린 뒤에도 예외는 그대로
        # 올려 core.scans.run_scan이 이번 실행을 실패로 기록하게 둔다.
        for contest_id in contest_ids:
            store.mark_changed(contest_id)
        raise

    return {"contest_ids": contest_ids, "count": len(contest_ids)}


CONTEST_VIEW_FLUSH_SCAN = ScanSpec(
    name=SCAN_NAME,
    candidates=_candidates,
    handle_row=_handle_row,
    interval_seconds=_FLUSH_INTERVAL_SECONDS,
)
