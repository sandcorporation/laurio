"""문제·클래스 복사 (#292/#293, CONTEXT.md 「강의실」).

**복사는 언제나 문제와 체크리스트와 채점 설정(문제 자신의 `model`)만
데려온다.** 제출물·시도·Score·참여자는 애초에 이 함수가 모르는
것들이다 — 원본에 그런 행이 있어도 이 함수가 참조하는 필드는 여기
적힌 것뿐이라 자연히 따라오지 않는다. 복사본은 원본과 행이 다르므로
한쪽을 고쳐도 다른 쪽이 바뀌지 않는다.
"""

from __future__ import annotations

from .models import (
    ChecklistItem,
    Class,
    Problem,
    ProblemTemplate,
    ProblemTemplateChecklistItem,
)


def pending_reported_templates() -> list[ProblemTemplate]:
    """운영자가 확인해야 할 신고 큐(#320) — 신고가 있고 아직 내려가지 않았고,
    그 신고 이후에 운영자 판단이 없는 템플릿. 판단(기각 포함) 뒤에 같은
    템플릿이 **다시** 신고되면 그 새 신고가 새 사건이라 대기열에 다시
    뜬다 — 별도 `resolved_at` 필드 없이 시각 비교만으로 계산한다."""

    candidates = (
        ProblemTemplate.objects.filter(taken_down_at__isnull=True)
        .filter(reports__isnull=False)
        .distinct()
        .prefetch_related("reports", "moderation_decisions")
        .order_by("-created_at")
    )

    pending = []
    for template in candidates:
        reports = list(template.reports.all())
        if not reports:
            continue
        latest_report_at = max(r.created_at for r in reports)
        decisions = list(template.moderation_decisions.all())
        latest_decision_at = max((d.decided_at for d in decisions), default=None)
        if latest_decision_at is None or latest_decision_at < latest_report_at:
            pending.append(template)
    return pending


def copy_problem_to_class(problem: Problem, target_class: Class) -> Problem:
    """`problem`을 `target_class` 안에 새 행으로 복사한다. 원본 상태(초안/열림)와
    무관하게 복사본은 언제나 초안으로 들어온다(#292 AC) — 대상 클래스에서는
    아직 아무도 그 문제를 통과한 적이 없으므로 열림이 뜻이 없다. 대상 클래스의
    기존 문제 뒤에 순서대로 붙는다.
    """

    copy = Problem.objects.create(
        classroom=target_class,
        title=problem.title,
        description=problem.description,
        submission_format=problem.submission_format,
        status=Problem.Status.DRAFT,
        order=target_class.problems.count(),
        model=problem.model,
    )
    ChecklistItem.objects.bulk_create(
        ChecklistItem(
            problem=copy, label=item.label, required=item.required, order=item.order
        )
        for item in problem.checklist_items.all()
    )
    return copy


def copy_class(class_obj: Class, instructor_id: int) -> Class:
    """`class_obj`를 복사해 `instructor_id`가 여는 새 클래스를 만든다(#293 AC).

    **OpenAI 키는 따라오지 않는다** — AC가 「문제와 체크리스트와 채점
    설정」이라고만 적고 키는 언급하지 않는다: 키는 강사 본인의 결제 수단이지
    「채점 설정」(어떤 모델을 쓸지)이 아니다. 새 클래스는 `has_openai_key`가
    거짓으로 시작해 강사가 다시 넣어야 한다 — 저장 뒤에는 다시 못 보는
    값이므로 어차피 이 코드가 평문을 복사할 방법이 없다(#284).

    참여자·제출물·Score·달성률은 이 함수가 모르는 모델이라 자연히 따라오지
    않는다 — `ClassMember`·`Submission`이 아직 없다(#279~#281/#286~#290).
    """

    new_class = Class.objects.create(
        instructor_id=instructor_id,
        name=class_obj.name,
        default_model=class_obj.default_model,
    )
    for problem in class_obj.problems.order_by("order", "id"):
        copy_problem_to_class(problem, new_class)
    return new_class


def publish_problem_as_template(
    problem: Problem, *, published_by_id: int, publisher_display_name: str
) -> ProblemTemplate:
    """`problem`을 공개 시점의 사본으로 뜬다(#316). 원본 `Problem`·`Class`를
    가리키지 않는다 — 만든 뒤에는 원본이 어떻게 바뀌든(고쳐지거나 지워지거나)
    이 행은 그대로다. 채점 모델은 애초에 `ProblemTemplate`에 필드가 없어
    따라올 길이 없다."""

    template = ProblemTemplate.objects.create(
        published_by_id=published_by_id,
        publisher_display_name=publisher_display_name,
        title=problem.title,
        description=problem.description,
        submission_format=problem.submission_format,
    )
    ProblemTemplateChecklistItem.objects.bulk_create(
        ProblemTemplateChecklistItem(
            template=template, label=item.label, required=item.required, order=item.order
        )
        for item in problem.checklist_items.all()
    )
    return template


def import_problem_template(template: ProblemTemplate, target_class: Class) -> Problem:
    """템플릿을 `target_class` 안의 새 문제로 가져온다(#316). 언제나 초안으로
    들어온다 — `copy_problem_to_class`와 같은 이유(대상 클래스에서는 아직
    아무도 통과한 적이 없다). 채점 모델은 비운 채로 만든다 — 가져간 사람의
    `default_model`을 그대로 따르게 한다(AC "채점 모델은 따라오지 않는다")."""

    problem = Problem.objects.create(
        classroom=target_class,
        title=template.title,
        description=template.description,
        submission_format=template.submission_format,
        status=Problem.Status.DRAFT,
        order=target_class.problems.count(),
    )
    ChecklistItem.objects.bulk_create(
        ChecklistItem(problem=problem, label=item.label, required=item.required, order=item.order)
        for item in template.checklist_items.all()
    )
    return problem
