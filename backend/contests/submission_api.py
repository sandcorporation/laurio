"""공모전 Submission API — 제출·수정·조회 (#10, ADR-0014, ADR-0005, ADR-0011,
#218/ADR-0030, #270/ADR-0039).

핵심 규율:

- 전체 소스코드 또는 공개 GitHub 저장소 중 최소 하나는 필수다. 둘 다 없으면
  422로 거부한다(플랫폼의 "강제하지 않고 신호한다" 원칙에서 유일한 예외 —
  ADR-0014, #218이 저장소를 그 예외의 두 번째 길로 열었다). 저장소만 낸
  제출은 마감 시점에 그 저장소가 도달 불가능(private·404)이면 채점이 0%
  Score를 남긴다(`scoring.services`) — Score 자체가 없어지지는 않는다.
- `Verification`을 마치지 않았거나(또는 만 19세 미만이라 VERIFIED에 도달하지 못했거나)
  마감이 지났으면 제출·수정 모두 거부한다. "마감"은 Contest 상태 전이(#11)를 기다리지
  않고 `deadline_at`과 `core.clock.Clock.now()`를 직접 비교한다. **무료 공모전
  (`contest.is_free`, #416, ADR-0048)은 예외다** — 본인확인을 요구하지 않는 대신
  「수상작의 소스는 개최자가 볼 수 있습니다」에 대한 동의(`source_access_consent`)를
  요구한다. 동의가 없으면 422다.
- Contest의 Sponsor와 같은 CI를 가진 사람은 제출할 수 없다(자전거래 차단) — 무료
  공모전은 본인확인 자체가 없어 CI가 없으므로 이 검사도 함께 건너뛴다.
- 소스는 어떤 API 응답에서도 소유자 본인 외에는 절대 나오지 않는다 — Award 자체는
  #13(`awards` 앱)이 만들었지만, 그 이후 Sponsor에게 소스 접근 권한을 여는 것
  (Handover)은 #14 소관이라 여기 새 분기가 필요할 뿐, 지금은 그 분기가 없다
  (`submissions.resolvers`의 SOURCE_SLOT 분기 주석 참고).
- 진행 중에는 다른 Developer의 Submission이 전혀 보이지 않는다. Sponsor는 데모·영상은
  볼 수 있지만 소스는 볼 수 없다. 마감 후에는 데모·영상이 전면 공개된다.

파일 자체는 이 API를 거치지 않는다 — presigned 업로드는 storage 앱이 이미 제공한다
(#6). 이 API는 storage가 발급한 object_key 문자열을 받아서 저장할 뿐이다. Evidence의
"스크린샷" 값도 마찬가지로 storage object_key를 담을 수 있는 불투명한 문자열이다.

**#270(ADR-0039) 이후 이 모듈이 `submissions` 앱에서 이 앱으로 옮겨왔다.**
`submissions`가 공유층이 되면서 공모전 전용 API·스키마·판정이 전부 이쪽으로
왔다 — 엔드포인트 경로와 응답 스키마는 바뀌지 않았고, 어느 앱이 라우터를
등록하는지만 달라졌다. 부모(`submissions.Submission`)를 직접 만들지 않는다 —
`contests.models.ContestSubmission`(자식)을 통해서만 만든다, 그래야 자식 없는
부모 행이 생기지 않는다.
"""

# list_my_participation(#74)이 예전엔 `@paginate`로 감쌌었다(그 래퍼는 원본 함수의
# `__globals__`를 가져갈 수 없어 `from __future__ import annotations`를 쓰면 문자열이
# 된 어노테이션을 해석하지 못했다 — contests/api.py(#39)와 appeals/api.py(#72)가 같은
# 자리에서 `QueryParams is not fully defined` 500을 겪었다). #152가 그 엔드포인트를
# 커서로 옮기며 `@paginate`는 이 파일에서 사라졌지만, 다른 이유로 다시 걸릴 수 있어
# `from __future__ import annotations`는 여전히 쓰지 않는다.

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import HttpRequest
from django.utils import timezone
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from accounts.models import DeveloperProfile
from accounts.sanitize import sanitize_free_text
from awards.models import Award
from core.clock import Clock
from core.keyset import decode_cursor, keyset_page
from policies.scope import current_policy
from policies.services import get_current_policy
from core.quality_review import quality_view
from scoring.models import SubmissionBonusScore
from scoring.quality import bonus_scores, ranked_reviews
from storage.adapters import get_storage_adapter
from storage.filenames import build_download_filename
from storage.policy import get_download_ttl_resolver
from submissions.models import (
    Evidence,
    RequirementResponse,
    Submission,
    SubmissionAsset,
    REPOSITORY_URL_SHAPES_MESSAGE,
    parse_github_submission_url,
)
from submissions.schemas import (
    AssetSummaryOut,
    CompletionOut,
    EvidenceOut,
    RequirementResponseOut,
    SubmissionAssetOut,
)
from submissions.video_link import VIDEO_LINK_SHAPE_MESSAGE, is_safe_video_link
from verification.models import Verification

from .images import ALLOWED_CONTEST_IMAGE_CONTENT_TYPES
from .models import Contest, ContestSubmission, Requirement
from .submission_participation import next_action_for
from .submission_retention import demo_video_destroy_at
from .submission_schemas import (
    ComparisonEntryOut,
    BonusScoreIn,
    BonusScoreOut,
    ComparisonQualityOut,
    ComparisonSubmissionOut,
    CompletionDistributionOut,
    ContestComparisonOut,
    ContestMetricsOut,
    DailyParticipationOut,
    DeveloperPublicProfileOut,
    ErrorOut,
    MyParticipationOut,
    MyParticipationPageOut,
    OwnScoreOut,
    PublicSubmissionOut,
    RequirementComparisonOut,
    RequirementFulfillmentOut,
    SubmissionIn,
    SubmissionOut,
    ViewMetricsOut,
)
from .submission_target_refs import target_ref_for_asset_kind

logger = logging.getLogger(__name__)

router = Router(tags=["submissions"])

_EVIDENCE_KINDS = {choice for choice, _label in Evidence.Kind.choices}

#: 무료 공모전 제출의 소스 열람 동의가 없을 때의 거절 문장 — 강의실의 「공모전에도 내기」
#: (#549, `contests.classroom_entries`)도 같은 문장을 받는다.
SOURCE_ACCESS_CONSENT_REQUIRED_MESSAGE = (
    "수상작의 소스는 개최자가 볼 수 있습니다 — 동의해야 제출할 수 있습니다."
)


# --- 가드 -------------------------------------------------------------------


def _require_verification(user) -> Verification:
    verification = Verification.objects.filter(user=user).first()
    if verification is None or not verification.is_verified:
        raise HttpError(
            403,
            "본인확인을 완료해야 제출할 수 있습니다. "
            "휴대폰 본인확인을 먼저 마쳐주세요.",
        )
    return verification


def _require_verification_unless_free(contest: Contest, user) -> Verification | None:
    """무료 공모전은 제출에 본인확인을 요구하지 않는다(#416, ADR-0048) —
    개최 권한이 개최를 걸러 주듯, 제출에는 애초에 그 문이 없다. 유료
    공모전은 그대로 `_require_verification`을 거친다(그리고 그 결과가
    자전거래 검사의 입력이 된다).

    반환값이 `None`이면 무료 공모전이라 검사를 건너뛴 것이지 실패가 아니다
    — 호출부는 `None`이면 `_reject_self_dealing`도 함께 건너뛴다(무료
    공모전은 본인확인 CI가 아예 없어 그 검사 자체가 성립하지 않는다).
    """

    if contest.is_free:
        return None
    return _require_verification(user)


def _resolve_source_access_consent(contest: Contest, payload: SubmissionIn):
    """무료 공모전 제출의 소스 열람 동의를 확인하고 동의 시각을 낸다(#416).

    동의가 없으면 422다 — 이 문장 하나가 무료 공모전에서 본인확인이 서던
    자리(「알고 참가한다」는 사실 확인)를 대신한다. 유료 공모전은 이 필드를
    보지 않는다(`payload.source_access_consent`가 와도 무시한다) — 본인확인이
    이미 그 역할을 한다.
    """

    if not contest.is_free:
        return None
    if not payload.source_access_consent:
        raise HttpError(422, SOURCE_ACCESS_CONSENT_REQUIRED_MESSAGE)
    return Clock.now()


