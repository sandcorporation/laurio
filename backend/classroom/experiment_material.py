"""채점 방식 실험의 재료 사본 — 강의실 몫(#1262).

- `collect`: 운영의 강의실 제출을 가명 사본 항목으로 읽는다. **읽기만 한다** — 저장소 고정 커밋을 박지 않고(이미 채점된
  제출만 받는다), 채점·시도 기록도 남기지 않는다. 담는 것과 담지 않는 것은 `core.experiment_material`.
- `experiment_call`: 사본 항목 하나를 강의실 운영 채점과 같은 프롬프트(`_build_prompt`)·한 번 호출로 채점한다 — 실험 줄
  `classroom_call:<모델>`. DB 를 읽지 않는다(저장하지 않은 모델 객체에 사본 값을 싣는다).
"""

from __future__ import annotations

from collections.abc import Sequence

from core import evidence_check
from core.experiment_material import (
    ChecklistEntry,
    ClassroomCallResult,
    Item,
    MaterialError,
    ProblemText,
    ProductionVerdict,
    pseudonym,
)
from core.llm_scoring import ScoringInput, SourceFile
from core.repository_adapters import GitHubAdapterError, get_github_adapter
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset

from .current_score import current_score, with_current_score
from .models import Class, ChecklistGrade, ChecklistItem, ClassroomSubmission, Problem
from .scoring import (
    ANTHROPIC_SCORING_ADAPTER,
    PreparedScoring,
    _build_prompt,
    _derive_rules,
    _Head,
    _machine_only,
    _numbered_source_text,
    _requirement_inputs,
    _scoring_adapter,
    _scoring_request,
    _scoring_source_files,
    _scoring_source_text,
    _confirmed_labels,
    _staged_plan,
    _two_step_plan,
    call_vendor_sync,
    outcome_reasoning,
)
from . import two_step
from .scoring_connection import anthropic_key_connection, openai_key_connection

from .syntax_check import SYNTAX_CHECK_ITEM_ID, run_syntax_check

#: 실제 벤더로 나갈 때의 OpenAI 어댑터 — 개발 환경의 강의실 어댑터 모드(fake)와 상관없이 이 실험 명령만 나간다.
OPENAI_SCORING_ADAPTER = "core.llm_scoring.OpenAIScoringAdapter"


def _source_bytes(asset: SubmissionAsset) -> bytes:
    if asset.kind == SubmissionAsset.Kind.SOURCE:
        raw = get_storage_adapter().read_object(asset.value)
        if raw is None:
            raise MaterialError("소스 오브젝트를 스토리지에서 찾을 수 없다")
        return raw
    if not asset.repository_commit_sha:
        raise MaterialError("저장소 제출에 고정 커밋이 없다 — 운영이 본 내용을 다시 받을 수 없다")
    try:
        return get_github_adapter().clone(asset.value, commit_sha=asset.repository_commit_sha).zip_bytes
    except GitHubAdapterError as exc:
        raise RepositoryUnreachable() from exc


class RepositoryUnreachable(MaterialError):
    """저장소·커밋·zip 을 GitHub 에서 받을 수 없다(지웠거나 비공개로 돌렸다)."""


def _verdicts(reasoning: object) -> tuple[ProductionVerdict, ...]:
    out = []
    for entry in reasoning if isinstance(reasoning, list) else []:
        if not isinstance(entry, dict):
            continue
        item_id, is_met = entry.get("checklist_item_id"), entry.get("is_met")
        if isinstance(item_id, int) and item_id != SYNTAX_CHECK_ITEM_ID and isinstance(is_met, bool):
            out.append(ProductionVerdict(item_id, is_met, str(entry.get("reasoning") or "")))
    return tuple(out)


NO_PINNED_COMMIT = "고정 커밋 없음"
REPOSITORY_UNREACHABLE = "저장소 닿지 않음"


