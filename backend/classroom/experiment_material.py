"""채점 방식 실험의 재료 사본 — 강의실 몫(#1262).

- `collect`: 운영의 강의실 제출을 가명 사본 항목으로 읽는다. **읽기만 한다** — 저장소 고정 커밋을 박지 않고(이미 채점된
  제출만 받는다), 채점·시도 기록도 남기지 않는다. 담는 것과 담지 않는 것은 `core.experiment_material`.
- `experiment_call`: 사본 항목 하나를 강의실 운영 채점과 같은 프롬프트(`_build_prompt`)·한 번 호출로 채점한다 — 실험 줄
  `classroom_call:<모델>`. DB 를 읽지 않는다(저장하지 않은 모델 객체에 사본 값을 싣는다).
"""

from __future__ import annotations

from collections.abc import Sequence

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

from .models import ChecklistGrade, ChecklistItem, ClassroomScore, ClassroomSubmission, Problem
from .scoring import (
    ANTHROPIC_SCORING_ADAPTER,
    _build_prompt,
    _requirement_inputs,
    _scoring_adapter,
    _scoring_source_text,
)
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
        s.pk: s for s in ClassroomSubmission.objects.filter(pk__in=submission_ids).select_related("problem__classroom")
    }
    missing = [sid for sid in submission_ids if sid not in submissions]
    if missing:
        raise MaterialError(f"강의실 제출이 없다: {', '.join(map(str, missing))}")
    scores = {s.submission_id: s for s in ClassroomScore.objects.filter(submission_id__in=submission_ids)}
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
                    ChecklistEntry(id=c.id, label=c.label, grade=c.grade, hidden=c.hidden, points=c.points)
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