def _get_published_contest_or_404(contest_id: int) -> Contest:
    # "제출 대상"이라고 쓴다 — 이 함수는 공모전·과제 양쪽 제출 경로가 함께
    # 쓰므로(create_submission/update_submission이 kind로 갈리기 전에 먼저
    # 부른다) "공모전을 찾을 수 없습니다"라고 못 박으면 과제 제출에서 거짓말이
    # 된다(#268).
    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "제출 대상을 찾을 수 없습니다.") from exc
    if not Contest.Status.SUBMITTABLE(contest.status):
        # draft Contest는 아직 결제가 끝나지 않아 공개되지 않았다 — 존재를
        # 드러내지 않는다(contests.api.get_contest와 같은 원칙). CLOSED는 여기
        # 포함하지 않는다 — 제출·수정은 어차피 _reject_if_past_deadline이 별도로
        # 막으므로, 이 헬퍼는 "결제로 공개되었는가"만 본다.
        raise HttpError(404, "제출 대상을 찾을 수 없습니다.")
    return contest


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
        raise HttpError(404, "제출 대상을 찾을 수 없습니다.") from exc
    if not Contest.Status.OWN_SUBMISSION_VIEWABLE(contest.status):
        raise HttpError(404, "제출 대상을 찾을 수 없습니다.")
    return contest


def _reject_if_past_deadline(contest: Contest) -> None:
    if Clock.now() >= contest.deadline_at:
        raise HttpError(403, "마감 시각이 지나 제출하거나 수정할 수 없습니다.")


def _reject_self_dealing(contest: Contest, developer_verification: Verification) -> None:
    """Sponsor와 Developer가 동일인이면 제출을 막는다(자전거래 차단, ADR-0011).

    비교할 CI가 없으면 "통과"가 아니라 거부다(#90) — 지금까지는 비교 대상이
    없다는 것을 조용히 통과로 처리했는데, 그건 "검사할 수 없다"와 "안전하다"를
    혼동한 것이었다. 이 함수가 걸리는 두 실패 분기(Developer의 ci_hash가
    비어 있음 / Sponsor에게 VERIFIED 신원이 없음)는 정상 운영에서는 도달
    불가능해야 한다:

    - Developer 쪽: `VerificationResult`가 빈 CI로는 생성 자체를 거부하고
      (#84, ADR-0024), `Verification.set_ci`도 같은 이유로 빈 값을 거부한다
      (모델 층의 두 번째 방어선). 이 함수를 호출하는 `_require_verification`은
      `status == VERIFIED`인 행만 넘기므로, 그 행은 반드시 `set_ci`를 거쳐
      만들어졌고 따라서 `ci_hash`가 비어 있을 수 없다.
    - Sponsor 쪽: 개최에는 본인확인이 필요하고(ADR-0011), 한 계정의 신원은
      다른 사람의 것으로 바뀌지 않는다(#99, ADR-0025) — 이미 CI가 확정된
      계정은 같은 CI로만 재확인이 통과되므로, 성인으로 개최한 Sponsor가
      재확인 한 번으로 미성년(UNDERAGE, CI 소거)이 되는 일은 일어나지 않는다.
      그리고 Developer와 같은 이유로, VERIFIED인 Sponsor 행도 `set_ci`를
      거쳤을 것이므로 `ci_hash`가 빈 문자열일 수 없다 — 이 논거는 두 쪽 모두에
      똑같이 적용되므로 가드도 양쪽에 똑같이 있어야 한다(코드리뷰 지적 —
      `sponsor_verification is None`만 막고 "VERIFIED인데 ci_hash가 빈
      문자열"은 막지 않으면, 마지막 비교 `"" == developer_ci_hash`가 항상
      False가 되어 자전거래 검사가 조용히 통과해버린다).

    그럼에도 도달했다면 위 불변식 중 하나가 깨진 것이므로, "무엇이 참인지
    모르는 상태"에서 통과시키지 않고 fail-closed로 거부하며 ERROR로 남겨
    운영자가 즉시 알아채게 한다 — `set_ci`가 어댑터 가드 위에 모델 가드를
    하나 더 둔 것과 같은 규율이다.
    """
    if not developer_verification.ci_hash:
        logger.error(
            "VERIFIED 상태인 Developer(user_id=%s)의 ci_hash가 비어 있다 — 불변식 위반. "
            "#84 이후 이 상태는 정상 운영에서 도달 불가능해야 한다.",
            developer_verification.user_id,
        )
        raise HttpError(
            403,
            "본인확인 정보를 확인할 수 없어 제출할 수 없습니다. 운영자에게 문의해 주세요.",
        )

    sponsor_verification = Verification.objects.filter(
        user_id=contest.sponsor.user_id, status=Verification.Status.VERIFIED
    ).first()
    if sponsor_verification is None:
        logger.error(
            "Contest(id=%s)의 Sponsor(user_id=%s)에게 VERIFIED 신원이 없어 자전거래 "
            "검사를 할 수 없다 — 불변식 위반. 개최에는 본인확인이 필요하므로(ADR-0011) "
            "이 상태는 정상 운영에서 도달 불가능해야 한다(#90).",
            contest.id,
            contest.sponsor.user_id,
        )
        raise HttpError(
            403,
            "이 공모전은 개최자의 본인확인 상태를 확인할 수 없어 제출할 수 없습니다. "
            "운영자에게 문의해 주세요.",
        )
    if not sponsor_verification.ci_hash:
        # "신원이 없다"(위 분기)와 "신원은 있는데 CI가 비었다"(이 분기)는 서로
        # 다른 불변식이 깨진 것이라 로그 문구를 따로 남긴다 — 하나로 합치면
        # 운영자가 두 원인을 로그만으로 가릴 수 없다. 이 분기가 없으면
        # `"" == developer_verification.ci_hash`가 항상 False가 되어 자전거래
        # 검사가 조용히 통과한다(코드리뷰 지적, #90의 좁은 형태).
        logger.error(
            "Contest(id=%s)의 VERIFIED Sponsor(user_id=%s)의 ci_hash가 비어 있다 — "
            "불변식 위반. #84 이후 이 상태는 정상 운영에서 도달 불가능해야 한다.",
            contest.id,
            contest.sponsor.user_id,
        )
        raise HttpError(
            403,
            "이 공모전은 개최자의 본인확인 상태를 확인할 수 없어 제출할 수 없습니다. "
            "운영자에게 문의해 주세요.",
        )

    if sponsor_verification.ci_hash == developer_verification.ci_hash:
        raise HttpError(
            403, "이 공모전의 개최자와 동일인으로 확인되어 제출할 수 없습니다(자전거래 차단)."
        )


_ASSET_KINDS = {k.value for k in SubmissionAsset.Kind}

_KIND_LIMIT_FIELDS = {
    SubmissionAsset.Kind.SOURCE: "max_source_assets",
    SubmissionAsset.Kind.DEMO_VIDEO: "max_demo_video_assets",
    SubmissionAsset.Kind.SCREENSHOT: "max_screenshot_assets",
    SubmissionAsset.Kind.DEMO_URL: "max_demo_url_assets",
    SubmissionAsset.Kind.REPOSITORY: "max_repository_assets",
}

#: 「시연 영상」 한 칸을 파일과 링크 두 방식으로 채운다(#910) — 개수 한도(`max_demo_video_assets`)는
#: 둘을 합쳐 센다. 정책 필드를 따로 두지 않는다.
_DEMO_VIDEO_KINDS = (SubmissionAsset.Kind.DEMO_VIDEO, SubmissionAsset.Kind.VIDEO_LINK)

_KIND_LABELS = dict(SubmissionAsset.Kind.choices)

# ContestImage(#234, ADR-0032)와 같은 허용목록을 그대로 쓴다(#264, ADR-0036).
# `policies.models`의 `max_screenshot_asset_bytes`와 달리 여기서는 직접
# import해도 순환이 생기지 않는다 — `contests.images`는 `submissions`를 (직접도
# 간접도) 임포트하지 않는다(`contests.schemas`가 끌어오는 것은
# `submissions.scoring_basis`뿐이라 이 모듈과는 별도 모듈이다).
ALLOWED_SCREENSHOT_CONTENT_TYPES = ALLOWED_CONTEST_IMAGE_CONTENT_TYPES


@dataclass(frozen=True)
class _CleanedAsset:
    """검증을 통과해 저장할 수 있게 다듬어진 자료 하나 (#190).

    `_clean_assets_in`과 `_merge_assets` 사이의 계약이다. dict로 넘기면 그 키가
    말없이 모델 필드 이름 노릇을 하게 되고(`**row`), `id`를 언제 꺼내느냐에 따라
    호출부가 조용히 달라진다 — 그 결합을 이름 있는 타입 하나로 끊는다.
    """

    kind: str
    value: str
    label: str
    test_account: str
    order: int
    #: 기존 자료를 가리키는 id. 첫 제출에는 언제나 None이다.
    id: int | None = None
    #: 업로드 발급 시 받은 content-type(#241) — SOURCE·DEMO_VIDEO가 아니면 항상
    #: 빈 문자열이다(`_clean_assets_in`이 그 외 종류에서는 무시한다).
    content_type: str = ""
    #: 저장소 자료의 브랜치 이름·커밋 SHA(#777) — `value` 는 저장소 URL 이고 이 둘이 낸 URL 의
    #: 나머지다. 다른 종류는 항상 빈 문자열이다.
    repository_ref: str = ""
    repository_commit_sha: str = ""

    def as_model_fields(self) -> dict:
        return {
            "kind": self.kind,
            "value": self.value,
            "label": self.label,
            "test_account": self.test_account,
            "order": self.order,
            "content_type": self.content_type,
            "repository_ref": self.repository_ref,
            "repository_commit_sha": self.repository_commit_sha,
        }

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """자료의 정체성 — `SubmissionAsset`의 UniqueConstraint 키에 ref·커밋을 더한 것(#777).
        같은 저장소를 다른 브랜치로 다시 내면 **다른 자료**다 — 공개 여부·고정 커밋이 옛
        브랜치의 것이면 안 되므로 옛 행을 지우고 새 행을 만든다. 브랜치 자료의 고정 커밋은
        스캔이 뒤에 박는 값이라 정체성에 들지 않는다."""

        return _asset_identity(
            self.kind, self.value, self.repository_ref, self.repository_commit_sha
        )


