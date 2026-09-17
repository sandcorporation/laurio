"""조회수 옮기기 스캔 — `contest-view-flush` (#446, spec #444).

`contests.view_tracking`이 Redis에 실시간으로 세는 조회수는 그 자체로는 DB에 남지
않는다. 이 스캔이 10분마다 「바뀐 공모전」만 Redis에서 `Contest.view_count`(DB)로
옮긴다 — 개최자 지표 화면·공개 목록·랜딩 큐레이션이 모두 이 DB 값을 읽으므로, 그
값을 확인하려면 먼저 이 스캔을 거쳐야 한다(`tests/test_contest_metrics.py`의
`_view_metrics`가 이미 그렇게 한다).

시임은 언제나 HTTP 다(CLAUDE.md) — 스캔은 `/api/internal/scans/contest-view-flush`로,
일괄 옮기기는 `import_contest_view_counts` 관리 명령으로 친다. Redis 내부 키를
`call_command`/직접 캐시 조작으로 건드리는 자리는 **테스트 준비**뿐이다(다른 테스트가
`ClockOverride.objects.update_or_create`로 시계를 직접 미는 것과 같은 관용구) —
단언은 항상 HTTP 응답으로 한다.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.core.cache import caches
from django.core.management import call_command

from contests.models import Category, Contest, DeliverableType

from tests.test_source_readings import _publish_contest, _verified_user

CONTESTS_URL = "/api/contests"
VIEWS_URL = "/api/contests/{contest_id}/views"
FLUSH_SCAN_URL = "/api/internal/scans/contest-view-flush"
TICK_URL = "/api/internal/tick"


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _record_view(client, contest_id: int, *, access: str | None = None, **extra):
    headers = _auth_header(access) if access else {}
    headers.update(extra)
    return client.post(VIEWS_URL.format(contest_id=contest_id), **headers)


def _flush(client) -> dict:
    response = client.post(FLUSH_SCAN_URL, **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _list_view_count(client, contest_id: int) -> int:
    response = client.get(CONTESTS_URL)
    assert response.status_code == 200, response.content
    item = next(item for item in response.json()["items"] if item["id"] == contest_id)
    return item["view_count"]


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


@pytest.mark.django_db
def test_unique_view_then_flush_reflects_in_the_list_response(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-flush-1", "ci-flush-1")

    assert _list_view_count(client, contest["id"]) == 0

    _record_view(client, contest["id"], access=dev["access"])
    # 스캔을 돌리기 전에는 아직 옮겨지지 않았다 — DB 값은 그대로 0이다.
    assert _list_view_count(client, contest["id"]) == 0

    result = _flush(client)
    assert result["count"] == 1
    assert result["failed"] == []

    assert _list_view_count(client, contest["id"]) == 1


@pytest.mark.django_db
def test_flush_does_not_touch_contests_that_did_not_change(client, category, landing_type):
    sponsor_a, contest_a = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-flush-a", sponsor_ci="ci-flush-sponsor-a",
    )
    sponsor_b, contest_b = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-flush-b", sponsor_ci="ci-flush-sponsor-b",
    )
    dev = _verified_user(client, "dev-flush-2", "ci-flush-2")

    # contest_b는 이번 스캔과 무관하게 이미 DB에 값을 갖고 있다고 가정한다 —
    # HTTP로는 이 값을 직접 심을 길이 없어 DB를 직접 건드린다(테스트 준비).
    Contest.objects.filter(id=contest_b["id"]).update(view_count=42)

    _record_view(client, contest_a["id"], access=dev["access"])
    result = _flush(client)

    # 이번에 옮긴 것은 contest_a 하나뿐이다 — contest_b의 id는 어디에도 없다.
    assert result["rows"][0]["contest_ids"] == [contest_a["id"]]

    assert _list_view_count(client, contest_a["id"]) == 1
    assert _list_view_count(client, contest_b["id"]) == 42


@pytest.mark.django_db
def test_a_run_with_no_changed_contests_does_nothing(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    result = _flush(client)

    assert result["count"] == 0
    assert result["rows"] == []
    assert result["failed"] == []


@pytest.mark.django_db
def test_a_failed_flush_is_retried_on_the_next_run(client, category, landing_type, monkeypatch):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-flush-3", "ci-flush-3")

    _record_view(client, contest["id"], access=dev["access"])

    def _boom(*args, **kwargs):
        raise RuntimeError("옮기기 도중 DB 오류를 흉내낸다")

    monkeypatch.setattr(Contest.objects, "bulk_update", _boom)
    failing_result = _flush(client)
    assert failing_result["count"] == 0
    assert len(failing_result["failed"]) == 1
    monkeypatch.undo()

    # 실패했지만 DB 값은 그대로다 — 옮기지 못한 숫자를 0으로 덮어쓰지 않는다.
    assert _list_view_count(client, contest["id"]) == 0

    retry_result = _flush(client)
    assert retry_result["count"] == 1
    assert retry_result["failed"] == []

    assert _list_view_count(client, contest["id"]) == 1


@pytest.mark.django_db
def test_counting_resumes_from_the_db_value_after_redis_is_emptied(
    client, category, landing_type
):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev_a = _verified_user(client, "dev-flush-4a", "ci-flush-4a")
    dev_b = _verified_user(client, "dev-flush-4b", "ci-flush-4b")

    _record_view(client, contest["id"], access=dev_a["access"])
    _flush(client)
    assert _list_view_count(client, contest["id"]) == 1

    # Redis(여기서는 테스트의 LocMem "sessions" 캐시)가 재시작이나 캐시 비움으로
    # 통째로 비었다고 가정한다 — DB의 1은 그대로 남는다.
    caches["sessions"].clear()

    _record_view(client, contest["id"], access=dev_b["access"])
    _flush(client)

    # 0에서 다시 세지 않고 DB의 1에서 이어 센다.
    assert _list_view_count(client, contest["id"]) == 2


@pytest.mark.django_db
def test_the_sponsors_own_view_never_reaches_the_flush(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    _record_view(client, contest["id"], access=sponsor["access"])
    result = _flush(client)

    assert result["count"] == 0
    assert _list_view_count(client, contest["id"]) == 0


@pytest.mark.django_db
def test_flush_scan_runs_as_part_of_tick(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-flush-5", "ci-flush-5")

    _record_view(client, contest["id"], access=dev["access"])

    response = client.post(TICK_URL, **_internal_headers())
    assert response.status_code == 200, response.content
    assert "contest-view-flush" in response.json()["scans"]

    assert _list_view_count(client, contest["id"]) == 1


# --- 배포 뒤 첫 회차 한 번 — 기존 Redis 값을 DB 로 옮기는 관리 명령 -------------


@pytest.mark.django_db
def test_import_command_moves_existing_redis_counts_into_the_db(
    client, category, landing_type
):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-flush-import-1", "ci-flush-import-1")

    # 스캔이 이 기능 배포 전부터 있었다고 가정한다 — 조회는 이미 Redis에 쌓여
    # 있지만, 「바뀐 공모전」으로는 아무도 표시한 적이 없다(이 기능이 아직 없었으므로).
    _record_view(client, contest["id"], access=dev["access"])
    from contests.view_flush_store import InMemoryChangedContestsStore

    InMemoryChangedContestsStore._ids.clear()

    # 정기 스캔은 바뀐 것이 없어 아무 일도 하지 않는다.
    assert _flush(client)["count"] == 0
    assert _list_view_count(client, contest["id"]) == 0

    call_command("import_contest_view_counts")

    assert _list_view_count(client, contest["id"]) == 1


@pytest.mark.django_db
def test_import_command_is_idempotent(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-flush-import-2", "ci-flush-import-2")

    _record_view(client, contest["id"], access=dev["access"])

    call_command("import_contest_view_counts")
    call_command("import_contest_view_counts")

    assert _list_view_count(client, contest["id"]) == 1
