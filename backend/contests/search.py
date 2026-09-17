"""공모전 검색 모듈 — 어댑터 방식 (#449, 부모 #444 스펙, ADR-0007).

검색을 다른 외부 연동(스토리지·LLM·이벤트 버스)과 같은 모양으로 갈아끼운다 —
`SEARCH_ADAPTER_MODE` 설정이 어댑터를 고른다. **이 티켓은 fake(DB 포함 검색)만
만든다** — 실물 OpenSearch 어댑터·커밋 후 색인 태스크·매일 재색인 스캔은 #450이
만들고, 배포 부팅 가드는 #451이 켠다(`config/settings.py`의 주석 참고).

인터페이스는 셋이다 — 실물 어댑터가 목록 API를 건드리지 않고 그대로 슬롯인할
수 있도록 여기서 고정한다:

- `search`: 검색어(+카테고리·요구형태 필터)로 Contest id를 관련도 순서로 돌려준다.
  목록 API(`contests.api.list_contests`)가 `q`가 있을 때 이 id 순서로 결과를
  만든다. **초안은 절대 나오지 않는다** — 실물 색인이 초안을 담지 않는 것과 같은
  결과를, fake는 검색 시점에 `Contest.Status.PUBLICLY_VISIBLE`로 직접 좁혀서
  낸다.
- `index_or_remove`: Contest 하나를 색인하거나(공개 상태면) 지운다(초안·비공개면).
  fake에는 실제 색인이 없으므로 대신 "이 id가 지금 색인돼 있다고 기록됐는가"만
  관찰 가능하게 남긴다 — #450이 "저장하면 색인 태스크가 그 공모전을 반영했는가"를
  이 기록으로 확인한다.
- `rebuild`: 전체를 다시 만든다. fake는 지금 공개 상태인 Contest id 전체로 그
  기록을 다시 채운다.

`FakeContestSearchAdapter._indexed`는 `core.events.FakeEventBus._queues`와 같은
이유로 **클래스 레벨**이다 — `get_search_adapter()`가 호출마다 새 인스턴스를
만들어도(`resolve_adapter`의 `fake_factory`) 인덱싱 요청과 검색 요청이 서로 다른
HTTP 요청(그래서 서로 다른 인스턴스)일 수 있기 때문이다. `tests/conftest.py`의
autouse 픽스처가 매 테스트 전후로 비운다.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from django.conf import settings

from core.adapters import resolve_adapter

from .models import Contest


@runtime_checkable
class ContestSearchAdapter(Protocol):
    def search(
        self,
        *,
        query: str,
        category: int | None = None,
        deliverable_type: int | None = None,
    ) -> list[int]: ...

    def index_or_remove(self, contest_id: int) -> None: ...

    def rebuild(self) -> None: ...


# 제목 일치가 가장 위로 오도록(#449 인수조건), 필드마다 다른 가중치를 준다 —
# 부모 스펙의 실물 어댑터 가중치("제목 > 카테고리·요구형태 > 개최자 > 설명")를
# fake도 그대로 따른다.
_WEIGHT_TITLE = 8
_WEIGHT_CATEGORY = 4
_WEIGHT_DELIVERABLE_TYPE = 4
_WEIGHT_SPONSOR = 2
_WEIGHT_DESCRIPTION = 1


def _score(contest: Contest, needle: str) -> int:
    """이 Contest가 `needle`(이미 소문자)과 얼마나 관련 있는가 — 0이면 안 걸린다."""

    score = 0
    if needle in contest.title.lower():
        score += _WEIGHT_TITLE
    if needle in contest.category.name.lower():
        score += _WEIGHT_CATEGORY
    if any(needle in dt.name.lower() for dt in contest.deliverable_types.all()):
        score += _WEIGHT_DELIVERABLE_TYPE
    display_name = contest.sponsor.display_name
    if display_name and needle in display_name.lower():
        score += _WEIGHT_SPONSOR
    if needle in contest.description.lower():
        score += _WEIGHT_DESCRIPTION
    return score


class FakeContestSearchAdapter:
    """DB 포함 검색 — pytest·CI·dev 기본값. 네트워크도 별도 색인도 없다."""

    #: contest_id -> 색인돼 있다고 기록된 사실. 클래스 레벨 이유는 모듈 docstring.
    _indexed: dict[int, bool] = {}

    def search(
        self,
        *,
        query: str,
        category: int | None = None,
        deliverable_type: int | None = None,
    ) -> list[int]:
        needle = query.strip().lower()
        if not needle:
            return []

        queryset = Contest.objects.filter(
            status__in=Contest.Status.PUBLICLY_VISIBLE.statuses
        )
        if category is not None:
            queryset = queryset.filter(category_id=category)
        if deliverable_type is not None:
            queryset = queryset.filter(deliverable_types__id=deliverable_type)

        contests = queryset.select_related("category", "sponsor").prefetch_related(
            "deliverable_types"
        )

        scored = ((contest.id, _score(contest, needle)) for contest in contests)
        matched = [(contest_id, score) for contest_id, score in scored if score > 0]
        # 관련도 내림차순, 동점이면 id — DB가 순서를 보장하지 않는 동점을 안정화한다
        # (contests.api.list_contests의 다른 정렬이 마지막 키로 id를 붙이는 것과
        # 같은 이유).
        matched.sort(key=lambda pair: (-pair[1], pair[0]))
        return [contest_id for contest_id, _score_value in matched]

    def index_or_remove(self, contest_id: int) -> None:
        visible = Contest.objects.filter(
            id=contest_id, status__in=Contest.Status.PUBLICLY_VISIBLE.statuses
        ).exists()
        if visible:
            FakeContestSearchAdapter._indexed[contest_id] = True
        else:
            FakeContestSearchAdapter._indexed.pop(contest_id, None)

    def rebuild(self) -> None:
        visible_ids = Contest.objects.filter(
            status__in=Contest.Status.PUBLICLY_VISIBLE.statuses
        ).values_list("id", flat=True)
        # 클래스 레벨 dict 자체를 다른 객체로 바꿔치지 않고 제자리에서 비우고
        # 채운다 — `tests/conftest.py`가 들고 있는 것과 같은 참조를 계속 가리킨다.
        FakeContestSearchAdapter._indexed.clear()
        FakeContestSearchAdapter._indexed.update({contest_id: True for contest_id in visible_ids})


def get_search_adapter() -> ContestSearchAdapter:
    return resolve_adapter(
        mode=getattr(settings, "SEARCH_ADAPTER_MODE", "fake"),
        fake_factory=FakeContestSearchAdapter,
        not_implemented_hint=(
            "SEARCH_ADAPTER_MODE 가 가리키는 dotted path를 import할 수 없다 — "
            "실물 어댑터(OpenSearch)는 #450이 만든다."
        ),
    )
