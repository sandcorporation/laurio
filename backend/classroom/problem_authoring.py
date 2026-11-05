"""문제와 체크리스트를 만들고 고치는 일 — 화면과 연결된 앱이 같은 함수를 부른다
(#514, spec #511 「도구는 기존 강사 서비스 함수·검증을 그대로 부른다」).

**문은 호출부가 연다.** 소유권 → 존재 → 보관 확인은 `instructor_scope.class_scope`/
`problem_scope(..., write=True)` 의 몫이고, 이 모듈의 함수는 그 확인을 마친 `Class`·
`Problem` 을 받는다 — 강사 화면 라우트(`classroom.api`)와 MCP 도구
(`classroom.mcp_problem_tools`)가 각자 첫 줄에서 범위를 열고 같은 함수를 부른다.
범위 호출을 라우트에 남겨 둔 것은 `tests/test_classroom_instructor_scope_structure.py`
가 「쓰기 라우트는 전부 쓰기 범위를 지난다」를 라우트 몸통에서 읽기 때문이다.

**검증과 거절 문구도 여기 하나다.** 제출 형식·채점 지침·채점 모델·추론 강도·금칙어·
필수 항목 하한이 만들기·고치기 두 자리와 두 표면에서 같은 규칙과 같은 문장으로
거절한다. 거절은 `HttpError` 로 낸다 — 화면은 그것을 그대로 응답으로, 연결된 앱은
같은 문장을 도구 오류로 받는다.
"""

from __future__ import annotations

from django.db import transaction
from ninja.errors import HttpError

from core.banned_words import BannedWordViolation, find_banned_word_violation

from .contest_problems import is_contest_problem, reject_if_locked
from .models import ChecklistItem, Class, Problem
from .problem_transitions import NO_REQUIRED_ITEM_MESSAGE, assert_required_item_floor
from .schemas import ChecklistItemIn, ChecklistItemPatchIn, ProblemIn, ProblemPatchIn
from .scoring_model_catalog import get_scoring_model_catalog
from .scoring_connection import connection_for, mark_verified
from .scoring_model_probe import ScoringModelProbeFailed, ensure_model_keeps_scoring_format
from .scoring_models import is_fallback_model_for, is_valid_reasoning_effort

# --- 검증 ----------------------------------------------------------------------

_SUBMISSION_FORMATS = {choice for choice, _label in Problem.SubmissionFormat.choices}
#: 화면에 늘 같은 순서로 보이도록(체크박스 둘의 고정 순서), 저장 전에 이
#: 순서로 정렬해 중복을 제거한다 — 입력 순서를 그대로 믿지 않는다.
_SUBMISSION_FORMAT_ORDER = [choice for choice, _label in Problem.SubmissionFormat.choices]


def _normalize_submission_formats(values: list[str]) -> list[str]:
    unique = set(values)
    return [f for f in _SUBMISSION_FORMAT_ORDER if f in unique]


def validate_submission_formats(values: list[str]) -> list[str]:
    """빈 목록·모르는 값을 422로 거절한다(#373 AC) — 만들기·편집 두 자리가
    같은 규칙을 쓴다."""

    if not values:
        raise HttpError(422, "제출 형식을 하나 이상 골라주세요.")
    unknown = [v for v in values if v not in _SUBMISSION_FORMATS]
    if unknown:
        raise HttpError(422, f"알 수 없는 제출 형식입니다: {unknown[0]}")
    return _normalize_submission_formats(values)


_GRADING_STRICTNESS_VALUES = {choice for choice, _label in Problem.GradingStrictness.choices}


def validate_grading_guideline(strictness: str, text: str) -> tuple[str, str]:
    """채점 지침 두 칸을 검증하고 저장할 모양으로 정규화한다(#386 AC) —
    만들기·편집 두 자리가 같은 규칙을 쓴다(`validate_submission_formats`와
    같은 관용구). 알 수 없는 단계와 빈 직접 입력 문장은 422다. 직접 입력이
    아니면 문장을 언제나 빈 문자열로 되돌린다 — "문장은 직접 입력일 때만
    비어 있지 않다"(#385 Implementation Decisions)를 저장 시점에 구조로
    지킨다."""

    if strictness not in _GRADING_STRICTNESS_VALUES:
        raise HttpError(422, f"알 수 없는 채점 지침입니다: {strictness}")
    if strictness == Problem.GradingStrictness.CUSTOM:
        if not text.strip():
            raise HttpError(422, "직접 입력 채점 지침은 문장을 비울 수 없습니다.")
        return strictness, text
    return strictness, ""