def _asset_identity(kind: str, value: str, ref: str, commit_sha: str) -> tuple[str, str, str, str]:
    return (kind, value, ref, "" if ref else commit_sha)


def _clean_assets_in(
    assets_in,
    *,
    contest: Contest,
    developer_user_id: int,
    existing_asset_values: set[tuple[str, str]] = frozenset(),
) -> list[_CleanedAsset]:
    """페이로드의 자료를 검증하고 저장 가능한 값으로 다듬는다 (#190).

    여기서 걸러지는 것: 알 수 없는 종류, 소스도 저장소도 없음(#218), 남의 업로드
    대상을 가리키는 object_key, GitHub 형식이 아닌 저장소 URL, 종류별·합산 개수
    상한, 같은 값의 중복, 스크린샷의 MIME 허용목록(#264). 마지막에서 둘째 것을
    API가 막는 이유는 `UniqueConstraint`가 대신 걸리면 422가 아니라
    500(IntegrityError)이 나기 때문이다.

    `existing_asset_values`는 **이미 이 Submission에 있는 (kind, value) 정체성**이다
    (수정 요청에서만 채워진다, 첫 제출에는 지울 기존 자료가 없다). 이미 있는
    값이면 MIME 검사를 건너뛴다 — content-type은 업로드 시점에만 실려 오고
    (`SubmissionAssetOut`에 그 필드가 없다, #241), 값이 바뀌지 않은 행을 그대로
    되돌려 보내는 편집 UI는 content_type을 다시 채워 보내지 않는다
    (`asset-kind-section.tsx`). 그 행까지 매번 다시 검사하면 스크린샷이 있는
    제출작은 체크리스트 한 줄만 고쳐도 저장이 거절된다.
    """

    cleaned: list[_CleanedAsset] = []
    seen: set[tuple[str, str]] = set()
    counts: dict[str, int] = {}

    for item in assets_in:
        if item.kind not in _ASSET_KINDS:
            raise HttpError(422, f"알 수 없는 자료 종류입니다: {item.kind}")

        value = (item.value or "").strip()
        if not value:
            raise HttpError(422, f"{_KIND_LABELS[item.kind]} 자료의 값이 비어 있습니다.")
        repository_ref = repository_commit_sha = ""

        expected_ref = target_ref_for_asset_kind(
            item.kind, contest_id=contest.id, developer_user_id=developer_user_id
        )
        if expected_ref is not None:
            if not value.startswith(f"{expected_ref}/"):
                raise HttpError(
                    422,
                    f"{_KIND_LABELS[item.kind]} 자료가 본인의 업로드 대상(target_ref)에 "
                    "속하지 않습니다.",
                )
        elif item.kind == SubmissionAsset.Kind.REPOSITORY:
            # 저장소 · `/tree/<브랜치>` · `/commit/<sha>` 셋을 받는다(#777) — `value` 는
            # 저장소 URL 로 남기고(중복 검사·유니크 제약이 그 키다) ref·SHA 는 따로 담는다.
            target = parse_github_submission_url(value)
            if target is None:
                raise HttpError(422, REPOSITORY_URL_SHAPES_MESSAGE)
            value = target.repo_url
            repository_ref, repository_commit_sha = target.ref, target.commit_sha
        elif item.kind == SubmissionAsset.Kind.VIDEO_LINK:
            # 시연 영상 링크(#910) — http(s) 에 호스트가 있고 사용자 정보가 없는 URL 만.
            value = sanitize_free_text(value)
            if not is_safe_video_link(value):
                raise HttpError(422, VIDEO_LINK_SHAPE_MESSAGE)
        else:
            # 데모 URL은 자유 텍스트다 — 다중화 이전과 같은 취급이다.
            value = sanitize_free_text(value)
            if not value:
                raise HttpError(422, "데모 URL 자료의 값이 비어 있습니다.")

        if (item.kind, value) in seen:
            raise HttpError(422, "같은 자료가 두 번 담겼습니다.")
        seen.add((item.kind, value))
        counts[item.kind] = counts.get(item.kind, 0) + 1

        test_account = sanitize_free_text(item.test_account or "")
        if test_account and item.kind not in SubmissionAsset.TEST_ACCOUNT_KINDS:
            # 모델의 CheckConstraint가 최후의 방어선이지만 그것이 걸리면 500이다
            # (ADR-0023과 같은 규율).
            raise HttpError(
                422,
                f"{_KIND_LABELS[item.kind]} 자료에는 테스트 계정을 붙일 수 없습니다.",
            )

        # content-type은 storage object_key를 갖는 종류(SOURCE·DEMO_VIDEO·SCREENSHOT)
        # 에만 의미가 있다(#241) — URL 종류에 실려 와도 조용히 버린다. 저장해 봐야
        # 쓰는 곳(다운로드 파일명)이 없고, 의미 없는 데이터가 쌓이지 않게 한다.
        content_type = (
            (item.content_type or "").strip()
            if item.kind in SubmissionAsset.OBJECT_KEY_KINDS
            else ""
        )

        if item.kind == SubmissionAsset.Kind.SCREENSHOT and (
            item.kind, value
        ) not in existing_asset_values:
            # ADR-0036: ContestImage와 같은 MIME 허용목록으로 이미지가 아닌
            # 파일을 거절한다. 바이트 상한(#261의 presigned POST 전환)과 달리
            # 이 검사는 스토리지가 아니라 여기서 한다 — 업로드 자체는 아직 일반
            # presigned PUT이라 declared content-type을 스토리지 조건에 실을 수
            # 없다. content-type을 아예 안 실었어도(빈 문자열) 거절한다 — 안
            # 그러면 이 검사를 빈 값 하나로 건너뛸 수 있다. **새 값에만 적용한다**
            # — 위 docstring의 `existing_asset_values` 설명 참고.
            if content_type not in ALLOWED_SCREENSHOT_CONTENT_TYPES:
                raise HttpError(
                    422, "스크린샷은 png/jpeg/webp/gif 형식만 올릴 수 있습니다."
                )

        cleaned.append(
            _CleanedAsset(
                id=item.id,
                kind=item.kind,
                value=value,
                label=sanitize_free_text(item.label or ""),
                test_account=test_account,
                order=item.order,
                content_type=content_type,
                repository_ref=repository_ref,
                repository_commit_sha=repository_commit_sha,
            )
        )

    if not counts.get(SubmissionAsset.Kind.SOURCE) and not counts.get(
        SubmissionAsset.Kind.REPOSITORY
    ):
        # ADR-0014/0030: 전체 소스코드 또는 공개 GitHub 저장소 중 최소 하나는
        # 필수다. 이 항목만 "강제하지 않고 신호한다"는 플랫폼 원칙의 예외다 —
        # 그러지 않으면 아무도 채점 입력을 내지 않은 Contest에서 Distribution
        # 대상이 0명이 되어 상금이 Escrow에 갇힌다(ADR-0014의 함정, ADR-0030이
        # 저장소를 그 예외의 두 번째 길로 연다). 저장소만 낸 제출은 마감 후
        # 그 저장소가 닫혀 있으면 0% Score로 채점된다(`scoring.services`) —
        # Score가 아예 없어지는 것은 아니다.
        raise HttpError(
            422, "전체 소스코드 또는 GitHub 저장소 중 최소 하나가 필수입니다."
        )

    policy = get_current_policy()
    for kind, limit_field in _KIND_LIMIT_FIELDS.items():
        limit = getattr(policy, limit_field)
        if counts.get(kind, 0) > limit:
            raise HttpError(
                422, f"{_KIND_LABELS[kind]} 자료는 최대 {limit}개까지 담을 수 있습니다."
            )
    if sum(counts.get(k, 0) for k in _DEMO_VIDEO_KINDS) > policy.max_demo_video_assets:
        raise HttpError(
            422,
            "시연 영상은 파일과 링크를 합쳐 최대 "
            f"{policy.max_demo_video_assets}개까지 담을 수 있습니다.",
        )

    scoring_inputs = sum(counts.get(k, 0) for k in SubmissionAsset.SCORING_INPUT_KINDS)
    if scoring_inputs > policy.max_scoring_input_assets:
        # 소스와 저장소는 같은 채점 예산을 나눠 쓴다(#191) — 종류별 상한만으로는
        # 막을 수 없다.
        raise HttpError(
            422,
            "소스코드와 GitHub 저장소를 합쳐 최대 "
            f"{policy.max_scoring_input_assets}개까지 담을 수 있습니다.",
        )

    return cleaned


