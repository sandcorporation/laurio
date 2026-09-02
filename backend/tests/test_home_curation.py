"""홈의 네 묶음 — 진행중·마감임박·심사중·완료 (#94, spec #92).

**판정은 백엔드가 한다.** `contests.curation.home_bucket_for`가 하나의 값으로
번역하고, 이 테스트는 그 값이 `GET /api/contests/home` 응답에 그대로 실리는지
HTTP 시임으로 확인한다(CLAUDE.md — 시임은 언제나 HTTP).

`test_every_public_status_lands_in_exactly_one_bucket`가 이 파일에서 가장
중요한 테스트다 — 고정된 상태 목록이 아니라 `Contest.Status` 자체를 순회한다.
나중에 상태가 하나 늘면 이 테스트도 그 값을 함께 돌기 때문에,
`contests.curation.home_bucket_for`나 `contests.api._PUBLICLY_VISIBLE_STATUSES`
어느 한쪽이라도 그 값을 받아들이지 않으면 여기서 즉시 드러난다 — 화면이
조용히 그 부류를 안 보여주게 되는 실패를 여기서 막는다(#94 인수조건).
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import SponsorProfile
from contests.curation import HOME_IMMINENT_DEADLINE_DAYS, HomeCurationBucket
from contests.models import Category, Contest, DeliverableType

HOME_URL = "/api/contests/home"


@pytest.fixture
def sponsor(db):
    user = get_user_model().objects.create_user(
        username="home-curation-sponsor", email="home-curation-sponsor@example.invalid"
    )
    return SponsorProfile.objects.create(user=user, display_name="홈 큐레이션 스폰서")


@pytest.fixture
def category(db):
    return Category.objects.create(name="홈큐레이션")


@pytest.fixture
def deliverable_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _make_contest(
    sponsor, category, deliverable_type, *, status, deadline_at, judging_ends_at=None,
    title="공모전",
):
    contest = Contest.objects.create(
        sponsor=sponsor,
        title=title,
        category=category,
        prize=1_000_000,
        deadline_at=deadline_at,
        status=status,
        judging_ends_at=judging_ends_at,
    )
    contest.deliverable_types.set([deliverable_type])
    return contest


def _buckets(client) -> dict:
    response = client.get(HOME_URL)
    assert response.status_code == 200, response.content
    return {group["bucket"]: group["contests"] for group in response.json()}


def _ids(contests) -> list[int]:
    return [c["id"] for c in contests]


@pytest.mark.django_db
def test_empty_platform_still_returns_all_four_buckets(client):
    """빈 플랫폼은 빈 목록이 아니라 "비어 있다"고 말할 수 있어야 한다(#94 인수조건)."""

    response = client.get(HOME_URL)
    assert response.status_code == 200, response.content
    body = response.json()

    assert {group["bucket"] for group in body} == {b.value for b in HomeCurationBucket}
    for group in body:
        assert group["contests"] == []


@pytest.mark.django_db
def test_published_far_from_deadline_is_ongoing(client, sponsor, category, deliverable_type):
    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 5),
    )

    buckets = _buckets(client)

    assert contest.id in _ids(buckets[HomeCurationBucket.ONGOING])
    assert contest.id not in _ids(buckets[HomeCurationBucket.IMMINENT])


@pytest.mark.django_db
def test_published_near_deadline_is_imminent_not_ongoing(
    client, sponsor, category, deliverable_type
):
    """마감이 가까운 Contest가 「진행중」이 아니라 「마감임박」에 들어간다(#94 인수조건)."""

    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=1),
    )

    buckets = _buckets(client)

    assert contest.id in _ids(buckets[HomeCurationBucket.IMMINENT])
    assert contest.id not in _ids(buckets[HomeCurationBucket.ONGOING])


@pytest.mark.django_db
def test_closed_is_in_judging(client, sponsor, category, deliverable_type):
    """CLOSED는 심사중이다 — 데모·영상은 이미 전면 공개다(ADR-0014)."""

    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.CLOSED,
        deadline_at=timezone.now() - timedelta(days=1),
        judging_ends_at=timezone.now() + timedelta(days=6),
    )

    buckets = _buckets(client)

    assert contest.id in _ids(buckets[HomeCurationBucket.IN_JUDGING])


