"""AI 채점 도메인 로직 (#12, ADR-0006, ADR-0014).

API 레이어(`scoring.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP다
(`CLAUDE.md`). 여기 함수를 테스트가 직접 부르지 않는다.

핵심 규율: `Score`는 Submission당 정확히 한 번만 만들어진다. 이미 있으면
`score_submission_once`는 아무 것도 하지 않고 돌아온다 — 재채점 코드 경로는
존재하지 않는다(ADR-0006). LLM 호출이 실패하면 `ScoringAttempt`에 이력만
남기고 Score를 만들지 않은 채 돌아오므로, 다음 스캔(`run_pending_scoring`)이
"아직 한 번도 성공하지 못한 첫 시도"를 자동으로 반복한다 — 이것이 이 프로젝트가
구현하는 "재시도"다. 별도의 재시도 카운터·백오프 스케줄이 없어도, 스캔이 반복되는
한 실패는 스스로 낫는다(ADR-0003과 같은 정신).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import IntegrityError, transaction

from contests.models import Contest, Requirement
from storage.adapters import get_storage_adapter
from submissions.models import RequirementResponse, Submission

from .adapters import (
    LLMAdapterError,
    RequirementInput,
    ScoringInput,
    get_adapter,
)
from .models import Score, ScoringAttempt
from .source_selection import select_source_files

# 한 스캔에서 시도하는 최대 Submission 수. core.transitions.DEFAULT_BATCH_SIZE와
# 같은 이유 — 무제한 스캔은 백로그가 쌓였을 때 요청 자체를 타임아웃으로 몰아넣는다.
BATCH_SIZE = 50


def _requirement_inputs(submission: Submission) -> list[RequirementInput]:
    requirements = list(
        Requirement.objects.filter(contest_id=submission.contest_id).order_by("order", "id")
    )
    responses = {
        r.requirement_id: r
        for r in RequirementResponse.objects.filter(submission=submission).prefetch_related(
            "evidence_items"
        )
    }

    inputs: list[RequirementInput] = []
    for requirement in requirements:
        response = responses.get(requirement.id)
        if response is None:
            inputs.append(
                RequirementInput(
                    requirement_id=requirement.id,
                    text=requirement.text,
                    grade=requirement.grade,
                    self_reported_met=False,
                    evidence=[],
                )
            )
            continue
        inputs.append(
            RequirementInput(
                requirement_id=requirement.id,
                text=requirement.text,
                grade=requirement.grade,
                self_reported_met=response.is_met,
                evidence=[
                    {"kind": e.kind, "value": e.value} for e in response.evidence_items.all()
                ],
            )
        )
    return inputs


def _build_prompt(*, contest: Contest, requirements: list[RequirementInput], source_files) -> str:
    lines = [
        "당신은 Laurio 공모전 제출물을 채점하는 심사 보조자입니다.",
        f"Contest: {contest.title}",
        "각 Requirement에 대해 (a) 연결된 Evidence가 주장을 뒷받침하는지, "
        "(b) 소스코드에 그 기능이 실재하는지를 함께 보고 충족 여부를 판단하세요. "
        "자가 응답은 참고용일 뿐 신뢰하지 마세요. Evidence가 없거나 소스에서 근거를 "
        "찾지 못하면 반드시 미달로 판정하세요.",
        "",
        "## Requirements",
    ]
    for r in requirements:
        lines.append(f"- [{r.grade}] #{r.requirement_id}: {r.text}")
        lines.append(f"  자가 응답(참고용): {'충족' if r.self_reported_met else '미충족'}")
        if r.evidence:
            for e in r.evidence:
                lines.append(f"  Evidence[{e['kind']}]: {e['value']}")
        else:
            lines.append("  Evidence: (없음)")
    lines.append("")
    lines.append("## Source (선별된 파일)")
    if source_files:
        for f in source_files:
            lines.append(f"### {f.path}")
            lines.append(f.content)
    else:
        lines.append("(선별된 소스 파일 없음)")
    return "\n".join(lines)


def _percentage(*, requirements: list[RequirementInput], verdicts) -> Decimal:
    verdict_by_id = {v.requirement_id: v for v in verdicts}
    required = [r for r in requirements if r.grade == Requirement.Grade.REQUIRED]
    if not required:
        return Decimal("0.00")
    met = sum(1 for r in required if verdict_by_id[r.requirement_id].is_met)
    raw = Decimal(met) / Decimal(len(required)) * Decimal(100)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def score_submission_once(submission: Submission) -> dict:
    """이 Submission을 정확히 한 번만 채점한다. 이미 Score가 있으면 그대로 돌아온다."""

    if Score.objects.filter(submission_id=submission.id).exists():
        return {"submission_id": submission.id, "status": "already_scored"}

    requirements = _requirement_inputs(submission)

    storage_adapter = get_storage_adapter()
    raw_source = storage_adapter.read_object(submission.source_object_key)
    source_files = select_source_files(raw_source) if raw_source else []

    contest = submission.contest
    prompt = _build_prompt(contest=contest, requirements=requirements, source_files=source_files)

    llm = get_adapter()
    scoring_input = ScoringInput(
        submission_id=submission.id,
        contest_id=contest.id,
        prompt=prompt,
        source_files=source_files,
        requirements=requirements,
    )

    try:
        output = llm.score(scoring_input)
    except LLMAdapterError as exc:
        ScoringAttempt.objects.create(submission=submission, error=str(exc))
        return {"submission_id": submission.id, "status": "failed", "error": str(exc)}

    percentage = _percentage(requirements=requirements, verdicts=output.verdicts)
    reasoning_payload = [
        {"requirement_id": v.requirement_id, "is_met": v.is_met, "reasoning": v.reasoning}
        for v in output.verdicts
    ]

    try:
        with transaction.atomic():
            Score.objects.create(
                submission=submission,
                percentage=percentage,
                model_version=output.model_version,
                prompt=prompt,
                reasoning=reasoning_payload,
            )
    except IntegrityError:
        # 동시에 다른 스캔이 먼저 이겼다 — unique(submission) 제약이 막아준다.
        # 이미 Score가 있으므로 여기서도 재채점하지 않는다(ADR-0006).
        return {"submission_id": submission.id, "status": "already_scored"}

    return {"submission_id": submission.id, "status": "scored", "percentage": str(percentage)}


def run_pending_scoring(as_of=None) -> list[dict]:
    """CLOSED Contest 중 아직 Score 없는 Submission을 스캔해 채점을 시도한다.

    마감 전이가 일어난 바로 다음 스캔에서 채점이 1회 시작된다(ADR-0006) — Contest가
    CLOSED로 전이되는 순간과 이 스캔이 도는 순간은 별개의 호출이지만(core의 틱과
    이 앱의 내부 엔드포인트, notifications.dispatch_due_notifications와 같은
    구조), 실제 배포에서는 둘 다 Celery beat가 짧은 주기로 반복 호출하므로 사실상
    "마감 직후"로 수렴한다.
    """

    pending = (
        Submission.objects.filter(contest__status=Contest.Status.CLOSED, score__isnull=True)
        .select_related("contest")
        .order_by("id")[:BATCH_SIZE]
    )
    return [score_submission_once(submission) for submission in pending]
