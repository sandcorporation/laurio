"""강의실 채점 (#287, ADR-0006, ADR-0031, ADR-0037, ADR-0039).

**제출 즉시 비동기로 채점한다** — 마감이 없으니 "마감 직후 1회"(`scoring.
services`, ADR-0006)가 성립하지 않는다. 대신 스캔(`CLASSROOM_SUBMISSION_SCORING_SCAN`)이
매 tick마다 아직 `ClassroomScore`가 없는 시도를 찾아 채점한다 — Score가 시도당
정확히 하나만 생기고 다시 채점되지 않는다는 계약(ADR-0006)은 그대로다.

**강사 본인의 OpenAI 키로 돈다**(CONTEXT.md 「Class」) — 플랫폼의
`LLM_ADAPTER_MODE`/`OPEN_AI_API_KEY`(공모전이 쓰는 값)를 거치지 않는다.
`core.llm_scoring.get_adapter()`를 부르지 않고 `OpenAIScoringAdapter`를 매
채점마다 그 클래스의 복호화된 키로 직접 생성한다(#287이 그 클래스의 `api_key`
인자를 열었다). **키가 없는 클래스는 애초에 후보에 들지 않는다** — "시도했는데
실패했다"가 아니라 "아직 시도하지 않았다"이므로 `ClassroomScoringAttempt`를
남기지 않는다(`docs/features/classroom.md`의 "키가 없으면 채점되지 않는다").

**채점은 반드시 끝난다**(ADR-0031과 같은 규율, `SCORING_FAILURE_LIMIT`) —
강의실에는 마감이 없어 `scoring.services`의 "마감 후 6시간 유예"가 성립하지
않는다. 그래서 실패 **횟수**만 본다: 영구 실패(`LLMAdapterPermanentError`,
예를 들어 틀린 키의 401)는 유예 없이 즉시, 그 밖의 실패는 `SCORING_FAILURE_LIMIT`
회에 이르면 전체 미달(0%에 대응하는 "필수 항목 전부 미충족") `ClassroomScore`를
직접 만든다 — `submissions.scoring_basis.PLATFORM_FAILURE_MODEL_VERSION`을
그대로 재사용한다(공유층이라 강의실도 쓸 수 있다). 다만 참가자에게 보이는 문구는
직접 쓴다 — 그 모듈의 `participant_facing_reasoning()`은 "이의를 제기할 수
있다"고 말하는데 강의실에는 이의제기 자체가 없다(ADR-0037, 강의실은 Operator·
Appeal을 모른다).

**저장소(repository) 형식은 GitHub에서 직접 읽는다** — 공개가 아니거나 clone이
실패하면 소스와 같은 이유로 재시도 대상일 뿐이다(참가자 귀책·플랫폼 귀책을
가르지 않는다 — 강의실에는 그 구분이 쓰이는 이의제기 절차가 없다).
"""

from __future__ import annotations

import logging

from django.db import models, transaction
from django.db.models import Count

from core.crypto import decrypt
from core.llm_scoring import (
    LLMAdapterError,
    LLMAdapterPermanentError,
    OpenAIScoringAdapter,
    RequirementInput,
    ScoringInput,
)
from core.repository_adapters import GitHubAdapterError, get_github_adapter
from core.scans import ScanSpec
from core.source_selection import select_source_files
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION

from .models import ChecklistItem, ClassroomScore, ClassroomScoringAttempt, ClassroomSubmission
from .scoring_models import is_valid_model

logger = logging.getLogger(__name__)

#: ADR-0031과 같은 개념(`scoring.services.SCORING_FAILURE_LIMIT`) — 강의실에는
#: 마감이 없어 "마감 후 6시간 유예"가 성립하지 않으므로 횟수만 본다.
SCORING_FAILURE_LIMIT = 5

#: 강의실 참가자에게 자동 미달을 설명하는 문구 — `submissions.scoring_basis`의
#: 것을 그대로 쓰지 않는다(그쪽은 "이의를 제기할 수 있다"고 말하는데 강의실에는
#: 이의제기가 없다).
_PLATFORM_FAILURE_REASONING = (
    "채점이 반복적으로 실패해 플랫폼이 자동으로 미달 처리했습니다. AI가 이 "
    "시도를 채점하지 않았습니다 — 다시 제출해 새 시도를 만들어 보세요."
)


def _requirement_inputs(checklist_items: list[ChecklistItem]) -> list[RequirementInput]:
    """`core.llm_scoring.RequirementInput`을 재사용한다 — 필드 이름(`requirement_id`
    등)은 공모전 것이지만 형태만 빌린다. `self_reported_met`·`evidence`는 강의실에
    없는 개념이라 항상 빈 값이다(CONTEXT.md 「Problem」 "근거 연결도 자가 체크도
    없다") — 실제로 프롬프트에 실리는 것은 `_build_prompt`가 별도로 쓴다."""

    return [
        RequirementInput(
            requirement_id=item.id,
            text=item.label,
            grade="필수" if item.required else "선택",
            self_reported_met=False,
            evidence=[],
        )
        for item in checklist_items
    ]


