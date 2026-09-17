"""헤더 검색창 + 목록 API 의 `q`·`sort=relevance` (#449, 부모 #444 스펙).

이 티켓은 검색 엔진 없이 fake(`contests.search.FakeContestSearchAdapter`, DB 포함
검색)로 끝까지 동작한다 — pytest·CI·dev 기본값이 그 fake다(`SEARCH_ADAPTER_MODE`).
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
        username="search-sponsor", email="search-sponsor@example.invalid"
    )
    return SponsorProfile.objects.create(user=user, display_name="검색 테스트 스폰서")


@pytest.fixture
def games(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def web(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=2_000_000)


@pytest.fixture
def mobile(db):
    return DeliverableType.objects.create(name="모바일 앱", minimum_prize=1_500_000)


def _publish(sponsor, category, deliverable_types, *, title, description="", prize, days):
    contest = Contest.objects.create(
        sponsor=sponsor,
        title=title,
        description=description,
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
def test_title_match_ranks_above_description_only_match(client, sponsor, games, web):
    title_hit = _publish(
        sponsor, games, [web], title="중고 거래 플랫폼", description="아무 설명", prize=1_000_000, days=5
    )
    description_hit = _publish(
        sponsor,
        games,
        [web],
        title="다른 제목",
        description="이 서비스는 중고 거래를 도와준다",
        prize=1_000_000,
        days=6,
    )

    payload = client.get("/api/contests?q=거래").json()

    assert _ids(payload) == [title_hit.id, description_hit.id]


@pytest.mark.django_db
def test_q_defaults_to_relevance_sort_without_explicit_sort_param(client, sponsor, games, web):
    # 관련도순이 기본이면, sort 를 명시적으로 deadline/prize 로 줬을 때와 결과 "순서"가
    # 달라져야 한다 — 마감이 가까운 것과 제목 일치가 서로 다른 항목을 위로 올리도록 심는다.
    title_hit = _publish(
        sponsor, games, [web], title="리액트 스터디", description="", prize=1_000_000, days=30
    )
    description_hit = _publish(
        sponsor,
        games,
        [web],
        title="다른 제목",
        description="리액트 경험이 있으면 좋다",
        prize=1_000_000,
        days=1,
    )

    relevance_payload = client.get("/api/contests?q=리액트").json()
    deadline_payload = client.get("/api/contests?q=리액트&sort=deadline").json()

    assert _ids(relevance_payload) == [title_hit.id, description_hit.id]
    assert _ids(deadline_payload) == [description_hit.id, title_hit.id]


@pytest.mark.django_db
def test_q_combines_with_existing_filters(client, sponsor, games, web, mobile):
    matching_category_and_type = _publish(
        sponsor, games, [web], title="플러터 앱 공모전", prize=1_000_000, days=5
    )
    _publish(sponsor, games, [mobile], title="플러터 앱 공모전(모바일)", prize=1_000_000, days=6)

    other_category = Category.objects.create(name="생산성")
    _publish(sponsor, other_category, [web], title="플러터 앱 공모전(생산성)", prize=1_000_000, days=7)

    payload = client.get(
        f"/api/contests?q=플러터&category={games.id}&deliverable_type={web.id}"
    ).json()

    assert _ids(payload) == [matching_category_and_type.id]


@pytest.mark.django_db
def test_q_respects_pagination(client, sponsor, games, web):
    matches = [
        _publish(
            sponsor, games, [web], title=f"검색어 {i:03d}", prize=1_000_000 + i, days=i + 1
        )
        for i in range(25)
    ]
    _publish(sponsor, games, [web], title="상관없음", prize=1_000_000, days=1)

    seen: list[int] = []
    page = 1
    while True:
        payload = client.get(f"/api/contests?q=검색어&page={page}&page_size=10").json()
        assert payload["count"] == 25
        if not payload["items"]:
            break
        seen.extend(_ids(payload))
        page += 1
        assert page < 10, "페이지가 끝나지 않는다"

    assert set(seen) == {c.id for c in matches}
    assert len(seen) == len(set(seen)) == 25


@pytest.mark.django_db
def test_draft_contest_never_appears_in_search(client, sponsor, games, web):
    draft = Contest.objects.create(
        sponsor=sponsor,
        title="초안 검색어",
        category=games,
        prize=1_000_000,
        deadline_at=timezone.now() + timedelta(days=5),
        status=Contest.Status.DRAFT,
    )
    draft.deliverable_types.set([web])

    payload = client.get("/api/contests?q=검색어").json()

    assert draft.id not in _ids(payload)


@pytest.mark.django_db
def test_q_matches_category_deliverable_type_and_sponsor_display_name(
    client, sponsor, games, web
):
    by_category = _publish(sponsor, games, [web], title="A", prize=1_000_000, days=5)
    by_sponsor = _publish(sponsor, games, [web], title="B", prize=1_000_000, days=6)
    unrelated_category = Category.objects.create(name="생산성")
    unrelated = _publish(sponsor, unrelated_category, [web], title="C", prize=1_000_000, days=7)

    category_payload = client.get("/api/contests?q=게임").json()
    sponsor_payload = client.get("/api/contests?q=검색").json()  # "검색 테스트 스폰서"

    assert set(_ids(category_payload)) == {by_category.id, by_sponsor.id}
    assert unrelated.id not in _ids(category_payload)
    assert set(_ids(sponsor_payload)) == {by_category.id, by_sponsor.id, unrelated.id}


@pytest.mark.django_db
def test_no_match_is_an_empty_list_not_an_error(client, sponsor, games, web):
    _publish(sponsor, games, [web], title="아무 제목", prize=1_000_000, days=5)

    payload = client.get("/api/contests?q=존재하지않는검색어").json()

    assert payload["items"] == []
    assert payload["count"] == 0
