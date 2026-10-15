"""`contests.search_opensearch.OpenSearchContestSearch`가 실제 OpenSearch를 치는
live 테스트 (#450, 부모 #444 스펙).

`OPENSEARCH_URL`이 있을 때만 돈다(dev `search` 프로필,
`docker compose -f docker/compose.dev.yaml --profile search up -d`) — 없으면
`tests/live.py`의 원칙대로 skip이지 실패가 아니다. `@live_infra`라 기본
스위트·CI에서 제외된다(#450 AC "CI는 이 테스트를 건너뛴다").

부모 스펙이 요구하는 세 가지만 본다(#450 AC):
1. 한국어 조사가 달라도(nori 형태소 분석) 같은 공모전이 찾아진다.
2. 제목 가중이 설명보다 높다.
3. 재색인(`rebuild`) 중에도(별칭 원자적 교체) 검색이 끊기지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings
from django.utils import timezone

from tests.live import live_infra, require_live_credential


def _contest(sponsor, category, deliverable_types, *, title, description="", days=5):
    from contests.models import Contest

    contest = Contest.objects.create(
        sponsor=sponsor,
        title=title,
        description=description,
        category=category,
        prize=1_000_000,
        deadline_at=timezone.now() + timedelta(days=days),
        status=Contest.Status.PUBLISHED,
    )
    contest.deliverable_types.set(deliverable_types)
    return contest


@pytest.fixture
def opensearch_url():
    return require_live_credential("OPENSEARCH_URL")


@pytest.fixture
def adapter(opensearch_url):
    from contests.search_opensearch import INDEX_ALIAS, OpenSearchContestSearch

    with override_settings(OPENSEARCH_URL=opensearch_url):
        instance = OpenSearchContestSearch()
        yield instance

    # 정리 — 이 테스트가 만든 판을 다음 실행을 위해 걷어낸다. 다른 곳(dev의
    # 나머지 데이터)을 건드리지 않는다: 별칭 뒤의 backing index만 지운다.
    try:
        existing = instance.client.indices.get_alias(name=INDEX_ALIAS)
        for index_name in existing:
            instance.client.indices.delete(index=index_name, ignore=[404])
    except Exception:  # noqa: BLE001 - 정리 실패가 테스트 실패로 번지지 않게 한다
        pass


@pytest.fixture
def sponsor_and_category(db):
    from accounts.models import SponsorProfile
    from contests.models import Category, DeliverableType

    user = get_user_model().objects.create_user(
        username="opensearch-live-sponsor", email="opensearch-live-sponsor@example.invalid"
    )
    sponsor = SponsorProfile.objects.create(user=user, display_name="라이브 검색 스폰서")
    category = Category.objects.create(name="라이브검색카테고리")
    deliverable_type = DeliverableType.objects.create(
        name="라이브검색요구형태", minimum_prize=1_000_000
    )
    return sponsor, category, [deliverable_type]


@live_infra
@pytest.mark.django_db
def test_korean_particles_still_find_the_same_contest(adapter, sponsor_and_category):
    sponsor, category, deliverable_types = sponsor_and_category
    contest = _contest(sponsor, category, deliverable_types, title="중고 거래 플랫폼")

    adapter.rebuild()

    with_particle = adapter.search(query="거래를")
    bare_noun = adapter.search(query="거래")

    assert contest.id in with_particle
    assert contest.id in bare_noun


@live_infra
@pytest.mark.django_db
def test_title_match_outranks_a_description_only_match(adapter, sponsor_and_category):
    sponsor, category, deliverable_types = sponsor_and_category
    title_hit = _contest(sponsor, category, deliverable_types, title="특이토큰라이브검색히트")
    description_hit = _contest(
        sponsor,
        category,
        deliverable_types,
        title="다른 제목",
        description="이 설명 안에 특이토큰라이브검색히트가 들어 있다",
    )

    adapter.rebuild()

    results = adapter.search(query="특이토큰라이브검색히트")

    assert results.index(title_hit.id) < results.index(description_hit.id)


@live_infra
@pytest.mark.django_db
def test_search_never_breaks_while_reindexing(adapter, sponsor_and_category):
    sponsor, category, deliverable_types = sponsor_and_category
    contest = _contest(sponsor, category, deliverable_types, title="재색인끊김확인공모전")

    # 첫 rebuild — 별칭이 아직 없던 상태에서 판을 만들고 붙인다.
    adapter.rebuild()
    assert contest.id in adapter.search(query="재색인끊김확인공모전")

    # 연달아 다시 rebuild — 별칭을 옛 판에서 새 판으로 옮기는 그 순간에도
    # `_swap_alias`가 add+remove를 한 요청으로 보내므로 별칭이 사라지는
    # 틈이 없다. 그 직후 검색이 여전히(예외 없이) 성공하는 것으로 확인한다.
    adapter.rebuild()
    assert contest.id in adapter.search(query="재색인끊김확인공모전")
