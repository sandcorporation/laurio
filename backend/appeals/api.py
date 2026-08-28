"""Appeal API (#21, ADR-0004, ADR-0006).

- `POST /submissions/{submission_id}/appeal` — Developer 본인이 자신의 Score에
  이의를 제기한다. Score가 아직 없으면(채점 전) 거부한다 — 이의는 판정이 이미
  나온 것에 대한 것이다.
- `GET /submissions/{submission_id}/appeal` — Developer 본인이 자신의 이의제기
  상태·심판 결과를 조회한다.
- `GET /internal/appeals`, `GET /internal/appeals/{appeal_id}` — 운영자 조회
  진입점. `scoring.api`의 `/internal/scoring/incomplete-contests`와 같은 구조로
  `InternalAuth`를 쓴다 — 이 코드베이스에는 아직 별도의 "운영자" 사용자 인증이
  없고, 사람이 아닌 인프라가 아니라 사람(운영자)이 직접 호출하더라도 지금까지의
  관용구를 그대로 따른다.
- `POST /internal/appeals/{appeal_id}/rule` — 운영자가 인용/기각을 심판한다.
  인용하면 정정 분개가 추가된다. **재채점을 하지 않는다** — 이 라우터도,
  `appeals.services`도 `scoring` 앱을 import하지 않는다.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from core.auth import InternalAuth
from submissions.models import Submission

from .models import Appeal
from .schemas import (
    AppealCreateIn,
    AppealDetailOut,
    AppealOut,
    AppealRulingIn,
    ErrorOut,
    ScoreSnapshotOut,
)
from .services import reject_appeal, uphold_appeal

router = Router(tags=["appeals"])
internal_router = Router(tags=["internal", "appeals"], auth=InternalAuth())


def _serialize(appeal: Appeal) -> AppealOut:
    return AppealOut(
        id=appeal.id,
        submission_id=appeal.submission_id,
        reason=appeal.reason,
        status=appeal.status,
        ruling_note=appeal.ruling_note,
        correction_amount=appeal.correction_amount,
        ruled_at=appeal.ruled_at,
        created_at=appeal.created_at,
    )


def _get_owned_submission(request: HttpRequest, submission_id: int) -> Submission:
    try:
        submission = Submission.objects.select_related("developer", "contest").get(
            id=submission_id
        )
    except Submission.DoesNotExist as exc:
        raise HttpError(404, "Submission을 찾을 수 없습니다.") from exc

    if submission.developer.user_id != request.auth_user.id:
        raise HttpError(403, "본인의 Submission에만 접근할 수 있습니다.")
    return submission


@router.post(
    "/submissions/{submission_id}/appeal",
    response={201: AppealOut, 403: ErrorOut, 404: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def create_appeal(request: HttpRequest, submission_id: int, payload: AppealCreateIn):
    submission = _get_owned_submission(request, submission_id)

    if not hasattr(submission, "score"):
        raise HttpError(409, "아직 채점되지 않은 Submission은 이의제기할 수 없습니다.")

    if Appeal.objects.filter(submission=submission).exists():
        raise HttpError(409, "이미 이 Submission에 대한 이의제기가 접수되어 있습니다.")

    appeal = Appeal.objects.create(submission=submission, reason=payload.reason)
    return 201, _serialize(appeal)


@router.get(
    "/submissions/{submission_id}/appeal",
    response={200: AppealOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_own_appeal(request: HttpRequest, submission_id: int):
    submission = _get_owned_submission(request, submission_id)

    try:
        appeal = Appeal.objects.get(submission=submission)
    except Appeal.DoesNotExist as exc:
        raise HttpError(404, "이 Submission에 대한 이의제기가 없습니다.") from exc

    return 200, _serialize(appeal)


def _get_appeal_or_404(appeal_id: int) -> Appeal:
    try:
        return Appeal.objects.select_related("submission__score", "submission__contest").get(
            id=appeal_id
        )
    except Appeal.DoesNotExist as exc:
        raise HttpError(404, "이의제기를 찾을 수 없습니다.") from exc


def _serialize_detail(appeal: Appeal) -> AppealDetailOut:
    score = appeal.submission.score
    return AppealDetailOut(
        id=appeal.id,
        submission_id=appeal.submission_id,
        reason=appeal.reason,
        status=appeal.status,
        ruling_note=appeal.ruling_note,
        correction_amount=appeal.correction_amount,
        ruled_at=appeal.ruled_at,
        created_at=appeal.created_at,
        score=ScoreSnapshotOut(
            percentage=str(score.percentage),
            model_version=score.model_version,
            prompt=score.prompt,
            reasoning=score.reasoning,
            created_at=score.created_at,
        ),
    )


@internal_router.get("/appeals", response=list[AppealOut])
def list_appeals(request, status: str | None = None):
    """운영자가 검토할 이의제기 목록. `status` 쿼리로 pending/upheld/rejected를
    거를 수 있다(기본은 전체).
    """

    qs = Appeal.objects.all()
    if status:
        qs = qs.filter(status=status)
    return [_serialize(a) for a in qs]


@internal_router.get(
    "/appeals/{appeal_id}", response={200: AppealDetailOut, 404: ErrorOut}
)
def get_appeal_detail(request, appeal_id: int):
    """운영자가 Score 스냅샷(점수·근거·프롬프트·모델버전)과 함께 이의를 조회한다
    (#21 AC)."""

    appeal = _get_appeal_or_404(appeal_id)
    return 200, _serialize_detail(appeal)


@internal_router.post(
    "/appeals/{appeal_id}/rule",
    response={200: AppealOut, 404: ErrorOut, 409: ErrorOut, 422: ErrorOut},
)
def rule_appeal(request, appeal_id: int, payload: AppealRulingIn):
    """운영자가 이의를 인용하거나 기각한다.

    이미 심판이 끝난 이의제기를 다시 심판하려 하면 409 — 정정 분개가 두 번 남는
    사고를 API 레벨에서도 막는다(`appeals.services`의 조건부 UPDATE가 최후의
    방어선이다).
    """

    appeal = _get_appeal_or_404(appeal_id)

    if appeal.status != Appeal.Status.PENDING:
        raise HttpError(409, "이미 심판이 끝난 이의제기입니다.")

    if payload.decision == "uphold":
        if not payload.correction_amount:
            raise HttpError(422, "인용하려면 correction_amount가 필요합니다.")
        appeal = uphold_appeal(
            appeal, correction_amount=payload.correction_amount, ruling_note=payload.ruling_note
        )
    elif payload.decision == "reject":
        appeal = reject_appeal(appeal, ruling_note=payload.ruling_note)
    else:
        raise HttpError(422, "decision은 uphold 또는 reject 여야 합니다.")

    return 200, _serialize(appeal)
