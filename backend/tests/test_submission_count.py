"""공개 화면(목록·상세·홈 큐레이션)에 참가작 수가 보인다 (#106, spec #105).

핵심 규율:

- 참가작 수는 백엔드가 annotate로 낸 값이다 — 화면도 이 테스트도 따로 세지
  않는다. 그래서 대부분의 테스트가 "심고 세는 것"을 같은 단언 안에서 대비시킨다
  (`Submission.objects.filter(...).count()`와 응답 값을 나란히 비교한다) — 화면이
  원시 상태에서 파생하다 갈리는 실패를 이 저장소가 반복해서 겪었다(CLAUDE.md).
- 0도 숨기지 않는다 — 응답은 숫자 0을 그대로 싣고, "아직 참가작이 없습니다"라는
  문구는 화면의 몫이다. 숫자와 문구가 다른 층에서 결정된다는 것을 이 테스트가
  드러낸다.
- 마감 전에 이 수를 공개하는 것은 ADR-0014를 어기지 않는다 — 그 규율이 감추는
  것은 개별 Submission이고, 집계는 그 대상이 아니다. 이 파일은 집계를 열면서 그
  규율이 함께 열리지 않았다는 것을 **없는지**로 단언한다(있는지가 아니라).
- 네 묶음(진행중·마감임박·심사중·완료) 모두에서 수가 나오는지는 고정된 나열이
  아니라 `HomeCurationBucket` 자체를 순회해 확인한다 — 홈 큐레이션 테스트
  (test_home_curation.py)와 같은 관용구다.
- 목록이 행마다 세지 않는다는 것은 `CaptureQueriesContext`로 직접 쿼리 수를
  잰다 — `test_distributions.py`가 이미 쓰는 관용구와 같다.
- 시임은 HTTP다(CLAUDE.md) — 마운트된 django-ninja API를 전체 요청 스택으로
  친다.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from contests.curation import HOME_IMMINENT_DEADLINE_DAYS, HomeCurationBucket
from contests.models import Category, Contest, DeliverableType
from submissions.models import Submission

CONTESTS_URL = "/api/contests"
HOME_URL = "/api/contests/home"
SUBMISSIONS_URL = "/api/submissions"


@pytest.fixture
def sponsor(db):
    user = get_user_model().objects.create_user(
        username="submission-count-sponsor",
        email="submission-count-sponsor@example.invalid",
    )
    return SponsorProfile.objects.create(user=user, display_name="참가작수 테스트 스폰서")


@pytest.fixture
def category(db):
    return Category.objects.create(name="참가작수")


@pytest.fixture
def deliverable_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _make_contest(
    sponsor,
    category,
    deliverable_type,
    *,
    status,
    deadline_at,
    judging_ends_at=None,
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


_developer_seq = 0


def _make_developer(prefix):
    global _developer_seq
    _developer_seq += 1
    username = f"submission-count-dev-{prefix}-{_developer_seq}"
    user = get_user_model().objects.create_user(
        username=username, email=f"{username}@example.invalid"
    )
    return DeveloperProfile.objects.create(user=user)


def _plant_submissions(contest, count, *, prefix):
    """`contest`에 서로 다른 Developer가 낸 Submission을 `count`건 심는다.

    한 Developer는 한 Contest에 하나만 낼 수 있으므로(Submission의 unique
    constraint) 매번 새 Developer를 만든다.
    """

    for i in range(count):
        developer = _make_developer(f"{prefix}-{i}")
        Submission.objects.create(
            contest=contest,
            developer=developer,
            source_object_key=f"submission:{contest.id}:{prefix}:{i}:source/deadbeef",
        )


@pytest.mark.django_db
def test_submission_count_in_list_matches_actual_submissions(
    client, sponsor, category, deliverable_type
):
    contest = _make_contest(
        sponsor,
        category,
        deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=10),
        title="목록 참가작 수 테스트",
    )
    _plant_submissions(contest, 3, prefix="list")

    response = client.get(CONTESTS_URL)
    assert response.status_code == 200, response.content
    item = next(c for c in response.json()["items"] if c["id"] == contest.id)

    assert item["submission_count"] == 3
    assert item["submission_count"] == Submission.objects.filter(contest=contest).count()


@pytest.mark.django_db
def test_submission_count_in_detail_matches_actual_submissions(
    client, sponsor, category, deliverable_type
):
    contest = _make_contest(
        sponsor,
        category,
        deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=10),
    )
    _plant_submissions(contest, 2, prefix="detail")

    response = client.get(f"{CONTESTS_URL}/{contest.id}")
    assert response.status_code == 200, response.content

    assert response.json()["submission_count"] == 2
    assert response.json()["submission_count"] == Submission.objects.filter(
        contest=contest
    ).count()


@pytest.mark.django_db
def test_zero_submissions_returns_zero_not_omitted(
    client, sponsor, category, deliverable_type
):
    """0도 숨기지 않는다 — 응답은 숫자 그대로, 문구는 화면의 몫이다."""

    contest = _make_contest(
        sponsor,
        category,
        deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=10),
    )

    response = client.get(f"{CONTESTS_URL}/{contest.id}")
    assert response.status_code == 200, response.content
    body = response.json()

    assert "submission_count" in body
    assert body["submission_count"] == 0


@pytest.mark.django_db
def test_home_curation_shows_submission_count_for_every_bucket(
    client, sponsor, category, deliverable_type
):
    """네 묶음 모두에서 수가 나온다 — 고정 나열이 아니라 묶음 자체를 순회한다."""

    far_future = timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 20)
    near_future = timezone.now() + timedelta(days=1)
    near_past = timezone.now() - timedelta(days=1)

    plan = {
        HomeCurationBucket.ONGOING: (Contest.Status.PUBLISHED, far_future, None, 1),
        HomeCurationBucket.IMMINENT: (Contest.Status.PUBLISHED, near_future, None, 2),
        HomeCurationBucket.IN_JUDGING: (
            Contest.Status.CLOSED,
            near_past,
            timezone.now() + timedelta(days=6),
            3,
        ),
        HomeCurationBucket.COMPLETED: (
            Contest.Status.AWARDED,
            near_past,
            timezone.now() - timedelta(hours=1),
            4,
        ),
    }

    contest_ids: dict = {}
    for bucket in HomeCurationBucket:
        status, deadline_at, judging_ends_at, count = plan[bucket]
        contest = _make_contest(
            sponsor,
            category,
            deliverable_type,
            status=status,
            deadline_at=deadline_at,
            judging_ends_at=judging_ends_at,
            title=f"묶음 참가작 수 테스트 — {bucket}",
        )
        _plant_submissions(contest, count, prefix=str(bucket))
        contest_ids[bucket] = (contest.id, count)

    response = client.get(HOME_URL)
    assert response.status_code == 200, response.content
    groups = {g["bucket"]: g["contests"] for g in response.json()}

    for bucket in HomeCurationBucket:
        contest_id, expected_count = contest_ids[bucket]
        matches = [c for c in groups[bucket.value] if c["id"] == contest_id]
        assert matches, f"「{bucket}」 묶음에 참가작 수 테스트용 Contest 가 없다"
        assert matches[0]["submission_count"] == expected_count


@pytest.mark.django_db
def test_list_query_count_does_not_grow_with_more_contests(
    client, sponsor, category, deliverable_type
):
    """목록이 행마다 세지 않는다 — 집계는 질의 하나에 함께 실린다(#106 인수조건).

    홈 큐레이션(#94)이 같은 자리에서 N+1을 명시적으로 경계했고, 목록은 그보다
    행이 많다. 행 수를 늘려도(3건 -> 11건) 질의 수가 늘지 않는 것을 고정한다.
    """

    def _seed(n, prefix):
        for i in range(n):
            contest = _make_contest(
                sponsor,
                category,
                deliverable_type,
                status=Contest.Status.PUBLISHED,
                deadline_at=timezone.now() + timedelta(days=10 + i),
                title=f"{prefix}-{i}",
            )
            _plant_submissions(contest, i % 3, prefix=f"{prefix}{i}")

    _seed(3, "small")
    with CaptureQueriesContext(connection) as small_ctx:
        small_response = client.get(CONTESTS_URL)
    assert small_response.status_code == 200, small_response.content

    _seed(8, "large")
    with CaptureQueriesContext(connection) as large_ctx:
        large_response = client.get(CONTESTS_URL)
    assert large_response.status_code == 200, large_response.content

    assert len(large_ctx.captured_queries) == len(small_ctx.captured_queries), (
        f"쿼리 수가 행 수(3 -> 11)에 비례해 늘었다: "
        f"{len(small_ctx.captured_queries)} -> {len(large_ctx.captured_queries)}"
    )


@pytest.mark.django_db
def test_individual_submission_still_404_before_deadline_despite_open_aggregate(
    client, sponsor, category, deliverable_type
):
    """집계를 여는 것이 개별 Submission을 여는 것으로 이어지지 않는다(ADR-0014).

    목록·상세가 참가작 수를 공개해도, 그 수를 이루는 개별 Submission은 마감 전에
    여전히 404다 — "있는지"가 아니라 "없는지"를 본다.
    """

    contest = _make_contest(
        sponsor,
        category,
        deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=10),
    )
    developer = _make_developer("aggregate-vs-individual")
    submission = Submission.objects.create(
        contest=contest,
        developer=developer,
        source_object_key=f"submission:{contest.id}:agg:source/deadbeef",
    )

    # 집계는 열려 있다.
    detail = client.get(f"{CONTESTS_URL}/{contest.id}")
    assert detail.status_code == 200, detail.content
    assert detail.json()["submission_count"] == 1

    # 개별 Submission은 여전히 없다.
    response = client.get(f"{SUBMISSIONS_URL}/{submission.id}")
    assert response.status_code == 404


@pytest.mark.django_db
def test_draft_contest_never_appears_even_with_submissions(
    client, sponsor, category, deliverable_type
):
    """DRAFT Contest는 참가작이 있어도 어느 공개 표면에도 나타나지 않는다."""

    contest = _make_contest(
        sponsor,
        category,
        deliverable_type,
        status=Contest.Status.DRAFT,
        deadline_at=timezone.now() + timedelta(days=10),
    )
    _plant_submissions(contest, 2, prefix="draft")

    list_response = client.get(CONTESTS_URL)
    assert contest.id not in [c["id"] for c in list_response.json()["items"]]

    home_response = client.get(HOME_URL)
    for group in home_response.json():
        assert contest.id not in [c["id"] for c in group["contests"]]

    detail_response = client.get(f"{CONTESTS_URL}/{contest.id}")
    assert detail_response.status_code == 404
