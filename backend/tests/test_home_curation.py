"""홈의 네 묶음 — 진행중·마감임박·심사중·완료 (#94, spec #92).

**판정은 백엔드가 한다.** `contests.curation.home_bucket_for`가 하나의 값으로
번역하고, 이 테스트는 그 값이 `GET /api/contests/home` 응답에 그대로 실리는지
HTTP 시임으로 확인한다(CLAUDE.md — 시임은 언제나 HTTP).

`test_every_public_status_lands_in_exactly_one_bucket`가 이 파일에서 가장
중요한 테스트다 — 고정된 상태 목록이 아니라 `Contest.Status` 자체를 순회한다.
나중에 상태가 하나 늘면 이 테스트도 그 값을 함께 돌기 때문에,
`contests.curation.home_bucket_for`나 `Contest.Status.PUBLICLY_VISIBLE`
어느 한쪽이라도 그 값을 받아들이지 않으면 여기서 즉시 드러난다 — 화면이
조용히 그 부류를 안 보여주게 되는 실패를 여기서 막는다(#94 인수조건).
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import SponsorProfile
from contests.curation import HOME_IMMINENT_DEADLINE_DAYS, HomeCurationBucket, home_bucket_for
from contests.models import Category, Contest, DeliverableType
from tests.submission_assets import assets_of, first_value, demo_account_of

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
def test_ongoing_bucket_carries_sponsor_display_name(client, sponsor, category, deliverable_type):
    """랜딩 큐레이션 응답에도 개최자의 공개용 표시 이름이 실린다(#447)."""

    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 5),
    )

    buckets = _buckets(client)
    ongoing_by_id = {c["id"]: c for c in buckets[HomeCurationBucket.ONGOING]}

    assert ongoing_by_id[contest.id]["sponsor_display_name"] == sponsor.display_name


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
    client, sponsor, category, deliverable_type, caplog
):
    """새 `Contest.Status`가 생겨도 홈이 그 부류를 조용히 누락하지 않는다.

    고정된 상태 목록이 아니라 `Contest.Status` 자체를 순회한다 — 이 스위트를
    돌리는 시점의 그 enum 이 갖고 있는 모든 값을 대상으로 한다. 나중에 상태가
    하나 늘면 이 테스트도 자동으로 그 값을 포함해서 돈다.

    **두 가지를 함께 지킨다.** 화면에 실제로 보이는 것은
    `home_bucket_queryset`(#94 코드리뷰 4, 성능 때문에 SQL로 다시 쓴 필터)의
    결과이므로 그쪽이 새 상태를 놓치면 `all_bucketed_ids`에서 바로 드러난다.
    하지만 `home_bucket_for`(판정의 원본)만 새 상태를 놓치고
    `home_bucket_queryset`은 우연히 맞는 경우, 화면은 정상이어도 둘이
    갈렸다는 사실은 로그로만 드러난다 — 그래서 ERROR 로그가 하나도 없는지도
    같이 확인한다. 이게 없으면 리뷰어가 `home_bucket_for`에서
    `JUDGING_ENDED` 처리를 빼는 뮤테이션을 넣었을 때 이 테스트가 더 이상
    실패하지 않는다(#94 코드리뷰 4/5 대응 중 실제로 확인된 회귀).
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

    with caplog.at_level("ERROR", logger="contests.api"):
        buckets = _buckets(client)
    all_bucketed_ids = [cid for contests in buckets.values() for cid in _ids(contests)]

    hidden_statuses = {Contest.Status.DRAFT}
    for status, contest_id in contest_id_by_status.items():
        if status in hidden_statuses:
            assert contest_id not in all_bucketed_ids, f"{status} 는 어느 묶음에도 없어야 한다"
        else:
            assert contest_id in all_bucketed_ids, f"{status} 가 어떤 묶음에도 없다"

    # 같은 Contest가 두 묶음에 동시에 들어가지 않는다.
    assert len(all_bucketed_ids) == len(set(all_bucketed_ids))

    # `home_bucket_queryset`과 `home_bucket_for`가 이 상태 집합 전체에서
    # 하나도 갈리지 않았다 — 화면은 맞아도 판정의 원본이 조용히 틀어지는
    # 것까지 잡는다.
    assert not [r for r in caplog.records if "불일치" in r.message], (
        "쿼리와 home_bucket_for가 갈렸는데 화면은 우연히 맞았다 — "
        f"{[r.message for r in caplog.records]}"
    )


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



@pytest.mark.django_db
def test_overdue_published_lands_in_in_judging_not_imminent(
    client, sponsor, category, deliverable_type
):
    """마감이 지났는데 스캔이 아직 CLOSED로 못 옮긴 PUBLISHED는 「마감임박」이
    아니라 「심사중」이다(#94 코드리뷰 2).

    `deadline_at - now <= 임계값`에만 기대면 이 음수 구간(마감이 며칠 전이어도
    참)까지 「마감임박」으로 잡힌다 — 그리고 오름차순 정렬에서 가장 작은(가장
    음수인) 값이 맨 앞에 온다. `submissions.participation.next_action_for`가
    같은 상황에서 `Contest.status`가 아니라 `deadline_at`을 직접 비교해 마감
    이후로 취급하는 것과 같은 근거로, 이 구간은 「심사중」으로 다룬다.
    """

    overdue = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() - timedelta(days=2),
        title="스캔을 놓친 마감 지난 공모전",
    )

    buckets = _buckets(client)

    assert overdue.id in _ids(buckets[HomeCurationBucket.IN_JUDGING])
    assert overdue.id not in _ids(buckets[HomeCurationBucket.IMMINENT])
    assert overdue.id not in _ids(buckets[HomeCurationBucket.ONGOING])


@pytest.mark.django_db
def test_imminent_bucket_is_not_crowded_out_by_overdue_published(
    client, sponsor, category, deliverable_type
):
    """마감이 지난 PUBLISHED가 「마감임박」 앞자리를 차지해 진짜 D-1을 밀어내지
    않는다(#94 코드리뷰 2 — 실제로 재현됐던 순서 버그)."""

    overdue = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() - timedelta(days=10),
        title="아주 오래 전에 마감된 채로 남은 공모전",
    )
    real_imminent = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=1),
        title="진짜 D-1",
    )

    imminent_ids = _ids(_buckets(client)[HomeCurationBucket.IMMINENT])

    assert real_imminent.id in imminent_ids
    assert overdue.id not in imminent_ids