def _existing_identity(asset: SubmissionAsset) -> tuple[str, str, str, str]:
    return _asset_identity(
        asset.kind, asset.value, asset.repository_ref, asset.repository_commit_sha
    )


def _merge_assets(submission: ContestSubmission, cleaned: list[_CleanedAsset]) -> set[int]:
    """자료를 병합한다 — 이 API에서 부분 갱신 의미론을 갖는 유일한 곳이다 (#190).

    **자료는 그 값이 곧 정체성이다.** `(submission, kind, value)`가 이미 유일하므로,
    id를 실어 보내지 않아도 같은 값이면 같은 행이다 — 그렇게 보지 않으면 편집 UI가
    id를 하나라도 빠뜨릴 때 유니크 제약이 대신 걸려 422가 아니라 500이 난다.

    그래서 병합은 이렇게 한다:

    - `id`가 있으면 그 행이 **이 Submission의 것인지** 먼저 확인한다. 그 검사가
      없으면 남의 행을 자기 제출작으로 옮길 수 있다.
    - `id`가 있는데 값이나 종류가 바뀌었으면 그건 **다른 자료**다 — 옛 행은
      사라지고 새 행이 생긴다(파일을 갈아끼우면 object_key 자체가 새로 발급된다).
      값을 제자리에서 바꾸지 않는 덕분에, 두 행이 값을 맞바꾸는 편집도 유니크
      제약에 걸리지 않는다.
    - `id`가 없으면 같은 (종류, 값)의 기존 행을 찾아 그대로 이어 쓴다.
    - 어디에도 걸리지 않은 기존 행은 지워진다. 그것을 가리키던 `Evidence`도
      함께 사라진다(FK가 CASCADE다).

    삭제를 생성보다 **먼저** 한다 — 그래야 지워지는 행이 쓰던 값을 새 행이 바로
    다시 쓸 수 있다.

    **지운 자산의 id를 돌려준다**(#195). 그것을 가리키던 `Evidence`는 거부가 아니라
    조용히 연결이 풀려야 하는데, 그 판정은 「이번 요청이 지운 것인가」와 「애초에 남의
    것인가」를 가를 수 있어야 한다 — 삭제가 끝난 뒤에는 둘 다 똑같이 「없는 id」로
    보이므로 여기서 알려주는 수밖에 없다.
    """

    existing = {a.id: a for a in submission.assets.all()}
    by_identity = {_existing_identity(a): a for a in existing.values()}

    kept: dict[int, _CleanedAsset] = {}
    creates: list[_CleanedAsset] = []

    for row in cleaned:
        if row.id is not None:
            asset = existing.get(row.id)
            if asset is None:
                raise HttpError(422, "이 제출물에 속하지 않은 자료 id입니다.")
            if asset.created_by_platform:
                # #220(ADR-0030): 저장소만 낸 제출이 채점 시점에 남기는 박제
                # 소스는 참가자가 지우거나 고칠 수 없다. 실제로는 그 자료가
                # 생기는 시점(마감 후 채점)에 이미 이 API 전체가 마감을 이유로
                # 거부하므로 여기 닿지 않는다 — 그래도 그 불변식이 나중에
                # (예: 마감 후 부분 수정을 여는 기능이 생기면) 느슨해져도
                # 조용히 깨지지 않게 한 번 더 막는다.
                raise HttpError(422, "플랫폼이 만든 자료는 수정할 수 없습니다.")
            if _existing_identity(asset) == row.identity and asset.id not in kept:
                kept[asset.id] = row
                continue
            creates.append(row)
            continue

        match = by_identity.get(row.identity)
        if match is not None and match.id not in kept:
            kept[match.id] = row
            continue
        creates.append(row)

    # 같은 이유로, 페이로드에 없다는 것만으로 박제 자료를 지우지 않는다.
    stale = [
        aid for aid in existing if aid not in kept and not existing[aid].created_by_platform
    ]
    if stale:
        SubmissionAsset.objects.filter(id__in=stale).delete()

    for asset_id, row in kept.items():
        asset = existing[asset_id]
        asset.label = row.label
        asset.test_account = row.test_account
        asset.order = row.order
        # content_type은 여기서 건드리지 않는다(#241) — value(object_key)가 같다는
        # 것은 같은 파일을 가리킨다는 뜻이고, 파일이 그대로면 그 형식도 그대로다.
        # 편집 화면이 기존 자료를 다시 보낼 때 content_type을 모른 채(서버가
        # `SubmissionAssetOut`에 이 필드를 내주지 않는다) 빈 문자열로 채워 보내도,
        # 여기서 그 값을 무시하므로 이미 알려진 content_type을 조용히 지우지 않는다.
        asset.save(update_fields=["label", "test_account", "order", "updated_at"])

    for row in creates:
        SubmissionAsset.objects.create(submission=submission, **row.as_model_fields())

    return set(stale)


# --- 자가 응답 · Evidence -----------------------------------------------------


def _replace_requirement_responses(
    submission: ContestSubmission,
    contest: Contest,
    responses_in,
    *,
    removed_asset_ids: set[int],
) -> None:
    """자가 응답과 그 근거를 통째로 새로 쓴다.

    **근거가 가리키는 자료의 판정이 세 갈래다**(#190, #195):

    - 살아 있는 이 Submission의 자료 → 그대로 연결한다.
    - **이번 요청이 지운** 이 Submission의 자료 → 연결만 조용히 푼다. 자료를 지우면서
      그 근거를 함께 정리하는 것은 클라이언트가 아니라 **서버가 할 일이다** — 서버는
      `_merge_assets` 뒤의 자산을 이미 알고 있고, 클라이언트가 그 정체성 규칙을
      흉내 내면 규칙이 바뀔 때마다 조용히 어긋난다(#192에서 실제로 두 번 틀렸다).
    - 그 밖의 id → 여전히 422다. **남의 자료 id를 근거에 붙여 그 존재를 확인하는
      경로를 만들지 않는다**(#190) — 이 갈래를 함께 뭉개면 그 방어가 사라진다.
    """

    own_asset_ids = set(submission.assets.values_list("id", flat=True))
    validate_requirement_responses(
        contest, responses_in, own_asset_ids=own_asset_ids, removed_asset_ids=removed_asset_ids
    )

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
                Evidence(
                    response=response,
                    kind=e.kind,
                    value=sanitize_free_text(e.value),
                    # 이번 요청이 지운 자료를 가리켰다면 연결만 푼다(#195).
                    asset_id=e.asset_id if e.asset_id in own_asset_ids else None,
                )
                for e in item.evidence
            ]
        )


def validate_requirement_responses(
    contest: Contest,
    responses_in,
    *,
    own_asset_ids: set[int],
    removed_asset_ids: set[int],
) -> None:
    """자가 응답의 모양을 본다 — 아무것도 쓰지 않는다. 강의실의 「공모전에도 내기」(#549)가
    시도를 만들기 전에 같은 검사로 미리 거른다(`contests.classroom_entries`)."""

    # 숨은 항목(#906)은 자가 응답·확인 위치 대상이 아니다 — 그 id 로 온 응답은 남의 공모전 항목처럼 거절한다
    # (응답이 받아지면 그 id 가 숨은 항목인지 떠보는 길이 된다).
    valid_requirement_ids = set(
        Requirement.objects.filter(contest=contest, hidden=False).values_list("id", flat=True)
    )
    seen_ids: set[int] = set()
    for item in responses_in:
        if item.requirement_id in seen_ids:
            raise HttpError(422, "같은 요구사항에 대한 응답이 중복되었습니다.")
        seen_ids.add(item.requirement_id)
        if item.requirement_id not in valid_requirement_ids:
            raise HttpError(422, "이 제출 대상에 속하지 않은 요구사항입니다.")
        for evidence in item.evidence:
            if evidence.kind not in _EVIDENCE_KINDS:
                raise HttpError(422, f"알 수 없는 근거 종류입니다: {evidence.kind}")
            if (
                evidence.asset_id is not None
                and evidence.asset_id not in own_asset_ids
                and evidence.asset_id not in removed_asset_ids
            ):
                raise HttpError(422, "이 제출물에 속하지 않은 자료를 근거로 지정했습니다.")


# --- 직렬화 -------------------------------------------------------------------


