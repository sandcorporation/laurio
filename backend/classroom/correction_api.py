"""강의실 점수 정정 API(#1317) — 클래스 소유자(강사)가 건다. 비용은 그 클래스 키다.

- `POST /classroom/classes/{class_id}/score-corrections` — 시도 id 목록과 사유로 정정을 건다. 걸 수 있는 범위는
  `classroom.score_corrections.correctable` 이 정하고, 못 거는 시도는 까닭과 함께 `skipped` 로 돌려준다.
- `GET /classroom/classes/{class_id}/score-corrections` — 이 클래스에 걸린 정정(최신 먼저).

공동 강사·참여자·남의 클래스는 `instructor_scope.class_scope(owner=True)` 의 규율대로 막힌다(남의 클래스는 404).
"""

from __future__ import annotations

from datetime import datetime

from django.db.models import F
from django.http import HttpRequest
from ninja import Field, Router, Schema

from accounts.middleware import jwt_auth

from .instructor_scope import class_scope
from .models import ClassroomScoreCorrection, ClassroomSubmission
from .schemas import ErrorOut
from .score_corrections import CorrectionReasonRequired, request_corrections

router = Router(tags=["classroom", "score-corrections"])

#: 한 번에 거는 시도 수 상한 — 한 클래스의 한 문제 명단이 넉넉히 든다.
MAX_SUBMISSIONS_PER_REQUEST = 500


class ScoreCorrectionIn(Schema):
    submission_ids: list[int] = Field(min_length=1, max_length=MAX_SUBMISSIONS_PER_REQUEST)
    reason: str = Field(max_length=4000)


class ScoreCorrectionOut(Schema):
    id: int
    submission_id: int
    status: str
    reason: str
    error: str
    created_at: datetime
    finished_at: datetime | None


class SkippedOut(Schema):
    submission_id: int
    #: `not_scored`(아직 점수 없음)·`not_latest`(최근 시도가 아님)·`in_progress`(이미 진행 중).
    reason: str


class ScoreCorrectionRequestOut(Schema):
    corrections: list[ScoreCorrectionOut]
    skipped: list[SkippedOut]


class ScoreCorrectionListOut(Schema):
    corrections: list[ScoreCorrectionOut]


def _out(correction: ClassroomScoreCorrection, submission_id: int) -> ScoreCorrectionOut:
    return ScoreCorrectionOut(
        id=correction.id,
        submission_id=submission_id,
        status=correction.status,
        reason=correction.reason,
        error=correction.error,
        created_at=correction.created_at,
        finished_at=correction.finished_at,
    )


@router.post(
    "/classes/{class_id}/score-corrections",
    response={201: ScoreCorrectionRequestOut, 403: ErrorOut, 404: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def request_score_corrections(request: HttpRequest, class_id: int, payload: ScoreCorrectionIn):
    """정정을 건다 — 소유자만. 이 클래스의 시도가 아닌 id 가 섞이면 422(어느 것도 걸지 않는다)."""

    class_obj = class_scope(class_id, request.auth_user.id, write=True, owner=True).class_obj
    wanted = set(payload.submission_ids)
    submissions = list(
        ClassroomSubmission.objects.filter(id__in=wanted, problem__classroom=class_obj).select_related(
            "classroom_score"
        )
    )
    if len(submissions) != len(wanted):
        return 422, ErrorOut(detail="이 클래스의 제출이 아닌 것이 섞여 있습니다.")
    try:
        result = request_corrections(submissions, requested_by=request.auth_user, reason=payload.reason)
    except CorrectionReasonRequired:
        return 422, ErrorOut(detail="사유를 적어 주세요.")
    return 201, ScoreCorrectionRequestOut(
        corrections=[_out(c, c.score.submission_id) for c in result.corrections],
        skipped=[SkippedOut(submission_id=sid, reason=why) for sid, why in result.skipped],
    )


@router.get(
    "/classes/{class_id}/score-corrections",
    response={200: ScoreCorrectionListOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def list_score_corrections(request: HttpRequest, class_id: int):
    class_obj = class_scope(class_id, request.auth_user.id, write=False, owner=True).class_obj
    corrections = (
        ClassroomScoreCorrection.objects.filter(score__submission__problem__classroom=class_obj)
        .annotate(submission_id=F("score__submission_id"))
        .defer("prompt", "reasoning", "syntax_check_result")
        .order_by("-id")
    )
    return 200, ScoreCorrectionListOut(corrections=[_out(c, c.submission_id) for c in corrections])
