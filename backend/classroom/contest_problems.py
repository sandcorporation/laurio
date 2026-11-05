"""공모전 문제 — 허용된 무료 공모전을 클래스의 문제로 들여오고 그 원본을 따라간다
(#548, 스펙 #546, ADR-0054, CONTEXT.md 「공모전 문제」).

강의실은 공모전 앱을 임포트하지 못한다(ADR-0037). 원본은 공유층 `core.contest_catalog` 로
읽고, 원본이 바뀌었다는 소식은 같은 모듈의 `contest_source_changed` 신호로 받는다
(`classroom.apps` 가 이 모듈의 `on_contest_source_changed` 를 연결한다).

**따라가는 것** — 제목·설명·체크리스트. 체크리스트는 그 공모전의 Requirement 그대로다(문구·
필수/선택·순서). 항목마다 `contest_requirement_id` 로 원본 Requirement 를 기억해 두고, 원본이
바뀌면 같은 항목을 고친다 — 시도의 판정이 항목 id 를 가리키므로 새로 만들지 않는다. 원본에서
사라진 Requirement 의 항목은 지운다(강사가 항목을 지울 때와 같다: 지난 판정은 남고 달성률만
새 체크리스트로 다시 셈된다, CONTEXT.md 「달성률」).

**강사가 정하는 것** — 수업용 안내(`instructor_note`)·채점 지침·채점 모델·받는 형식. 잠긴
칸을 고치려 하면 화면과 연결된 앱이 같은 문장으로 거절받는다(`problem_authoring`).
"""

from __future__ import annotations

import logging

from django.db import transaction
from ninja.errors import HttpError

from core.contest_catalog import ContestSource, contest_catalog

from .models import ChecklistItem, Class, Problem

logger = logging.getLogger(__name__)

#: 잠긴 칸을 고치려 할 때의 거절 문장 — 화면과 연결된 앱이 같은 문장을 받는다.
LOCKED_BY_CONTEST_MESSAGE = (
    "공모전 문제의 제목·설명·체크리스트는 공모전을 따라갑니다. 수업용 안내에 덧붙여 주세요."
)
NOT_IMPORTABLE_MESSAGE = "들여올 수 없는 공모전입니다 — 마감됐거나 개최자가 허용하지 않았습니다."
TEMPLATE_BLOCKED_MESSAGE = (
    "공모전 문제는 템플릿으로 공개할 수 없습니다 — 제목·설명·요구사항은 개최자의 글입니다."
)


def is_contest_problem(problem: Problem) -> bool:
    return problem.contest_id is not None


def reject_if_locked(problem: Problem) -> None:
    if is_contest_problem(problem):
        raise HttpError(422, LOCKED_BY_CONTEST_MESSAGE)


def import_contest_problem(class_obj: Class, contest_id: int) -> Problem:
    """허용된 무료 공모전 하나를 초안 문제로 들여온다. 받는 형식은 공모전 제출이 받는 두 가지
    (소스·저장소)로 시작한다 — 강사가 고친다."""

    source = contest_catalog().get_source(contest_id)
    if source is None or not source.accepts_classroom_entries:
        raise HttpError(422, NOT_IMPORTABLE_MESSAGE)

    with transaction.atomic():
        problem = Problem.objects.create(
            classroom=class_obj,
            title=source.title[:200],
            description=source.description,
            submission_formats=[
                Problem.SubmissionFormat.SOURCE,
                Problem.SubmissionFormat.REPOSITORY,
            ],
            order=class_obj.problems.count(),
            status=Problem.Status.DRAFT,
            contest_id=source.contest_id,
        )
        _apply_source(problem, source)
    return problem


def sync_contest_problem(problem: Problem, source: ContestSource | None = None) -> None:
    """원본을 다시 읽어 제목·설명·체크리스트를 맞춘다. 원본을 읽을 수 없으면(공모전이 지워졌다)
    지금 상태를 그대로 둔다 — 평범한 문제로 남는다."""

    if not is_contest_problem(problem):
        return
    if source is None:
        source = contest_catalog().get_source(problem.contest_id)
    if source is None:
        return
    with transaction.atomic():
        _apply_source(problem, source)


def _apply_source(problem: Problem, source: ContestSource) -> None:
    update_fields = []
    title = source.title[:200]
    if problem.title != title:
        problem.title = title
        update_fields.append("title")
    if problem.description != source.description:
        problem.description = source.description
        update_fields.append("description")
    if update_fields:
        problem.save(update_fields=[*update_fields, "updated_at"])

    existing = {
        item.contest_requirement_id: item
        for item in problem.checklist_items.filter(contest_requirement_id__isnull=False)
    }
    kept: set[int] = set()
    for index, requirement in enumerate(sorted(source.requirements, key=lambda r: (r.order, r.requirement_id))):
        # 등급·배점은 공모전 값 그대로다(#904) — 강사가 고칠 수 없다.
        wanted = (requirement.text, requirement.grade, requirement.points, index)
        item = existing.get(requirement.requirement_id)
        if item is None:
            ChecklistItem.objects.create(
                problem=problem,
                label=requirement.text,
                grade=requirement.grade,
                points=requirement.points,
                order=index,
                contest_requirement_id=requirement.requirement_id,
            )
        elif (item.label, item.grade, item.points, item.order) != wanted:
            item.label, item.grade, item.points, item.order = wanted
            item.save(update_fields=["label", "grade", "points", "order"])
        kept.add(requirement.requirement_id)
    for requirement_id, item in existing.items():
        if requirement_id not in kept:
            item.delete()


def on_contest_source_changed(sender, contest_id: int, **kwargs) -> None:
    """공유층 신호 수신자 — 그 공모전을 들여온 문제 전부를 맞춘다. 원본은 한 번만 읽는다."""

    problems = list(Problem.objects.filter(contest_id=contest_id))
    if not problems:
        return
    source = contest_catalog().get_source(contest_id)
    for problem in problems:
        try:
            sync_contest_problem(problem, source)
        except Exception:  # 한 문제의 실패가 다른 클래스의 문제를 막지 않게
            logger.exception("공모전 문제 동기화 실패(problem=%s, contest=%s)", problem.pk, contest_id)


def contest_state(problem: Problem) -> dict | None:
    """화면에 보일 공모전 상태 — 공모전 문제가 아니면 None."""

    if not is_contest_problem(problem):
        return None
    source = contest_catalog().get_source(problem.contest_id)
    return {
        "contest_id": problem.contest_id,
        "accepts_entries": bool(source and source.accepts_classroom_entries),
        "deadline_at": source.deadline_at if source else None,
    }