def validate_scoring_model_choice(class_obj: Class, model_id: str, *, current_value: str) -> None:
    """저장 시점에 이 모델이 그 클래스의 키로 실제로 쓸 수 있는지 검증한다
    (#401 AC). 클래스 기본값·문제별 값 둘 다 이 함수 하나를 쓴다 — 두
    자리가 갈리면 클래스에서는 통과한 값이 문제에서는 거절되는(또는 그
    반대) 상태가 생긴다.

    조회가 되면(`source == "live"`) 그 결과에 있어야만 받는다 — 이미 같은
    값을 쓰고 있어도 예외를 두지 않는다(그 사이 키의 권한이 좁혀졌을 수
    있다). 조회가 불가하면(`source == "fallback"`, 키 없음·거부·조회 실패)
    기본 목록 안의 값이거나 지금 저장된 값과 같을 때만 받는다 — 오타는
    막되, 멀쩡히 쓰던 값이 벤더 장애 한 번에 막히지 않는다(#401
    Implementation Decisions)."""

    catalog = get_scoring_model_catalog(class_obj)
    if catalog.source == "manual":
        # 호환 서버가 목록을 주지 않았다(#601) — 소유자가 그 서버의 모델 이름을 직접 넣는다.
        if model_id.strip() and model_id == model_id.strip() and len(model_id) <= 200:
            return
        raise HttpError(422, "모델 이름을 200자 안으로, 앞뒤 공백 없이 넣어주세요.")
    if catalog.source == "live":
        if any(choice.id == model_id for choice in catalog.models):
            return
        raise HttpError(422, f"이 키로 쓸 수 없는 채점 모델입니다: {model_id}")

    if model_id == current_value or is_fallback_model_for(class_obj.scoring_connection_kind, model_id):
        return
    raise HttpError(
        422,
        f"지금은 모델 목록을 확인할 수 없어 기본 목록의 모델이나 지금 쓰는 모델만 "
        f"저장할 수 있습니다: {model_id}",
    )


def probe_scoring_model_choice(class_obj: Class, model_id: str, *, reasoning_effort: str | None) -> None:
    """호환 서버면 이 모델이 채점 형식을 지키는지 시험 호출로 확인한다(#602) — 못 지키면 422 와
    이유 문장. 클래스 기본·문제별 모델이 이 함수 하나를 쓴다(`validate_scoring_model_choice` 와
    같은 이유). 「OpenAI 키」 연결은 아무것도 하지 않는다. `reasoning_effort` 는 채점 때 실릴 값
    그대로다 — 「추론 모델」 스위치가 꺼져 있으면 `None`."""

    connection = connection_for(class_obj)
    try:
        probed = ensure_model_keeps_scoring_format(connection, model_id, reasoning_effort=reasoning_effort)
    except ScoringModelProbeFailed as exc:
        raise HttpError(422, exc.message) from None
    if probed:
        mark_verified(class_obj.pk, connection)


def validate_reasoning_effort(value: str) -> None:
    if not is_valid_reasoning_effort(value):
        raise HttpError(422, f"알 수 없는 추론 강도입니다: {value}")


def reject_banned_public_text(value: str, field_label: str) -> None:
    """클래스 이름·문제 제목·설명·체크리스트 항목에 욕설이 있으면 거절한다
    (spec #474, #479) — 사칭 목록은 걸지 않는다: 「관리자 페이지 만들기」는
    정당한 문제 제목이다(`core.banned_word_rules.RULES`의
    `("classroom", ...)` 항목들). 클래스 이름은 가입 미리보기에, 나머지는
    그 클래스의 참여자 전부에게 로그인 없이도 보인다."""

    violation = find_banned_word_violation(value, check_impersonation=False)
    if violation is BannedWordViolation.PROFANITY:
        raise HttpError(422, f"{field_label}에 욕설을 쓸 수 없습니다.")


# --- 문제 ----------------------------------------------------------------------


DUE_ORDER_MESSAGE = "권장 기한은 마감보다 늦을 수 없습니다."