def collect(submission_ids: Sequence[int], *, name: str) -> tuple[list[Item], dict[str, list[int]]]:
    """운영 채점이 끝난 강의실 제출들을 사본 항목으로. 없는 제출·채점 안 된 제출이 하나라도 있으면 아무것도 담지 않는다.

    소스를 꺼낼 수 없는 제출(고정 커밋 없음·저장소 닿지 않음)은 건너뛰고 까닭별 제출 번호를 함께 돌려준다.
    """

    submissions = {
        s.pk: s for s in with_current_score(ClassroomSubmission.objects.filter(pk__in=submission_ids).select_related("problem__classroom"))
    }
    missing = [sid for sid in submission_ids if sid not in submissions]
    if missing:
        raise MaterialError(f"강의실 제출이 없다: {', '.join(map(str, missing))}")
    scores = {
        sid: score
        for sid, submission in submissions.items()
        if (score := current_score(submission)) is not None
    }
    unscored = [sid for sid in submission_ids if sid not in scores]
    if unscored:
        raise MaterialError(f"운영 채점이 없는 제출: {', '.join(map(str, unscored))}")
    items = []
    skipped: dict[str, list[int]] = {}
    for sid in submission_ids:
        submission = submissions[sid]
        problem = submission.problem
        try:
            source = _source_bytes(submission.assets.get())
        except RepositoryUnreachable:
            skipped.setdefault(REPOSITORY_UNREACHABLE, []).append(sid)
            continue
        except MaterialError as exc:
            if "고정 커밋" not in str(exc):
                raise MaterialError(f"제출 {sid}: {exc}") from exc
            skipped.setdefault(NO_PINNED_COMMIT, []).append(sid)
            continue
        checklist = problem.checklist_items.exclude(grade=ChecklistGrade.BONUS)  # 운영 채점이 읽는 그대로(`_prepare_head`)
        score = scores[sid]
        items.append(
            Item(
                material_id=pseudonym(name, sid),
                asset_kind=submission.assets.get().kind,
                source=source,
                problem=ProblemText(
                    title=problem.title,
                    description=problem.description,
                    grading_strictness=problem.grading_strictness,
                    grading_guideline_text=problem.grading_guideline_text,
                    syntax_check_enabled=problem.syntax_check_enabled,
                    reasoning_effort=problem.effective_reasoning_effort(),
                    marked_reasoning=problem.effective_model_marked_reasoning(),
                ),
                checklist=tuple(
                    ChecklistEntry(
                        id=c.id, label=c.label, grade=c.grade, hidden=c.hidden, points=c.points, machine_rule=c.machine_rule
                    )
                    for c in checklist
                ),
                verdicts=_verdicts(score.reasoning),
                model_version=score.model_version,
            )
        )
    return items, skipped


def experiment_call(item: Item, *, model: str, api_key: str | None) -> ClassroomCallResult:
    """강의실 운영 채점(`prepare_tail` → `call_vendor_sync`)의 한 번 호출 갈래를 사본 위에서 그대로 — 프롬프트·소스 예산·
    문법 검사 항목·어댑터가 같다. 키만 강사 키가 아니라 실험 키다(`api_key`, None 이면 흉내 어댑터)."""

    problem = Problem(
        title=item.problem.title,
        description=item.problem.description,
        grading_strictness=item.problem.grading_strictness,
        grading_guideline_text=item.problem.grading_guideline_text,
        syntax_check_enabled=item.problem.syntax_check_enabled,
    )
    submission = ClassroomSubmission(problem=problem)
    checklist = [
        ChecklistItem(id=c.id, label=c.label, grade=c.grade, hidden=c.hidden, points=c.points) for c in item.checklist
    ]
    asset = SubmissionAsset(id=1, kind=item.asset_kind, label="")  # 운영 자산 id·라벨은 사본에 없다
    syntax_check = run_syntax_check(item.source, enabled=problem.syntax_check_enabled)
    instruction_bytes = len(
        _build_prompt(submission, checklist, "", asset_kind=asset.kind, syntax_check=syntax_check).encode("utf-8")
    )
    source_text, omission = _scoring_source_text(item.source, asset, model=model, instruction_bytes=instruction_bytes)
    if omission.any:
        return ClassroomCallResult("held", problem="소스가 모델 컨텍스트에 다 들어가지 않는다(운영이면 크기 초과 보류)")
    prompt = _build_prompt(submission, checklist, source_text, asset_kind=asset.kind, syntax_check=syntax_check)
    requirements = _requirement_inputs(checklist)
    synthetic = syntax_check.synthetic_requirement()
    if synthetic is not None:
        requirements = [*requirements, synthetic]
    anthropic = model.startswith("claude-")
    connection = (anthropic_key_connection if anthropic else openai_key_connection)(api_key or "")
    reasoning_effort = (
        item.problem.reasoning_effort
        if connection.sends_reasoning_effort(model, marked_reasoning=item.problem.marked_reasoning)
        else None
    )
    mode = "fake" if api_key is None else (ANTHROPIC_SCORING_ADAPTER if anthropic else OPENAI_SCORING_ADAPTER)
    adapter = _scoring_adapter(connection=connection, model=model, reasoning_effort=reasoning_effort, mode=mode)
    output = adapter.score(
        ScoringInput(
            submission_id=item.key,
            contest_id=0,
            prompt=prompt,
            source_files=[
                SourceFile(path=f"asset-{asset.id}", content=source_text, asset_id=asset.id, asset_label=asset.label),
                *syntax_check.extra_source_files(asset_id=asset.id, asset_label=asset.label),
            ],
            requirements=requirements,
        )
    )
    ids = {c.id for c in item.checklist}
    return ClassroomCallResult(
        "scored",
        verdicts=tuple(
            ProductionVerdict(v.requirement_id, v.is_met, v.reasoning) for v in output.verdicts if v.requirement_id in ids
        ),
        input_tokens=output.input_tokens,
        output_tokens=output.output_tokens,
        model_version=output.model_version,
        prompt=prompt,
    )


