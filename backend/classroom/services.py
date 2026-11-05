"""문제·클래스 복사 (#292/#293/#389, CONTEXT.md 「강의실」).

**복사는 언제나 문제와 체크리스트와 채점 설정(문제 자신의 `model`)·채점
지침(#389)만 데려온다.** 제출물·시도·Score·참여자는 애초에 이 함수가 모르는
것들이다 — 원본에 그런 행이 있어도 이 함수가 참조하는 필드는 여기
적힌 것뿐이라 자연히 따라오지 않는다. 복사본은 원본과 행이 다르므로
한쪽을 고쳐도 다른 쪽이 바뀌지 않는다.

**채점 지침은 채점 모델과 달리 템플릿에도 따라간다** — 지침은 "무엇을
통과로 볼지"의 일부라, 옮기지 않으면 가져간 사람이 다른 기준으로 채점되는
문제를 넘겨받는 셈이다(#385 Implementation Decisions).

**문법 검사 기본 항목의 켜짐 여부도 채점 지침과 같은 이유로 따라간다**
(#410, CONTEXT.md 「문법 검사」) — "무엇을 통과로 볼지"의 일부이지, 채점
모델처럼 가져간 사람의 청구서에 영향을 주는 값이 아니다.

**어느 필드가 어느 경로로 옮겨지는지는 `PROBLEM_FIELD_TRANSFER_TABLE` 한
곳에 적혀 있다**(#441, 부모 #432 「복사·템플릿 필드 표」). 이 파일의 여섯
함수(`copy_problem_to_class`·`copy_class`·`publish_problem_as_template`·
`import_problem_template`·`publish_class_as_template`·
`import_class_template`)는 모두 그 표에서 뽑은 필드만 옮기고, 대상이
달라지는 자리(classroom·status·order)만 직접 정한다. `Problem`에 필드를
더하고 표에 적지 않으면 `tests/test_classroom_problem_field_transfer_table.py`
의 구조 검사가 실패한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.db.models import Count, Q

from .instructors import active_participant_q, classes_taught_by

from .models import (
    ChecklistItem,
    Class,
    ClassTemplate,
    ClassTemplateProblem,
    ClassTemplateProblemChecklistItem,
    Problem,
    ProblemTemplate,
    ProblemTemplateChecklistItem,
)


@dataclass(frozen=True)
class ProblemFieldTransferRule:
    """`Problem`의 구체 필드 하나가 여섯 경로에서 옮겨지는지 적어 두는 규칙 한
    줄(#441, 부모 #385/#432 Implementation Decisions 「복사·템플릿 필드 표」).

    `copies`는 문제 복사(`copy_problem_to_class`)·클래스 복사(`copy_class`,
    안에서 앞의 함수를 부른다)에서 옮기는가, `templates`는 문제·클래스
    템플릿의 공개·가져오기 네 경로에서 옮기는가다. 둘 다 거짓이면 그 필드는
    여섯 경로 어디서도 원본 값을 그대로 옮기지 않는다는 뜻이다 — 새 행은
    자기만의 값(기본값 또는 호출하는 쪽이 직접 정하는 값)으로 시작한다."""

    field: str
    copies: bool
    templates: bool
    note: str = ""


#: `test_classroom_problem_field_transfer_table.py`의 구조 검사가 `Problem`의
#: 구체 필드(`Problem._meta.get_fields()`에서 `concrete`인 것) 전부가 여기 한
#: 줄씩 있는지를 확인한다 — 표에 적지 않은 새 필드가 생기면 그 테스트가
#: 빨개진다. 옮기는 규칙은 지금까지의 동작 그대로다: 채점 모델은 복사
#: 때만, 추론 강도는 어디서도, 나머지 설정(형식·채점 지침·문법 검사)은
#: 모두 옮긴다.
PROBLEM_FIELD_TRANSFER_TABLE: tuple[ProblemFieldTransferRule, ...] = (
    ProblemFieldTransferRule("id", copies=False, templates=False, note="식별자 — 새 행은 새 pk를 받는다"),
    ProblemFieldTransferRule(
        "classroom", copies=False, templates=False, note="대상 클래스는 호출하는 쪽이 직접 정한다"
    ),
    ProblemFieldTransferRule("title", copies=True, templates=True),
    ProblemFieldTransferRule("description", copies=True, templates=True),
    ProblemFieldTransferRule("submission_formats", copies=True, templates=True),
    ProblemFieldTransferRule(
        "status", copies=False, templates=False, note="복사본·가져온 문제는 언제나 초안으로 시작한다"
    ),
    ProblemFieldTransferRule(
        "order", copies=False, templates=False, note="대상 클래스 안에서 경로마다 새로 매겨진다"
    ),
    ProblemFieldTransferRule(
        "model", copies=True, templates=False, note="복사 때만 — 템플릿은 청구서 결정을 가져간 사람에게 둔다"
    ),
    ProblemFieldTransferRule(
        "scoring_model_rejected_at",
        copies=False,
        templates=False,
        note="벤더 거부 시각 — 새 문제는 아직 거부된 적이 없다",
    ),
    ProblemFieldTransferRule(
        "reasoning_effort",
        copies=False,
        templates=False,
        note="비용 결정은 가져간 사람이 한다 — 어디서도 옮기지 않는다",
    ),
    ProblemFieldTransferRule(
        "model_marked_reasoning",
        copies=True,
        templates=False,
        note="「추론 모델」 스위치(#602) — 그 모델과 함께 간다",
    ),
    ProblemFieldTransferRule("grading_strictness", copies=True, templates=True),
    ProblemFieldTransferRule("grading_guideline_text", copies=True, templates=True),
    ProblemFieldTransferRule("syntax_check_enabled", copies=True, templates=True),
    ProblemFieldTransferRule(
        "quality_public",
        copies=False,
        templates=False,
        note="완성도 공개(#883) — 새 문제의 참여자에게 공개할지는 그 문제에서 강사가 다시 정한다",
    ),
    ProblemFieldTransferRule(
        "contest_id",
        copies=True,
        templates=False,
        note="공모전 문제(#548) — 복사본도 그 공모전을 따라간다. 템플릿은 공모전 문제를 받지 않는다",
    ),
    ProblemFieldTransferRule(
        "instructor_note",
        copies=True,
        templates=False,
        note="공모전 문제의 수업용 안내(#548) — 템플릿은 공모전 문제를 받지 않는다",
    ),
    ProblemFieldTransferRule(
        "recommended_due_at",
        copies=False,
        templates=False,
        note="권장 기한(#769) — 다음 기수·남의 클래스의 날짜는 가져간 사람이 새로 정한다",
    ),
    ProblemFieldTransferRule(
        "due_at", copies=False, templates=False, note="마감(#769) — 권장 기한과 같은 이유로 어디서도 옮기지 않는다"
    ),
    ProblemFieldTransferRule("created_at", copies=False, templates=False, note="시각 — auto_now_add"),
    ProblemFieldTransferRule("updated_at", copies=False, templates=False, note="시각 — auto_now"),
)


def _problem_copy_fields(source) -> dict:
    """`PROBLEM_FIELD_TRANSFER_TABLE`에서 복사 때 옮기는 필드만 `source`에서
    읽어 담는다 — 문제 복사·클래스 복사가 함께 쓴다."""

    return {
        rule.field: getattr(source, rule.field)
        for rule in PROBLEM_FIELD_TRANSFER_TABLE
        if rule.copies
    }


def _problem_template_fields(source) -> dict:
    """`PROBLEM_FIELD_TRANSFER_TABLE`에서 템플릿 공개·가져오기 때 옮기는
    필드만 읽어 담는다. `source`는 `Problem`이거나(공개) `ProblemTemplate`·
    `ClassTemplateProblem`(가져오기)이다 — 셋 다 표에 적힌 필드 이름을
    그대로 공유한다."""

    return {
        rule.field: getattr(source, rule.field)
        for rule in PROBLEM_FIELD_TRANSFER_TABLE
        if rule.templates
    }


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
        status=Problem.Status.DRAFT,
        order=target_class.problems.count(),
        **_problem_copy_fields(problem),
    )
    ChecklistItem.objects.bulk_create(
        ChecklistItem(
            problem=copy,
            label=item.label,
            grade=item.grade,
            points=item.points,
            order=item.order,
            # 공모전 문제의 항목은 복사본에서도 같은 Requirement 를 따라간다(#548).
            contest_requirement_id=item.contest_requirement_id,
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

    **`instructor_display_name`은 `name`과 같이 따라온다**(#299) — 다음
    기수를 여는 것은 대개 같은 강사가 같은 맥락에서 계속 가르치는 것이라,
    가입 미리보기에 다시 빈 줄이 뜨게 두지 않는다. 다른 이름을 쓰고
    싶으면 클래스 설정에서 고치면 된다.

    **이름은 원본 그대로 오지 않는다**(#339) — `" 사본"`을 붙인다. 「복사해서
    새로 열기」는 클릭 한 번으로 바로 새 클래스 상세로 이동하는 흐름이라(AC)
    이 자리에서 이름을 물어볼 수 없고, 원본과 같은 이름이면 목록과 문제
    복사 대상 목록에서 두 줄이 똑같아 구별할 수 없었다. 다음 기수 번호
    (「3기」→「4기」)까지 추측하지 않는 이유는 그 추측이 틀렸을 때 원본
    이름이 그대로인 것보다 더 헷갈리기 때문이다 — 다른 이름을 쓰고 싶으면
    클래스 설정에서 고친다. 붙인 결과가 `name` 필드 길이(200자)를 넘으면
    원본 쪽을 줄인다 — 원본 이름이 198~200자여도 `DataError` 없이 복사되게
    한다.
    """

    suffix = " 사본"
    max_length = Class._meta.get_field("name").max_length
    base_name = class_obj.name[: max_length - len(suffix)]
    new_class = Class.objects.create(
        instructor_id=instructor_id,
        name=f"{base_name}{suffix}",
        instructor_display_name=class_obj.instructor_display_name,
        default_model=class_obj.default_model,
    )
    for problem in class_obj.problems.order_by("order", "id"):
        copy_problem_to_class(problem, new_class)
    return new_class


def publish_problem_as_template(
    problem: Problem, *, published_by_id: int, publisher_display_name: str
) -> tuple[ProblemTemplate, bool]:
    """`problem`을 공개 시점의 사본으로 뜬다(#316). 사본의 필드(title 등)는
    원본 `Problem`·`Class`를 가리키지 않는다 — 만든 뒤에는 원본이 어떻게
    바뀌든(고쳐지거나 지워지거나) 이 행은 그대로다. 채점 모델은 애초에
    `ProblemTemplate`에 필드가 없어 따라올 길이 없다.

    **같은 문제에 살아 있는 템플릿이 이미 있으면 새로 만들지 않는다**(#333
    AC) — 그 템플릿을 그대로 돌려준다. 반환값의 두 번째 항목이 거짓이면
    새로 만들지 않았다는 뜻이다. 내려간 템플릿은 이 검사에 걸리지 않는다 —
    「내린 뒤에는 다시 공개할 수 있다」가 새 사본을 허용해야 하기 때문이다."""

    existing = ProblemTemplate.objects.filter(
        source_problem=problem, taken_down_at__isnull=True
    ).first()
    if existing is not None:
        return existing, False

    try:
        # 중첩 atomic(세이브포인트)으로 감싼다 — `payments.api.request_payment`와
        # 같은 이유: IntegrityError가 나면 Postgres가 바깥 트랜잭션 전체를
        # "aborted"로 만들어, 세이브포인트 없이는 그 뒤 재조회 쿼리도 막힌다.
        with transaction.atomic():
            template = ProblemTemplate.objects.create(
                source_problem=problem,
                published_by_id=published_by_id,
                publisher_display_name=publisher_display_name,
                **_problem_template_fields(problem),
            )
            ProblemTemplateChecklistItem.objects.bulk_create(
                ProblemTemplateChecklistItem(
                    template=template, label=item.label, grade=item.grade, points=item.points, order=item.order
                )
                for item in problem.checklist_items.all()
            )
    except IntegrityError:
        # 위 존재 확인 뒤 동시에 다른 요청이 먼저 이겼다 —
        # unique_live_problem_template_per_source가 막아준다. 이미 있는
        # 살아 있는 템플릿을 그대로 돌려준다.
        return ProblemTemplate.objects.get(source_problem=problem, taken_down_at__isnull=True), False
    return template, True


def import_problem_template(template: ProblemTemplate, target_class: Class) -> Problem:
    """템플릿을 `target_class` 안의 새 문제로 가져온다(#316). 언제나 초안으로
    들어온다 — `copy_problem_to_class`와 같은 이유(대상 클래스에서는 아직
    아무도 통과한 적이 없다). 채점 모델은 비운 채로 만든다 — 가져간 사람의
    `default_model`을 그대로 따르게 한다(AC "채점 모델은 따라오지 않는다")."""

    problem = Problem.objects.create(
        classroom=target_class,
        status=Problem.Status.DRAFT,
        order=target_class.problems.count(),
        **_problem_template_fields(template),
    )
    ChecklistItem.objects.bulk_create(
        ChecklistItem(
            problem=problem, label=item.label, grade=item.grade, points=item.points, order=item.order
        )
        for item in template.checklist_items.all()
    )
    return problem


def publish_class_as_template(
    class_obj: Class, *, published_by_id: int, publisher_display_name: str
) -> tuple[ClassTemplate, bool]:
    """`class_obj`를 공개 시점의 사본으로 뜬다(#319) — 문제들과 그 순서, 각
    문제의 체크리스트가 함께 담긴다. 사본의 필드는 원본 `Class`·`Problem`을
    가리키지 않으니 이후 원본이 어떻게 바뀌든(고쳐지거나 지워지거나) 이 사본은
    그대로다. 채점 모델은 애초에 `ClassTemplate`/`ClassTemplateProblem`에
    필드가 없어 따라올 길이 없다.

    **같은 클래스에 살아 있는 템플릿이 이미 있으면 새로 만들지 않는다**(#333
    AC, `publish_problem_as_template`와 같은 규율) — 반환값의 두 번째 항목이
    거짓이면 기존 템플릿을 그대로 돌려준 것이다."""

    existing = ClassTemplate.objects.filter(
        source_class=class_obj, taken_down_at__isnull=True
    ).first()
    if existing is not None:
        return existing, False

    try:
        # `publish_problem_as_template`과 같은 세이브포인트 관용구.
        with transaction.atomic():
            template = ClassTemplate.objects.create(
                source_class=class_obj,
                published_by_id=published_by_id,
                publisher_display_name=publisher_display_name,
                name=class_obj.name,
            )
            for problem in class_obj.problems.order_by("order", "id"):
                template_problem = ClassTemplateProblem.objects.create(
                    template=template,
                    order=problem.order,
                    **_problem_template_fields(problem),
                )
                ClassTemplateProblemChecklistItem.objects.bulk_create(
                    ClassTemplateProblemChecklistItem(
                        problem=template_problem,
                        label=item.label,
                        grade=item.grade,
                        points=item.points,
                        order=item.order,
                    )
                    for item in problem.checklist_items.all()
                )
    except IntegrityError:
        # 위 존재 확인 뒤 동시에 다른 요청이 먼저 이겼다 —
        # unique_live_class_template_per_source가 막아준다.
        return ClassTemplate.objects.get(source_class=class_obj, taken_down_at__isnull=True), False
    return template, True


def import_class_template(template: ClassTemplate, *, instructor_id: int, name: str) -> Class:
    """템플릿을 `instructor_id`가 여는 새 클래스로 가져온다(#319). 이름은
    가져가는 사람이 직접 정한다(AC) — 원본 이름이 그대로 앉으면 남의 수업
    이름이 내 목록에 헷갈리게 남는다. 새 클래스는 `Class.join_code`의 기본값
    (`_generate_join_code`)으로 **자기만의** 가입 코드를 받는다 — 원본의 것을
    복사하지 않는다. 문제들은 `import_problem_template`과 같은 이유로 언제나
    초안으로 들어오고, 채점 모델은 비운 채로(대상 클래스의 `default_model`을
    따르게) 만든다."""

    new_class = Class.objects.create(instructor_id=instructor_id, name=name)
    for template_problem in template.problems.order_by("order", "id"):
        problem = Problem.objects.create(
            classroom=new_class,
            status=Problem.Status.DRAFT,
            order=template_problem.order,
            **_problem_template_fields(template_problem),
        )
        ChecklistItem.objects.bulk_create(
            ChecklistItem(
            problem=problem, label=item.label, grade=item.grade, points=item.points, order=item.order
        )
            for item in template_problem.checklist_items.all()
        )
    return new_class


def instructor_classes(instructor_id: int):
    """「내 클래스」 — 본인이 강사인 클래스만, 화면 목록과 같은 순서로(#278).

    강사 화면(`GET /api/classroom/classes`)과 연결된 앱의 `list_my_classes`
    도구(`classroom.mcp`, ADR-0052)가 함께 부른다 — 두 표면이 「누구의 클래스가
    보이는가」를 따로 정하지 않게 한 곳에 둔다. 도구가 쓰는 세는 값(참여자 수·
    상태별 문제 수)을 주석으로 단다: 참여자는 강사와 내보내진 사람을 빼고
    센다(CONTEXT.md 「달성률」의 분모와 같은 사람들). 「본인이 강사인가」·「그 가입이
    강사의 것인가」는 `classroom.instructors` 가 답한다(#559)."""

    return classes_taught_by(instructor_id).annotate(
        participant_count=Count(
            "members", filter=active_participant_q(member="members", classroom=""), distinct=True
        ),
        open_problem_count=Count(
            "problems", filter=Q(problems__status=Problem.Status.OPEN), distinct=True
        ),
        draft_problem_count=Count(
            "problems", filter=Q(problems__status=Problem.Status.DRAFT), distinct=True
        ),
        hidden_problem_count=Count(
            "problems", filter=Q(problems__status=Problem.Status.HIDDEN), distinct=True
        ),
    ).order_by("-created_at", "-id")
