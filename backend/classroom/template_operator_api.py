"""신고된 문제 템플릿을 운영자가 확인하고 내린다 (#320, #312).

미리 심사하지 않고 바로 공개하되(#316) 신고로 내릴 수 있게 한다 — 사람이
판단하는 행위는 운영자 API로만 한다(`CLAUDE.md` 「운영」, Django admin은
쓰지 않는다).

**「내림」과 「기각」 둘 다 감사 기록이 남는다**(`ProblemTemplateModerationDecision`
docstring) — `appeals.api`의 `rule_appeal`과 같은 규율이다.

**대기열의 정의.** 신고가 있고(taken_down_at이 비어 있고) 아직 그 신고 이후의
판단이 없는 템플릿만 나온다 — 판단 뒤에 새 신고가 다시 오면 그 템플릿은 다시
대기열에 뜬다(재신고가 새 사건이라는 뜻). `resolved_at` 같은 별도 필드 없이
"최신 신고 시각 vs 최신 판단 시각"만으로 계산한다 — 이 판단은 `services.
pending_reported_templates`가 진다.
"""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from core.operator_auth import OperatorAuth

from .models import ProblemTemplate, ProblemTemplateModerationDecision
from .schemas import (
    ErrorOut,
    ModerationDecisionIn,
    ProblemTemplateChecklistItemOut,
    ProblemTemplateOut,
    ReportedTemplateOut,
)
from .services import pending_reported_templates

operator_router = Router(tags=["operator", "classroom", "templates"], auth=OperatorAuth())


def _serialize_reported(template: ProblemTemplate) -> ReportedTemplateOut:
    reports = list(template.reports.all())
    return ReportedTemplateOut(
        id=template.id,
        title=template.title,
        description=template.description,
        submission_formats=template.submission_formats,
        publisher_display_name=template.publisher_display_name,
        report_count=len(reports),
        report_reasons=[r.reason for r in reports],
        taken_down=template.taken_down_at is not None,
    )


def _serialize_template(template: ProblemTemplate) -> ProblemTemplateOut:
    return ProblemTemplateOut(
        id=template.id,
        share_code=template.share_code,
        title=template.title,
        description=template.description,
        submission_formats=template.submission_formats,
        grading_strictness=template.grading_strictness,
        grading_guideline_text=template.grading_guideline_text,
        syntax_check_enabled=template.syntax_check_enabled,
        publisher_display_name=template.publisher_display_name,
        created_at=template.created_at,
        taken_down=template.taken_down_at is not None,
        checklist_items=[
            ProblemTemplateChecklistItemOut(label=i.label, required=i.required, order=i.order)
            for i in template.checklist_items.all()
        ],
    )


@operator_router.get("/classroom/problem-templates/reported", response=list[ReportedTemplateOut])
def list_reported_templates(request):
    """운영자가 확인할 신고 큐(#320 AC "내용·신고 사유·신고 수를 본다")."""

    templates = pending_reported_templates()
    return [_serialize_reported(t) for t in templates]


@operator_router.post(
    "/classroom/problem-templates/{template_id}/moderate",
    response={200: ProblemTemplateOut, 404: ErrorOut, 422: ErrorOut},
)
def moderate_template(request, template_id: int, payload: ModerationDecisionIn):
    """운영자가 내리거나(「takedown」) 신고를 기각한다(「dismiss」). 둘 다
    이유를 반드시 남긴다 — 판단이면 누가·언제·왜가 남아야 한다(AC)."""

    if payload.decision not in (
        ProblemTemplateModerationDecision.Decision.TAKEDOWN,
        ProblemTemplateModerationDecision.Decision.DISMISS,
    ):
        raise HttpError(422, "decision은 takedown 또는 dismiss여야 합니다.")

    if not payload.note.strip():
        raise HttpError(422, "판단 이유(note)를 남겨야 합니다.")

    with transaction.atomic():
        # 행을 잠근 뒤 다시 읽는다 — 동시에 들어온 두 판단 요청이 서로 다른
        # `taken_down_at` 판단(하나는 "아직 안 내려갔다", 하나는 "이미
        # 내려갔다")을 갖고 경합하는 것을 막는다. 판단 기록 자체는 매번
        # 남긴다 — 기각도 판단이고, 이미 내려간 템플릿에 또 「내림」이
        # 온 것도 그 나름의 사실(운영자가 다시 확인했다)이라 지우지 않는다.
        try:
            template = (
                ProblemTemplate.objects.select_for_update()
                .prefetch_related("reports", "checklist_items")
                .get(id=template_id)
            )
        except ProblemTemplate.DoesNotExist as exc:
            raise HttpError(404, "템플릿을 찾을 수 없습니다.") from exc

        ProblemTemplateModerationDecision.objects.create(
            template=template,
            decided_by=request.auth,
            decision=payload.decision,
            note=payload.note,
            decided_at=timezone.now(),
        )
        if (
            payload.decision == ProblemTemplateModerationDecision.Decision.TAKEDOWN
            and template.taken_down_at is None
        ):
            template.taken_down_at = timezone.now()
            template.save(update_fields=["taken_down_at"])

    return 200, _serialize_template(template)