def experiment_staged_call(item: Item, *, model: str, api_key: str | None) -> ClassroomCallResult:
    """강의실 운영 채점의 staged 갈래(#1283~#1286)를 사본 위에서 그대로 — 기계 판정(강사 규칙)·줄 번호 인용·큰
    제출 두 걸음을 운영 설정 기본값대로 돈다. 같은 입력 재사용(#1287)은 끈다(사본에는 이전 점수가 없다). 도출(#1293)은
    사본에 도출 칸이 없어 칸마다 새로 한다(`_derive_rules`, 저장하지 않고 그 호출의 비용을 칸에 더한다)."""

    problem = Problem(
        id=0,
        title=item.problem.title,
        description=item.problem.description,
        grading_strictness=item.problem.grading_strictness,
        grading_guideline_text=item.problem.grading_guideline_text,
        syntax_check_enabled=item.problem.syntax_check_enabled,
    )
    submission = ClassroomSubmission(id=item.key, problem=problem)
    checklist = [
        ChecklistItem(id=c.id, label=c.label, grade=c.grade, hidden=c.hidden, points=c.points, machine_rule=c.machine_rule)
        for c in item.checklist
    ]
    asset = SubmissionAsset(id=1, kind=item.asset_kind, label="")
    anthropic = model.startswith("claude-")
    connection = (anthropic_key_connection if anthropic else openai_key_connection)(api_key or "")
    class_obj = Class(
        id=0,
        scoring_connection_kind=Class.ScoringConnectionKind.ANTHROPIC_KEY if anthropic else Class.ScoringConnectionKind.OPENAI_KEY,
    )
    head = _Head(
        submission=submission,
        owner="experiment",
        class_obj=class_obj,
        problem=problem,
        checklist_items=checklist,
        connection=connection,
        asset=asset,
        pause_recheck=False,
        staged=True,
        two_step_threshold=two_step.THRESHOLD_CHARS,
        two_step_budget=two_step.BUDGET_CHARS,
    )
    syntax_check = run_syntax_check(item.source, enabled=problem.syntax_check_enabled)
    mode = "fake" if api_key is None else (ANTHROPIC_SCORING_ADAPTER if anthropic else OPENAI_SCORING_ADAPTER)
    # 도출(#1293)은 사본에 도출 칸이 없어 칸마다 새로 한다 — 운영 채점이 prepare_tail 안에서 하는 것과 같다. 결과는 항목에 얹혀
    # `_staged_plan` 이 읽고, 저장은 하지 않는다. 그 호출의 토큰·비용도 이 칸에 더한다.
    derivation = _derive_rules(head, model, mode=mode)
    derive_usage: tuple[tuple[str, int, int], ...] = (
        ((derivation.model or model, derivation.input_tokens, derivation.output_tokens),)
        if derivation is not None and derivation.total_tokens
        else ()
    )
    # 운영과 같은 확정 규칙(#1294) — 충족만 기계가 정하고, 미충족·판정 불가는 「기계 확인: …」 메모를 달아 모델에게 넘긴다.
    split = _staged_plan(checklist, item.source)
    asked_items, machine_entries, machine_notes = split.asked_items, split.machine_entries, split.machine_notes
    confirmed = _confirmed_labels(checklist, machine_entries)
    machine_ids = tuple(e["checklist_item_id"] for e in machine_entries)
    if not asked_items and syntax_check.synthetic_requirement() is None:
        prepared = _machine_only(head, syntax_check=syntax_check, model=model, machine_entries=machine_entries)
        outcome = call_vendor_sync(prepared, reuse=False)
        assert outcome.output is not None
        return ClassroomCallResult(
            "scored",
            verdicts=_final_verdicts(outcome_reasoning(prepared, outcome.output), item),
            model_version=outcome.output.model_version,
            prompt=prepared.prompt,
            machine_ids=machine_ids,
            extra_usage=derive_usage,
        )
    instruction_bytes = len(
        _build_prompt(
            submission,
            asked_items,
            "",
            asset_kind=asset.kind,
            syntax_check=syntax_check,
            cite=True,
            machine_notes=machine_notes,
            machine_confirmed=confirmed,
        ).encode("utf-8")
    )
    sent_files, omission = _scoring_source_files(item.source, asset, model=model, instruction_bytes=instruction_bytes)
    plan = _two_step_plan(head, asked_items, item.source, sent_files, omission) if asked_items and head.two_step_threshold > 0 else None
    if omission.any and plan is None:
        return ClassroomCallResult("held", problem="소스가 모델 컨텍스트에 다 들어가지 않는다(운영이면 크기 초과 보류)")
    reasoning_effort = (
        item.problem.reasoning_effort
        if connection.sends_reasoning_effort(model, marked_reasoning=item.problem.marked_reasoning)
        else None
    )
    if plan is not None:
        prompt = plan.selection_prompt
        scoring_input = ScoringInput(
            submission_id=item.key,
            contest_id=0,
            prompt=prompt,
            source_files=list(plan.files),
            requirements=_requirement_inputs(asked_items),
            ask_citations=True,
        )
    else:
        prompt, scoring_input = _scoring_request(
            submission,
            asked_items,
            _numbered_source_text(sent_files),
            sent_files,
            asset_id=asset.id,
            asset_label=asset.label,
            asset_kind=asset.kind,
            syntax_check=syntax_check,
            staged=True,
            machine_notes=machine_notes,
            machine_confirmed=confirmed,
        )
    prepared = PreparedScoring(
        submission=submission,
        owner="experiment",
        class_obj=head.class_obj,
        problem=problem,
        checklist_items=checklist,
        connection=connection,
        model=model,
        reasoning_effort=reasoning_effort,
        prompt=prompt,
        scoring_input=scoring_input,
        syntax_check=syntax_check,
        pause_recheck=False,
        staged=True,
        machine_entries=machine_entries,
        machine_notes=machine_notes,
        sent_lines={} if plan is not None else {evidence_check.normalize_path(f.path): tuple(f.content.splitlines()) for f in sent_files},
        sent_files=() if plan is not None else tuple(sent_files),
        asset_kind=asset.kind,
        two_step=plan,
    )
    outcome = call_vendor_sync(prepared, reuse=False, mode=mode)
    if outcome.error is not None or outcome.output is None:
        return ClassroomCallResult("held", problem=str(outcome.error or "응답 없음"))
    scored = outcome.second_step or prepared
    output = outcome.output
    extra: list[tuple[str, int, int]] = list(derive_usage)
    input_tokens = output.input_tokens + (outcome.selection.input_tokens if outcome.selection else 0)
    output_tokens = output.output_tokens + (outcome.selection.output_tokens if outcome.selection else 0)
    return ClassroomCallResult(
        "scored",
        verdicts=_final_verdicts(outcome_reasoning(scored, output), item),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        model_version=output.model_version,
        prompt=scored.prompt,
        machine_ids=machine_ids,
        extra_usage=tuple(extra),
    )


def _final_verdicts(reasoning: list[dict], item: Item) -> tuple[ProductionVerdict, ...]:
    ids = {c.id for c in item.checklist}
    return tuple(
        ProductionVerdict(e["checklist_item_id"], bool(e["is_met"]), str(e.get("reasoning", "")))
        for e in reasoning
        if e["checklist_item_id"] in ids
    )