@pytest.mark.django_db
def test_ongoing_bucket_orders_soonest_deadline_first(
    client, sponsor, category, deliverable_type
):
    """「진행중」·「마감임박」은 마감이 가까운 순이다(#94 코드리뷰 1)."""

    far = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 20),
        title="가장 늦게 마감",
    )
    soon = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 5),
        title="가장 빨리 마감",
    )

    ongoing_ids = _ids(_buckets(client)[HomeCurationBucket.ONGOING])

    assert ongoing_ids.index(soon.id) < ongoing_ids.index(far.id)


@pytest.mark.django_db
def test_in_judging_bucket_orders_most_recently_closed_first(
    client, sponsor, category, deliverable_type
):
    """「심사중」·「완료」는 최근에 마감된 순이다 — 전부 같은 정렬(오름차순)을
    쓰면 「완료」·「심사중」은 가장 오래된 6건에 영구히 고정된다(#94 코드리뷰
    1, 실제로 재현됐던 버그)."""

    long_ago = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.CLOSED,
        deadline_at=timezone.now() - timedelta(days=30),
        judging_ends_at=timezone.now() + timedelta(days=1),
        title="오래 전에 마감",
    )
    just_now = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.CLOSED,
        deadline_at=timezone.now() - timedelta(hours=1),
        judging_ends_at=timezone.now() + timedelta(days=6),
        title="방금 마감",
    )

    in_judging_ids = _ids(_buckets(client)[HomeCurationBucket.IN_JUDGING])

    assert in_judging_ids.index(just_now.id) < in_judging_ids.index(long_ago.id)


@pytest.mark.django_db
def test_completed_bucket_orders_most_recently_completed_first(
    client, sponsor, category, deliverable_type
):
    """어제 선정 완료된 공모전이 몇 달 전 것에 밀려 홈에 안 오르는 일이 없다
    (#94 코드리뷰 1 — 「완료」 묶음의 존재 이유 그 자체)."""

    long_ago = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.JUDGING_ENDED,
        deadline_at=timezone.now() - timedelta(days=60),
        judging_ends_at=timezone.now() - timedelta(days=53),
        title="몇 달 전에 완료",
    )
    recent = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.AWARDED,
        deadline_at=timezone.now() - timedelta(days=8),
        judging_ends_at=timezone.now() - timedelta(days=1),
        title="어제 선정 완료",
    )

    completed_ids = _ids(_buckets(client)[HomeCurationBucket.COMPLETED])

    assert completed_ids.index(recent.id) < completed_ids.index(long_ago.id)


@pytest.mark.django_db
def test_home_bucket_for_agrees_with_the_query_for_every_status_and_boundary(
    client, sponsor, category, deliverable_type
):
    """`home_bucket_queryset`(성능 때문에 SQL로 다시 쓴 필터)과
    `home_bucket_for`(판정의 원본)가 임계값 양쪽 끝에서도 갈리지 않는다(#94
    코드리뷰 4/5 — 조건을 두 벌로 쓰면 언젠가 갈라진다는 이 저장소의 경험).

    임계값 바로 안쪽·바로 바깥쪽·경계 정확히 위 세 지점을 모두 확인한다.
    **시계를 고정한다** — 그렇지 않으면 테스트가 계산한 "지금"과 뷰가 요청
    시점에 부르는 `Clock.now()`가 몇 밀리초 어긋나, 경계에 정확히 걸친
    케이스(마감이 정확히 지금·임계값이 정확히 지금)의 판정이 어느 쪽으로도
    갈 수 있어 테스트 자체가 흔들린다(#78 이후 이 저장소 시간 시임의 관용구
    — `core.models.ClockOverride`).
    """

    from core.models import ClockOverride

    from contests.curation import home_bucket_for

    now = timezone.now()
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": now})
    threshold = timedelta(days=HOME_IMMINENT_DEADLINE_DAYS)

    boundary_cases = [
        ("마감 1초 전", now - timedelta(seconds=1)),
        ("마감 정확히 지금", now),
        ("임계값 정확히 위", now + threshold),
        ("임계값 1초 초과", now + threshold + timedelta(seconds=1)),
    ]

    contests = []
    for label, deadline_at in boundary_cases:
        contest = _make_contest(
            sponsor, category, deliverable_type,
            status=Contest.Status.PUBLISHED, deadline_at=deadline_at,
            title=f"경계값 — {label}",
        )
        contests.append(contest)

    buckets = _buckets(client)
    bucket_by_id = {
        cid: bucket for bucket, contests_in_bucket in buckets.items() for cid in _ids(contests_in_bucket)
    }

    for contest in contests:
        expected = home_bucket_for(contest, now=now)
        assert bucket_by_id.get(contest.id) == expected, (
            f"{contest.title}: 쿼리는 {bucket_by_id.get(contest.id)!r}인데 "
            f"home_bucket_for는 {expected!r}"
        )



