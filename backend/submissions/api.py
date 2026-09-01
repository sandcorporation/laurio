"""Submission API — 제출·수정·조회 (#10, ADR-0014, ADR-0005, ADR-0011).

핵심 규율:

- 전체 소스코드는 필수다. 없으면 422로 거부한다(플랫폼의 "강제하지 않고 신호한다"
  원칙에서 유일한 예외 — ADR-0014).
- `Verification`을 마치지 않았거나(또는 만 19세 미만이라 VERIFIED에 도달하지 못했거나)
  마감이 지났으면 제출·수정 모두 거부한다. "마감"은 Contest 상태 전이(#11)를 기다리지
  않고 `deadline_at`과 `core.clock.Clock.now()`를 직접 비교한다.
- Contest의 Sponsor와 같은 CI를 가진 사람은 제출할 수 없다(자전거래 차단).
- 소스는 어떤 API 응답에서도 소유자 본인 외에는 절대 나오지 않는다 — Award 자체는
  #13(`awards` 앱)이 만들었지만, 그 이후 Sponsor에게 소스 접근 권한을 여는 것
  (Handover)은 #14 소관이라 여기 새 분기가 필요할 뿐, 지금은 그 분기가 없다
  (`submissions.resolvers`의 SOURCE_SLOT 분기 주석 참고).
- 진행 중에는 다른 Developer의 Submission이 전혀 보이지 않는다. Sponsor는 데모·영상은
  볼 수 있지만 소스는 볼 수 없다. 마감 후에는 데모·영상이 전면 공개된다.

파일 자체는 이 API를 거치지 않는다 — presigned 업로드는 storage 앱이 이미 제공한다
(#6). 이 API는 storage가 발급한 object_key 문자열을 받아서 저장할 뿐이다. Evidence의
"스크린샷" 값도 마찬가지로 storage object_key를 담을 수 있는 불투명한 문자열이다.
"""

# `from __future__ import annotations` 를 쓰지 않는다 — 이 모듈에는 `@paginate` 로
# 감싼 엔드포인트가 있고(list_my_participation, #74), 그 래퍼는 원본 함수의
# `__globals__` 를 가져갈 수 없어 문자열이 된 어노테이션을 해석하지 못한다.
# contests/api.py(#39)와 appeals/api.py(#72)가 같은 자리에서
# `QueryParams is not fully defined` 500 을 겪고 같은 결론에 도달했다.

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError
from ninja.pagination import PageNumberPagination, paginate

from accounts.middleware import jwt_auth
from accounts.models import DeveloperProfile
from accounts.sanitize import sanitize_free_text
from awards.models import Award
from contests.models import Contest, Requirement
from core.clock import Clock
from verification.models import Verification

from .models import Evidence, RequirementResponse, Submission
from .participation import next_action_for
from .schemas import (
    ErrorOut,
    MyParticipationOut,
    OwnScoreOut,
    ComparisonEntryOut,
    ComparisonSubmissionOut,
    CompletionOut,
    ContestComparisonOut,
    DeveloperPublicProfileOut,
    EvidenceOut,
    PublicSubmissionOut,
    RequirementComparisonOut,
    RequirementResponseOut,
    SubmissionIn,
    SubmissionOut,
)
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
        # 드러내지 않는다(contests.api.get_contest와 같은 원칙). CLOSED는 여기
        # 포함하지 않는다 — 제출·수정은 어차피 _reject_if_past_deadline이 별도로
        # 막으므로, 이 헬퍼는 "결제로 공개되었는가"만 본다.
        raise HttpError(404, "Contest를 찾을 수 없습니다.")
    return contest


_VIEWABLE_STATUSES = (
    Contest.Status.PUBLISHED,
    Contest.Status.CLOSED,
    # AWARDED·JUDGING_ENDED도 포함한다(#13) — 그렇지 않으면 Award되거나 심사기간이
    # 끝나는 순간 Developer가 자기 제출물을 조회하지 못하게 된다. 정확히 #11이
    # CLOSED를 추가할 때 반영했던 것과 같은 원칙을, 이 티켓이 추가한 두 상태에도
    # 적용한다(#12 리뷰 지적 4의 재발 방지).
    Contest.Status.AWARDED,
    Contest.Status.JUDGING_ENDED,
)


