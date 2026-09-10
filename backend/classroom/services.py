"""문제·클래스 복사 (#292/#293, CONTEXT.md 「강의실」).

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