def validate_due_order(recommended_due_at, due_at) -> None:
    """둘 다 있으면 권장 기한 ≤ 마감이어야 한다(#769) — 같은 시각은 된다."""

    if recommended_due_at is not None and due_at is not None and recommended_due_at > due_at:
        raise HttpError(422, DUE_ORDER_MESSAGE)


def create_problem(class_obj: Class, payload: ProblemIn) -> Problem:
    """만들기 한 번이 문제와 체크리스트 항목을 함께 만든다(#315). `open`이
    참이면 만든 직후 바로 연다 — 필수 항목이 하나도 없으면(`open_problem`과
    같은 규칙) 문제 자체를 만들지 않고 거부한다("실패하면 문제도 안
    생긴다")."""

    submission_formats = validate_submission_formats(payload.submission_formats)

    # 편집(`update_problem`)과 같은 규칙이다 — 두 자리가 갈리면 만들 때는
    # 통과한 값이 고칠 때 거절되는 상태가 생긴다.
    if payload.reasoning_effort:
        validate_reasoning_effort(payload.reasoning_effort)
    if payload.model:
        validate_scoring_model_choice(class_obj, payload.model, current_value="")
        probe_scoring_model_choice(
            class_obj,
            payload.model,
            reasoning_effort=(
                (payload.reasoning_effort or class_obj.default_reasoning_effort)
                if payload.model_is_reasoning
                else None
            ),
        )
    grading_strictness, grading_guideline_text = validate_grading_guideline(
        payload.grading_strictness, payload.grading_guideline_text
    )
    validate_due_order(payload.recommended_due_at, payload.due_at)

    reject_banned_public_text(payload.title, "제목")
    reject_banned_public_text(payload.description, "설명")
    for item_in in payload.checklist_items:
        reject_banned_public_text(item_in.label, "체크리스트 항목")
    # 참여자도 어떤 기준으로 판정되는지 알고 제출해야 하므로(#385 User Story
    # 18) 참여자에게도 보인다 — 체크리스트 항목과 같은 노출(빠뜨렸던 것을
    # #480 구조 검사가 잡았다).
    reject_banned_public_text(grading_guideline_text, "채점 지침")

    if payload.open and not any(item.required for item in payload.checklist_items):
        raise HttpError(400, NO_REQUIRED_ITEM_MESSAGE)

    with transaction.atomic():
        next_order = class_obj.problems.count()
        problem = Problem.objects.create(
            classroom=class_obj,
            title=payload.title,
            description=payload.description,
            submission_formats=submission_formats,
            model=payload.model,
            reasoning_effort=payload.reasoning_effort,
            model_marked_reasoning=payload.model_is_reasoning,
            grading_strictness=grading_strictness,
            grading_guideline_text=grading_guideline_text,
            syntax_check_enabled=payload.syntax_check_enabled,
            recommended_due_at=payload.recommended_due_at,
            due_at=payload.due_at,
            order=next_order,
            status=Problem.Status.OPEN if payload.open else Problem.Status.DRAFT,
        )
        for index, item_in in enumerate(payload.checklist_items):
            ChecklistItem.objects.create(
                problem=problem, label=item_in.label, required=item_in.required, order=index
            )
    return problem