def _get_viewable_contest_or_404(contest_id: int) -> Contest:
    """PUBLISHED·CLOSED·AWARDED·JUDGING_ENDED 모두 조회 가능하다. DRAFT만 존재를
    드러내지 않는다.

    마감 전이(#11)가 Contest.status를 CLOSED로 옮긴 뒤에도, 그리고 그 뒤 Award나
    심사기간 종료(#13)로 한 번 더 옮긴 뒤에도 본인 Submission 조회
    (get_my_submission)는 계속 성립해야 한다 — 마감이 지났다고 자기 제출물을 못
    보게 막을 이유가 없다. 단건 공개 조회(get_submission)는 애초에 status를 보지
    않고 deadline_at만 비교해 이 문제가 없었다(#12 리뷰 지적: 둘이 서로 다른
    기준을 쓰고 있었다) — 이 헬퍼로 그 기준에 맞춘다.
    """
    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc
    if contest.status not in _VIEWABLE_STATUSES:
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

    # 소스는 소유자 본인과, Award된 뒤의 Sponsor에게만 나온다(ADR-0014, #14
    # Handover) — Award되지 않은 Submission의 소스는 Sponsor에게도 절대 보이지
    # 않는다. 데모·영상은 진행 중엔 본인·Sponsor, 마감 후엔 전면 공개(ADR-0014의
    # "데모·영상" 칸). test_account는 그 칸에 없다 — 마감 후 공개되는 건 데모·영상
    # 뿐이고, 그걸 들여다볼 로그인 정보까지 공개 범위에 들어가지는 않는다(#10 리뷰
    # 지적). 그래서 test_account는 진행 중이든 마감 후든 항상 본인·Sponsor로만 좁힌다.
    is_awarded = is_sponsor and Award.objects.filter(submission_id=submission.id).exists()
    show_source = is_owner or is_awarded
    show_demo = is_owner or is_sponsor or past_deadline
    show_test_account = is_owner or is_sponsor

    return SubmissionOut(
        id=submission.id,
        contest_id=submission.contest_id,
        developer_id=submission.developer_id,
        is_owner=is_owner,
        source_object_key=submission.source_object_key if show_source else None,
        demo_video_object_key=(submission.demo_video_object_key or None) if show_demo else None,
        demo_url=(submission.demo_url or None) if show_demo else None,
        test_account=(submission.test_account or None) if show_test_account else None,
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
    contest = _get_viewable_contest_or_404(contest_id)

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


@router.get("/submissions/mine", response=list[MyParticipationOut], auth=jwt_auth)
@paginate(PageNumberPagination, page_size=20)
def list_my_participation(request: HttpRequest, **kwargs):
    """Developer 가 자기 제출들과 각각의 「다음 행동」을 본다 (#74).

    이 표면이 없어서 로그인한 Developer 가 "내가 어디에 냈고 각각 지금 어떤
    상태인가" 를 볼 곳이 없었다 — 공개 프로필은 마감 후 아카이브이고 단건
    조회는 하나씩이다. 이의도 지급도 걸 데가 없었다.

    **행은 도메인 상태가 아니라 「다음 행동」을 말한다**(`participation.py` 참고).
    판정은 백엔드에 있고 값은 타입 있는 enum 이라, 값이 하나 늘면 프론트의
    누락된 분기를 `tsc` 가 빌드타임에 잡는다.

    제출이 아직 없으면 빈 페이지로 200 이다 — "아직 아무 데도 안 냈다" 는
    정상적인 사실이지 없는 리소스가 아니다. 이 경로가
    `/submissions/{submission_id}` 보다 **먼저** 등록돼야 한다는 점에 주의한다
    — 뒤에 두면 "mine" 이 submission_id 로 먹혀 404 가 난다.
    """

    profile = DeveloperProfile.objects.filter(user=request.auth_user).first()
    if profile is None:
        return Submission.objects.none()

    # 「다음 행동」을 고르려면 Contest·Score·Award·Handover·Appeal 을 함께 본다.
    # 행마다 새로 조회하면 참가가 쌓일수록 N+1 이 된다.
    return (
        Submission.objects.filter(developer=profile)
        .select_related("contest", "score", "appeal", "contest__award__handover")
        .order_by("-created_at")
    )

@router.get(
    "/submissions/{submission_id}/score",
    response={200: OwnScoreOut, 403: ErrorOut, 404: ErrorOut},
    auth=jwt_auth,
)
def get_own_score(request: HttpRequest, submission_id: int):
    """Developer 가 자기 Submission 의 채점 결과를 본다 (#74).

    **이게 없으면 이의 제기는 화면이 아니었다.** Score 가 노출되는 곳은 운영자의
    이의 상세 하나뿐이었다 — 이의를 낸 다음에야, 그것도 낸 본인이 아니라 심판하는
    운영자만 볼 수 있었다. 「채점이 끝났다」는 알림을 받은 Developer 에게는 무엇에
    이의를 제기할지 볼 데가 없었다.

    채점 전에는 404 다. 「아직 채점되지 않았다」와 「그런 제출이 없다」는 다른
    사실이므로 detail 로 구분한다 — 앞은 기다리면 되고 뒤는 뭔가 잘못된 것이다.
    """

    submission = _get_owned_submission(request, submission_id)

    score = getattr(submission, "score", None)
    if score is None:
        raise HttpError(404, "아직 채점되지 않았습니다.")

    return 200, score


def _get_owned_submission(request: HttpRequest, submission_id: int) -> Submission:
    """`appeals.api._get_owned_submission` 과 같은 경계다 — 없는 것과 남의 것을
    가른다. 두 앱이 각자 자기 라우터에서 쓰므로 한쪽이 다른 쪽을 import 하지
    않는다(순환을 만들 이유가 없다)."""

    try:
        submission = Submission.objects.select_related("developer", "score").get(
            id=submission_id
        )
    except Submission.DoesNotExist as exc:
        raise HttpError(404, "Submission을 찾을 수 없습니다.") from exc

    if submission.developer.user_id != request.auth_user.id:
        raise HttpError(403, "본인의 Submission에만 접근할 수 있습니다.")
    return submission


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


@router.get(
    "/developers/{developer_id}/profile",
    response={200: DeveloperPublicProfileOut},
    auth=None,
)
def get_developer_public_profile(request: HttpRequest, developer_id: int):
    """Developer 공개 프로필 — 마감된 Submission이 자동으로 아카이브된다 (#11).

    "마감"은 여기서도 Contest.status(#11의 스케줄러 틱)가 아니라 `deadline_at`과
    `Clock.now()`를 직접 비교한다 — submissions.resolvers/api의 다른 가시성 판정과
    같은 기준이다. 파일이 움직이지 않는 것처럼(ADR-0005) 이 아카이브도 틱을 기다리지
    않고 그 순간 이미 옳다.

    데모·영상만 담는다 — 소스는 Award 전까지 아무에게도 공개되지 않고(ADR-0014),
    test_account는 "데모·영상" 칸에 없는 로그인 정보라 여기서도 내려주지 않는다
    (submissions.api._serialize와 같은 원칙, #10 리뷰 지적).
    """

    developer = DeveloperProfile.objects.filter(id=developer_id).select_related("user").first()
    if developer is None:
        raise HttpError(404, "Developer를 찾을 수 없습니다.")

    now = Clock.now()
    submissions = (
        Submission.objects.filter(developer=developer, contest__deadline_at__lte=now)
        .select_related("contest")
        .order_by("-contest__deadline_at")
    )

    return 200, DeveloperPublicProfileOut(
        developer_id=developer.id,
        display_name=developer.display_name,
        bio=developer.bio,
        submissions=[
            PublicSubmissionOut(
                submission_id=s.id,
                contest_id=s.contest_id,
                contest_title=s.contest.title,
                demo_video_object_key=s.demo_video_object_key or None,
                demo_url=s.demo_url or None,
                created_at=s.created_at,
            )
            for s in submissions
        ],
    )


@router.get(
    "/contests/{contest_id}/submissions/compare",
    response={200: ContestComparisonOut},
    auth=jwt_auth,
)
def compare_submissions(request: HttpRequest, contest_id: int):
    """Sponsor가 Requirement 체크리스트를 축으로 Submission들을 나란히 비교한다 (#13).

    앱 하나에 설치·가입·탐색만 20~30분이 걸리므로(REQUEST.md), Sponsor가 전부
    설치해보지 않고도 이 화면으로 1차로 거를 수 있어야 한다(User Story 45).

    소스는 이 응답 어디에도 없다 — Award 전까지 Sponsor에게 열리지 않는다
    (ADR-0014). 마감 전에는 열지 않는다 — 진행 중 비공개 원칙(REQUEST.md)이 여기도
    적용된다. "마감"은 다른 곳과 같은 기준으로 deadline_at을 직접 비교한다(#11 이후
    이 코드베이스의 일관된 규약).
    """

    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

    if contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest만 비교할 수 있습니다.")

    if Clock.now() < contest.deadline_at:
        raise HttpError(403, "마감 전에는 Submission을 비교할 수 없습니다.")

    requirements = list(Requirement.objects.filter(contest=contest).order_by("order", "id"))
    submissions = (
        Submission.objects.filter(contest=contest)
        .select_related("developer")
        .prefetch_related("requirement_responses__evidence_items")
        .order_by("id")
    )

    submission_outs: list[ComparisonSubmissionOut] = []
    entries_by_requirement: dict[int, list[ComparisonEntryOut]] = {r.id: [] for r in requirements}

    for submission in submissions:
        developer_name = (
            submission.developer.display_name or f"Developer#{submission.developer_id}"
        )
        responses_by_requirement = {
            r.requirement_id: r for r in submission.requirement_responses.all()
        }

        linked_count = 0
        for requirement in requirements:
            response = responses_by_requirement.get(requirement.id)
            if response is None:
                entries_by_requirement[requirement.id].append(
                    ComparisonEntryOut(
                        submission_id=submission.id,
                        developer_id=submission.developer_id,
                        developer_display_name=developer_name,
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
            entries_by_requirement[requirement.id].append(
                ComparisonEntryOut(
                    submission_id=submission.id,
                    developer_id=submission.developer_id,
                    developer_display_name=developer_name,
                    is_met=response.is_met,
                    note=response.note,
                    evidence=[EvidenceOut(kind=e.kind, value=e.value) for e in evidence_items],
                    is_linked=is_linked,
                )
            )

        total = len(requirements)
        submission_outs.append(
            ComparisonSubmissionOut(
                submission_id=submission.id,
                developer_id=submission.developer_id,
                developer_display_name=developer_name,
                demo_video_object_key=submission.demo_video_object_key or None,
                demo_url=submission.demo_url or None,
                completion=CompletionOut(
                    has_demo_video=bool(submission.demo_video_object_key),
                    has_demo_url=bool(submission.demo_url),
                    has_test_account=bool(submission.test_account),
                    total_requirement_count=total,
                    linked_requirement_count=linked_count,
                    unlinked_requirement_count=max(total - linked_count, 0),
                ),
            )
        )

    return 200, ContestComparisonOut(
        contest_id=contest.id,
        submissions=submission_outs,
        requirements=[
            RequirementComparisonOut(
                requirement_id=r.id,
                text=r.text,
                grade=r.grade,
                entries=entries_by_requirement[r.id],
            )
            for r in requirements
        ],
    )