@pytest.mark.django_db
def test_bucket_mismatch_is_logged_not_silently_dropped(
    client, sponsor, category, deliverable_type, monkeypatch, caplog
):
    """`home_bucket_queryset`과 `home_bucket_for`가 갈리면 조용히 넘어가지
    않고 로그로 드러난다(#94 코드리뷰 5 — `home_bucket_for`의 docstring이
    적어 둔 "호출부는 조용히 버리지 않고 드러내야 한다"는 계약).

    실제로 갈릴 상황을 만들기는 어려우므로(그러라고 방금 테스트들로 막아
    뒀다), `home_bucket_for`를 몽키패치해 강제로 갈라지게 한 뒤 로그를
    확인한다.
    """

    import contests.api as contests_api

    contest = _make_contest(
        sponsor, category, deliverable_type,
        status=Contest.Status.PUBLISHED,
        deadline_at=timezone.now() + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS + 10),
        title="일부러 갈라지게 만든 공모전",
    )

    def _always_completed(_contest, *, now):
        return HomeCurationBucket.COMPLETED

    monkeypatch.setattr(contests_api, "home_bucket_for", _always_completed)

    with caplog.at_level("ERROR", logger="contests.api"):
        response = client.get(HOME_URL)
    assert response.status_code == 200, response.content

    assert any(
        "불일치" in record.message and str(contest.id) in record.message
        for record in caplog.records
    ), "쿼리와 home_bucket_for가 갈렸는데도 로그가 안 남았다"


def test_demo_seed_fills_every_home_bucket(db, client):
    """`seed_demo_contests` 가 네 묶음을 실제로 채운다 (#52).

    staging 이 처음 떴을 때 홈의 네 묶음이 전부 「아직 없습니다」였다 — 코드가
    아니라 DB 가 비어서였는데, 그 상태로는 큐레이션이 어떻게 보이는지 확인할
    길이 없었다. 이 테스트는 그 시드가 **네 묶음을 전부 채운다**는 것을 HTTP
    시임에서 고정한다.

    시드 자신도 `home_bucket_for` 로 자기가 심은 것을 검사해 어긋나면
    CommandError 로 죽는다. 그건 「시드의 의도」와 「판정」이 맞는지를 보고,
    이 테스트는 그것이 **응답에 실제로 실리는지**를 본다 — 시드가 통과해도
    쿼리 쪽(`home_bucket_queryset`)이 그 행을 안 집으면 화면은 여전히 빈다.
    """

    from django.core.management import call_command

    call_command("seed_demo_contests", verbosity=0)

    groups = client.get(HOME_URL).json()
    by_bucket = {group["bucket"]: group["contests"] for group in groups}

    for bucket in HomeCurationBucket:
        assert by_bucket.get(bucket.value), f"{bucket.value} 묶음이 비어 있다"

    # 데모라는 것이 제목에 드러나야 한다 — staging 방문자가 실제 발주로
    # 오인하면 안 된다.
    for contests in by_bucket.values():
        for contest in contests:
            assert contest["title"].startswith("[데모] ")


def test_demo_seed_is_idempotent(db, client):
    """두 번 돌려도 개수가 늘지 않는다 (#52).

    staging 배포마다 다시 돌릴 수 있어야 하는데, 돌릴 때마다 쌓이면 홈이
    같은 공모전 수십 개로 뒤덮인다.
    """

    from django.core.management import call_command

    call_command("seed_demo_contests", verbosity=0)
    first = {g["bucket"]: len(g["contests"]) for g in client.get(HOME_URL).json()}

    call_command("seed_demo_contests", verbosity=0)
    second = {g["bucket"]: len(g["contests"]) for g in client.get(HOME_URL).json()}

    assert first == second


