"""클래스를 만들고 고치는 일 — 화면과 연결된 앱이 같은 함수를 부른다
(#516, spec #511 「도구는 기존 강사 서비스 함수·검증을 그대로 부른다」).

`classroom.problem_authoring` 과 같은 모양이다. **문은 호출부가 연다** — 소유권·존재·보관
확인은 `instructor_scope.class_scope` 의 몫이고, 이 모듈의 함수는 그 확인을 마친 `Class`
를 받는다. 강사 화면 라우트(`classroom.api`·`classroom.template_api`)와 MCP 도구
(`classroom.mcp_class_tools`)가 각자 첫 줄에서 범위를 열고 같은 함수를 부른다(범위 호출이
라우트 몸통에 남아야 `tests/test_classroom_instructor_scope_structure.py` 가 읽는다).

**검증과 거절 문구도 여기 하나다.** 이름 금칙어, 채점 모델·추론 강도, 내려진 템플릿의
404 가 두 표면에서 같은 규칙과 같은 문장으로 거절한다. 거절은 `HttpError` 다 — 화면은
그대로 응답으로, 연결된 앱은 같은 문장을 도구 오류로 받는다.

OpenAI 키를 넣는 일(`classroom.api.set_class_openai_key`)은 여기 없다 — 연결된 앱이
닿지 않는 화면 전용이다(#511 「OpenAI 키」).
"""

from __future__ import annotations

from django.utils import timezone
from ninja.errors import HttpError

from core.banned_words import BannedWordViolation, find_banned_word_violation

from .models import Class, ClassTemplate, ProblemTemplate, _generate_join_code
from .problem_authoring import (
    reject_banned_public_text,
    validate_reasoning_effort,
    validate_scoring_model_choice,
)
from .schemas import ClassIn, ClassPatchIn, ImportClassTemplateIn
from .services import import_class_template

TEMPLATE_GONE_MESSAGE = "이 템플릿은 더 이상 사용할 수 없습니다."


def reject_banned_name(name: str) -> None:
    """강의실에서 사람 이름으로 불리는 자리에 금칙어가 있으면 거절한다
    (spec #474, #475, #477) — 클래스 참여자 이름(가입 때 `join_class`·
    나중에 스스로 바꿀 때 `rename_myself`), 클래스가 들고 있는 강사 이름
    (만들 때·설정에서 고칠 때), 템플릿 공개자 이름(`classroom.template_api`의
    `publish_template`·`publish_class_template`)이 전부 이 검사 하나를 그대로
    쓴다. 이름 필드라 사칭·욕설 목록을 둘 다 건다(`core.banned_word_rules.RULES`가
    호출부마다 어느 입력 스키마·필드인지 표로 든다).

    걸린 낱말 자체는 응답에 담지 않는다 — 그러면 욕설이 오류 토스트로 화면에
    렌더되고, 금칙어 목록이 한 번에 하나씩 캐낼 수 있는 사전이 된다. 대신
    무엇이 걸렸는지 종류만 말한다."""

    violation = find_banned_word_violation(name, check_impersonation=True)
    if violation is BannedWordViolation.IMPERSONATION:
        raise HttpError(422, "이름에는 운영진을 뜻하는 말을 쓸 수 없습니다.")
    if violation is BannedWordViolation.PROFANITY:
        raise HttpError(422, "이름에 욕설을 쓸 수 없습니다.")


def create_class(instructor_id: int, payload: ClassIn) -> Class:
    # 강사 이름은 로그인하지 않은 사람도 보는 가입 미리보기에 뜨므로
    # 만드는 시점에 막는다(spec #474, #477).
    reject_banned_name(payload.instructor_display_name)
    reject_banned_public_text(payload.name, "클래스 이름")
    return Class.objects.create(
        instructor_id=instructor_id,
        name=payload.name,
        instructor_display_name=payload.instructor_display_name,
    )


def touches_budget(payload: ClassPatchIn) -> bool:
    """이 설정 고치기가 예산 칸(상한·경고 임계)을 건드리는가 — 예산은 소유자의 비용이라
    그때만 소유자 전용이다(ADR-0055). 화면과 연결된 앱이 같은 판단을 쓴다."""

    return payload.token_budget is not None or payload.token_budget_warning_threshold_percent is not None


