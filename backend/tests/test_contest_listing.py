"""공개 목록의 필터·정렬·페이지네이션을 백엔드가 처리한다 (#39).

왜 이 티켓이 있나 — FE-04(#29)를 만들 때 `GET /api/contests` 에는 `page`/`page_size`
밖에 없어서, 프론트가 최대 200건을 한 번에 받아 서버 컴포넌트 안에서 직접 거르고
정렬했다. 그 방식은 공개 Contest 가 200건을 넘는 순간 목록에서 **조용히 누락**된다 —
예외도 빈 화면도 아니고 그냥 없는 것처럼 보인다. 공개 표면에서 가장 나쁜 실패
방식이라 필터·정렬을 백엔드로 내린다.

시임은 HTTP 다(CLAUDE.md) — 마운트된 django-ninja API 를 전체 요청 스택으로 친다.
"""

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import SponsorProfile
from contests.models import Category, Contest, DeliverableType


@pytest.fixture
def sponsor(db):
    user = get_user_model().objects.create_user(
        username="listing-sponsor", email="listing-sponsor@example.invalid"
    )
    return SponsorProfile.objects.create(user=user, display_name="목록 테스트 스폰서")


@pytest.fixture
def games(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def productivity(db):
    return Category.objects.create(name="생산성")


@pytest.fixture
def web(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=2_000_000)


@pytest.fixture
def mobile(db):
    return DeliverableType.objects.create(name="모바일 앱", minimum_prize=1_500_000)


def _publish(sponsor, category, deliverable_types, *, title, prize, days):
    contest = Contest.objects.create(
        sponsor=sponsor,
        title=title,
        category=category,
        prize=prize,
        deadline_at=timezone.now() + timedelta(days=days),
        status=Contest.Status.PUBLISHED,
    )
    contest.deliverable_types.set(deliverable_types)
    return contest


def _ids(payload):
    return [c["id"] for c in payload["items"]]


@pytest.mark.django_db
def test_category_filter_narrows_the_list(client, sponsor, games, productivity, web):
    game_contest = _publish(sponsor, games, [web], title="게임 하나", prize=3_000_000, days=5)
    other = _publish(sponsor, productivity, [web], title="생산성 하나", prize=3_000_000, days=6)

    payload = client.get(f"/api/contests?category={games.id}").json()

    assert _ids(payload) == [game_contest.id]
    assert other.id not in _ids(payload)
    assert payload["count"] == 1


@pytest.mark.django_db
def test_deliverable_type_filter_is_a_different_axis_from_category(
    client, sponsor, games, web, mobile
):
    web_only = _publish(sponsor, games, [web], title="웹만", prize=3_000_000, days=5)
    mobile_only = _publish(sponsor, games, [mobile], title="모바일만", prize=3_000_000, days=6)
    both = _publish(sponsor, games, [web, mobile], title="둘 다", prize=3_000_000, days=7)

    payload = client.get(f"/api/contests?deliverable_type={mobile.id}").json()

    assert set(_ids(payload)) == {mobile_only.id, both.id}
    assert web_only.id not in _ids(payload)


@pytest.mark.django_db
def test_two_filters_combine(client, sponsor, games, productivity, web, mobile):
    target = _publish(sponsor, games, [mobile], title="게임+모바일", prize=1_000_000, days=5)
    _publish(sponsor, games, [web], title="게임+웹", prize=1_000_000, days=5)
    _publish(sponsor, productivity, [mobile], title="생산성+모바일", prize=1_000_000, days=5)

    payload = client.get(
        f"/api/contests?category={games.id}&deliverable_type={mobile.id}"
    ).json()

    assert _ids(payload) == [target.id]


@pytest.mark.django_db
def test_default_sort_is_deadline_soonest_first(client, sponsor, games, web):
    later = _publish(sponsor, games, [web], title="나중", prize=1_000_000, days=30)
    sooner = _publish(sponsor, games, [web], title="곧", prize=9_000_000, days=2)
    middle = _publish(sponsor, games, [web], title="중간", prize=5_000_000, days=10)

    payload = client.get("/api/contests").json()

    assert _ids(payload) == [sooner.id, middle.id, later.id]


@pytest.mark.django_db
def test_prize_sort_is_highest_first(client, sponsor, games, web):
    small = _publish(sponsor, games, [web], title="적음", prize=1_000_000, days=2)
    big = _publish(sponsor, games, [web], title="많음", prize=9_000_000, days=30)
    middle = _publish(sponsor, games, [web], title="중간", prize=5_000_000, days=10)

    payload = client.get("/api/contests?sort=prize").json()

    assert _ids(payload) == [big.id, middle.id, small.id]


@pytest.mark.django_db
def test_filter_and_sort_stay_correct_past_the_old_200_item_ceiling(
    client, sponsor, games, productivity, web
):
    """#39 의 핵심 — 프론트가 200건을 받아 직접 거르던 시절의 실패를 재현한다.

    게임 210건 + 생산성 30건을 심는다. 게임 필터를 걸고 페이지를 끝까지 넘기면
    210건이 **하나도 빠짐없이** 나와야 한다. 예전 구조라면 앞의 200건만 받아온
    뒤 거르므로 게임 몇십 건이 조용히 사라졌다.
    """

    game_ids = {
        _publish(
            sponsor, games, [web], title=f"게임 {i:03d}", prize=1_000_000 + i, days=i + 1
        ).id
        for i in range(210)
    }
    for i in range(30):
        _publish(sponsor, productivity, [web], title=f"생산성 {i:03d}", prize=500_000, days=1)

    seen: list[int] = []
    prizes: list[int] = []
    page = 1
    while True:
        payload = client.get(
            f"/api/contests?category={games.id}&sort=prize&page={page}&page_size=50"
        ).json()
        assert payload["count"] == 210, "필터가 걸린 전체 건수도 필터 기준이어야 한다"
        if not payload["items"]:
            break
        seen.extend(_ids(payload))
        prizes.extend(c["prize"] for c in payload["items"])
        page += 1
        assert page < 20, "페이지가 끝나지 않는다"

    assert set(seen) == game_ids
    assert len(seen) == 210, "페이지 경계에서 중복되거나 빠진 항목이 있다"
    assert prizes == sorted(prizes, reverse=True), "페이지를 넘겨도 정렬이 이어져야 한다"


@pytest.mark.django_db
def test_ties_do_not_duplicate_or_drop_items_across_page_boundaries(
    client, sponsor, games, web
):
    """정렬 기준이 전부 동점이어도 페이지 경계가 흔들리면 안 된다.

    상금이 전부 같으면 DB 는 순서를 보장할 이유가 없다 — 페이지마다 다른 순서를
    돌려주면 같은 Contest 가 두 페이지에 나오고 다른 하나는 어느 페이지에도 안
    나온다. 고유 키로 타이브레이커를 두어야 한다.
    """

    same_deadline = timezone.now() + timedelta(days=7)
    ids = set()
    for i in range(45):
        contest = Contest.objects.create(
            sponsor=sponsor,
            title=f"동점 {i:03d}",
            category=games,
            prize=2_000_000,
            deadline_at=same_deadline,
            status=Contest.Status.PUBLISHED,
        )
        contest.deliverable_types.set([web])
        ids.add(contest.id)

    seen: list[int] = []
    for page in (1, 2, 3):
        payload = client.get(f"/api/contests?sort=prize&page={page}&page_size=20").json()
        seen.extend(_ids(payload))

    assert len(seen) == 45
    assert set(seen) == ids
    assert len(set(seen)) == len(seen), "같은 Contest 가 두 페이지에 걸쳐 나왔다"


@pytest.mark.django_db
def test_unknown_sort_value_is_a_client_error_not_a_server_error(client, sponsor, games, web):
    _publish(sponsor, games, [web], title="하나", prize=1_000_000, days=5)

    response = client.get("/api/contests?sort=nonsense")

    assert 400 <= response.status_code < 500, response.content


@pytest.mark.django_db
def test_non_numeric_filter_is_a_client_error_not_a_server_error(client, sponsor, games, web):
    _publish(sponsor, games, [web], title="하나", prize=1_000_000, days=5)

    for query in ("category=abc", "deliverable_type=abc"):
        response = client.get(f"/api/contests?{query}")
        assert 400 <= response.status_code < 500, (query, response.content)


@pytest.mark.django_db
def test_filtering_by_an_id_that_does_not_exist_is_an_empty_list_not_an_error(
    client, sponsor, games, web
):
    _publish(sponsor, games, [web], title="하나", prize=1_000_000, days=5)

    payload = client.get("/api/contests?category=99999999").json()

    assert payload["items"] == []
    assert payload["count"] == 0


@pytest.mark.django_db
def test_draft_contests_are_still_invisible_through_the_new_filters(
    client, sponsor, games, web
):
    """필터를 붙이면서 공개 범위가 넓어지면 안 된다(Contest.Status.PUBLICLY_VISIBLE)."""

    draft = Contest.objects.create(
        sponsor=sponsor,
        title="초안",
        category=games,
        prize=1_000_000,
        deadline_at=timezone.now() + timedelta(days=5),
        status=Contest.Status.DRAFT,
    )
    draft.deliverable_types.set([web])

    for query in ("", f"?category={games.id}", f"?deliverable_type={web.id}", "?sort=prize"):
        payload = client.get(f"/api/contests{query}").json()
        assert draft.id not in _ids(payload), query
