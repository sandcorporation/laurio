"""공유층 「공모전 카탈로그」의 공모전 쪽 구현 (#547, ADR-0054).

강의실은 공모전 앱을 임포트하지 못한다(ADR-0037). 「공모전 문제」(CONTEXT.md)가 따라갈
원본과 들여오기 목록은 이 구현이 `core.contest_catalog` 에 등록되어 건넨다
(`contests.apps`). 무료 공모전만 다룬다 — 유료 공모전은 들여올 수 없다(#546 범위 밖).
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import Q

from core.clock import Clock
from core.contest_catalog import ContestRequirementSource, ContestSource, ImportableContest
from core.contest_switch import contest_product_enabled

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
        accepts = (
            contest_product_enabled()
            and contest.allows_classroom_import
            and contest.status == Contest.Status.PUBLISHED
            and contest.deadline_at > Clock.now()
        )
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