def update_class(class_obj: Class, payload: ClassPatchIn) -> Class:
    """클래스 설정을 고친다 — 보낸 칸만. 보관 뒤에도 고칠 수 있다(`classroom.participation`
    모듈 docstring 「열어 두는 것」) — 호출부가 `class_scope(write=False)` 로 연다."""

    if payload.default_model is not None:
        validate_scoring_model_choice(class_obj, payload.default_model, current_value=class_obj.default_model)
    if payload.default_reasoning_effort is not None:
        validate_reasoning_effort(payload.default_reasoning_effort)

    update_fields = []
    if payload.name is not None:
        reject_banned_public_text(payload.name, "클래스 이름")
        class_obj.name = payload.name
        update_fields.append("name")
    if payload.instructor_display_name is not None:
        # 만들 때만 막으면 그 뒤에 사칭 이름으로 바꾸면 그만이다(spec #474,
        # #477) — 참여자 이름을 바꿀 때(`rename_myself`)와 같은 이유.
        reject_banned_name(payload.instructor_display_name)
        class_obj.instructor_display_name = payload.instructor_display_name
        update_fields.append("instructor_display_name")
    if payload.default_model is not None and payload.default_model != class_obj.default_model:
        class_obj.default_model = payload.default_model
        update_fields.append("default_model")
        # 클래스 기본값을 물려받던 문제(자기 모델을 명시하지 않은 것)들은
        # 새 모델로 다시 시도할 자격을 얻는다(#403 AC "모델을 바꾼 뒤 새
        # 시도는 새 모델로 채점된다") — 이전 모델이 거부됐던 것이든 아니든,
        # 값이 실제로 바뀌었으면 그 문제들의 "거부됨" 표시는 더 이상 지금
        # 값을 설명하지 않는다.
        class_obj.problems.filter(model="").update(scoring_model_rejected_at=None)
    if payload.default_reasoning_effort is not None:
        class_obj.default_reasoning_effort = payload.default_reasoning_effort
        update_fields.append("default_reasoning_effort")
    if payload.token_budget is not None and payload.token_budget != class_obj.token_budget:
        class_obj.token_budget = payload.token_budget
        update_fields.append("token_budget")
        if class_obj.token_budget_warning_sent_at is not None:
            # 예산 값을 바꾸는 것을 새 주기의 시작으로 본다(#295) — 그러지
            # 않으면 한 번 경고한 뒤로는 예산을 아무리 늘려도 다시는 경고가
            # 가지 않는다.
            class_obj.token_budget_warning_sent_at = None
            update_fields.append("token_budget_warning_sent_at")
    if payload.token_budget_warning_threshold_percent is not None:
        class_obj.token_budget_warning_threshold_percent = payload.token_budget_warning_threshold_percent
        update_fields.append("token_budget_warning_threshold_percent")
    if update_fields:
        class_obj.save(update_fields=update_fields)
    return class_obj


def regenerate_join_link(class_obj: Class) -> Class:
    """새 코드로 덮어쓴다(#279) — 이전 코드는 그 순간부터 어떤 클래스도 가리키지 않는다."""

    class_obj.join_code = _generate_join_code()
    class_obj.save(update_fields=["join_code"])
    return class_obj


def archive_class(class_obj: Class) -> Class:
    """이미 보관된 클래스를 다시 보관해도 오류를 내지 않는다(멱등, #294)."""

    if class_obj.archived_at is None:
        class_obj.archived_at = timezone.now()
        class_obj.save(update_fields=["archived_at"])
    return class_obj


def unarchive_class(class_obj: Class) -> Class:
    """`archived_at` 을 지우면 그대로 진행중이다 — 보관 이력을 따로 남기지 않는다(#294)."""

    if class_obj.archived_at is not None:
        class_obj.archived_at = None
        class_obj.save(update_fields=["archived_at"])
    return class_obj


# --- 템플릿 가져오기 ------------------------------------------------------------


def visible_problem_template_or_404(share_code: str) -> ProblemTemplate:
    """내려진 템플릿은 링크로도 열리지 않는다(#320 AC) — 가져오기·신고처럼
    「내려진 뒤에는 누구도 상호작용할 수 없다」가 성립해야 하는 자리가 쓴다."""

    try:
        return ProblemTemplate.objects.prefetch_related("checklist_items").get(
            share_code=share_code, taken_down_at__isnull=True
        )
    except ProblemTemplate.DoesNotExist as exc:
        raise HttpError(404, TEMPLATE_GONE_MESSAGE) from exc


def visible_class_template_or_404(share_code: str) -> ClassTemplate:
    """`visible_problem_template_or_404` 와 같은 이유."""

    try:
        return ClassTemplate.objects.prefetch_related("problems__checklist_items").get(
            share_code=share_code, taken_down_at__isnull=True
        )
    except ClassTemplate.DoesNotExist as exc:
        raise HttpError(404, TEMPLATE_GONE_MESSAGE) from exc


def import_class_template_as(share_code: str, instructor_id: int, payload: ImportClassTemplateIn) -> Class:
    """클래스 템플릿을 새 클래스로 가져온다(#319) — 이름은 가져가는 사람이 정한다.
    새 클래스를 만드는 일이라 열 범위가 없다(`create_class` 와 같은 이유)."""

    # 가져가는 사람이 새로 붙이는 클래스 이름이다 — `ClassIn.name`과
    # 같은 필드(빠뜨렸던 것을 #480 구조 검사가 잡았다), 같은 규칙을 쓴다.
    reject_banned_public_text(payload.name, "클래스 이름")
    template = visible_class_template_or_404(share_code)
    return import_class_template(template, instructor_id=instructor_id, name=payload.name)
