"""정정 채점 — 운영자가 건 「플랫폼 오류 정정」을 처음 커밋으로 다시 채점해 정정 행을 채운다(#1180, 스펙 #1178).

**거는 것과 도는 것이 따로다.** `request_corrections` 는 「진행 중」 정정 행만 만든다 — 그 행이 곧 큐의 한 칸이고,
`score-correction` 스캔(beat, 워커 안)이 집어 판정을 채운다. 워커가 죽어도 행이 「진행 중」으로 남아 다음 실행이
다시 집는다.

**판정은 처음 채점과 같다**(`scoring.services._judge`) — 에이전트·한 번 호출의 동작을 바꾸지 않는다. 다른 것은 입력뿐이다:

- 저장소는 처음 채점 때 받은 커밋(`Score.scored_assets` 의 `commit_sha`, 없으면 그때의 `RepositorySnapshot`, 없으면
  고정 커밋)으로 받는다. 마감 뒤 기본 브랜치에 들어온 push 가 섞이지 않는다. 처음 커밋을 모르는 저장소는 싣지 않는다.
- 소스 자료는 참가자가 올린 것만 싣는다. 처음 채점이 저장소를 박제한 자료(`created_by_platform`)는 같은 저장소를
  두 번 싣게 되므로 뺀다. 박제본을 다시 만들지도 않는다.

보류(크기 초과·에이전트 조건 어긋남)와 오류는 정정을 「실패」로 넘기고 까닭을 `error` 에 남긴다 — 처음 채점의 시도 기록·
실패 상한에는 닿지 않는다. 벤더 계정 거절만 「진행 중」으로 두고 다음 실행에 미룬다(처음 채점의 #1052 와 같다).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from django.contrib.auth.models import AbstractBaseUser
from django.db import IntegrityError, transaction

from contests.models import ContestSubmission
from core.agent_scoring import AgentVendorRefused, note_scan_refusal, scan_refusal
from core.clock import Clock
from core.scans import ScanSpec
from policies.runtime_settings import contest_ai_scoring_enabled
from repositories.adapters import ClonedRepository, get_github_adapter
from repositories.models import RepositorySnapshot
from storage.adapters import get_storage_adapter
from submissions.models import SubmissionAsset

from .models import Score, ScoreCorrection
from .services import AGENT_JOB_MAX_SECONDS, CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS, _judge

logger = logging.getLogger(__name__)

#: 정정이 「끝」으로 확정된 뒤(커밋 뒤) 한 번씩 부르는 줄 — 「정정이 끝나면」 할 일(알림·완성도 다시 돌리기)은 여기에 걸고
#: `run_correction` 끝에 직접 넣지 않는다. 한 줄의 실패가 다른 줄과 정정 자체를 막지 않는다.
CORRECTION_DONE_HOOKS: list[Callable[[ScoreCorrection], None]] = []


def on_correction_done(hook: Callable[[ScoreCorrection], None]) -> Callable[[ScoreCorrection], None]:
    CORRECTION_DONE_HOOKS.append(hook)
    return hook


def _fire_correction_done(correction_id: int) -> None:
    correction = ScoreCorrection.objects.get(pk=correction_id)
    for hook in CORRECTION_DONE_HOOKS:
        try:
            hook(correction)
        except Exception:  # noqa: BLE001 - 후속 일 하나의 실패가 정정과 다른 후속 일을 되돌리면 안 된다.
            logger.exception("ScoreCorrection(pk=%s) 정정 완료 후속 %s 실패", correction_id, hook.__name__)

SKIP_NOT_SCORED = "not_scored"
SKIP_IN_PROGRESS = "in_progress"


class CorrectionReasonRequired(ValueError):
    """사유 없이 정정을 걸었다 — 정정 행이 감사 기록이라 사유가 빠지면 「왜」가 남지 않는다."""


class CorrectionInputUnavailable(Exception):
    """처음 채점의 입력을 그대로 다시 받을 수 없다 — 정정을 실패로 넘긴다."""


class _CorrectionHeld(Exception):
    """판정이 보류됐다 — 정정에는 사람이 풀 보류가 없으니 실패로 넘긴다."""


@dataclass
class CorrectionRequest:
    created: list[ScoreCorrection] = field(default_factory=list)
    # (submission_id, 까닭) — `SKIP_NOT_SCORED`(아직 Score 가 없다)·`SKIP_IN_PROGRESS`(이미 진행 중 정정이 있다).
    skipped: list[tuple[int, str]] = field(default_factory=list)


def request_corrections(
    submissions: Iterable[ContestSubmission], *, operator: AbstractBaseUser, reason: str
) -> CorrectionRequest:
    """제출마다 「진행 중」 정정 행을 하나 만든다 — 채점은 `score-correction` 스캔이 한다."""

    reason = (reason or "").strip()
    if not reason:
        raise CorrectionReasonRequired("정정 사유를 적어야 합니다.")
    result = CorrectionRequest()
    for submission in submissions:
        score = Score.objects.filter(submission_id=submission.pk).first()
        if score is None:
            result.skipped.append((submission.pk, SKIP_NOT_SCORED))
            continue
        try:
            with transaction.atomic():
                correction = ScoreCorrection.objects.create(score=score, reason=reason, operator=operator)
        except IntegrityError:
            # `score_correction_one_in_progress` — 앞서 건 정정이 아직 돈다.
            result.skipped.append((submission.pk, SKIP_IN_PROGRESS))
            continue
        result.created.append(correction)
    return result


def first_commit(score: Score, asset: SubmissionAsset) -> str | None:
    """이 저장소 자산을 처음 채점이 받은 커밋 — 모르면 None."""

    for entry in score.scored_assets or []:
        if entry.get("asset_id") == asset.id and entry.get("commit_sha"):
            return str(entry["commit_sha"])
    snapshot = RepositorySnapshot.objects.filter(asset=asset).order_by("cloned_at", "id").first()
    if snapshot is not None:
        return snapshot.commit_sha
    return asset.repository_commit_sha or None


def _fixed_inputs(
    score: Score, submission: ContestSubmission
) -> tuple[list[tuple[SubmissionAsset, bytes]], list[tuple[SubmissionAsset, ClonedRepository]]]:
    sources = list(
        submission.assets.filter(kind=SubmissionAsset.Kind.SOURCE, created_by_platform=False).order_by("order", "id")
    )
    repositories = list(submission.assets.filter(kind=SubmissionAsset.Kind.REPOSITORY).order_by("order", "id"))

    storage = get_storage_adapter()
    readable: list[tuple[SubmissionAsset, bytes]] = []
    for asset in sources:
        raw = storage.read_object(asset.value)
        if raw is None:
            raise CorrectionInputUnavailable(f"소스 자료(pk={asset.id})를 스토리지에서 찾을 수 없다")
        readable.append((asset, raw))

    cloned: list[tuple[SubmissionAsset, ClonedRepository]] = []
    pinned = [(asset, sha) for asset in repositories if (sha := first_commit(score, asset))]
    if pinned:
        github = get_github_adapter()
        for asset, sha in pinned:
            cloned.append((asset, github.clone(asset.value, commit_sha=sha)))
    unpinned = len(repositories) - len(pinned)
    if unpinned:
        logger.warning(
            "Submission(pk=%s) 정정 채점: 처음 커밋을 모르는 저장소 %s개는 싣지 않는다", submission.pk, unpinned
        )
    if not readable and not cloned:
        raise CorrectionInputUnavailable("처음 채점 때의 입력(소스 자료·처음 커밋)이 하나도 없다")
    return readable, cloned


def _hold_correction(submission: ContestSubmission, reason: str, *, size: bool) -> dict:
    raise _CorrectionHeld(reason)


def _fail(correction: ScoreCorrection, error: str) -> dict:
    correction.status = ScoreCorrection.Status.FAILED
    correction.error = error[:2000]
    correction.finished_at = Clock.now()
    correction.save()
    return {"correction_id": correction.id, "status": "failed", "error": correction.error}


def run_correction(correction: ScoreCorrection) -> dict:
    """정정 하나를 채점해 「끝」이나 「실패」로 넘긴다. 벤더 계정 거절(`AgentVendorRefused`)은 그대로 올린다."""

    score = correction.score
    submission = ContestSubmission.objects.select_related("contest").get(pk=score.submission_id)
    try:
        readable, cloned = _fixed_inputs(score, submission)
        judged = _judge(submission, readable, cloned, on_hold=_hold_correction)
    except AgentVendorRefused:
        raise
    except _CorrectionHeld as held:
        return _fail(correction, str(held))
    except Exception as exc:  # noqa: BLE001 - 정정 하나의 실패가 배치를 막지 않는다. 까닭은 행에 남는다.
        logger.exception("ScoreCorrection(pk=%s) 정정 채점 실패", correction.id)
        return _fail(correction, f"{type(exc).__name__}: {exc}")
    # `_judge` 는 보류면 `_hold_correction` 이 올린 예외로 끝나므로 여기 dict 는 오지 않는다.
    assert not isinstance(judged, dict)
    correction.percentage = judged.percentage
    correction.model_version = judged.model_version
    correction.prompt = judged.prompt
    correction.reasoning = judged.reasoning
    correction.scored_assets = judged.scored_assets
    correction.status = ScoreCorrection.Status.DONE
    correction.finished_at = Clock.now()
    correction.save()
    transaction.on_commit(lambda: _fire_correction_done(correction.id))
    return {"correction_id": correction.id, "status": "done", "percentage": str(judged.percentage)}


def _in_progress(as_of, ctx):
    return ScoreCorrection.objects.filter(status=ScoreCorrection.Status.IN_PROGRESS).select_related("score")


def _correct_one(correction: ScoreCorrection, as_of, ctx) -> dict:
    refused = scan_refusal(ctx)
    if refused is not None:
        return {"correction_id": correction.id, "status": "deferred", "error": refused}
    try:
        return run_correction(correction)
    except AgentVendorRefused as exc:
        note_scan_refusal(ctx, exc)
        logger.warning("ScoreCorrection(pk=%s) 정정 채점 미룸 — 벤더 계정 거절: %s", correction.id, exc.reason)
        return {"correction_id": correction.id, "status": "deferred", "error": exc.reason}


# 처음 채점 스캔(`SUBMISSION_SCORING_SCAN`)과 같은 틀이다 — 워커 안에서 돌고, 한도·잠금·스위치가 같다.
# 공모전 AI 채점 스위치가 꺼지면 정정도 「진행 중」으로 기다린다(벤더를 부르는 일이다).
SCORE_CORRECTION_SCAN = ScanSpec(
    name="score-correction",
    candidates=_in_progress,
    handle_row=_correct_one,
    time_budget_seconds=60.0,
    worker_time_limit_seconds=60.0 + max(CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS, AGENT_JOB_MAX_SECONDS) + 60.0,
    enabled=contest_ai_scoring_enabled,
    keep_scheduled_when_disabled=True,
)
