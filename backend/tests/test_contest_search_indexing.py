"""공모전 저장·변경이 검색 색인을 맞춘다 — 단건 색인 태스크와 전체 재색인
스캔, 그리고 실물 어댑터 장애 시 DB 검색 물러나기 (#450, 부모 #444 스펙).

**단건 색인 태스크의 효과는 그 함수를 직접 불러 확인한다**
(`core.tasks.backup_database`·`contests/tasks.py` 모듈 docstring과 같은
관용구) — dev·CI는 이 태스크를 소비할 워커가 없으므로(#40) `.delay()`는 큐에
쌓이기만 한다. 저장 시점에 그 태스크가 실제로 큐에 들어가는지는 `delay`를
몽키패치해 별도로 확인한다(`tests/test_classroom_immediate_scoring.py`와 같은
관용구).

전체 재색인은 스캔 등록부에 있으므로 `POST /api/internal/scans/contest-search-
reindex`로 돈다(CLAUDE.md "HTTP가 유일한 시임이다").
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import SponsorProfile
from contests import search as search_module
from contests import tasks as contests_tasks
from contests.models import Category, Contest, DeliverableType
from contests.search import FakeContestSearchAdapter

SCAN_URL = "/api/internal/scans/contest-search-reindex"


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


@pytest.fixture
def sponsor(db):
    user = get_user_model().objects.create_user(
        username="index-sponsor", email="index-sponsor@example.invalid"
    )
    return SponsorProfile.objects.create(user=user, display_name="색인 테스트 스폰서")


@pytest.fixture
def games(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def web(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=2_000_000)


def _contest(sponsor, category, deliverable_types, *, status=Contest.Status.PUBLISHED, days=5, **fields):
    contest = Contest.objects.create(
        sponsor=sponsor,
        title=fields.pop("title", "색인 테스트 공모전"),
        description=fields.pop("description", "설명"),
        category=category,
        prize=fields.pop("prize", 1_000_000),
        deadline_at=timezone.now() + timedelta(days=days),
        status=status,
        **fields,
    )
    contest.deliverable_types.set(deliverable_types)
    return contest


# --- 저장·변경 → 태스크가 큐에 들어간다 --------------------------------------


def test_saving_a_contest_enqueues_the_index_task(
    db, sponsor, games, web, monkeypatch, django_capture_on_commit_callbacks
):
    calls: list[int] = []
    monkeypatch.setattr(
        contests_tasks.index_contest, "delay", lambda contest_id: calls.append(contest_id)
    )

    with django_capture_on_commit_callbacks(execute=True):
        contest = _contest(sponsor, games, [web])

    assert contest.id in calls


def test_changing_deliverable_types_enqueues_the_index_task(
    db, sponsor, games, web, monkeypatch, django_capture_on_commit_callbacks
):
    mobile = DeliverableType.objects.create(name="모바일 앱", minimum_prize=1_500_000)
    contest = _contest(sponsor, games, [web])

    calls: list[int] = []
    monkeypatch.setattr(
        contests_tasks.index_contest, "delay", lambda contest_id: calls.append(contest_id)
    )

    with django_capture_on_commit_callbacks(execute=True):
        contest.deliverable_types.add(mobile)

    assert contest.id in calls


def test_sponsor_display_name_change_enqueues_every_one_of_their_contests(
    db, sponsor, games, web, monkeypatch, django_capture_on_commit_callbacks
):
    first = _contest(sponsor, games, [web])
    second = _contest(sponsor, games, [web])

    calls: list[int] = []
    monkeypatch.setattr(
        contests_tasks.index_contest, "delay", lambda contest_id: calls.append(contest_id)
    )

    with django_capture_on_commit_callbacks(execute=True):
        sponsor.display_name = "새 표시 이름"
        sponsor.save()

    assert set(calls) == {first.id, second.id}


# --- 태스크 자신의 효과: fake 어댑터 상태로 확인 ------------------------------


def test_the_task_indexes_a_published_contest(db, sponsor, games, web):
    contest = _contest(sponsor, games, [web])

    contests_tasks.index_contest(contest.id)

    assert FakeContestSearchAdapter._indexed.get(contest.id) is True


def test_the_task_removes_a_contest_that_returned_to_draft(db, sponsor, games, web):
    contest = _contest(sponsor, games, [web])
    contests_tasks.index_contest(contest.id)
    assert contest.id in FakeContestSearchAdapter._indexed

    contest.status = Contest.Status.DRAFT
    contest.save(update_fields=["status"])
    contests_tasks.index_contest(contest.id)

    assert contest.id not in FakeContestSearchAdapter._indexed


# --- 전체 재색인 스캔 ---------------------------------------------------------


def _make_reindex_overdue():
    """이 스캔은 실제 벽시계로 하루에 한 번만 돈다(`contests/models.py`의
    `ContestSearchReindexState` docstring) — 새로 만든 행은 "방금 찜됐다"는
    뜻이라 곧바로 다시 돌지 않는다. 그래서 "지금 도는가"를 보는 테스트는 그
    행을 하루 전으로 직접 되돌려 "이미 하루가 지났다"를 흉내낸다."""

    from contests.models import ContestSearchReindexState

    ContestSearchReindexState.objects.update_or_create(
        pk=1, defaults={"last_reindexed_at": timezone.now() - timedelta(days=2)}
    )


def test_reindex_scan_runs_through_the_internal_endpoint(db, client, sponsor, games, web):
    published = _contest(sponsor, games, [web])
    draft = _contest(sponsor, games, [web], status=Contest.Status.DRAFT)
    _make_reindex_overdue()

    response = client.post(SCAN_URL, **_internal_headers())

    assert response.status_code == 200, response.json()
    assert FakeContestSearchAdapter._indexed.get(published.id) is True
    assert draft.id not in FakeContestSearchAdapter._indexed


def test_reindex_scan_does_not_run_again_within_the_same_day(db, client, sponsor, games, web):
    """`tests/test_scheduler_tick.py`가 다른 모든 스캔에 요구하는 것과 같은
    계약이다 — 두 번 불러도 실제로 하는 일은 한 번뿐이다(ADR-0003)."""

    _make_reindex_overdue()
    first = client.post(SCAN_URL, **_internal_headers())
    assert first.json()["count"] == 1

    second = client.post(SCAN_URL, **_internal_headers())

    assert second.json()["count"] == 0


def test_reindex_scan_is_not_due_right_after_this_process_first_touches_it(db, client):
    """새로 만든 `ContestSearchReindexState` 행은 "방금 찜됐다"로 본다 — 이
    프로세스에서 처음 스캔을 건드린 순간 곧바로 다시 돌지 않는다. 이게 없으면
    검색과 무관한 테스트가 주입된 시계를 며칠씩 앞당길 때마다(`ClockOverride`)
    이 스캔이 `/api/internal/tick`의 `rows`에 끼어든다 — `contests/models.py`의
    `ContestSearchReindexState` docstring 참고."""

    response = client.post(SCAN_URL, **_internal_headers())

    assert response.json()["count"] == 0


def test_reindex_scan_rejects_without_the_internal_token(client, db):
    response = client.post(SCAN_URL, content_type="application/json")

    assert response.status_code == 401


# --- 검색 어댑터 실패 → DB 검색으로 물러난다 ----------------------------------


def test_search_falls_back_to_db_search_when_the_adapter_is_unavailable(
    client, db, monkeypatch, sponsor, games, web
):
    """`FakeContestSearchAdapter.search`가 `ContestSearchUnavailable`을 던지도록
    몽키패치해 실물 어댑터의 연결 실패·시간 초과를 흉내낸다 — fake 자체에는
    장애 시나리오 설정을 두지 않는다(`contests/search.py` 모듈 docstring)."""

    hit = _contest(sponsor, games, [web])
    Contest.objects.filter(pk=hit.pk).update(title="중고 거래 플랫폼")
    miss = _contest(sponsor, games, [web])
    Contest.objects.filter(pk=miss.pk).update(title="상관없는 제목", description="상관없음")

    def _raising_search(self, *, query, category=None, deliverable_type=None):
        raise search_module.ContestSearchUnavailable("연결할 수 없습니다.")

    monkeypatch.setattr(FakeContestSearchAdapter, "search", _raising_search)

    response = client.get("/api/contests?q=거래")

    assert response.status_code == 200
    assert [c["id"] for c in response.json()["items"]] == [hit.id]


def test_search_contests_reports_the_fallback_to_the_error_collector(
    db, monkeypatch, sponsor, games, web
):
    hit = _contest(sponsor, games, [web])
    Contest.objects.filter(pk=hit.pk).update(title="중고 거래 플랫폼")

    def _raising_search(self, *, query, category=None, deliverable_type=None):
        raise search_module.ContestSearchUnavailable("연결할 수 없습니다.")

    monkeypatch.setattr(FakeContestSearchAdapter, "search", _raising_search)

    captured: list[BaseException] = []
    monkeypatch.setattr(
        "core.observability.capture_handled_exception",
        lambda exc, **tags: captured.append(exc),
    )

    result = search_module.search_contests(query="거래")

    assert result == [hit.id]
    assert len(captured) == 1
    assert isinstance(captured[0], search_module.ContestSearchUnavailable)