@pytest.mark.django_db
def test_awarded_is_completed(client, sponsor, category, deliverable_type):
    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.AWARDED,
        deadline_at=timezone.now() - timedelta(days=10),
        judging_ends_at=timezone.now() - timedelta(days=3),
    )

    buckets = _buckets(client)

    assert contest.id in _ids(buckets[HomeCurationBucket.COMPLETED])


@pytest.mark.django_db
def test_judging_ended_is_completed(client, sponsor, category, deliverable_type):
    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.JUDGING_ENDED,
        deadline_at=timezone.now() - timedelta(days=10),
        judging_ends_at=timezone.now() - timedelta(days=1),
    )

    buckets = _buckets(client)

    assert contest.id in _ids(buckets[HomeCurationBucket.COMPLETED])


@pytest.mark.django_db
def test_draft_appears_in_no_bucket(client, sponsor, category, deliverable_type):
    """결제 전 Contest가 새지 않는다(#94 인수조건) — 공개 목록/상세와 같은 경계다."""

    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.DRAFT,
        deadline_at=timezone.now() + timedelta(days=5),
    )

    buckets = _buckets(client)

    for contests in buckets.values():
        assert contest.id not in _ids(contests)


@pytest.mark.django_db
def test_every_public_status_lands_in_exactly_one_bucket(
    client, sponsor, category, deliverable_type
):
    """새 `Contest.Status`가 생겨도 홈이 그 부류를 조용히 누락하지 않는다.

    고정된 상태 목록이 아니라 `Contest.Status` 자체를 순회한다 — 이 스위트를
    돌리는 시점의 그 enum 이 갖고 있는 모든 값을 대상으로 한다. 나중에 상태가
    하나 늘면 이 테스트도 자동으로 그 값을 포함해서 돈다.
    """

    far_future = timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 20)
    near_past = timezone.now() - timedelta(days=1)

    contest_id_by_status = {}
    for status in Contest.Status:
        deadline_at = far_future if status == Contest.Status.PUBLISHED else near_past
        judging_ends_at = None
        if status in (
            Contest.Status.CLOSED,
            Contest.Status.AWARDED,
            Contest.Status.JUDGING_ENDED,
        ):
            judging_ends_at = timezone.now() + timedelta(days=6)

        contest = _make_contest(
            sponsor, category, deliverable_type,
            status=status, deadline_at=deadline_at, judging_ends_at=judging_ends_at,
            title=f"상태 고정 테스트 — {status}",
        )
        contest_id_by_status[status] = contest.id

    buckets = _buckets(client)
    all_bucketed_ids = [cid for contests in buckets.values() for cid in _ids(contests)]

    for status, contest_id in contest_id_by_status.items():
        if status == Contest.Status.DRAFT:
            assert contest_id not in all_bucketed_ids, f"{status} 는 어느 묶음에도 없어야 한다"
        else:
            assert contest_id in all_bucketed_ids, f"{status} 가 어떤 묶음에도 없다"

    # 같은 Contest가 두 묶음에 동시에 들어가지 않는다.
    assert len(all_bucketed_ids) == len(set(all_bucketed_ids))


@pytest.mark.django_db
def test_bucket_caps_at_the_home_limit(client, sponsor, category, deliverable_type):
    """홈은 큐레이션이지 탐색이 아니다 — 한 묶음이 무한정 길어지지 않는다(#94)."""

    from contests.api import _HOME_BUCKET_LIMIT

    for i in range(_HOME_BUCKET_LIMIT + 3):
        _make_contest(
            sponsor, category, deliverable_type,
            status=Contest.Status.PUBLISHED,
            deadline_at=timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 10, minutes=i),
            title=f"진행중 {i}",
        )

    buckets = _buckets(client)

    assert len(buckets[HomeCurationBucket.ONGOING]) == _HOME_BUCKET_LIMIT
