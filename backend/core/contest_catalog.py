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
    #: "required" | "optional" — 공모전의 등급 값 그대로다.
    grade: str
    order: int


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


@runtime_checkable
class ContestCatalog(Protocol):
    def list_importable(self) -> list[ImportableContest]:
        """지금 들여올 수 있는 무료 공모전 — 공개 중 · 마감 전 · 허용 켜짐, 마감 빠른 순."""

    def get_source(self, contest_id: int) -> ContestSource | None:
        """공모전 하나의 원본. 무료 공모전이 아니거나 한 번도 공개된 적이 없으면 None."""


class _EmptyCatalog:
    def list_importable(self) -> list[ImportableContest]:
        return []

    def get_source(self, contest_id: int) -> ContestSource | None:
        return None


_catalog: ContestCatalog = _EmptyCatalog()


def register_contest_catalog(catalog: ContestCatalog) -> None:
    global _catalog
    _catalog = catalog


def contest_catalog() -> ContestCatalog:
    return _catalog


#: 공개 중인 무료 공모전의 원본이 바뀌었다 — `contest_id=<int>` 인자 하나로 보낸다.
#: 커밋 뒤(`transaction.on_commit`)에만 보낸다: 받는 쪽이 원본을 다시 읽을 때 새 값이 보여야 한다.
contest_source_changed = Signal()