def update_problem(class_obj: Class, problem: Problem, payload: ProblemPatchIn) -> Problem:
    """보낸 칸만 고친다 — `None`(칸을 생략)은 바꾸지 않는다는 기존 PATCH 관례다."""

    submission_formats = (
        validate_submission_formats(payload.submission_formats)
        if payload.submission_formats is not None
        else None
    )
    if payload.model:
        validate_scoring_model_choice(class_obj, payload.model, current_value=problem.model)
    if payload.reasoning_effort:
        validate_reasoning_effort(payload.reasoning_effort)
    next_model = payload.model if payload.model is not None else problem.model
    next_marked = (
        payload.model_is_reasoning if payload.model_is_reasoning is not None else problem.model_marked_reasoning
    )
    # 자기 모델을 새로 고르거나 「추론 모델」 스위치를 바꿨을 때만 시험한다(#602) — 화면은 저장마다
    # 지금 값을 다시 보내므로, 그대로인 선택까지 서버에 묻지 않는다.
    if next_model and (next_model != problem.model or next_marked != problem.model_marked_reasoning):
        probe_scoring_model_choice(
            class_obj,
            next_model,
            reasoning_effort=(
                (payload.reasoning_effort or problem.reasoning_effort or class_obj.default_reasoning_effort)
                if next_marked
                else None
            ),
        )

    # 두 칸 중 하나라도 보내면 둘 다 함께 검증한다 — "문장은 직접 입력일
    # 때만 비어 있지 않다"는 두 칸을 함께 봐야 판단할 수 있는 불변식이라,
    # 필드 하나만 따로 저장하면 어긋난 상태가 생길 수 있다(#386). 예를
    # 들어 `grading_strictness="custom"`만 보내면 문장은 지금 저장된
    # 값(비-CUSTOM이었다면 빈 문자열)을 그대로 검증에 쓴다.
    grading_strictness = None
    grading_guideline_text = None
    if payload.grading_strictness is not None or payload.grading_guideline_text is not None:
        grading_strictness, grading_guideline_text = validate_grading_guideline(
            payload.grading_strictness
            if payload.grading_strictness is not None
            else problem.grading_strictness,
            payload.grading_guideline_text
            if payload.grading_guideline_text is not None
            else problem.grading_guideline_text,
        )
        # 참여자에게도 보이는 자리다(`create_problem`과 같은 이유, #480).
        reject_banned_public_text(grading_guideline_text, "채점 지침")

    # 공모전 문제는 제목·설명이 공모전을 따라간다(#548) — 대신 수업용 안내를 쓴다.
    if payload.title is not None or payload.description is not None:
        reject_if_locked(problem)
    if payload.instructor_note is not None and not is_contest_problem(problem):
        raise HttpError(422, "수업용 안내는 공모전 문제에만 둡니다 — 설명에 적어 주세요.")

    # 두 날짜는 생략과 null 이 다르다(#769) — 생략하면 그대로, null 이면 비운다. 순서는
    # 보낸 값과 저장된 값을 합쳐 본다: 마감(2020)이 있는 문제에 권장 기한(2099) 하나만
    # 보내도 거절돼야 한다.
    sent_dates = {"recommended_due_at", "due_at"} & payload.model_fields_set
    next_recommended = (
        payload.recommended_due_at if "recommended_due_at" in sent_dates else problem.recommended_due_at
    )
    next_due = payload.due_at if "due_at" in sent_dates else problem.due_at
    if sent_dates:
        validate_due_order(next_recommended, next_due)

    update_fields = []
    if sent_dates:
        problem.recommended_due_at = next_recommended
        problem.due_at = next_due
        update_fields.extend(["recommended_due_at", "due_at"])
    if payload.instructor_note is not None:
        reject_banned_public_text(payload.instructor_note, "수업용 안내")
        problem.instructor_note = payload.instructor_note
        update_fields.append("instructor_note")
    if payload.title is not None:
        reject_banned_public_text(payload.title, "제목")
        problem.title = payload.title
        update_fields.append("title")
    if payload.description is not None:
        reject_banned_public_text(payload.description, "설명")
        problem.description = payload.description
        update_fields.append("description")
    if submission_formats is not None:
        problem.submission_formats = submission_formats
        update_fields.append("submission_formats")
    if payload.model_is_reasoning is not None:
        problem.model_marked_reasoning = payload.model_is_reasoning
        update_fields.append("model_marked_reasoning")
    if payload.model is not None:
        problem.model = payload.model
        update_fields.append("model")
        # 강사가 이 문제의 채점 모델을 손댔으니 재시도할 자격을 준다(#403
        # AC "모델을 바꾼 뒤 새 시도는 새 모델로 채점된다") — 같은 값을
        # 다시 보내도 마찬가지다: "설정을 확인했다"는 사실 자체가 재시도
        # 트리거다, 값이 실제로 달라졌는지는 따지지 않는다.
        problem.scoring_model_rejected_at = None
        update_fields.append("scoring_model_rejected_at")
    if payload.reasoning_effort is not None:
        problem.reasoning_effort = payload.reasoning_effort
        update_fields.append("reasoning_effort")
    if grading_strictness is not None:
        problem.grading_strictness = grading_strictness
        problem.grading_guideline_text = grading_guideline_text
        update_fields.extend(["grading_strictness", "grading_guideline_text"])
    if payload.syntax_check_enabled is not None:
        problem.syntax_check_enabled = payload.syntax_check_enabled
        update_fields.append("syntax_check_enabled")
    if payload.quality_public is not None:
        problem.quality_public = payload.quality_public
        update_fields.append("quality_public")
    if update_fields:
        problem.save(update_fields=[*update_fields, "updated_at"])
    return problem