def test_demo_seed_leaves_nothing_for_the_money_scans(db):
    """데모 시드가 실물 돈 경로를 깨우지 않는다 (#52).

    staging 에는 celery beat 가 돈다. 배분 스캔은 `JUDGING_ENDED` 이면서
    `judging_ends_at` 이 `distribution_wait_days` 만큼 지난 Contest 를 집는데,
    데모를 「한 달 전에 끝난 공모전」으로 심으면 결제도 수상자도 없는 Contest 로
    배분을 만들려 들어 60초마다 실패한다 — 데모 데이터가 실물 어댑터(토스)를
    건드리게 된다.

    「완료」 묶음은 상태로 결정되므로 날짜를 당겨도 화면은 그대로다. 이 테스트는
    그 날짜 선택이 나중에 「더 그럴듯하게」 과거로 옮겨지는 것을 막는다.
    """

    from django.core.management import call_command
    from django.utils import timezone

    from distributions.services import distribution_due_contests
    from policies.models import PlatformPolicy

    call_command("seed_demo_contests", verbosity=0)

    policy = PlatformPolicy.objects.order_by("-id").first() or PlatformPolicy()
    due = list(distribution_due_contests(timezone.now(), policy))

    assert due == [], f"배분 스캔이 데모 Contest 를 집는다: {[c.title for c in due]}"


def test_demo_seed_gives_every_contest_entrants(db, client):
    """데모 공모전마다 참가작이 있고, 마감된 것은 공개로 보인다 (#52).

    참가작 없는 공모전만 늘어서 있으면 발주자에게 「여기 내면 사람이 온다」가
    보이지 않는다 — 큐레이션이 두 관객을 같은 화면으로 설득한다는 것이 spec #92
    의 근거였다.

    마감 전 참가작은 소유자·Sponsor 외에 404 다(ADR-0014). 그래서 「공개로
    보인다」는 마감된 것으로만 확인한다.
    """

    from django.core.management import call_command

    from contests.models import Contest, ContestSubmission

    call_command("seed_demo_contests", verbosity=0)

    demo = Contest.objects.filter(title__startswith="[데모] ")
    assert demo.exists()
    for contest in demo:
        assert contest.submissions.exists(), f"{contest.title} 에 참가작이 없다"

    closed = demo.filter(status=Contest.Status.CLOSED).first()
    submission = ContestSubmission.objects.filter(contest=closed).first()
    body = client.get(f"/api/submissions/{submission.pk}").json()

    # 마감 후에도 소스와 테스트 계정은 소유자 본인에게만 보인다(ADR-0014) —
    # 시드가 그 경계를 우회해 만든 데이터가 아니라는 것을 함께 고정한다.
    assert assets_of(body, "source") == []
    assert demo_account_of(body) == ""
    assert first_value(body, "demo_url")
    assert body["requirement_responses"], "Requirement 응답이 없으면 심사 비교 화면이 빈다"


def test_demo_seed_awarded_contest_actually_has_an_award(db):
    """AWARDED 인데 수상작이 없는 모순을 만들지 않는다 (#52).

    상태만 AWARDED 로 두면 그 Contest 를 여는 화면들이 실제 배포에서는 나올 수
    없는 조합을 그린다. Award 를 함께 심고, 그것이 그 Contest 의 참가작을
    가리키는지까지 본다.
    """

    from django.core.management import call_command

    from awards.models import Award
    from contests.models import Contest

    call_command("seed_demo_contests", verbosity=0)

    for contest in Contest.objects.filter(
        title__startswith="[데모] ", status=Contest.Status.AWARDED
    ):
        award = Award.objects.filter(contest=contest).first()
        assert award is not None, f"{contest.title} 이 AWARDED 인데 Award 가 없다"
        assert award.submission.contestsubmission.contest_id == contest.pk


def _demo_auth_header(user_id: int) -> dict:
    from accounts.tokens import issue_token_pair

    pair = issue_token_pair(user_id)
    return {"HTTP_AUTHORIZATION": f"Bearer {pair.access}"}


def test_demo_seed_developers_and_sponsor_are_verified(db):
    """데모 Developer 전원과 데모 Sponsor 가 VERIFIED 신원을 갖는다 (#252).

    staging 실측 — `seed_demo_contests` 가 만든 데모 Developer 는 전원
    Verification 이 없어, 「내 참여 → 제출물 수정하러 가기」가 본인확인 안내
    화면에서 막혔다. 이 테스트는 시드가 그 구멍을 메우는지를 관리 명령
    직접 호출로 고정한다(다른 `seed_*` 명령의 시임과 같은 자리 — HTTP 가 아니라
    커맨드 자체의 산출물을 본다).

    Sponsor 도 함께 확인한다 — `submissions.api._reject_self_dealing`은 Sponsor
    쪽에 VERIFIED 신원이나 `ci_hash`가 없으면 "불변식 위반"으로 보고 제출 자체를
    403 으로 막는다(정상 운영에서는 개최에 본인확인이 필수라 도달 불가능해야
    하는 경로). 데모는 정상 개최 플로우를 타지 않으므로(ORM 으로 직접 상태를
    만든다) 이 시드가 Sponsor 몫까지 채우지 않으면 데모 전체가 그 가드에
    걸려 죽는다.
    """

    from django.core.management import call_command

    from accounts.models import DeveloperProfile, SponsorProfile
    from verification.models import Verification

    call_command("seed_demo_contests", verbosity=0)

    sponsor = SponsorProfile.objects.get(user__username="demo-seed-sponsor")
    sponsor_verification = Verification.objects.get(user_id=sponsor.user_id)
    assert sponsor_verification.status == Verification.Status.VERIFIED
    assert sponsor_verification.ci_hash

    developers = DeveloperProfile.objects.filter(user__username__startswith="demo-seed-dev-")
    assert developers.count() == 6
    for developer in developers:
        verification = Verification.objects.get(user_id=developer.user_id)
        assert verification.status == Verification.Status.VERIFIED
        assert verification.ci_hash, f"{developer.display_name} 의 ci_hash 가 비어 있다"