def _build_prompt(submission: ClassroomSubmission, checklist_items: list[ChecklistItem], source_text: str) -> str:
    problem = submission.problem
    lines = [
        f"문제 제목: {problem.title}",
    ]
    if problem.description:
        lines.append(f"문제 설명: {problem.description}")
    lines.append("")
    lines.append(
        "아래 체크리스트 항목마다 제출된 소스를 직접 읽고 충족 여부를 판정하세요. "
        "자가 응답이나 근거 링크는 없습니다 — 소스 자체가 유일한 근거입니다. "
        "모든 requirement_id에 대해 빠짐없이 판정을 반환해야 합니다."
    )
    lines.append("")
    lines.append("체크리스트:")
    for item in checklist_items:
        grade = "필수" if item.required else "선택"
        lines.append(f"- requirement_id={item.id} ({grade}): {item.label}")
    lines.append("")
    lines.append(f"제출 형식: {problem.submission_format}")
    lines.append("제출된 소스:")
    lines.append(source_text if source_text.strip() else "(제출된 소스에서 읽을 수 있는 텍스트가 없습니다)")
    return "\n".join(lines)


class _SourceNotReady(Exception):
    """소스를 아직 읽을 수 없다 — 실패가 아니라 "아직" 상태다(`scoring.services`의
    "source_not_found"와 같은 뜻). 재시도 대상이지 영구 실패가 아니다."""


def _source_text_for(submission: ClassroomSubmission, asset: SubmissionAsset) -> str:
    """LLM 프롬프트에 실을 소스 텍스트. 소스는 스토리지에서, 저장소는 GitHub에서
    직접 읽는다 — 둘 다 `core.source_selection.select_source_files`로 같은
    예산·선별 규율을 받는다(ADR-0027과 같은 정신, 저장소도 소스와 같은 취급)."""

    if asset.kind == SubmissionAsset.Kind.SOURCE:
        raw = get_storage_adapter().read_object(asset.value)
        if raw is None:
            raise _SourceNotReady("소스 오브젝트를 아직 스토리지에서 찾을 수 없다.")
    else:
        github = get_github_adapter()
        if not github.check_public(asset.value):
            raise _SourceNotReady("저장소가 공개가 아니거나 아직 확인되지 않았다.")
        raw = github.clone(asset.value).zip_bytes

    files = select_source_files([(asset.id, asset.label, raw)])
    return "\n\n".join(f"# {f.path}\n{f.content}" for f in files)


def _scoring_cap_reached(submission: ClassroomSubmission) -> bool:
    """`scoring.services._scoring_cap_reached`와 같은 판정이되 마감 유예가 없다
    (모듈 docstring)."""

    counts = submission.classroom_scoring_attempts.aggregate(
        total=Count("id"), permanent=Count("id", filter=models.Q(permanent=True))
    )
    if counts["permanent"]:
        return True
    return (counts["total"] or 0) >= SCORING_FAILURE_LIMIT


def _finalize_platform_failure(submission: ClassroomSubmission, checklist_items: list[ChecklistItem]) -> ClassroomScore:
    reasoning = [
        {"checklist_item_id": item.id, "is_met": False, "reasoning": _PLATFORM_FAILURE_REASONING}
        for item in checklist_items
    ]
    return ClassroomScore.objects.create(
        submission=submission,
        model_version=PLATFORM_FAILURE_MODEL_VERSION,
        prompt=_PLATFORM_FAILURE_REASONING,
        reasoning=reasoning,
    )


