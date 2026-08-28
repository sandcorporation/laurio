"""Handover API — 소스 접근 개방(자동) + 인수 확인 + 빌드 자산 + Escrow 해제 (#14).

접근 개방 자체는 이 앱이 엔드포인트로 만드는 게 아니다 — `submissions.resolvers`가
`awards.Award`의 존재만으로 판정하므로(ADR-0005), Award가 만들어지는 순간(이 앱이
`awards.api.award_submission`과 같은 트랜잭션에서 만드는 `Handover` 행과 함께) 이미
열려 있다. 이 라우터가 실제로 담당하는 것은 세 가지뿐이다:

- Sponsor의 인수 확인(`POST .../handover/accept`) — Escrow를 해제한다.
- Developer의 빌드 자산 업로드 기록(`POST /submissions/{id}/build-assets`).
- 내부 스캔(`POST /internal/handovers/release-due`) — 인수 확인이 없어도 정해진
  기간이 지나면 틱이 Escrow를 해제한다. `core.transitions`의 일반 상태 전이
  레지스트리를 쓰지 않는 이유: 그 메커니즘은 같은 행의 컬럼값만 바꿀 뿐이라
  (해제 시 반드시 필요한) 원장 분개 같은 부수효과를 걸 자리가 없다 — `scoring`이
  `run-pending`이라는 자신만의 내부 스캔 엔드포인트를 따로 둔 것과 같은 이유·
  같은 패턴이다.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from core.auth import InternalAuth
from core.clock import Clock
from submissions.models import Submission
from submissions.target_refs import build_asset_target_ref

from .models import BuildAsset, Handover
from .schemas import BuildAssetIn, BuildAssetOut, ErrorOut, HandoverOut, _BUILD_ASSET_KINDS
from .services import release_escrow

router = Router(tags=["handovers"])
internal_router = Router(tags=["internal", "handovers"], auth=InternalAuth())

# 한 스캔에서 시도하는 최대 Handover 수. scoring.services.BATCH_SIZE·
# core.transitions.DEFAULT_BATCH_SIZE와 같은 이유 — 무제한 스캔은 백로그가
# 쌓였을 때 이 요청 자체를 타임아웃으로 몰아넣는다. 이 스캔은 Escrow를
# 해제하므로 타임아웃 중간에 끊기는 게 장식적인 문제가 아니다 — 배치를 넘는
# 잔여분은 다음 틱이 마저 처리한다(ADR-0003이 이미 "스캔 주기만큼 늦어지는 건
# 무해하다"고 규정했다).
BATCH_SIZE = 50


def _serialize_handover(handover: Handover) -> HandoverOut:
    return HandoverOut(
        contest_id=handover.award.contest_id,
        award_id=handover.award_id,
        status=handover.status,
        release_deadline_at=handover.release_deadline_at,
        released_via=handover.released_via or None,
        released_at=handover.released_at,
    )


def _get_handover_for_contest(contest_id: int) -> Handover:
    try:
        return Handover.objects.select_related("award__contest__sponsor").get(
            award__contest_id=contest_id
        )
    except Handover.DoesNotExist as exc:
        raise HttpError(404, "이 Contest는 아직 Award되지 않아 Handover가 없습니다.") from exc


@router.get(
    "/contests/{contest_id}/handover", response={200: HandoverOut, 403: ErrorOut}, auth=jwt_auth
)
def get_handover(request: HttpRequest, contest_id: int):
    """Award된 Contest의 Handover 상태. Sponsor 본인과 Award된 Developer만 볼 수 있다."""

    handover = _get_handover_for_contest(contest_id)
    contest = handover.award.contest
    user_id = request.auth_user.id

    is_sponsor = contest.sponsor.user_id == user_id
    is_awarded_developer = handover.award.submission.developer.user_id == user_id
    if not (is_sponsor or is_awarded_developer):
        raise HttpError(403, "본인이 개최했거나 Award된 Contest의 Handover만 볼 수 있습니다.")

    return 200, _serialize_handover(handover)


@router.post(
    "/contests/{contest_id}/handover/accept",
    response={200: HandoverOut, 403: ErrorOut, 409: ErrorOut},
    auth=jwt_auth,
)
def accept_handover(request: HttpRequest, contest_id: int):
    """Sponsor가 인수를 확인해 Escrow를 해제한다.

    이미 해제되어 있어도(수동이든 타임아웃이든) 200으로 현재 상태를 그대로
    돌려준다 — 재전송·중복 클릭에 안전하다(payments.api.confirm_payment와 같은
    관용구).
    """

    handover = _get_handover_for_contest(contest_id)
    contest = handover.award.contest

    if contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest만 인수 확인할 수 있습니다.")

    handover = release_escrow(handover, released_via=Handover.ReleasedVia.SPONSOR_ACCEPTED)
    return 200, _serialize_handover(handover)


@internal_router.post("/release-due")
def release_due_handovers(request):
    """인수 확인 없이 release_deadline_at이 지난 Handover를 스캔해 Escrow를 해제한다.

    Sponsor의 침묵이 Developer를 인질로 잡지 못한다는 규율의 실제 구현이다(#14 AC).
    같은 시각에 두 번 불러도(워커가 겹쳐 돌아도) `release_escrow`의 조건부 UPDATE가
    각 Handover를 정확히 한 번만 해제한다.
    """

    as_of = Clock.now()
    due = (
        Handover.objects.filter(
            status=Handover.Status.PENDING_ACCEPTANCE, release_deadline_at__lte=as_of
        )
        .select_related("award__contest")
        .order_by("id")[:BATCH_SIZE]
    )

    released = []
    for handover in due:
        result = release_escrow(handover, released_via=Handover.ReleasedVia.TIMEOUT, now=as_of)
        if result.status == Handover.Status.RELEASED:
            released.append({"handover_id": result.id, "award_id": result.award_id})

    return {"as_of": as_of.isoformat(), "count": len(released), "released": released}


# --- 빌드 자산 ----------------------------------------------------------------


def _get_awarded_submission_or_404(submission_id: int) -> Submission:
    try:
        submission = Submission.objects.select_related(
            "contest__sponsor", "developer"
        ).get(id=submission_id)
    except Submission.DoesNotExist as exc:
        raise HttpError(404, "Submission을 찾을 수 없습니다.") from exc

    if not submission.awards.exists():
        raise HttpError(
            409, "Award된 Submission에만 빌드 자산을 올리거나 조회할 수 있습니다."
        )
    return submission


def _serialize_build_asset(asset: BuildAsset) -> BuildAssetOut:
    return BuildAssetOut(
        id=asset.id,
        submission_id=asset.submission_id,
        kind=asset.kind,
        object_key=asset.object_key,
        label=asset.label,
        created_at=asset.created_at,
    )


@router.post(
    "/submissions/{submission_id}/build-assets",
    response={201: BuildAssetOut, 403: ErrorOut, 409: ErrorOut, 422: ErrorOut},
    auth=jwt_auth,
)
def upload_build_asset(request: HttpRequest, submission_id: int, payload: BuildAssetIn):
    """Developer가 storage에 이미 업로드한 빌드 자산의 object_key를 기록한다.

    바이트 자체는 storage.api의 presigned 업로드가 이미 옮겼다 — 이 엔드포인트는
    submissions.api.create_submission과 같은 얇은 기록 계층이다. object_key가
    BUILD_ASSET_SLOT 네임스페이스 밖이면(다른 Submission·다른 슬롯의 파일을
    끌어다 붙이는 시도) 거부한다.
    """

    submission = _get_awarded_submission_or_404(submission_id)

    if submission.developer.user_id != request.auth_user.id:
        raise HttpError(403, "본인의 Submission에만 빌드 자산을 올릴 수 있습니다.")

    if payload.kind not in _BUILD_ASSET_KINDS:
        raise HttpError(422, f"알 수 없는 빌드 자산 종류입니다: {payload.kind}")

    expected_ref = build_asset_target_ref(submission.contest_id, request.auth_user.id)
    if not payload.object_key.startswith(f"{expected_ref}/"):
        raise HttpError(422, "object_key가 본인의 빌드 자산 업로드 대상에 속하지 않습니다.")

    asset = BuildAsset.objects.create(
        submission=submission,
        kind=payload.kind,
        object_key=payload.object_key,
        label=payload.label,
    )
    return 201, _serialize_build_asset(asset)


@router.get(
    "/submissions/{submission_id}/build-assets",
    response={200: list[BuildAssetOut], 403: ErrorOut},
    auth=jwt_auth,
)
def list_build_assets(request: HttpRequest, submission_id: int):
    """Award된 Submission의 빌드 자산 목록. 소유 Developer와 그 Contest의 Sponsor만."""

    submission = _get_awarded_submission_or_404(submission_id)
    user_id = request.auth_user.id

    is_owner = submission.developer.user_id == user_id
    is_sponsor = submission.contest.sponsor.user_id == user_id
    if not (is_owner or is_sponsor):
        raise HttpError(403, "본인의 Submission이거나 본인이 개최한 Contest여야 합니다.")

    assets = submission.build_assets.all()
    return 200, [_serialize_build_asset(a) for a in assets]
