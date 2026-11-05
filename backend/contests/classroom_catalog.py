"""공유층 「공모전 카탈로그」의 공모전 쪽 구현 (#547, ADR-0054).

강의실은 공모전 앱을 임포트하지 못한다(ADR-0037). 「공모전 문제」(CONTEXT.md)가 따라갈
원본과 들여오기 목록은 이 구현이 `core.contest_catalog` 에 등록되어 건넨다
(`contests.apps`). 무료 공모전만 다룬다 — 유료 공모전은 들여올 수 없다(#546 범위 밖).
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q

from core.clock import Clock
from core.contest_catalog import (
    ContestEntry,
    ContestEntryContext,
    ContestRequirementSource,
    ContestSource,
    ImportableContest,
)
from core.contest_switch import contest_product_enabled

from . import classroom_entries
from .models import Contest


class ContestClassroomCatalog:
    def list_importable(
        self,
        *,
        query: str = "",
        after: tuple[datetime, int] | None = None,
        limit: int | None = None,
    ) -> list[ImportableContest]:
        if not contest_product_enabled():
            return []
        contests = (
            Contest.objects.filter(
                is_free=True,
                allows_classroom_import=True,
                # 보관한 공모전(#870)은 새로 들여올 수 없다 — 이미 들여온 문제(`get_source`)는 그대로다.
                archived_at__isnull=True,
                status=Contest.Status.PUBLISHED,
                deadline_at__gt=Clock.now(),
            )
            .prefetch_related("requirements")
            .order_by("deadline_at", "id")
        )
        if query.strip():
            contests = contests.filter(title__icontains=query.strip())
        if after is not None:
            deadline_at, contest_id = after
            contests = contests.filter(
                Q(deadline_at__gt=deadline_at) | Q(deadline_at=deadline_at, id__gt=contest_id)
            )
        if limit is not None:
            contests = contests[:limit]
        return [
            ImportableContest(
                contest_id=c.pk,
                title=c.title,
                deadline_at=c.deadline_at,
                requirement_count=len(c.requirements.all()),
            )
            for c in contests
        ]

    def get_source(self, contest_id: int) -> ContestSource | None:
        contest = (
            Contest.objects.filter(pk=contest_id, is_free=True)
            .exclude(status=Contest.Status.DRAFT)
            .prefetch_related("requirements")
            .first()
        )
        if contest is None:
            return None
        accepts = classroom_entries.accepts_entries(contest)
        return ContestSource(
            contest_id=contest.pk,
            title=contest.title,
            description=contest.description,
            deadline_at=contest.deadline_at,
            accepts_classroom_entries=accepts,
            requirements=tuple(
                ContestRequirementSource(
                    requirement_id=r.pk, text=r.text, grade=r.grade, order=r.order
                )
                for r in contest.requirements.all()
            ),
        )

    def entry_context(self, contest_id: int, user_id: int) -> ContestEntryContext | None:
        return classroom_entries.entry_context(contest_id, user_id)

    def check_entry(self, entry: ContestEntry) -> str | None:
        return classroom_entries.check_entry(entry)

    def entries_updated_at(self, contest_id: int, user_ids: set[int]) -> dict[int, datetime]:
        return classroom_entries.entries_updated_at(contest_id, user_ids)