def reorder_problems(class_obj: Class, problem_ids: list[int]) -> list[Problem]:
    """클래스의 문제 전부를 빠짐없이 새 순서로 받는다 — 하나라도 빠지거나 남의
    문제가 섞이면 422다. 새 순서대로 정렬한 문제 목록을 돌려준다."""

    # 응답이 문제마다 체크리스트를 그린다 — 목록처럼 한 번에 받는다(#679).
    problems = {p.id: p for p in class_obj.problems.prefetch_related("checklist_items")}
    if set(problem_ids) != set(problems):
        raise HttpError(422, "이 클래스의 문제 목록과 일치하지 않습니다.")

    with transaction.atomic():
        for index, problem_id in enumerate(problem_ids):
            problems[problem_id].order = index
        Problem.objects.bulk_update(problems.values(), ["order"])
    return sorted(problems.values(), key=lambda p: p.order)


# --- 체크리스트 ------------------------------------------------------------------


def owned_checklist_item_or_404(problem: Problem, item_id: int) -> ChecklistItem:
    try:
        return problem.checklist_items.get(id=item_id)
    except ChecklistItem.DoesNotExist as exc:
        raise HttpError(404, "체크리스트 항목을 찾을 수 없습니다.") from exc


def add_checklist_item(problem: Problem, payload: ChecklistItemIn) -> ChecklistItem:
    reject_if_locked(problem)
    reject_banned_public_text(payload.label, "체크리스트 항목")
    return ChecklistItem.objects.create(
        problem=problem,
        label=payload.label,
        required=payload.required,
        order=problem.checklist_items.count(),
    )


def update_checklist_item(problem: Problem, item_id: int, payload: ChecklistItemPatchIn) -> ChecklistItem:
    """열린·숨긴 문제는 필수 항목을 하나 이상 유지해야 한다(#440) — 마지막
    필수 항목을 필수 해제하면 422로 거절한다(초안은 예외, `classroom.
    problem_transitions.assert_required_item_floor`)."""

    item = owned_checklist_item_or_404(problem, item_id)
    reject_if_locked(problem)

    if payload.required is False and item.required:
        remaining = problem.checklist_items.filter(required=True).exclude(id=item.id).count()
        assert_required_item_floor(problem, remaining_required_count=remaining)

    update_fields = []
    if payload.label is not None:
        reject_banned_public_text(payload.label, "체크리스트 항목")
        item.label = payload.label
        update_fields.append("label")
    if payload.required is not None:
        item.required = payload.required
        update_fields.append("required")
    if update_fields:
        item.save(update_fields=update_fields)
    return item


def delete_checklist_item(problem: Problem, item_id: int) -> ChecklistItem:
    """열린·숨긴 문제의 마지막 필수 항목은 지울 수 없다(#440) —
    `assert_required_item_floor`와 같은 이유, `update_checklist_item`과
    같은 규율(초안은 예외). 지운 항목을(행이 사라진 뒤의 인스턴스로)
    돌려준다 — 기록이 무엇을 지웠는지 적을 수 있게."""

    item = owned_checklist_item_or_404(problem, item_id)
    reject_if_locked(problem)

    if item.required:
        remaining = problem.checklist_items.filter(required=True).exclude(id=item.id).count()
        assert_required_item_floor(problem, remaining_required_count=remaining)

    deleted_id = item.id
    item.delete()
    item.id = deleted_id
    return item


def reorder_checklist_items(problem: Problem, item_ids: list[int]) -> list[ChecklistItem]:
    reject_if_locked(problem)
    items = {i.id: i for i in problem.checklist_items.all()}
    if set(item_ids) != set(items):
        raise HttpError(422, "이 문제의 체크리스트 항목과 일치하지 않습니다.")

    with transaction.atomic():
        for index, item_id in enumerate(item_ids):
            items[item_id].order = index
        ChecklistItem.objects.bulk_update(items.values(), ["order"])
    return sorted(items.values(), key=lambda i: i.order)