#: 마감 후 전면 공개되는 종류 (ADR-0014의 "데모·영상" 칸 — 스크린샷도 #264/ADR-0036이
#: 같은 칸에 세웠다).
_PUBLIC_AFTER_DEADLINE_KINDS = (
    SubmissionAsset.Kind.DEMO_VIDEO,
    SubmissionAsset.Kind.VIDEO_LINK,
    SubmissionAsset.Kind.SCREENSHOT,
    SubmissionAsset.Kind.DEMO_URL,
)
#: Award 전까지 본인만 보는 종류. 저장소가 여기 있는 이유는 ADR-0027 — 공개
#: 레포라도 플랫폼이 Sponsor에게 코드로 가는 길을 먼저 열어주지는 않는다.
_OWNER_UNTIL_AWARD_KINDS = (
    SubmissionAsset.Kind.SOURCE,
    SubmissionAsset.Kind.REPOSITORY,
)


def _visible_asset_kinds(
    *, is_owner: bool, is_sponsor: bool, is_awarded: bool, past_deadline: bool
) -> tuple[str, ...]:
    """이 뷰어에게 보이는 자료 종류 (ADR-0014, ADR-0027).

    **볼 수 없는 종류는 목록에서 빠진다** — 예전에는 종류마다 필드가 하나씩이라
    null로 "존재하지만 안 보임"을 표현했지만, 목록에서는 그 구분이 성립하지 않는다.
    """

    if is_owner:
        # **소유자는 종류를 가리지 않고 자기 자료를 전부 본다** (#195 리뷰). 아래
        # 두 목록은 알려진 네 종류만 열거하므로, 종류가 하나 늘고 이 함수를 함께
        # 고치지 않으면 **주인에게도 자기 자료가 안 보인다** — 그리고 그 자료를
        # 가리키는 근거의 참조가 `_evidence_outs`에서 지워져, 화면이 "연결이
        # 풀렸다"고 거짓으로 말하게 된다.
        return tuple(SubmissionAsset.Kind.values)

    kinds: list[str] = []
    if is_awarded:
        kinds.extend(_OWNER_UNTIL_AWARD_KINDS)
    if is_sponsor or past_deadline:
        kinds.extend(_PUBLIC_AFTER_DEADLINE_KINDS)
    return tuple(kinds)


def _evidence_outs(evidence_items, visible_asset_ids: set[int]) -> list[EvidenceOut]:
    """근거를 직렬화한다 — **보이지 않는 자료를 가리키는 참조는 지운다** (#190).

    id 자체는 불투명한 정수지만, 그것을 그대로 내리면 "이 사람에게 보이지 않는
    자료가 존재한다"가 근거를 통해 새어나간다. 자료가 안 보이면 그것을 가리킨다는
    사실도 안 보여야 한다 — 근거의 `kind`·`value`는 그대로 남으므로 심사에
    필요한 정보는 잃지 않는다.
    """

    return [
        EvidenceOut(
            kind=e.kind,
            value=e.value,
            asset_id=e.asset_id if e.asset_id in visible_asset_ids else None,
        )
        for e in evidence_items
    ]


def _public_asset_summaries(
    assets, *, contest_id: int, developer_user_id: int
) -> list[AssetSummaryOut]:
    """마감 후 공개되는 자료(데모·영상·스크린샷)만 요약한다 (#190, #264/#265).

    공개 프로필과 심사 비교가 같은 것을 낸다 — 두 자리가 각자 종류를 거르면
    언젠가 한쪽만 새 종류를 흘린다. 원소 타입에 `test_account`가 없다.

    **호출하는 두 화면 다 이미 마감 후에만 이 함수를 부른다**(비교 화면은 마감
    전 403, 공개 프로필은 `contest__deadline_at__lte=now`로 이미 걸렀다) — 그래서
    이 함수에 넘어오는 대상은 언제나 `SubmissionTargetStateResolver`가 PUBLIC으로
    판정할 대상이다. 그 전제 위에서 object_key 자산(`DEMO_VIDEO`·`SCREENSHOT`)에는
    **presigned 다운로드 URL을 직접 실어 보낸다**(#265) — target_ref 형식(ADR-0005)을
    프론트에 새로 노출하는 대신, 이미 여는 것으로 확정된 URL 하나를 낸다. 영상은
    화면 안에서 재생해야 해서 다른 종류보다 긴 서명 수명을 쓴다
    (`storage.policy.get_download_ttl_resolver`, ADR-0036).
    """

    adapter = None
    ttl_resolver = None
    out: list[AssetSummaryOut] = []
    for a in assets:
        if a.kind not in _PUBLIC_AFTER_DEADLINE_KINDS:
            continue

        download_url = None
        # 파일이 파기된 자료는 **서명하지 않는다**(#262, ADR-0035). 서명은
        # 오브젝트가 실재하는지 묻지 않으므로, 그대로 두면 화면이 아무것도
        # 재생하지 않는 `<video>`를 그린다 — 사실은 「보존 기간이 지났다」인데
        # 사용자에게는 고장으로 보인다. 자료 행 자체는 그대로 내보낸다:
        # 라벨과 근거는 살아 있고, 그것이 이 파기 규칙의 요지다.
        expired = a.destroyed_at is not None
        if a.kind in SubmissionAsset.OBJECT_KEY_KINDS and not expired:
            if adapter is None:
                adapter = get_storage_adapter()
            if ttl_resolver is None:
                ttl_resolver = get_download_ttl_resolver()
            target_ref = target_ref_for_asset_kind(
                a.kind, contest_id=contest_id, developer_user_id=developer_user_id
            )
            ttl_seconds = ttl_resolver.resolve(target_ref)
            presigned = adapter.presign_download(
                a.value,
                expires_in=timedelta(seconds=ttl_seconds),
                filename=build_download_filename(a.content_type or None),
            )
            download_url = presigned.url

        out.append(
            AssetSummaryOut(
                id=a.id,
                kind=a.kind,
                value=a.value,
                label=a.label,
                order=a.order,
                download_url=download_url,
                expired=expired,
            )
        )
    return out


def _completion_of(
    assets, *, total_requirements: int, linked_count: int
) -> CompletionOut:
    """자료 목록에서 채움률 지표를 만든다 (#190).

    `assets`는 **가시성으로 거르기 전의 전체 목록**이어야 한다 — 이 지표는
    "제출작이 얼마나 채워졌는가"이지 "당신에게 몇 개가 보이는가"가 아니다.
    """

    counts: dict[str, int] = {}
    has_test_account = False
    for asset in assets:
        counts[asset.kind] = counts.get(asset.kind, 0) + 1
        if asset.test_account:
            has_test_account = True

    # 시연 영상은 파일이든 링크든 한 칸이다(#910).
    demo_video_total = sum(counts.get(k, 0) for k in _DEMO_VIDEO_KINDS)

    return CompletionOut(
        has_demo_video=demo_video_total > 0,
        has_demo_url=bool(counts.get(SubmissionAsset.Kind.DEMO_URL)),
        has_test_account=has_test_account,
        source_count=counts.get(SubmissionAsset.Kind.SOURCE, 0),
        demo_video_count=demo_video_total,
        demo_url_count=counts.get(SubmissionAsset.Kind.DEMO_URL, 0),
        repository_count=counts.get(SubmissionAsset.Kind.REPOSITORY, 0),
        total_requirement_count=total_requirements,
        linked_requirement_count=linked_count,
        unlinked_requirement_count=max(total_requirements - linked_count, 0),
    )