def score_classroom_submission_once(submission: ClassroomSubmission) -> dict:
    """이 시도를 정확히 한 번만 채점한다. 이미 `ClassroomScore`가 있으면 그대로
    돌아온다 — 재채점 코드 경로는 없다(ADR-0006).

    `scoring.services.score_submission_once`처럼 예외를 밖으로 던지지 않는다 —
    모든 실패는 `ClassroomScoringAttempt`에 남고 상태 문자열로 돌아온다."""

    if ClassroomScore.objects.filter(submission_id=submission.id).exists():
        return {"submission_id": submission.id, "status": "already_scored"}

    problem = submission.problem
    class_obj = problem.classroom
    checklist_items = list(problem.checklist_items.all())

    if _scoring_cap_reached(submission):
        score = _finalize_platform_failure(submission, checklist_items)
        return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}

    raw_key = (class_obj.openai_api_key_encrypted or "").strip()
    if not raw_key:
        # 후보 쿼리(CLASSROOM_SUBMISSION_SCORING_SCAN)가 이미 키 있는 클래스만
        # 고르지만, tick 사이에 강사가 키를 지웠을 수 있다 — 그 경합에서도 시도로
        # 남기지 않고 조용히 건너뛴다("아직 시도하지 않았다"는 사실은 그대로다).
        return {"submission_id": submission.id, "status": "no_key"}

    asset = submission.assets.get()

    try:
        source_text = _source_text_for(submission, asset)
    except _SourceNotReady as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc))
        return {"submission_id": submission.id, "status": "source_not_ready"}
    except GitHubAdapterError as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc)[:2000])
        return {"submission_id": submission.id, "status": "repository_unreachable"}

    model = problem.model or class_obj.default_model
    if not is_valid_model(model):
        # Problem.model·Class.default_model은 저장 시점에 검증되지만(classroom.api),
        # 채점 시점의 SCORING_MODEL_CHOICES가 그 사이 좁혀졌을 수 있다 — 재시도로
        # 나을 수 없는 설정 오류다.
        ClassroomScoringAttempt.objects.create(
            submission=submission, error=f"알 수 없는 채점 모델: {model!r}", permanent=True
        )
        if _scoring_cap_reached(submission):
            score = _finalize_platform_failure(submission, checklist_items)
            return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}
        return {"submission_id": submission.id, "status": "failed_permanently"}

    prompt = _build_prompt(submission, checklist_items, source_text)
    scoring_input = ScoringInput(
        submission_id=submission.id,
        # ScoringInput.contest_id는 공모전 전용 필드지만 core.llm_scoring이
        # 그 값을 실제로 읽지 않는다(어댑터는 prompt·requirements만 본다) —
        # 공유 dataclass를 건드리지 않으려고 problem.id로 채워 둔다.
        contest_id=problem.id,
        prompt=prompt,
        source_files=[],
        requirements=_requirement_inputs(checklist_items),
    )

    try:
        adapter = OpenAIScoringAdapter(api_key=decrypt(raw_key), model=model)
        output = adapter.score(scoring_input)
    except LLMAdapterPermanentError as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc)[:2000], permanent=True)
        if _scoring_cap_reached(submission):
            score = _finalize_platform_failure(submission, checklist_items)
            return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}
        return {"submission_id": submission.id, "status": "failed_permanently"}
    except LLMAdapterError as exc:
        ClassroomScoringAttempt.objects.create(submission=submission, error=str(exc)[:2000])
        if _scoring_cap_reached(submission):
            score = _finalize_platform_failure(submission, checklist_items)
            return {"submission_id": submission.id, "status": "cap_reached", "score_id": score.id}
        return {"submission_id": submission.id, "status": "failed"}

    reasoning = [
        {"checklist_item_id": v.requirement_id, "is_met": v.is_met, "reasoning": v.reasoning}
        for v in output.verdicts
    ]
    with transaction.atomic():
        score = ClassroomScore.objects.create(
            submission=submission,
            model_version=output.model_version,
            prompt=prompt,
            reasoning=reasoning,
        )
    return {"submission_id": submission.id, "status": "scored", "score_id": score.id}


def _pending_submissions(as_of, ctx):
    """아직 `ClassroomScore`가 없고, 그 클래스에 채점 키가 있는 시도(#287).

    키 없는 클래스의 시도는 애초에 후보가 아니다 — "아직 시도하지 않았다"를
    `ClassroomScoringAttempt` 이력 없이 유지한다(모듈 docstring). `scoring.
    services._pending_submissions`와 같은 이유로 시도 횟수 오름차순 정렬한다
    (한 번도 시도되지 않은 것이 재시도 중인 것보다 항상 앞선다, ADR-0031).
    """

    attempt_count = (
        ClassroomScoringAttempt.objects.filter(submission=models.OuterRef("pk"))
        .order_by()
        .values("submission")
        .annotate(count=Count("id"))
        .values("count")
    )

    return (
        ClassroomSubmission.objects.filter(
            classroom_score__isnull=True,
        )
        .exclude(problem__classroom__openai_api_key_encrypted="")
        .annotate(attempt_count=models.functions.Coalesce(models.Subquery(attempt_count), 0))
        .select_related("problem", "problem__classroom", "member")
    )


def _score_one(submission, as_of, ctx):
    try:
        return score_classroom_submission_once(submission)
    except Exception as exc:  # noqa: BLE001 - 한 행의 실패가 나머지 배치를 막으면 안 된다.
        logger.exception(
            "ClassroomSubmission(pk=%s) 채점 스캔 처리 중 예외, 다음 건으로 계속", submission.id
        )
        is_permanent = isinstance(exc, LLMAdapterPermanentError)
        ClassroomScoringAttempt.objects.create(
            submission=submission, error=f"{type(exc).__name__}: {exc}"[:2000], permanent=is_permanent
        )
        status = "failed_permanently" if is_permanent else "failed"
        return {"submission_id": submission.id, "status": status, "error": str(exc)}


CLASSROOM_SUBMISSION_SCORING_SCAN = ScanSpec(
    name="classroom-submission-scoring",
    candidates=_pending_submissions,
    handle_row=_score_one,
    order_by=("attempt_count", "id"),
)
