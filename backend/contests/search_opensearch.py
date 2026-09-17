"""실물 공모전 검색 어댑터 — OpenSearch + nori (#450, 부모 #444 스펙, ADR-0007).

`contests.search.ContestSearchAdapter` 계약(search/index_or_remove/rebuild)을
그대로 구현한다 — `SEARCH_ADAPTER_MODE=contests.search_opensearch.
OpenSearchContestSearch`일 때만 `core.adapters.resolve_adapter`가 이 클래스를
고른다(dev·CI·pytest 기본값은 fake다, `contests/search.py`).

**판(alias) 전략.** 실제 트래픽은 언제나 별칭 `contests`를 거친다. 전체
재색인(`rebuild`)은 새 backing index(`contests-<epoch ms>`)를 만들고 채운 뒤,
`indices.update_aliases`로 별칭을 그 새 index로 원자적으로 옮겨 붙인다 — 검색이
끊기는 순간이 없다(부모 스펙 "검색이 끊기지 않게"). 옛 backing index는 별칭을
옮긴 뒤 지운다. 색인은 DB에서 언제든 다시 만들 수 있으므로 볼륨을 백업하지
않는다(#451 compose 결정과 짝이다).

**물러나기.** 연결 실패·시간 초과(`ConnectionError`·`ConnectionTimeout`)는
`contests.search.ContestSearchUnavailable`로 다시 던진다 — 호출자
(`contests.search.search_contests`)가 그것을 잡아 DB 검색으로 물러나고 오류
수집기에 남긴다. 그 밖의 오류(매핑 오류 등 "이미 구현했는데 깨졌다" 부류)는
그대로 올려보낸다 — `core.adapters.resolve_adapter`의 원칙과 같다.
"""

from __future__ import annotations

import logging
import re
import time

from django.conf import settings

from opensearchpy import OpenSearch, helpers
from opensearchpy.exceptions import ConnectionError as OpenSearchConnectionError
from opensearchpy.exceptions import ConnectionTimeout, NotFoundError

from .models import Contest
from .search import ContestSearchUnavailable

logger = logging.getLogger(__name__)

#: 실제 트래픽이 거치는 이름 — 판(backing index)이 아니다.
INDEX_ALIAS = "contests"
_INDEX_PREFIX = f"{INDEX_ALIAS}-"

#: 검색 요청 자체의 타임아웃(초). dev `search` 프로필의 단일 노드 기준 —
#: staging·prod도 같은 값을 쓴다(내부망 호출이라 여유를 크게 둘 이유가 없다).
_DEFAULT_TIMEOUT_SECONDS = 3.0

_ANALYSIS_SETTINGS = {
    "analysis": {
        "analyzer": {
            "nori": {
                "type": "custom",
                "tokenizer": "nori_tokenizer",
                "filter": ["nori_posfilter", "lowercase"],
            }
        },
        "tokenizer": {"nori_tokenizer": {"type": "nori_tokenizer", "decompound_mode": "mixed"}},
        "filter": {
            "nori_posfilter": {
                "type": "nori_part_of_speech",
                # 조사·어미·구두점 등 검색에 의미 없는 품사를 걸러낸다 — OpenSearch
                # nori 분석기 공식 문서가 예시로 드는 기본 제외 태그 목록이다.
                "stoptags": [
                    "E",
                    "IC",
                    "J",
                    "MAG",
                    "MAJ",
                    "MM",
                    "SP",
                    "SSC",
                    "SSO",
                    "SC",
                    "SE",
                    "XPN",
                    "XSA",
                    "XSN",
                    "XSV",
                    "UNA",
                    "NA",
                    "VSV",
                ],
            }
        },
    }
}

_MAPPINGS = {
    "properties": {
        "title": {"type": "text", "analyzer": "nori"},
        "category_name": {"type": "text", "analyzer": "nori"},
        "deliverable_type_names": {"type": "text", "analyzer": "nori"},
        "sponsor_display_name": {"type": "text", "analyzer": "nori"},
        "description": {"type": "text", "analyzer": "nori"},
        "status": {"type": "keyword"},
        "deadline_at": {"type": "date"},
        # 텍스트 필드와 별개로 정확 일치만 보는 필터 전용 필드 — 목록 API의
        # category/deliverable_type id 필터(#449)를 검색 쪽에서도 지원한다.
        "category_id": {"type": "integer"},
        "deliverable_type_ids": {"type": "integer"},
    }
}

