"""강의실 에이전트 실행 기록 목록(#1167) — 공유층 `core.agent_ports.AGENT_RUN_LISTERS` 에 `classroom` 으로 올린다.

강의실 실행은 #1036 부터 `ClassroomAgentRun` 에 남지만, 운영자 조회는 공모전 `AgentRun` 만 읽어 보이지 않았다.
"""

from __future__ import annotations

from django.db.models import Q

from core.agent_ports import AgentRunRow

from .models import ClassroomAgentRun


def classroom_agent_runs(*, include_all: bool, limit: int) -> list[AgentRunRow]:
    runs = ClassroomAgentRun.objects.select_related("submission__problem").order_by("-created_at", "-id")
    if not include_all:
        runs = runs.filter(Q(outcome=ClassroomAgentRun.Outcome.HELD) | ~Q(review=""))
    return [
        AgentRunRow(
            source="classroom",
            id=run.id,
            submission_id=run.submission_id,
            contest_id=None,
            class_id=run.submission.problem.classroom_id,
            problem_id=run.submission.problem_id,
            purpose=run.purpose,
            outcome=run.outcome,
            review=run.review,
            reasons=run.reasons,
            model_version=run.model_version,
            attempts=len(run.record.get("attempts") or []),
            created_at=run.created_at.isoformat(),
        )
        for run in runs[:limit]
    ]