def test_demo_seed_verification_declares_itself_as_demo_and_never_collides(db):
    """심는 본인확인이 실제 신원처럼 보이지 않고, 서로/실사용자와 CI 가 겹치지 않는다 (#252).

    ADR-0025 의 "한 계정의 신원은 다른 사람의 것으로 바뀌지 않는다" 불변식은 CI 가
    같으면 동일인으로 본다는 뜻이다 — 데모 CI 가 우연히도 실제 발급 CI 포맷(NICE/KMC
    의 불투명 base64 문자열)과 겹칠 걱정이 없도록, 애초에 실제 CI 가 취하지 않는
    모양("demo-seed-ci-" 접두)으로 짓는다. real_name 도 복호화했을 때 실제 이름으로
    오인되지 않도록 자기 정체를 밝히는 문구를 포함한다.
    """

    from django.core.management import call_command

    from accounts.models import DeveloperProfile, SponsorProfile
    from verification.models import Verification

    call_command("seed_demo_contests", verbosity=0)

    sponsor = SponsorProfile.objects.get(user__username="demo-seed-sponsor")
    developers = list(
        DeveloperProfile.objects.filter(user__username__startswith="demo-seed-dev-")
    )
    verifications = [Verification.objects.get(user_id=sponsor.user_id)] + [
        Verification.objects.get(user_id=d.user_id) for d in developers
    ]

    ci_hashes = {v.ci_hash for v in verifications}
    assert len(ci_hashes) == len(verifications), "데모 신원끼리 CI 가 겹친다 — 자전거래 오탐"

    for verification in verifications:
        assert verification.ci.startswith("demo-seed-ci-"), (
            "데모 CI 가 실제 CI 포맷과 구별되지 않는다"
        )
        assert "데모" in verification.real_name, (
            "복호화된 real_name 이 데모임을 스스로 밝히지 않는다"
        )