def _serialize(
    submission: ContestSubmission,
    *,
    contest: Contest,
    is_owner: bool,
    is_sponsor: bool,
    past_deadline: bool,
) -> SubmissionOut:
    # 숨은 항목(#906)은 응답 칸도 채움률 분모에도 없다 — 응답을 받지 않으니 개최자에게도 빈 줄일 뿐이다.
    requirements = list(Requirement.objects.filter(contest=contest, hidden=False).order_by("order", "id"))
    responses_by_requirement = {
        r.requirement_id: r
        for r in submission.requirement_responses.all().prefetch_related("evidence_items")
    }

    # 소스·저장소는 소유자 본인과, Award된 뒤의 Sponsor에게만 나온다(ADR-0014,
    # ADR-0027, #14 Handover) — Award되지 않은 Submission의 소스는 Sponsor에게도
    # 절대 보이지 않는다. 데모·영상은 진행 중엔 본인·Sponsor, 마감 후엔 전면 공개.
    #
    # `test_account`는 데모 URL 자료에 붙어 있다 — 마감 후 공개되는 건 데모·영상
    # 뿐이고, 그걸 들여다볼 로그인 정보까지 공개 범위에 들어가지는 않는다(#10 리뷰
    # 지적). 그래서 자료 자체는 마감 후 공개되어도 계정은 본인·Sponsor로만 좁힌다.
    assets = list(submission.assets.all())
    is_awarded = is_sponsor and Award.objects.filter(submission_id=submission.id).exists()
    visible_kinds = _visible_asset_kinds(
        is_owner=is_owner,
        is_sponsor=is_sponsor,
        is_awarded=is_awarded,
        past_deadline=past_deadline,
    )
    visible_assets = [a for a in assets if a.kind in visible_kinds]
    visible_asset_ids = {a.id for a in visible_assets}
    show_test_account = is_owner or is_sponsor

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
                evidence=_evidence_outs(evidence_items, visible_asset_ids),
                is_linked=is_linked,
            )
        )

    total = len(requirements)
    completion = _completion_of(assets, total_requirements=total, linked_count=linked_count)

    # 「지금 무엇을 해야/기다려야 하는가」(#247) — 자기 제출물일 때만 낸다.
    # `list_my_participation`이 쓰는 것과 **같은 함수**다(조건을 두 벌로 두지
    # 않는다). 판정 자체가 관련 객체를 더 읽을 수 있으므로(점수·이의·Award·
    # Payout), 남의 제출물에는 그 값을 계산조차 하지 않는다.
    next_action = next_action_for(submission) if is_owner else None
    grace_days = current_policy().demo_video_retention_grace_days

    return SubmissionOut(
        id=submission.id,
        contest_id=submission.contest_id,
        developer_id=submission.developer_id,
        is_owner=is_owner,
        next_action=next_action,
        assets=[
            SubmissionAssetOut(
                id=a.id,
                kind=a.kind,
                value=a.submitted_url,
                label=a.label,
                test_account=a.test_account if show_test_account else "",
                order=a.order,
                is_public=a.is_public,
                commit_sha=a.repository_commit_sha or None,
                repository_ref_found=a.repository_ref_found,
                created_by_platform=a.created_by_platform,
                demo_video_retention_deadline=(
                    None
                    if a.kind != SubmissionAsset.Kind.DEMO_VIDEO or a.destroyed_at is not None
                    else demo_video_destroy_at(contest, grace_days)
                ),
                demo_video_destroyed=a.destroyed_at is not None,
            )
            for a in visible_assets
        ],
        requirement_responses=response_outs,
        completion=completion,
        created_at=submission.created_at,
        updated_at=submission.updated_at,
        source_access_consent_at=submission.source_access_consent_at,
    )


# --- 엔드포인트 ---------------------------------------------------------------


@router.post(
    "/contests/{contest_id}/submissions", response={201: SubmissionOut}, auth=jwt_auth
)
def create_submission(request: HttpRequest, contest_id: int, payload: SubmissionIn):
    contest = _get_published_contest_or_404(contest_id)
    _reject_if_past_deadline(contest)

    verification = _require_verification_unless_free(contest, request.auth_user)
    if verification is not None:
        _reject_self_dealing(contest, verification)
    consent_at = _resolve_source_access_consent(contest, payload)

    developer, _created = DeveloperProfile.objects.get_or_create(user=request.auth_user)

    if ContestSubmission.objects.filter(contest=contest, developer=developer).exists():
        raise HttpError(
            409, "이미 제출한 적이 있습니다. 수정은 PUT을 사용하세요."
        )

    cleaned_assets = _clean_assets_in(
        payload.assets, contest=contest, developer_user_id=request.auth_user.id
    )
    if any(row.id is not None for row in cleaned_assets):
        # 첫 제출에는 유지할 기존 자료가 없다. id를 실어 보냈다면 그것은 다른
        # Submission의 것이거나 클라이언트 버그다 — 어느 쪽이든 조용히 무시하면
        # 안 된다.
        raise HttpError(422, "첫 제출에는 자료 id를 실을 수 없습니다.")

    try:
        with transaction.atomic():
            # 부모(`Submission`)를 직접 만들지 않는다 — 자식을 통해서만 만들어야
            # 부모의 `user`가 언제나 자식의 `developer.user`와 일치한다(#270의
            # 두 불변식 중 하나, ADR-0039).
            submission = ContestSubmission.objects.create(
                user=request.auth_user,
                product=Submission.Product.CONTEST,
                contest=contest,
                developer=developer,
                source_access_consent_at=consent_at,
            )
            removed = _merge_assets(submission, cleaned_assets)
            _replace_requirement_responses(
                submission, contest, payload.requirement_responses, removed_asset_ids=removed
            )
    except IntegrityError as exc:
        raise HttpError(409, "이미 제출한 적이 있습니다.") from exc

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

    verification = _require_verification_unless_free(contest, request.auth_user)
    if verification is not None:
        _reject_self_dealing(contest, verification)
    consent_at = _resolve_source_access_consent(contest, payload)

    developer = DeveloperProfile.objects.filter(user=request.auth_user).first()
    submission = (
        ContestSubmission.objects.filter(contest=contest, developer=developer).first()
        if developer is not None
        else None
    )
    if submission is None:
        raise HttpError(404, "수정할 제출물이 없습니다. 먼저 제출하세요.")

    existing_asset_values = set(submission.assets.values_list("kind", "value"))
    cleaned_assets = _clean_assets_in(
        payload.assets,
        contest=contest,
        developer_user_id=request.auth_user.id,
        existing_asset_values=existing_asset_values,
    )

    with transaction.atomic():
        removed = _merge_assets(submission, cleaned_assets)
        # `updated_at`(auto_now)이 자료만 바뀐 수정에도 움직이게 한다 — 안 그러면
        # "마지막으로 손댄 때"가 체크리스트를 고친 때만 가리킨다.
        update_fields = ["updated_at"]
        if consent_at is not None:
            # 무료 공모전은 수정마다 동의를 다시 확인하고 시각을 새로 찍는다
            # (#416) — 유료 공모전은 `consent_at`이 항상 None이라 이 컬럼을
            # 건드리지 않는다.
            submission.source_access_consent_at = consent_at
            update_fields.append("source_access_consent_at")
        submission.save(update_fields=update_fields)
        _replace_requirement_responses(
            submission, contest, payload.requirement_responses, removed_asset_ids=removed
        )

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
    # `next_action_for`(#247, #250)가 보는 관계를 함께 당긴다 — `list_my_
    # participation`이 이미 쓰는 것과 같은 목록이다. `developer__user__
    # verification`은 #250이 더한 것 — 본인확인이 `verified`가 아니면 마감
    # 전이어도 `NEEDS_REVERIFICATION`을 돌려줘야 하는데, `next_action_for`는
    # 그 판정에 새 조회를 내지 않기로 돼 있다(같은 파일 docstring). 이 조회는
    # 한 건뿐이라 N+1 이 되진 않지만, 미리 당기지 않으면 왕복이 여러 번(점수·
    # 이의·Award·Handover·본인확인) 생긴다.
    submission = (
        ContestSubmission.objects.filter(contest=contest, developer=developer)
        .select_related(
            "contest", "score", "appeal", "contest__award__handover", "developer__user__verification"
        )
        .first()
        if developer is not None
        else None
    )
    if submission is None:
        raise HttpError(404, "제출물이 없습니다.")

    past_deadline = Clock.now() >= contest.deadline_at
    return 200, _serialize(
        submission, contest=contest, is_owner=True, is_sponsor=False, past_deadline=past_deadline
    )


# 한 페이지에 몇 행인가. 오프셋 시절의 `page_size=20` 을 그대로 이어받는다.
_MY_PARTICIPATION_PAGE_SIZE = 20


