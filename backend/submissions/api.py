"""Submission API — 제출·수정·조회 (#10, ADR-0014, ADR-0005, ADR-0011).

핵심 규율:

- 전체 소스코드는 필수다. 없으면 422로 거부한다(플랫폼의 "강제하지 않고 신호한다"
  원칙에서 유일한 예외 — ADR-0014).
- `Verification`을 마치지 않았거나(또는 만 19세 미만이라 VERIFIED에 도달하지 못했거나)
  마감이 지났으면 제출·수정 모두 거부한다. "마감"은 Contest 상태 전이(#11)를 기다리지
  않고 `deadline_at`과 `core.clock.Clock.now()`를 직접 비교한다.
- Contest의 Sponsor와 같은 CI를 가진 사람은 제출할 수 없다(자전거래 차단).
- 소스는 어떤 API 응답에서도 소유자 본인 외에는 절대 나오지 않는다 — Award 이후
  Sponsor에게 여는 것(Handover)은 #13/#14 소관이라 여기 새 분기가 필요할 뿐, 지금은
  그 분기가 없다.
- 진행 중에는 다른 Developer의 Submission이 전혀 보이지 않는다. Sponsor는 데모·영상은
  볼 수 있지만 소스는 볼 수 없다. 마감 후에는 데모·영상이 전면 공개된다.

파일 자체는 이 API를 거치지 않는다 — presigned 업로드는 storage 앱이 이미 제공한다
(#6). 이 API는 storage가 발급한 object_key 문자열을 받아서 저장할 뿐이다. Evidence의
"스크린샷" 값도 마찬가지로 storage object_key를 담을 수 있는 불투명한 문자열이다.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from accounts.models import DeveloperProfile
from accounts.sanitize import sanitize_free_text
from contests.models import Contest, Requirement
from core.clock import Clock
from verification.models import Verification

from .models import Evidence, RequirementResponse, Submission
from .schemas import CompletionOut, EvidenceOut, RequirementResponseOut, SubmissionIn, SubmissionOut
from .target_refs import demo_video_target_ref, source_target_ref

router = Router(tags=["submissions"])

_EVIDENCE_KINDS = {choice for choice, _label in Evidence.Kind.choices}


# --- 가드 -------------------------------------------------------------------


def _require_verification(user) -> Verification:
    verification = Verification.objects.filter(user=user).first()
    if verification is None or not verification.is_verified:
        raise HttpError(
            403,
            "본인확인(Verification)을 완료해야 제출할 수 있습니다. "
            "휴대폰 본인확인을 먼저 마쳐주세요.",
        )
    return verification


def _get_published_contest_or_404(contest_id: int) -> Contest:
    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc
    if contest.status != Contest.Status.PUBLISHED:
        # draft Contest는 아직 결제가 끝나지 않아 공개되지 않았다 — 존재를
        # 드러내지 않는다(contests.api.get_contest와 같은 원칙).
        raise HttpError(404, "Contest를 찾을 수 없습니다.")
    return contest


def _reject_if_past_deadline(contest: Contest) -> None:
    if Clock.now() >= contest.deadline_at:
        raise HttpError(403, "마감 시각이 지나 제출하거나 수정할 수 없습니다.")


def _reject_self_dealing(contest: Contest, developer_verification: Verification) -> None:
    if not developer_verification.ci_hash:
        return
    sponsor_verification = Verification.objects.filter(
        user_id=contest.sponsor.user_id, status=Verification.Status.VERIFIED
    ).first()
    if sponsor_verification is None:
        return
    if sponsor_verification.ci_hash == developer_verification.ci_hash:
        raise HttpError(
            403, "이 Contest의 Sponsor와 동일인으로 확인되어 제출할 수 없습니다(자전거래 차단)."
        )


def _validate_object_key(
    object_key: str | None, *, expected_target_ref: str, field_name: str
) -> None:
    if not object_key:
        return
    if not object_key.startswith(f"{expected_target_ref}/"):
        raise HttpError(
            422, f"{field_name}가 본인의 업로드 대상(target_ref)에 속하지 않습니다."
        )


def _require_source_object_key(source_object_key: str, *, expected_target_ref: str) -> None:
    if not source_object_key or not source_object_key.strip():
        # ADR-0014: 전체 소스코드는 필수다. 이 항목만 "강제하지 않고 신호한다"는
        # 플랫폼 원칙의 예외다.
        raise HttpError(422, "전체 소스코드(source_object_key)는 필수입니다.")
    _validate_object_key(
        source_object_key, expected_target_ref=expected_target_ref, field_name="source_object_key"
    )


# --- 자가 응답 · Evidence -----------------------------------------------------


def _replace_requirement_responses(submission: Submission, contest: Contest, responses_in) -> None:
    valid_requirement_ids = set(
        Requirement.objects.filter(contest=contest).values_list("id", flat=True)
    )

    seen_ids: set[int] = set()
    for item in responses_in:
        if item.requirement_id in seen_ids:
            raise HttpError(422, "같은 Requirement에 대한 응답이 중복되었습니다.")
        seen_ids.add(item.requirement_id)
        if item.requirement_id not in valid_requirement_ids:
            raise HttpError(422, "이 Contest에 속하지 않은 Requirement입니다.")
        for evidence in item.evidence:
            if evidence.kind not in _EVIDENCE_KINDS:
                raise HttpError(422, f"알 수 없는 Evidence 종류입니다: {evidence.kind}")

    # 편집 UI가 매번 체크리스트 전체를 다시 제출하는 형태와 맞춘다 — 부분 갱신이
    # 아니라 이 Submission의 자가 응답 전체를 새로 쓴다.
    submission.requirement_responses.all().delete()
    for item in responses_in:
        response = RequirementResponse.objects.create(
            submission=submission,
            requirement_id=item.requirement_id,
            is_met=item.is_met,
            note=sanitize_free_text(item.note or ""),
        )
        Evidence.objects.bulk_create(
            [
                Evidence(response=response, kind=e.kind, value=sanitize_free_text(e.value))
                for e in item.evidence
            ]
        )


# --- 직렬화 -------------------------------------------------------------------


def _serialize(
    submission: Submission,
    *,
    contest: Contest,
    is_owner: bool,
    is_sponsor: bool,
    past_deadline: bool,
) -> SubmissionOut:
    requirements = list(Requirement.objects.filter(contest=contest).order_by("order", "id"))
    responses_by_requirement = {
        r.requirement_id: r
        for r in submission.requirement_responses.all().prefetch_related("evidence_items")
    }

    response_outs: list[RequirementResponseOut] = []
    linked_count = 0
    for requirement in requirements:
        response = responses_by_requirement.get(requirement.id)
        if response is None:
            response_outs.append(
                RequirementResponseOut(
                    requirement_id=requirement.id,
                    is_met=False,
                    note="",
                    evidence=[],
                    is_linked=False,
                )
            )
            continue

        evidence_items = list(response.evidence_items.all())
        is_linked = bool(evidence_items)
        if is_linked:
            linked_count += 1
        response_outs.append(
            RequirementResponseOut(
                requirement_id=requirement.id,
                is_met=response.is_met,
                note=response.note,
                evidence=[EvidenceOut(kind=e.kind, value=e.value) for e in evidence_items],
                is_linked=is_linked,
            )
        )

    total = len(requirements)
    completion = CompletionOut(
        has_demo_video=bool(submission.demo_video_object_key),
        has_demo_url=bool(submission.demo_url),
        has_test_account=bool(submission.test_account),
        total_requirement_count=total,
        linked_requirement_count=linked_count,
        unlinked_requirement_count=max(total - linked_count, 0),
    )

    # 소스는 소유자 본인 외에는 절대 나오지 않는다(ADR-0014) — Sponsor는 Award
    # 이후에만 열리는데, 그 개방은 #13/#14의 범위다. 데모·영상은 진행 중엔 본인·
    # Sponsor, 마감 후엔 전면 공개.
    show_source = is_owner
    show_demo = is_owner or is_sponsor or past_deadline

    return SubmissionOut(
        id=submission.id,
        contest_id=submission.contest_id,
        developer_id=submission.developer_id,
        is_owner=is_owner,
        source_object_key=submission.source_object_key if show_source else None,
        demo_video_object_key=(submission.demo_video_object_key or None) if show_demo else None,
        demo_url=(submission.demo_url or None) if show_demo else None,
        test_account=(submission.test_account or None) if show_demo else None,
        requirement_responses=response_outs,
        completion=completion,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
    )


# --- 엔드포인트 ---------------------------------------------------------------


@router.post(
    "/contests/{contest_id}/submissions", response={201: SubmissionOut}, auth=jwt_auth
)
def create_submission(request: HttpRequest, contest_id: int, payload: SubmissionIn):
    contest = _get_published_contest_or_404(contest_id)
    _reject_if_past_deadline(contest)

    verification = _require_verification(request.auth_user)
    _reject_self_dealing(contest, verification)

    developer, _created = DeveloperProfile.objects.get_or_create(user=request.auth_user)

    if Submission.objects.filter(contest=contest, developer=developer).exists():
        raise HttpError(
            409, "이미 이 Contest에 제출한 Submission이 있습니다. 수정은 PUT을 사용하세요."
        )

    expected_source_ref = source_target_ref(contest.id, request.auth_user.id)
    _require_source_object_key(payload.source_object_key, expected_target_ref=expected_source_ref)

    expected_demo_video_ref = demo_video_target_ref(contest.id, request.auth_user.id)
    _validate_object_key(
        payload.demo_video_object_key,
        expected_target_ref=expected_demo_video_ref,
        field_name="demo_video_object_key",
    )

    try:
        with transaction.atomic():
            submission = Submission.objects.create(
                contest=contest,
                developer=developer,
                source_object_key=payload.source_object_key,
                demo_video_object_key=payload.demo_video_object_key or "",
                demo_url=sanitize_free_text(payload.demo_url or ""),
                test_account=sanitize_free_text(payload.test_account or ""),
            )
            _replace_requirement_responses(submission, contest, payload.requirement_responses)
    except IntegrityError as exc:
        raise HttpError(409, "이미 이 Contest에 제출한 Submission이 있습니다.") from exc

    submission.refresh_from_db()
    return 201, _serialize(
        submission, contest=contest, is_owner=True, is_sponsor=False, past_deadline=False
    )


@router.put(
    "/contests/{contest_id}/submissions/me", response={200: SubmissionOut}, auth=jwt_auth
)
def update_submission(request: HttpRequest, contest_id: int, payload: SubmissionIn):
    contest = _get_published_contest_or_404(contest_id)
    _reject_if_past_deadline(contest)

    verification = _require_verification(request.auth_user)
    _reject_self_dealing(contest, verification)

    developer = DeveloperProfile.objects.filter(user=request.auth_user).first()
    submission = (
        Submission.objects.filter(contest=contest, developer=developer).first()
        if developer is not None
        else None
    )
    if submission is None:
        raise HttpError(404, "수정할 Submission이 없습니다. 먼저 제출하세요.")

    expected_source_ref = source_target_ref(contest.id, request.auth_user.id)
    _require_source_object_key(payload.source_object_key, expected_target_ref=expected_source_ref)

    expected_demo_video_ref = demo_video_target_ref(contest.id, request.auth_user.id)
    _validate_object_key(
        payload.demo_video_object_key,
        expected_target_ref=expected_demo_video_ref,
        field_name="demo_video_object_key",
    )

    with transaction.atomic():
        submission.source_object_key = payload.source_object_key
        submission.demo_video_object_key = payload.demo_video_object_key or ""
        submission.demo_url = sanitize_free_text(payload.demo_url or "")
        submission.test_account = sanitize_free_text(payload.test_account or "")
        submission.save()
        _replace_requirement_responses(submission, contest, payload.requirement_responses)

    submission.refresh_from_db()
    return 200, _serialize(
        submission, contest=contest, is_owner=True, is_sponsor=False, past_deadline=False
    )


@router.get(
    "/contests/{contest_id}/submissions/me", response={200: SubmissionOut}, auth=jwt_auth
)
def get_my_submission(request: HttpRequest, contest_id: int):
    contest = _get_published_contest_or_404(contest_id)

    developer = DeveloperProfile.objects.filter(user=request.auth_user).first()
    submission = (
        Submission.objects.filter(contest=contest, developer=developer).first()
        if developer is not None
        else None
    )
    if submission is None:
        raise HttpError(404, "Submission이 없습니다.")

    past_deadline = Clock.now() >= contest.deadline_at
    return 200, _serialize(
        submission, contest=contest, is_owner=True, is_sponsor=False, past_deadline=past_deadline
    )


@router.get("/submissions/{submission_id}", response={200: SubmissionOut}, auth=None)
def get_submission(request: HttpRequest, submission_id: int):
    """단건 조회. 진행 중에는 소유자·Sponsor 외에는 아예 안 보인다(404).

    마감 후에는 누구나(비로그인 포함) 조회할 수 있지만 소스는 여전히 소유자 본인에게만
    보인다 — ADR-0014.
    """

    try:
        submission = Submission.objects.select_related(
            "contest__sponsor", "developer"
        ).get(id=submission_id)
    except Submission.DoesNotExist as exc:
        raise HttpError(404, "Submission을 찾을 수 없습니다.") from exc

    contest = submission.contest
    auth_user = getattr(request, "auth_user", None)
    is_owner = auth_user is not None and submission.developer.user_id == auth_user.id
    is_sponsor = auth_user is not None and contest.sponsor.user_id == auth_user.id
    past_deadline = Clock.now() >= contest.deadline_at

    if not (is_owner or is_sponsor or past_deadline):
        # 다른 Developer(혹은 비로그인)에게는 진행 중인 Submission의 존재 자체를
        # 드러내지 않는다.
        raise HttpError(404, "Submission을 찾을 수 없습니다.")

    return 200, _serialize(
        submission,
        contest=contest,
        is_owner=is_owner,
        is_sponsor=is_sponsor,
        past_deadline=past_deadline,
    )