def test_demo_seed_developer_can_reach_submission_edit_screen(db, client):
    """데모 Developer 가 진행중 공모전의 제출물 수정 화면까지 막힘 없이 간다 (#252).

    `submissions.api._require_verification`이 실제로 이 요청 경로를 막는 서버
    쪽 관문이다 — 시드가 Verification 을 채우기 전에는 이 PUT 이 403
    "본인확인(Verification)을 완료해야..." 으로 죽었다. 시드 이후에는 그 관문을
    지나 정상적으로 갱신된다는 것을 HTTP 시임(CLAUDE.md)으로 고정한다.

    **예전에는 소스 자료를 새로 하나 지어 실어야 했다.** 시드가 심던 값
    (`submission:demo:{contest.pk}/{rank}/source.zip`)이 쓰기 검증이 기대하는
    형식과 달라, 기존 값을 그대로 되보내면 422 가 나서 200 과 403 을 구별할 수
    없었기 때문이다. #253 이 그 결함을 고쳐 시드가 실제 업로드 경로와 같은
    규칙으로 값을 만들므로, 이제는 우회 없이 **시드가 심은 그대로** 되보낸다 —
    우회가 남아 있으면 이 테스트는 「실제로 되보내면 어떻게 되는가」를 영원히
    안 보게 된다.
    """

    from django.core.management import call_command

    from contests.models import Contest, ContestSubmission

    call_command("seed_demo_contests", verbosity=0)

    contest = Contest.objects.filter(
        title__startswith="[데모] ", status=Contest.Status.PUBLISHED
    ).first()
    submission = ContestSubmission.objects.filter(contest=contest).first()
    headers = _demo_auth_header(submission.developer.user_id)

    existing = client.get(
        f"/api/contests/{contest.id}/submissions/me", **headers
    ).json()

    response = client.put(
        f"/api/contests/{contest.id}/submissions/me",
        data=_echo_payload(existing),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200, response.content


def test_demo_seed_verification_cannot_reach_a_real_transfer(db, client):
    """데모 신원이 있어도 지급·정산 경로가 실제 이체를 시도할 준비조차 되지 않는다 (#252).

    Verification 만으로는 아무 돈도 움직이지 않는다는 것을 두 지점에서 확인한다:

    1. `payouts.services.ensure_seller_registered`가 실제로 불리는 유일한 계기는
       Distribution 스캔(`distribution_due_q` — JUDGING_ENDED 이면서
       `distribution_wait_days` 가 지나야 후보다, 위
       `test_demo_seed_leaves_nothing_for_the_money_scans` 가 이미 그 후보가
       비어 있음을 고정한다)과 `POST /contests/{id}/payout`(Handover 가
       RELEASED 여야 하는 사람의 명시적 요청)뿐이다. 이 시드는 그 어느 것도
       만들지 않는다 — Seller·Payout 행이 하나도 없다.
    2. 데모 AWARDED Contest 는 `awards.api`(진짜 개최 플로우)를 거치지 않고
       ORM 으로 직접 Award 만 만든다 — Handover 가 없다. 그래서 진짜 Developer가
       로그인해 지급을 "요청"해도 서버는 404 로 답한다: 이 신원으로는 지급
       요청 자체가 도달 불가능하다.
    """

    from django.core.management import call_command

    from contests.models import Contest
    from payouts.models import Payout, Seller

    call_command("seed_demo_contests", verbosity=0)

    assert not Seller.objects.exists(), "데모 시드가 Seller 등록을 만들었다"
    assert not Payout.objects.exists(), "데모 시드가 Payout 을 만들었다"

    awarded = Contest.objects.filter(
        title__startswith="[데모] ", status=Contest.Status.AWARDED
    ).first()
    developer_user_id = awarded.submissions.first().developer.user_id
    headers = _demo_auth_header(developer_user_id)

    response = client.post(f"/api/contests/{awarded.id}/payout", **headers)

    assert response.status_code == 404
    assert "인수" in response.json()["detail"]


@pytest.mark.django_db
def test_each_bucket_query_matches_home_bucket_for_at_every_boundary(
    sponsor, category, deliverable_type
):
    """네 묶음 각각에 대해 「`home_bucket_for` 가 그 묶음이라고 답한다」와 「그 묶음의 쿼리가
    포함한다」가 경계 직전·경계·직후와 모든 status 에서 같다(#144) — 술어 ↔ Q 쌍의 공용 헬퍼."""

    from contests.curation import home_bucket_queryset
    from tests.predicate_pairs import assert_predicate_matches_q

    now = timezone.now()
    threshold = timedelta(days=HOME_IMMINENT_DEADLINE_DAYS)
    cases = []
    for label, deadline_at in [
        ("마감 1초 전", now - timedelta(seconds=1)),
        ("마감 정확히 지금", now),
        ("마감 1초 후", now + timedelta(seconds=1)),
        ("임계값 정확히 위", now + threshold),
        ("임계값 1초 초과", now + threshold + timedelta(seconds=1)),
    ]:
        cases.append((
            f"PUBLISHED · {label}",
            _make_contest(
                sponsor, category, deliverable_type,
                status=Contest.Status.PUBLISHED, deadline_at=deadline_at, title=label,
            ),
        ))
    for status in (
        Contest.Status.DRAFT, Contest.Status.CLOSED, Contest.Status.AWARDED, Contest.Status.JUDGING_ENDED
    ):
        cases.append((
            f"{status} · 마감 지남",
            _make_contest(
                sponsor, category, deliverable_type,
                status=status, deadline_at=now - timedelta(days=1), title=str(status),
            ),
        ))

    for bucket in HomeCurationBucket:
        assert_predicate_matches_q(
            cases,
            lambda contest, bucket=bucket: home_bucket_for(contest, now=now) == bucket,
            home_bucket_queryset(Contest.objects.all(), bucket, now=now),
        )


# --- 데모 제출물이 실제로 쓸 수 있는 데이터인가 (#253) ---------------------------
#
# #252 가 본인확인을 심어 제출 화면이 열리게 했더니 한 걸음 뒤에서 다시 막혔다 —
# 시드가 심은 자료 값이 쓰기 검증이 요구하는 형식이 아니었다. 「열린다」와 「쓸 수
# 있다」는 다르고, 후자는 저장을 눌러 본 사람만 발견한다. 그래서 여기서 고정한다.


def _open_demo_contest_and_submission():
    from contests.models import Contest, ContestSubmission

    contest = Contest.objects.filter(
        title__startswith="[데모] ", status=Contest.Status.PUBLISHED
    ).first()
    submission = ContestSubmission.objects.filter(contest=contest).first()
    return contest, submission


def _echo_payload(existing: dict) -> dict:
    """제출 화면이 「아무것도 바꾸지 않고 저장」할 때 보내는 것과 같은 모양.

    **`evidence` 를 반드시 함께 되보낸다.** 화면은 근거를 왕복시키는데 여기서
    빼면 두 가지가 동시에 망가진다 — 저장이 근거를 **지워** 이후 채점이 전부
    미달이 되고, 근거 왕복이 422 로 막혀도 이 테스트는 초록으로 남는다. 한
    걸음 뒤에서 다시 막히는 것을 잡자고 만든 테스트가 정확히 그 실패를 놓치게
    된다.
    """

    return {
        "assets": [
            {
                "id": asset["id"],
                "kind": asset["kind"],
                "value": asset["value"],
                "label": asset["label"],
                "test_account": asset["test_account"],
                "order": asset["order"],
            }
            for asset in existing["assets"]
        ],
        "requirement_responses": [
            {
                "requirement_id": r["requirement_id"],
                "is_met": r["is_met"],
                "note": r["note"],
                "evidence": [
                    {"kind": e["kind"], "value": e["value"], "asset_id": e["asset_id"]}
                    for e in r["evidence"]
                ],
            }
            for r in existing["requirement_responses"]
        ],
    }


def test_demo_submission_saves_unchanged(db, client):
    """데모 제출물을 아무것도 바꾸지 않고 저장해도 성공한다 (#253 AC1).

    화면은 기존 자료를 그대로 되보낸다. 시드가 심은 값이 쓰기 검증을 통과하지
    못하면 사용자는 **자기가 아무것도 안 했는데** 422 를 본다.
    """

    from django.core.management import call_command

    call_command("seed_demo_contests", verbosity=0)
    contest, submission = _open_demo_contest_and_submission()
    headers = _demo_auth_header(submission.developer.user_id)

    existing = client.get(f"/api/contests/{contest.id}/submissions/me", **headers).json()
    before = sum(len(r["evidence"]) for r in existing["requirement_responses"])
    assert before > 0, "시드가 근거를 안 붙였다 — 이 테스트가 볼 것이 없다"

    response = client.put(
        f"/api/contests/{contest.id}/submissions/me",
        data=_echo_payload(existing),
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200, response.content

    # **되보내기가 근거를 지우지 않는다.** 지우면 저장은 성공한 채로 이후 채점이
    # 전부 미달이 된다 — 사용자는 저장만 눌렀는데 점수가 0 이 되는 셈이다.
    after = client.get(f"/api/contests/{contest.id}/submissions/me", **headers).json()
    assert sum(len(r["evidence"]) for r in after["requirement_responses"]) == before


def test_demo_submission_saves_after_an_edit(db, client):
    """고쳐서 저장하는 것도 성공한다 (#253 AC2).

    되보내기만 통과하고 편집이 막히면 데모는 여전히 반쪽이다.
    """

    from django.core.management import call_command

    call_command("seed_demo_contests", verbosity=0)
    contest, submission = _open_demo_contest_and_submission()
    headers = _demo_auth_header(submission.developer.user_id)

    existing = client.get(f"/api/contests/{contest.id}/submissions/me", **headers).json()
    payload = _echo_payload(existing)
    payload["assets"].append(
        {"kind": "demo_url", "value": "https://example.invalid/added-by-test", "label": "추가"}
    )

    response = client.put(
        f"/api/contests/{contest.id}/submissions/me",
        data=payload,
        content_type="application/json",
        **headers,
    )

    assert response.status_code == 200, response.content
    after = client.get(f"/api/contests/{contest.id}/submissions/me", **headers).json()
    assert any(a["value"].endswith("/added-by-test") for a in after["assets"])


def test_demo_asset_values_come_from_the_real_upload_rule(db):
    """시드가 자료 값을 손으로 조립하지 않는다 (#253 AC3).

    규칙을 시드가 따로 적으면 조용히 갈라진다 — 실제로 갈라져 있었다. 이
    테스트는 **모든** 데모 자료를 훑어 실제 업로드 경로가 쓰는 것과 같은
    접두어인지 본다.
    """

    from django.core.management import call_command

    from contests.models import ContestSubmission
    from contests.submission_target_refs import target_ref_for_asset_kind
    from submissions.models import SubmissionAsset

    call_command("seed_demo_contests", verbosity=0)

    checked = 0
    for submission in ContestSubmission.objects.select_related("contest", "developer").all():
        for asset in SubmissionAsset.objects.filter(submission=submission):
            expected = target_ref_for_asset_kind(
                asset.kind,
                contest_id=submission.contest_id,
                developer_user_id=submission.developer.user_id,
            )
            if expected is None:
                continue
            assert asset.value.startswith(f"{expected}/"), (
                f"{asset.kind} 자료가 업로드 대상 밖이다: {asset.value}"
            )
            checked += 1

    assert checked > 0, "검사한 자료가 없다 — 시드가 자료를 안 만든 것인지 확인하라"


def test_demo_seed_writes_the_objects_it_points_at(db):
    """값만 맞고 파일이 없으면 채점이 소스를 못 찾는다 (#253 AC4).

    staging 실측 — 데모 제출물 14건이 전부 「플랫폼이 채점하지 못했다」(0%)로
    끝나 있었다. 데모가 플랫폼 장애를 전시하고 있었던 셈이다. 원인은 시드가
    가리키는 오브젝트를 아무도 쓰지 않은 것이다.
    """

    from django.core.management import call_command

    from storage.adapters import get_storage_adapter
    from submissions.models import Submission, SubmissionAsset
    from contests.submission_target_refs import SLOT_BY_ASSET_KIND

    call_command("seed_demo_contests", verbosity=0)

    adapter = get_storage_adapter()
    checked = 0
    for asset in SubmissionAsset.objects.filter(
        kind__in=list(SLOT_BY_ASSET_KIND), submission__in=Submission.objects.all()
    ):
        assert adapter.read_object(asset.value) is not None, (
            f"가리키는 오브젝트가 없다: {asset.value}"
        )
        checked += 1

    assert checked > 0


def test_demo_submissions_get_a_real_score_not_a_platform_failure(db, client):
    """데모 제출물이 실제로 채점된다 (#253 AC4).

    앞 테스트가 오브젝트의 존재를 보고, 이 테스트는 그 결과 **채점이 실제로
    도달하는지**를 본다 — 자동 0% 두 종류 중 어느 것도 아니어야 한다.
    """

    from django.core.management import call_command

    from contests.models import Contest
    from scoring.models import Score
    from scoring.services import (
        NO_SCORING_INPUT_MODEL_VERSION,
        PLATFORM_FAILURE_MODEL_VERSION,
    )

    call_command("seed_demo_contests", verbosity=0)

    scoreable = Contest.objects.filter(
        title__startswith="[데모] ", status__in=Contest.Status.SCOREABLE.statuses
    )
    assert scoreable.exists(), "채점 대상 데모 공모전이 없다"

    from tests.test_withdrawal import _internal_headers

    response = client.post(
        "/api/internal/scans/submission-scoring", **_internal_headers()
    )
    assert response.status_code == 200, response.content

    scores = list(
        Score.objects.filter(submission__contestsubmission__contest__in=scoreable).values_list(
            "model_version", flat=True
        )
    )
    assert scores, "채점이 하나도 남지 않았다"
    assert NO_SCORING_INPUT_MODEL_VERSION not in scores
    assert PLATFORM_FAILURE_MODEL_VERSION not in scores


def test_demo_url_says_it_will_not_open(db):
    """죽은 링크가 죽은 링크로 보이지 않는다 (#253 AC5).

    데모 URL 은 예약 TLD(`.invalid`)를 가리킨다 — 일부러 열리지 않는 주소이고,
    실재하는 남의 사이트를 가리키는 것보다 낫다. 다만 화면은 링크 텍스트로
    `label` 을 쓰므로(없으면 「데모 보기」), 그 자리에서 열리지 않는다는 것을
    말해야 누른 사람이 깨졌다고 오해하지 않는다.
    """

    from django.core.management import call_command

    from submissions.models import SubmissionAsset

    call_command("seed_demo_contests", verbosity=0)

    demo_urls = SubmissionAsset.objects.filter(kind=SubmissionAsset.Kind.DEMO_URL)
    assert demo_urls.exists()
    for asset in demo_urls:
        assert asset.label.strip(), f"데모 URL 에 라벨이 없다: {asset.value}"
        assert "열리지 않" in asset.label, f"열리지 않는다는 말이 없다: {asset.label}"


def test_demo_assets_carry_readable_labels(db):
    """업로드 자료에도 라벨이 있다 (#253).

    `value` 는 오브젝트 키라 사람이 읽을 것이 없는데, 근거(Evidence)를 어느
    자료에 걸지 고르는 드롭다운은 라벨이 없으면 그 값을 그대로 보여준다 —
    dev 에서 실측했다: 「소스코드: submission:12836:14467:source/794e2024…」.
    데모가 그 화면을 16진수 나열로 보여주면 그 화면이 무엇을 고르는 곳인지
    알 수 없다.
    """

    from django.core.management import call_command

    from submissions.models import SubmissionAsset
    from contests.submission_target_refs import SLOT_BY_ASSET_KIND

    call_command("seed_demo_contests", verbosity=0)

    uploaded = SubmissionAsset.objects.filter(kind__in=list(SLOT_BY_ASSET_KIND))
    assert uploaded.exists()
    for asset in uploaded:
        assert asset.label.strip(), f"업로드 자료에 라벨이 없다: {asset.kind} {asset.value}"
        assert asset.value not in asset.label


def test_demo_scores_are_not_all_zero(db, client):
    """데모 채점이 전부 0% 로 나오지 않는다 (#253).

    「채점이 도달한다」와 「채점이 무언가를 보여준다」는 다르다 — 실측으로 한 번
    더 겪었다: 오브젝트를 심어 플랫폼 실패는 없앴는데, 근거 문구가 소스에 문자
    그대로 없어서 12건이 전부 0.00% 로 나왔다. 데모가 보여주는 것이 「전부
    0점」이면 채점 화면·비교 화면·이의 화면 어느 것도 자기 일을 못 한다.
    """

    from django.core.management import call_command

    from contests.models import Contest
    from scoring.models import Score
    from tests.test_withdrawal import _internal_headers

    call_command("seed_demo_contests", verbosity=0)

    response = client.post("/api/internal/scans/submission-scoring", **_internal_headers())
    assert response.status_code == 200, response.content

    percentages = {
        str(p)
        for p in Score.objects.filter(
            submission__contestsubmission__contest__title__startswith="[데모] "
        ).values_list("percentage", flat=True)
    }
    assert percentages, "데모 채점이 하나도 없다"
    assert percentages != {"0.00"}, f"데모 점수가 전부 0% 다: {percentages}"
    # **아직 0% 아니면 100% 뿐이다.** 데모 공모전마다 필수 Requirement 가 하나라
    # 달성률이 두 값밖에 못 나온다(실측: 100% 11건·0% 1건). 상·중·하가 보이려면
    # 데모 공모전의 요구사항 구성을 바꿔야 하는데 그건 이 티켓의 범위가 아니다 —
    # 여기서는 「전부 0%」만 막는다. 이 주석이 다음 사람에게 그 사실을 넘긴다.