@router.get("/submissions/mine", response=MyParticipationPageOut, auth=jwt_auth)
def list_my_participation(request: HttpRequest, after: str | None = None):
    """Developer 가 자기 제출들과 각각의 「다음 행동」을 본다 (#74).

    이 표면이 없어서 로그인한 Developer 가 "내가 어디에 냈고 각각 지금 어떤
    상태인가" 를 볼 곳이 없었다 — 공개 프로필은 마감 후 아카이브이고 단건
    조회는 하나씩이다. 이의도 지급도 걸 데가 없었다.

    **행은 도메인 상태가 아니라 「다음 행동」을 말한다**(`contests.submission_
    participation` 참고). 판정은 백엔드에 있고 값은 타입 있는 enum 이라, 값이
    하나 늘면 프론트의 누락된 분기를 `tsc` 가 빌드타임에 잡는다.

    제출이 아직 없으면 빈 페이지로 200 이다 — "아직 아무 데도 안 냈다" 는
    정상적인 사실이지 없는 리소스가 아니다. 이 경로가
    `/submissions/{submission_id}` 보다 **먼저** 등록돼야 한다는 점에 주의한다
    — 뒤에 두면 "mine" 이 submission_id 로 먹혀 404 가 난다.

    **자르기는 커서다**(#151/#152) — 오프셋은 목록이 머리 쪽에서 자라면 경계가
    밀린다. 개발자가 다른 탭에서 제출을 하나 더 하는 동안 「더 보기」를 넘기면
    2페이지가 1페이지의 행을 다시 돌려주고, 원래 그 자리에 와야 했던 행은 어느
    페이지에도 안 나온다. 정렬 마지막 키에 `id` 를 붙이는 이유도 운영자 지급
    큐와 같다 — `created_at` 이 같은 두 행의 순서를 DB 가 보장하지 않는다.
    """

    if after is not None and decode_cursor(after) is None:
        # 읽을 수 없는 커서는 조용히 처음부터가 아니라 422 다 — 운영자 지급
        # 큐와 같은 규율(#151). 조용히 1페이지로 되돌리면 「더 보기」를 눌렀는데
        # 목록이 처음으로 돌아간 화면이 되어 무엇을 봤고 못 봤는지 알 수 없어진다.
        raise HttpError(422, "읽을 수 없는 커서입니다.")

    profile = DeveloperProfile.objects.filter(user=request.auth_user).first()
    if profile is None:
        return {"items": [], "count": 0, "next": None}

    # 「다음 행동」을 고르려면 Contest·Score·Award·Handover·Appeal 을 함께 본다.
    # 행마다 새로 조회하면 참가가 쌓일수록 N+1 이 된다.
    # `developer__user__verification`도 같은 이유로 더한다(#250) — 이 목록의
    # 모든 행이 같은 Developer(`profile`)의 것이라 실제로는 값이 하나뿐이지만,
    # select_related 없이 `next_action_for`가 행마다 `submission.developer.user.
    # verification`을 걸으면 JOIN 대신 행마다 왕복이 난다.
    submissions = (
        ContestSubmission.objects.filter(developer=profile)
        .select_related(
            "contest", "score", "appeal", "contest__award__handover", "developer__user__verification"
        )
        .order_by("-created_at", "-id")
    )

    items, next_cursor = keyset_page(
        submissions, after=after, page_size=_MY_PARTICIPATION_PAGE_SIZE
    )
    return {"items": items, "count": submissions.count(), "next": next_cursor}

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


def _get_owned_submission(request: HttpRequest, submission_id: int) -> ContestSubmission:
    """`appeals.api._get_owned_submission` 과 같은 경계다 — 없는 것과 남의 것을
    가른다. 두 앱이 각자 자기 라우터에서 쓰므로 한쪽이 다른 쪽을 import 하지
    않는다(순환을 만들 이유가 없다)."""

    try:
        # `score.submission.contest` 와 `.appeal` 을 이 조회에서 함께 끌어온다 —
        # `OwnScoreOut` 의 이의 창 판정이 그것을 본다.
        submission = ContestSubmission.objects.select_related(
            "developer", "score", "contest", "appeal", "quality_review"
        ).get(id=submission_id)
    except ContestSubmission.DoesNotExist as exc:
        raise HttpError(404, "제출물을 찾을 수 없습니다.") from exc

    if submission.developer.user_id != request.auth_user.id:
        raise HttpError(403, "본인의 제출물에만 접근할 수 있습니다.")
    return submission


