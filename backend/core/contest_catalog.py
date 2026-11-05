"""공모전 문제가 강의실↔공모전 경계를 건너는 자리 (ADR-0054, #546).

강의실(`classroom`)과 공모전 가족(`contests` 등)은 서로를 임포트하지 못한다(ADR-0037,
`tests/test_app_boundaries.py` 규칙 A). 「공모전 문제」(CONTEXT.md)는 그래도 공모전의
제목·설명·Requirement 를 따라가야 하므로, 둘이 함께 아는 **계약만** 이 공유층 모듈에 둔다.

- **읽기 자리** — 「들여올 수 있는 무료 공모전 목록」과 「공모전 하나의 원본」. 공모전 쪽이
  `register_contest_catalog` 로 구현을 등록하고(`contests.apps`), 강의실은
  `contest_catalog()` 로 읽는다. 등록이 없으면(공모전 앱이 빠진 구성) 비어 있는 카탈로그가
  답한다 — 강의실은 「들여올 공모전이 없다」로 읽는다.
- **바뀌었다 신호** — `contest_source_changed`. 공모전 쪽이 공개 중인 무료 공모전의 제목·
  설명·Requirement·마감을 고치거나 「클래스에서 들여오기」를 켜고 끄면 커밋 뒤에 보낸다.
  강의실이 받아 공모전 문제를 맞춘다(#548). 실시간 신호 버스(ADR-0046, `core.events`)와
  다르다 — 그쪽은 화면에 「바뀌었다」만 알리고, 이쪽은 앱 사이의 일을 넘긴다. 선례는
  `accounts.signals.user_withdrawn` 이다.
- **내 달라 · 결과 신호** — `contest_entry_requested` / `contest_entry_resolved` (#549).
  참여자가 공모전 문제의 시도를 「공모전에도 내기」로 내면, 강의실이 시도를 커밋한 뒤
  `ContestEntry` 하나를 실어 보낸다. 공모전 쪽이 직접 제출과 같은 검증을 거쳐
  ContestSubmission 을 만들거나 고치고, 같은 `attempt_id` 로 결과를 돌려준다. 공모전 쪽은
  `attempt_id` 를 짝짓는 데만 쓰고 저장하지 않는다 — 공모전 제출에는 클래스를 가리키는
  칸이 없다(ADR-0054).
  강의실이 시도를 만들기 **전에** 거를 수 있는 것(동의·근거 모양·선택 자료)은 카탈로그의
  `check_entry` 가 미리 답한다 — 화면이 422 로 막을 수 있게. 마감·허용 철회 경합은 그
  사이에 생기므로 공모전 쪽이 받을 때 한 번 더 본다.

이 모듈은 어느 기능 앱도 임포트하지 않는다(규칙 B) — 데이터 모양과 등록부뿐이다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol, runtime_checkable

from django.dispatch import Signal


@dataclass(frozen=True)
class ContestRequirementSource:
    """공모전 Requirement 하나 — 공모전 문제의 체크리스트 한 줄이 된다."""

    requirement_id: int
    text: str
    #: "required" | "optional" | "bonus" — 공모전의 등급 값 그대로다.
    grade: str
    order: int
    #: 배점 1~10(#904) — 공모전 문제의 항목이 그대로 따른다.
    points: int = 1


@dataclass(frozen=True)
class ContestSource:
    """공모전 문제가 따라가는 공모전 하나의 원본."""

    contest_id: int
    title: str
    description: str
    deadline_at: datetime
    #: 지금 「공모전에도 내기」를 받을 수 있는가 — 공개 중 · 마감 전 · 허용 켜짐.
    accepts_classroom_entries: bool
    requirements: tuple[ContestRequirementSource, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ImportableContest:
    """들여오기 목록의 한 줄 — 고르는 데 필요한 것만."""

    contest_id: int
    title: str
    deadline_at: datetime
    requirement_count: int


@dataclass(frozen=True)
class EntryEvidence:
    """요구사항 하나에 붙는 근거 한 줄 — 공모전 직접 제출의 Evidence 와 같은 모양이다.
    자료를 가리키는 칸(asset_id)은 없다: 강의실에서 낸 자료는 아직 공모전 쪽 id 가 없다."""

    kind: str
    value: str


@dataclass(frozen=True)
class EntryResponse:
    """요구사항 하나에 대한 자가 응답."""

    requirement_id: int
    is_met: bool
    note: str = ""
    evidence: tuple[EntryEvidence, ...] = ()


@dataclass(frozen=True)
class EntryAsset:
    """공모전 제출에 실릴 자료 하나. `kind` 는 공모전 제출 자료 종류 값 그대로다."""

    kind: str
    value: str
    label: str = ""
    content_type: str = ""


@dataclass(frozen=True)
class ContestEntry:
    """「공모전에도 내기」 하나 — 이 시도로 그 공모전의 내 제출을 만들거나 바꿔 달라."""

    contest_id: int
    user_id: int
    #: 결과 신호를 그 시도에 짝짓는 열쇠다. 공모전 쪽은 저장하지 않는다.
    attempt_id: int
    #: 시도가 낸 것 — 소스(강의실 업로드 대상의 object_key)거나 저장소 URL. 공모전 쪽이
    #: 소스를 자기 업로드 대상으로 옮겨 필수 자료로 쓴다.
    scoring_asset: EntryAsset
    responses: tuple[EntryResponse, ...] = ()
    #: 데모 주소·시연 영상·스크린샷. 영상·스크린샷은 이미 공모전 쪽 업로드 대상에 올라가 있다.
    optional_assets: tuple[EntryAsset, ...] = ()
    source_access_consent: bool = False


@dataclass(frozen=True)
class ContestEntryContext:
    """「공모전에도 내기」 칸을 그리는 데 필요한 것 — 그 사람의 지금 제출을 미리 채운다."""

    #: 이 사람이 그 공모전에 이미 낸 제출이 있는가(직접 냈든 다른 클래스에서 냈든).
    has_entry: bool
    responses: tuple[EntryResponse, ...] = ()
    optional_assets: tuple[EntryAsset, ...] = ()
    #: 선택 자료 종류 → 그 사람의 공모전 업로드 대상(target_ref). 형식은 공모전 쪽만 안다.
    upload_target_refs: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class ContestCatalog(Protocol):
    def list_importable(
        self,
        *,
        query: str = "",
        after: tuple[datetime, int] | None = None,
        limit: int | None = None,
    ) -> list[ImportableContest]:
        """지금 들여올 수 있는 무료 공모전 — 공개 중 · 마감 전 · 허용 켜짐, 마감 빠른 순.
        `query` 는 제목에 든 글자, `after` 는 (마감, 번호) 커서 — 그 뒤부터 `limit` 개."""

    def get_source(self, contest_id: int) -> ContestSource | None:
        """공모전 하나의 원본. 무료 공모전이 아니거나 한 번도 공개된 적이 없으면 None."""

    def entry_context(self, contest_id: int, user_id: int) -> ContestEntryContext | None:
        """그 사람의 「공모전에도 내기」 칸 — 지금 받지 않는 공모전이면 None."""

    def check_entry(self, entry: ContestEntry) -> str | None:
        """받을 수 있는 내기인가 — 받을 수 있으면 None, 아니면 사람이 읽는 거절 이유."""

    def entries_updated_at(self, contest_id: int, user_ids: set[int]) -> dict[int, datetime]:
        """그 공모전에 제출이 있는 사람마다 그 제출을 마지막으로 고친 때 — 강사 화면(#550)이
        「지금 공모전 제출인 시도」를 가린다: 그 시도가 받아들여진 뒤에 직접 고쳤으면 아니다.
        시각만 건넨다 — 근거·점수·수상은 건너가지 않는다."""


_NO_CATALOG_REASON = "공모전에 낼 수 없습니다."


class _EmptyCatalog:
    def list_importable(self, *, query="", after=None, limit=None) -> list[ImportableContest]:
        return []

    def get_source(self, contest_id: int) -> ContestSource | None:
        return None

    def entry_context(self, contest_id: int, user_id: int) -> ContestEntryContext | None:
        return None

    def check_entry(self, entry: ContestEntry) -> str | None:
        return _NO_CATALOG_REASON

    def entries_updated_at(self, contest_id: int, user_ids: set[int]) -> dict[int, datetime]:
        return {}


_catalog: ContestCatalog = _EmptyCatalog()


def register_contest_catalog(catalog: ContestCatalog) -> None:
    global _catalog
    _catalog = catalog


def contest_catalog() -> ContestCatalog:
    return _catalog


#: 공개 중인 무료 공모전의 원본이 바뀌었다 — `contest_id=<int>` 인자 하나로 보낸다.
#: 커밋 뒤(`transaction.on_commit`)에만 보낸다: 받는 쪽이 원본을 다시 읽을 때 새 값이 보여야 한다.
contest_source_changed = Signal()

#: 「공모전에도 내기」 — `entry=<ContestEntry>` 인자 하나로 보낸다. 강의실이 시도를 커밋한
#: 뒤에만 보낸다. 받는 쪽(공모전)은 반드시 `contest_entry_resolved` 로 답한다.
contest_entry_requested = Signal()

#: 내기의 결과 — `attempt_id=<int>`, `accepted=<bool>`, `reason=<str>`(거절일 때 사람이 읽는
#: 이유, 받았으면 빈 문자열). 강의실이 받아 그 시도에 남긴다.
contest_entry_resolved = Signal()
