"""문제를 다른 클래스로 복사한다 (#292, CONTEXT.md 「강의실」).

**복사는 언제나 문제와 체크리스트와 채점 설정(문제 자신의 `model`)만
데려온다.** 제출물·시도·Score·참여자는 애초에 이 함수가 모르는
것들이다 — 원본에 그런 행이 있어도 이 함수가 참조하는 필드는 여기
적힌 것뿐이라 자연히 따라오지 않는다. 복사본은 원본과 행이 다르므로
한쪽을 고쳐도 다른 쪽이 바뀌지 않는다.
"""

from __future__ import annotations

from .models import ChecklistItem, Class, Problem


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
