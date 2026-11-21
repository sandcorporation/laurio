"""운영자 점수 정정 API(#1180, 스펙 #1178) — 「플랫폼 오류 정정 채점」을 걸고, 공모전의 정정을 본다.

정정 채점 자체는 채점 앱(`scoring.corrections`)이 한다. 여기 있는 까닭은 「배분이 끝났는가」(`is_prize_settled`)가
배분 앱의 판정이고, 운영자가 그 답을 정정을 걸기 전에 봐야 하기 때문이다. 끝났으면 정정은 기록만 남고 순위·배분은
그대로다 — 이 API 는 그 사실을 `prize_settled` 로 내려 줄 뿐 막지 않는다.
"""

from __future__ import annotations

from django.db.models import Count, Q
from django.http import HttpRequest
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from certificates.models import Certificate
from contests.models import Contest, ContestSubmission
from core.operator_auth import OperatorAuth
from scoring.corrections import CorrectionReasonRequired, request_corrections
from scoring.models import Score, ScoreCorrection

from .services import is_prize_settled

operator_router = Router(tags=["operator", "score-corrections"], auth=OperatorAuth())


class ScoreCorrectionIn(Schema):
    reason: str = Field(..., max_length=4000)
    # 비우면 이 공모전에서 채점된 제출 전부.
    submission_ids: list[int] | None = None


class ScoreCorrectionOut(Schema):
    id: int
    submission_id: int
    status: str
    reason: str
    error: str
    operator_id: int
    created_at: str
    finished_at: str | None
    original_percentage: str
    original_model_version: str
    percentage: str | None
    model_version: str
    # 이 제출에 발급돼 취소되지 않은 상장 수 — 정정은 상장을 취소하지 않는다.
    certificates_issued: int


class SkippedCorrectionOut(Schema):
    submission_id: int
    reason: str


class ScoredSubmissionOut(Schema):
    """정정 대상으로 고를 수 있는 제출 — 처음 채점 점수 그대로(정정 판정은 아래 `corrections` 에 있다)."""

    submission_id: int
    participant: str
    original_percentage: str
    original_model_version: str


class ScoreCorrectionListOut(Schema):
    contest_id: int
    prize_settled: bool
    submissions: list[ScoredSubmissionOut]
    corrections: list[ScoreCorrectionOut]


class ScoreCorrectionRequestOut(Schema):
    contest_id: int
    prize_settled: bool
    corrections: list[ScoreCorrectionOut]
    skipped: list[SkippedCorrectionOut]


def _contest_or_404(contest_id: int) -> Contest:
    contest = Contest.objects.filter(pk=contest_id).first()
    if contest is None:
        raise HttpError(404, "공모전을 찾을 수 없습니다.")
    return contest


def _certificate_counts(submission_ids: list[int]) -> dict[int, int]:
    rows = (
        Certificate.objects.filter(submission_id__in=submission_ids, cancelled_at__isnull=True)
        .values("submission_id")
        .annotate(n=Count("id"))
    )
    return {row["submission_id"]: row["n"] for row in rows}


def _participant_name(user) -> str:
    profile = getattr(user, "developer_profile", None)
    return (profile.display_name if profile else "") or user.get_username()


def _scored_submissions(contest: Contest) -> list[ScoredSubmissionOut]:
    in_contest = ContestSubmission.objects.filter(contest=contest).values("pk")
    scores = (
        Score.objects.filter(submission_id__in=in_contest).select_related("submission__user__developer_profile").order_by("submission_id")
    )
    return [
        ScoredSubmissionOut(
            submission_id=s.submission_id,
            participant=_participant_name(s.submission.user),
            original_percentage=str(s.percentage),
            original_model_version=s.model_version,
        )
        for s in scores
    ]


def _serialize(corrections: list[ScoreCorrection]) -> list[ScoreCorrectionOut]:
    counts = _certificate_counts([c.score.submission_id for c in corrections])
    return [
        ScoreCorrectionOut(
            id=c.id,
            submission_id=c.score.submission_id,
            status=c.status,
            reason=c.reason,
            error=c.error,
            operator_id=c.operator_id,
            created_at=c.created_at.isoformat(),
            finished_at=c.finished_at.isoformat() if c.finished_at else None,
            original_percentage=str(c.score.percentage),
            original_model_version=c.score.model_version,
            percentage=None if c.percentage is None else str(c.percentage),
            model_version=c.model_version,
            certificates_issued=counts.get(c.score.submission_id, 0),
        )
        for c in corrections
    ]


@operator_router.post(
    "/contests/{contest_id}/score-corrections", response={201: ScoreCorrectionRequestOut}
)
def request_score_corrections(request: HttpRequest, contest_id: int, payload: ScoreCorrectionIn):
    contest = _contest_or_404(contest_id)
    submissions = ContestSubmission.objects.filter(contest=contest)
    if payload.submission_ids is None:
        submissions = submissions.filter(score__isnull=False)
    else:
        submissions = submissions.filter(pk__in=payload.submission_ids)
        outside = sorted(set(payload.submission_ids) - set(submissions.values_list("pk", flat=True)))
        if outside:
            raise HttpError(422, f"이 공모전의 제출이 아닙니다: {outside}")
    try:
        result = request_corrections(submissions.order_by("pk"), operator=request.auth, reason=payload.reason)
    except CorrectionReasonRequired as exc:
        raise HttpError(422, str(exc)) from exc
    return 201, ScoreCorrectionRequestOut(
        contest_id=contest.id,
        prize_settled=is_prize_settled(contest),
        corrections=_serialize(result.created),
        skipped=[SkippedCorrectionOut(submission_id=sid, reason=why) for sid, why in result.skipped],
    )


@operator_router.get("/contests/{contest_id}/score-corrections", response=ScoreCorrectionListOut)
def list_score_corrections(request: HttpRequest, contest_id: int):
    contest = _contest_or_404(contest_id)
    in_contest = ContestSubmission.objects.filter(contest=contest).values("pk")
    corrections = list(
        ScoreCorrection.objects.filter(Q(score__submission_id__in=in_contest)).select_related("score").order_by("-id")
    )
    return ScoreCorrectionListOut(
        contest_id=contest.id,
        prize_settled=is_prize_settled(contest),
        submissions=_scored_submissions(contest),
        corrections=_serialize(corrections),
    )