# fake 어댑터(`contests.search._WEIGHT_*`)와 같은 값 — 부모 스펙의 "제목 >
# 카테고리·요구형태 > 개최자 > 설명" 가중치를 실물도 그대로 따른다.
_WEIGHT_TITLE = 8
_WEIGHT_CATEGORY = 4
_WEIGHT_DELIVERABLE_TYPE = 4
_WEIGHT_SPONSOR = 2
_WEIGHT_DESCRIPTION = 1

# 마크다운 문법 토큰을 걷어낸다 — 완벽한 파서가 아니라 색인 문서에 `#`·`**`·
# `` ` `` 같은 잡음이 그대로 들어가 검색 관련도를 흐리지 않게 하는 정도면 된다
# (부모 스펙 "마크다운을 걷어낸 설명"). 렌더링은 이 모듈의 책임이 아니다 —
# 공개 앱의 `packages/markdown`이 실제 렌더러다.
_MARKDOWN_IMAGE_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_MARKDOWN_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_MARKDOWN_INLINE_CODE_RE = re.compile(r"`([^`]*)`")
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)
_MARKDOWN_EMPHASIS_RE = re.compile(r"(\*\*\*|\*\*|\*|___|__|_)")
_MARKDOWN_LIST_RE = re.compile(r"^\s*([-*+]|\d+\.)\s+", re.MULTILINE)
_MARKDOWN_BLOCKQUOTE_RE = re.compile(r"^>\s?", re.MULTILINE)


def strip_markdown(text: str) -> str:
    """마크다운 문법을 간단히 걷어낸 평문. 완벽한 렌더링이 아니라 색인용이다."""

    result = _MARKDOWN_IMAGE_RE.sub("", text)
    result = _MARKDOWN_CODE_FENCE_RE.sub("", result)
    result = _MARKDOWN_LINK_RE.sub(r"\1", result)
    result = _MARKDOWN_INLINE_CODE_RE.sub(r"\1", result)
    result = _MARKDOWN_HEADING_RE.sub("", result)
    result = _MARKDOWN_BLOCKQUOTE_RE.sub("", result)
    result = _MARKDOWN_LIST_RE.sub("", result)
    result = _MARKDOWN_EMPHASIS_RE.sub("", result)
    return result.strip()


