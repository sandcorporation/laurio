"""공모전 에이전트 실행 기록 목록(#1000) — 공유층 `core.agent_ports.AGENT_RUN_LISTERS` 에 `contest` 로 올린다(#1167)."""

from __future__ import annotations

from django.db.models import Q

from contests.models import ContestSubmission
from core.agent_ports import AgentRunRow

from .models import AgentRun


def contest_agent_runs(*, include_all: bool, limit: int) -> list[AgentRunRow]:
    runs = AgentRun.objects.order_by("-created_at", "-id")
    if not include_all:
        runs = runs.filter(Q(outcome=AgentRun.Outcome.HELD) | ~Q(review=""))
    picked = list(runs[:limit])
    contest_by_submission = dict(
        ContestSubmission.objects.filter(pk__in={run.submission_id for run in picked}).values_list("pk", "contest_id")
    )
    return [
        AgentRunRow(
            source="contest",
            id=run.id,
            submission_id=run.submission_id,
            contest_id=contest_by_submission.get(run.submission_id),
            class_id=None,
            problem_id=None,
            purpose=run.purpose,
            outcome=run.outcome,
            review=run.review,
            reasons=run.reasons,
            model_version=run.model_version,
            attempts=len(run.record.get("attempts") or []),
            created_at=run.created_at.isoformat(),
        )
        for run in picked
    ]