@router.get("/submissions/{submission_id}", response={200: SubmissionOut}, auth=None)
def get_submission(request: HttpRequest, submission_id: int):
    """단건 조회. 진행 중에는 소유자·Sponsor 외에는 아예 안 보인다(404).

    마감 후에는 누구나(비로그인 포함) 조회할 수 있지만 소스는 여전히 소유자 본인에게만
    보인다 — ADR-0014.

    """

    try:
        # `contest__award__handover`·`score`·`appeal`·`developer__user__
        # verification`은 소유자에게만 계산하는 `next_action_for`(#247, #250)이
        # 보는 관계다 — 미리 당겨 두면 소유자 본인이 조회할 때 왕복이 늘지
        # 않는다. `developer`단독 대신 `developer__user__verification`으로
        # 적는다 — 뒤엣것이 앞엣것을 포함하면서 본인확인 상태까지 한 JOIN으로
        # 당긴다.
        submission = ContestSubmission.objects.select_related(
            "contest__sponsor",
            "developer__user__verification",
            "score",
            "appeal",
            "contest__award__handover",
        ).get(id=submission_id)
    except ContestSubmission.DoesNotExist as exc:
        raise HttpError(404, "제출물을 찾을 수 없습니다.") from exc

    contest = submission.contest
    auth_user = getattr(request, "auth_user", None)
    is_owner = auth_user is not None and submission.developer.user_id == auth_user.id
    is_sponsor = auth_user is not None and contest.sponsor.user_id == auth_user.id
    past_deadline = Clock.now() >= contest.deadline_at

    if not (is_owner or is_sponsor or past_deadline):
        # 다른 Developer(혹은 비로그인)에게는 진행 중인 Submission의 존재 자체를
        # 드러내지 않는다.
        raise HttpError(404, "제출물을 찾을 수 없습니다.")

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
    `Clock.now()`를 직접 비교한다 — 다른 가시성 판정과 같은 기준이다. 파일이
    움직이지 않는 것처럼(ADR-0005) 이 아카이브도 틱을 기다리지 않고 그 순간
    이미 옳다.

    데모·영상만 담는다 — 소스는 Award 전까지 아무에게도 공개되지 않고(ADR-0014),
    test_account는 "데모·영상" 칸에 없는 로그인 정보라 여기서도 내려주지 않는다
    (`_serialize`와 같은 원칙, #10 리뷰 지적).

    **탈퇴한 Developer는 404다**(#100, ADR-0025) — "공개 프로필이 닫힌다"는
    실명·소개가 비는 것이 아니라 그 존재 자체가 더 이상 조회되지 않는 것이다.
    `user.is_active`가 그 판정이다(`accounts.withdrawal.execute_withdrawal`이
    탈퇴 시 이 값을 내린다) — 다른 이유로 존재하지 않는 Developer와 같은 404를
    돌려줘 탈퇴 여부 자체도 굳이 구별해 알려주지 않는다.
    """

    developer = DeveloperProfile.objects.filter(id=developer_id).select_related("user").first()
    if developer is None or not developer.user.is_active:
        raise HttpError(404, "참가자를 찾을 수 없습니다.")

    now = Clock.now()
    submissions = (
        ContestSubmission.objects.filter(developer=developer, contest__deadline_at__lte=now)
        .select_related("contest")
        .prefetch_related("assets")
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
                assets=_public_asset_summaries(
                    s.assets.all(), contest_id=s.contest_id, developer_user_id=developer.user_id
                ),
                created_at=s.created_at,
            )
            for s in submissions
        ],
    )


def _comparison_quality(found, points: dict[int, int], bonus) -> ComparisonQualityOut | None:
    if found is None:
        return None
    review, _total, rank = found
    return ComparisonQualityOut(**quality_view(review.items, points, bonus), rank=rank)


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
        raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc

    if contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 공모전만 비교할 수 있습니다.")

    if Clock.now() < contest.deadline_at:
        raise HttpError(403, "마감 전에는 제출물을 비교할 수 없습니다.")

    requirements = list(Requirement.objects.filter(contest=contest).order_by("order", "id"))
    submissions = (
        ContestSubmission.objects.filter(contest=contest)
        .select_related("developer")
        .prefetch_related("requirement_responses__evidence_items", "assets")
        .order_by("id")
    )

    submission_outs: list[ComparisonSubmissionOut] = []
    entries_by_requirement: dict[int, list[ComparisonEntryOut]] = {r.id: [] for r in requirements}
    # 완성도(#884) — 개최자는 모든 제출작의 완성도·등수·근거를 본다.
    quality_by_submission = ranked_reviews(contest.id, [s.id for s in submissions])
    quality_points = {r.id: r.points for r in requirements}
    # 가산(#905) — 개최자가 마감 뒤 매기는 사람 점수. 완성도 기록이 없어도 입력 칸은 나간다.
    bonus_by_submission = bonus_scores(contest.id, [s.id for s in submissions])

    for submission in submissions:
        developer_name = (
            submission.developer.display_name or f"Developer#{submission.developer_id}"
        )
        responses_by_requirement = {
            r.requirement_id: r for r in submission.requirement_responses.all()
        }
        assets = list(submission.assets.all())
        # 이 화면에 나오는 자료는 데모·영상·스크린샷뿐이다 — 소스·저장소를
        # 가리키는 근거는 참조 없이 나간다(`_evidence_outs` 참고).
        visible_asset_ids = {
            a.id for a in assets if a.kind in _PUBLIC_AFTER_DEADLINE_KINDS
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
                    evidence=_evidence_outs(evidence_items, visible_asset_ids),
                    is_linked=is_linked,
                )
            )

        total = sum(1 for r in requirements if not r.hidden)  # 숨은 항목은 채움률 대상이 아니다(#906)
        submission_outs.append(
            ComparisonSubmissionOut(
                submission_id=submission.id,
                developer_id=submission.developer_id,
                developer_display_name=developer_name,
                assets=_public_asset_summaries(
                    assets,
                    contest_id=contest.id,
                    developer_user_id=submission.developer.user_id,
                ),
                completion=_completion_of(
                    assets, total_requirements=total, linked_count=linked_count
                ),
                quality=_comparison_quality(
                    quality_by_submission.get(submission.id), quality_points, bonus_by_submission[submission.id]
                ),
                bonus_scores=[
                    BonusScoreOut(requirement_id=b.item_id, score=b.score, memo=b.memo, rated=b.rated)
                    for b in bonus_by_submission[submission.id]
                ],
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
                points=r.points,
                entries=entries_by_requirement[r.id],
            )
            for r in requirements
        ],
    )


@router.put(
    "/contests/{contest_id}/submissions/{submission_id}/bonus/{requirement_id}",
    response={200: BonusScoreOut},
    auth=jwt_auth,
)
def rate_bonus(request: HttpRequest, contest_id: int, submission_id: int, requirement_id: int, payload: BonusScoreIn):
    """개최자가 제출 하나의 가산 항목에 0~5 와 한 줄 메모를 매긴다(#905, ADR-0073). 덮어쓰기다.

    **마감 뒤에만** — 비교 화면(`compare_submissions`)과 같은 기준(`deadline_at`)이다. 마감 전에는 제출물을
    볼 수 없으니 매길 것도 없다. Score·달성률·Distribution 과 무관하고 완성도 합계에만 든다."""

    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc
    if contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 공모전의 가산만 매길 수 있습니다.")
    if Clock.now() < contest.deadline_at:
        raise HttpError(409, "가산은 마감 뒤에 매길 수 있습니다.")
    requirement = Requirement.objects.filter(
        id=requirement_id, contest=contest, grade=Requirement.Grade.BONUS
    ).first()
    if requirement is None:
        raise HttpError(404, "가산 항목을 찾을 수 없습니다.")
    if not ContestSubmission.objects.filter(id=submission_id, contest=contest).exists():
        raise HttpError(404, "제출물을 찾을 수 없습니다.")
    memo = payload.memo.strip()
    SubmissionBonusScore.objects.update_or_create(
        submission_id=submission_id,
        requirement=requirement,
        defaults={"score": payload.score, "memo": memo, "rated_by_id": request.auth_user.id, "rated_at": Clock.now()},
    )
    return 200, BonusScoreOut(requirement_id=requirement.id, score=payload.score, memo=memo, rated=True)


@router.get(
    "/contests/{contest_id}/metrics",
    response={200: ContestMetricsOut},
    auth=jwt_auth,
)
def get_contest_metrics(request: HttpRequest, contest_id: int):
    """Sponsor가 자기 Contest의 건강을 본다 (#107·#108, 부모 #105).

    지금까지 Sponsor가 자기 Contest 상태를 아는 수단은 제출을 하나씩 열어보는
    것뿐이었다 — 참가가 언제부터 들어오는지, 어느 Requirement가 사람들을
    걸러내는지 알 수 없어 "참가가 없다"를 마감 직전에야 알았다. 이
    엔드포인트가 일자별 누적 Submission 수(#107)에 이어 Requirement별 충족
    분포와 제출 채움률 분포(#108)를 낸다.

    `compare_submissions`와 같은 소유권 검사를 그대로 쓴다 — 새 예외를 만들지
    않는다. **그 엔드포인트와 달리 마감 전에도 열린다** — Sponsor는 마감 전에도
    개별 Submission을 볼 수 있으므로(진행 중 비공개는 Developer 사이의
    규율이다), 집계가 마감 전에 보여도 새로 알려주는 것이 없다.

    **Score는 이 함수 어디에도 조회하지 않는다** — `scoring.models.Score`를
    import조차 하지 않는다(ADR-0006/0014). **개별 Submission·Developer도
    응답에 없다** — 아래 어느 쿼리도 developer_id를 select하지 않는다.
    """

    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "공모전을 찾을 수 없습니다.") from exc

    if contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 공모전만 지표를 볼 수 있습니다.")

    submissions_qs = ContestSubmission.objects.filter(contest=contest)
    total_submission_count = submissions_qs.count()

    # 판정은 여기(백엔드)에서 한다 — 화면은 이미 묶인 일자별 누적치를 받아
    # 그리기만 한다. `TruncDate`에 `Asia/Seoul`을 명시하는 이유는
    # `settings.TIME_ZONE`이 그것이더라도, DB가 UTC로 저장한 `created_at`을
    # 그대로 자르면 자정 근처 제출이 하루 밀려 보일 수 있기 때문이다.
    daily_counts = (
        submissions_qs.annotate(
            day=TruncDate("created_at", tzinfo=timezone.get_current_timezone())
        )
        .values("day")
        .annotate(count=Count("id"))
        .order_by("day")
    )

    cumulative = 0
    daily_participation: list[DailyParticipationOut] = []
    for row in daily_counts:
        cumulative += row["count"]
        daily_participation.append(
            DailyParticipationOut(date=row["day"].isoformat(), cumulative_count=cumulative)
        )

    # #108 — Requirement별 충족 분포. 한 질의로 (requirement_id -> 충족 건수)를
    # 얻는다 — Requirement 수만큼 질의를 내면 요구사항이 많은 Contest에서
    # N+1이 된다. 분모는 total_submission_count다: 그 Requirement에 자가
    # 응답이 아예 없는 Submission도 "충족하지 못함"으로 세야
    # `RequirementFulfillmentOut`의 docstring이 약속한 채점 원칙과 맞는다.
    # `submission__contestsubmission__contest`로 부모(RequirementResponse.
    # submission, 손대지 않은 FK)에서 자식으로 내려간다 — #270 이후 `contest`는
    # 자식(`ContestSubmission`)에만 있다.
    met_counts_by_requirement = dict(
        RequirementResponse.objects.filter(
            submission__contestsubmission__contest=contest, is_met=True
        )
        .values("requirement_id")
        .annotate(met=Count("id"))
        .values_list("requirement_id", "met")
    )
    requirements = list(Requirement.objects.filter(contest=contest).order_by("order", "id"))
    requirement_fulfillment = [
        RequirementFulfillmentOut(
            requirement_id=requirement.id,
            text=requirement.text,
            grade=requirement.grade,
            met_count=met_counts_by_requirement.get(requirement.id, 0),
            total_submission_count=total_submission_count,
        )
        for requirement in requirements
    ]

    # #108 — 제출 채움률 분포. 세 boolean을 한 집계 질의로 센다(`Count` +
    # `filter=~Q(...)`) — Submission마다 훑지 않는다.
    # 세는 것은 여전히 "그 자료를 **하나라도** 가진 Submission 수"다(자료 수가
    # 아니다) — `Count(distinct=True)`가 그것이다. 다중화 이후 자료 수를 그대로
    # 세면 영상 다섯 편을 낸 한 사람이 분모(제출 수)를 넘겨 100%를 넘는 비율이
    # 나온다.
    completion_agg = submissions_qs.aggregate(
        demo_video_count=Count(
            "id", filter=Q(assets__kind__in=_DEMO_VIDEO_KINDS), distinct=True
        ),
        demo_url_count=Count(
            "id", filter=Q(assets__kind=SubmissionAsset.Kind.DEMO_URL), distinct=True
        ),
        repository_count=Count(
            "id", filter=Q(assets__kind=SubmissionAsset.Kind.REPOSITORY), distinct=True
        ),
        test_account_count=Count(
            "id", filter=~Q(assets__test_account=""), distinct=True
        ),
    )
    completion_distribution = CompletionDistributionOut(
        total_submission_count=total_submission_count,
        demo_video_count=completion_agg["demo_video_count"],
        demo_url_count=completion_agg["demo_url_count"],
        test_account_count=completion_agg["test_account_count"],
        repository_count=completion_agg["repository_count"],
    )

    # #109 — 조회수와 전환율. 쓰기는 `contests.view_tracking`이 캐시에서
    # 이미 해 뒀다 — 이 함수는 읽기만 한다(Score를 조회하지 않는 것과 같은
    # 이유로, 새 쓰기 경로를 여기 만들지 않는다). **읽는 값은 캐시가 아니라
    # `contest.view_count`(DB)다(#446)** — 공개 목록·큐레이션과 같은 값을
    # 읽어야 개최자가 자기 지표 화면과 공개 카드에서 같은 숫자를 본다(최대
    # 10분 늦음, `contests.view_flush`). 조회가 0이면 0으로 나누지 않고
    # None을 낸다.
    view_count = contest.view_count
    conversion_rate = (
        total_submission_count / view_count if view_count > 0 else None
    )
    view_metrics = ViewMetricsOut(view_count=view_count, conversion_rate=conversion_rate)

    return 200, ContestMetricsOut(
        contest_id=contest.id,
        total_submission_count=total_submission_count,
        daily_participation=daily_participation,
        requirement_fulfillment=requirement_fulfillment,
        completion_distribution=completion_distribution,
        view_metrics=view_metrics,
    )