class OpenSearchContestSearch:
    """`ContestSearchAdapter` 계약의 실물 구현. `core.adapters.resolve_adapter`가
    인자 없이 인스턴스화하므로 생성자는 필수 인자를 받지 않는다(`OPENSEARCH_URL`
    설정에서 접속 주소를 읽는다)."""

    def __init__(self) -> None:
        self._url = getattr(settings, "OPENSEARCH_URL", "http://127.0.0.1:9200")
        self._timeout = _DEFAULT_TIMEOUT_SECONDS
        self._client: OpenSearch | None = None

    @property
    def client(self) -> OpenSearch:
        if self._client is None:
            self._client = OpenSearch(
                hosts=[self._url],
                http_compress=True,
                use_ssl=False,
                verify_certs=False,
                timeout=self._timeout,
                max_retries=0,
                retry_on_timeout=False,
            )
        return self._client

    # --- ContestSearchAdapter ---------------------------------------------------

    def search(
        self,
        *,
        query: str,
        category: int | None = None,
        deliverable_type: int | None = None,
    ) -> list[int]:
        filters: list[dict] = []
        if category is not None:
            filters.append({"term": {"category_id": category}})
        if deliverable_type is not None:
            filters.append({"term": {"deliverable_type_ids": deliverable_type}})

        body = {
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": query,
                                "fields": [
                                    f"title^{_WEIGHT_TITLE}",
                                    f"category_name^{_WEIGHT_CATEGORY}",
                                    f"deliverable_type_names^{_WEIGHT_DELIVERABLE_TYPE}",
                                    f"sponsor_display_name^{_WEIGHT_SPONSOR}",
                                    f"description^{_WEIGHT_DESCRIPTION}",
                                ],
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "_source": False,
            # 목록 API가 한 페이지씩 보여주므로 이 상한을 넘는 관련도까지 볼
            # 일이 없다 — fake 어댑터(전체 스캔)와 달리 실물은 네트워크
            # 응답 크기를 신경 써야 한다.
            "size": 500,
        }

        try:
            response = self.client.search(
                index=INDEX_ALIAS, body=body, request_timeout=self._timeout
            )
        except (OpenSearchConnectionError, ConnectionTimeout) as exc:
            raise ContestSearchUnavailable(str(exc)) from exc
        except NotFoundError:
            # 별칭이 아직 없다 — 첫 배포에서 rebuild가 한 번도 돌지 않은 상태다.
            return []

        return [int(hit["_id"]) for hit in response.get("hits", {}).get("hits", [])]

    def index_or_remove(self, contest_id: int) -> None:
        try:
            contest = (
                Contest.objects.select_related("category", "sponsor")
                .prefetch_related("deliverable_types")
                .get(id=contest_id)
            )
        except Contest.DoesNotExist:
            self._delete(contest_id)
            return

        if contest.status not in Contest.Status.PUBLICLY_VISIBLE.statuses:
            self._delete(contest_id)
            return

        try:
            self.client.index(
                index=INDEX_ALIAS,
                id=str(contest_id),
                body=self._document(contest),
                refresh=False,
            )
        except (OpenSearchConnectionError, ConnectionTimeout) as exc:
            raise ContestSearchUnavailable(str(exc)) from exc

    def rebuild(self) -> None:
        new_index = f"{_INDEX_PREFIX}{int(time.time() * 1000)}"
        try:
            self.client.indices.create(
                index=new_index,
                body={
                    "settings": {
                        **_ANALYSIS_SETTINGS,
                        "number_of_shards": 1,
                        "number_of_replicas": 0,
                    },
                    "mappings": _MAPPINGS,
                },
            )

            contests = (
                Contest.objects.filter(status__in=Contest.Status.PUBLICLY_VISIBLE.statuses)
                .select_related("category", "sponsor")
                .prefetch_related("deliverable_types")
            )
            actions = (
                {"_index": new_index, "_id": str(contest.id), "_source": self._document(contest)}
                # chunk_size가 필요하다 — prefetch_related 뒤의 iterator()는 그 값
                # 없이는 즉시 ValueError다(Django의 명시적 요구, prefetch를 청크
                # 단위로만 안전하게 다시 실행할 수 있어서다).
                for contest in contests.iterator(chunk_size=500)
            )
            helpers.bulk(self.client, actions, refresh=True)

            self._swap_alias(new_index)
        except (OpenSearchConnectionError, ConnectionTimeout) as exc:
            raise ContestSearchUnavailable(str(exc)) from exc

    # --- 내부 ---------------------------------------------------------------

    def _delete(self, contest_id: int) -> None:
        try:
            self.client.delete(index=INDEX_ALIAS, id=str(contest_id), ignore=[404])
        except (OpenSearchConnectionError, ConnectionTimeout) as exc:
            raise ContestSearchUnavailable(str(exc)) from exc

    def _document(self, contest: Contest) -> dict:
        return {
            "title": contest.title,
            "category_name": contest.category.name,
            "deliverable_type_names": [dt.name for dt in contest.deliverable_types.all()],
            "sponsor_display_name": contest.sponsor.display_name or "",
            "description": strip_markdown(contest.description),
            "status": contest.status,
            "deadline_at": contest.deadline_at.isoformat(),
            "category_id": contest.category_id,
            "deliverable_type_ids": [dt.id for dt in contest.deliverable_types.all()],
        }

    def _swap_alias(self, new_index: str) -> None:
        """별칭을 새 판으로 원자적으로 옮겨 붙이고 옛 판을 지운다.

        `indices.update_aliases`가 remove+add를 한 요청으로 보내므로, 그 사이에
        별칭이 아예 없는 순간이 생기지 않는다(부모 스펙 "검색이 끊기지 않게").
        """

        try:
            existing = set(self.client.indices.get_alias(name=INDEX_ALIAS).keys())
        except NotFoundError:
            existing = set()

        actions = [{"add": {"index": new_index, "alias": INDEX_ALIAS}}]
        actions += [
            {"remove": {"index": old_index, "alias": INDEX_ALIAS}}
            for old_index in existing
            if old_index != new_index
        ]
        self.client.indices.update_aliases(body={"actions": actions})

        for old_index in existing:
            if old_index != new_index and old_index.startswith(_INDEX_PREFIX):
                self.client.indices.delete(index=old_index, ignore=[404])
