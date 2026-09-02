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
    client, sponsor, category, deliverable_type, caplog
):
    """새 `Contest.Status`가 생겨도 홈이 그 부류를 조용히 누락하지 않는다.

    고정된 상태 목록이 아니라 `Contest.Status` 자체를 순회한다 — 이 스위트를
    돌리는 시점의 그 enum 이 갖고 있는 모든 값을 대상으로 한다. 나중에 상태가
    하나 늘면 이 테스트도 자동으로 그 값을 포함해서 돈다.

    **두 가지를 함께 지킨다.** 화면에 실제로 보이는 것은
    `_home_bucket_queryset`(#94 코드리뷰 4, 성능 때문에 SQL로 다시 쓴 필터)의
    결과이므로 그쪽이 새 상태를 놓치면 `all_bucketed_ids`에서 바로 드러난다.
    하지만 `home_bucket_for`(판정의 원본)만 새 상태를 놓치고
    `_home_bucket_queryset`은 우연히 맞는 경우, 화면은 정상이어도 둘이
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

    for status, contest_id in contest_id_by_status.items():
        if status == Contest.Status.DRAFT:
            assert contest_id not in all_bucketed_ids, f"{status} 는 어느 묶음에도 없어야 한다"
        else:
            assert contest_id in all_bucketed_ids, f"{status} 가 어떤 묶음에도 없다"

    # 같은 Contest가 두 묶음에 동시에 들어가지 않는다.
    assert len(all_bucketed_ids) == len(set(all_bucketed_ids))

    # `_home_bucket_queryset`과 `home_bucket_for`가 이 상태 집합 전체에서
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
    """`_home_bucket_queryset`(성능 때문에 SQL로 다시 쓴 필터)과
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
    """`_home_bucket_queryset`과 `home_bucket_for`가 갈리면 조용히 넘어가지
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
    쿼리 쪽(`_home_bucket_queryset`)이 그 행을 안 집으면 화면은 여전히 빈다.
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

    from contests.models import Contest
    from submissions.models import Submission

    call_command("seed_demo_contests", verbosity=0)

    demo = Contest.objects.filter(title__startswith="[데모] ")
    assert demo.exists()
    for contest in demo:
        assert contest.submissions.exists(), f"{contest.title} 에 참가작이 없다"

    closed = demo.filter(status=Contest.Status.CLOSED).first()
    submission = Submission.objects.filter(contest=closed).first()
    body = client.get(f"/api/submissions/{submission.pk}").json()

    # 마감 후에도 소스와 테스트 계정은 소유자 본인에게만 보인다(ADR-0014) —
    # 시드가 그 경계를 우회해 만든 데이터가 아니라는 것을 함께 고정한다.
    assert body["source_object_key"] is None
    assert body["test_account"] is None
    assert body["demo_url"]
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
        assert award.submission.contest_id == contest.pk
