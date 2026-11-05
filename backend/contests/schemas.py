from datetime import datetime
from enum import Enum

from ninja import Schema
from pydantic import Field
from contests.curation import HomeCurationBucket
from contests.sponsorship import SponsorNextAction, sponsor_next_action_for


class CategoryOut(Schema):
    id: int
    name: str


class ContestSort(str, Enum):
    """공개 목록의 정렬 축 (#39).

    값 문자열은 URL 에 그대로 보이므로 프론트의 `?sort=` 와 같은 어휘를 쓴다
    (frontend/app/contests/page.tsx).
    """

    DEADLINE = "deadline"
    PRIZE = "prize"
    # 검색어(q)가 있을 때의 기본 정렬(#449, 부모 #444 스펙) — 검색 모듈
    # (`contests.search`)이 돌려준 id 순서 그대로다.
    RELEVANCE = "relevance"


class ContestListFilters(Schema):
    """`GET /api/contests` 의 필터·정렬 쿼리 (#39, `q`는 #449).

    api.py 가 아니라 여기 두는 이유가 있다 — api.py 는 `from __future__ import
    annotations` 를 쓰기 때문에, 엔드포인트 함수 시그니처에 Enum 을 직접 적으면
    ninja 가 만드는 쿼리 모델이 그 이름을 해석하지 못해 `QueryParams is not fully
    defined` 로 **500** 이 난다(직접 재현해 확인했다). 이 모듈에는 그 임포트가
    없으므로 Schema 로 감싸면 pydantic 이 제자리에서 해석한다.

    타입이 여기 모여 있어 얻는 것도 있다 — 이 스키마가 OpenAPI 에 그대로 실리고,
    프론트는 `pnpm generate:api` 로 같은 union 타입을 받는다(#28).

    알 수 없는 값은 500 이 아니라 4xx 여야 한다 — `sort` 는 Enum 이라, id 두 개는
    int 라 ninja 가 422 로 막는다. 존재하지 않는 id 는 오류가 아니라 빈 목록이다
    (필터는 "그런 게 있느냐"가 아니라 "그것으로 좁혀라"이다).

    `closed`(#227)는 `category`/`deliverable_type`과 다른 축이다 — 저 둘은 AND로
    좁히는 필터지만, `closed`는 **무엇을 보여줄지 자체**를 가른다(참가 가능 vs
    마감됨). 기본값 `False`가 "지금 참가할 수 있는 것"이다 — 예전 기본값(전부
    보여주고 마감 오름차순 정렬)은 마감된 Contest가 정의상 항상 과거라 첫 페이지
    위쪽을 가장 오래전에 끝난 것들로 채웠다.

    `q`(#449)가 있으면 `contests.search`의 검색 모듈이 돌려준 id 순서로 좁힌다.
    `sort`는 명시하지 않으면(`None`) **`q`가 있는가에 따라 기본값이 갈린다** —
    검색어가 있으면 관련도순, 없으면 마감임박순이다(부모 #444 스펙 "검색어가 있고
    정렬이 지정되지 않으면 관련도순이다"). 그래서 `sort` 자체의 기본값은 `None`이지
    `ContestSort.DEADLINE`이 아니다 — pydantic 기본값은 "클라이언트가 안 줬다"를
    구분하지 못하므로, 그 구분이 필요한 이 갈래는 `api.py`가 `None`을 보고 직접
    판단한다.
    """

    q: str | None = None
    category: int | None = None
    deliverable_type: int | None = None
    sort: ContestSort | None = None
    closed: bool = False


class DeliverableTypeOut(Schema):
    id: int
    name: str
    minimum_prize: int


# --- 운영자 표면(#80) --------------------------------------------------------
#
# 공개용 `DeliverableTypeOut`과 갈라 둔 이유: 운영자 화면은 비활성 종류도 봐야
# 하므로(이미 그 종류를 쓰는 Contest가 있을 수 있고, 되살릴 방법을 판단하려면
# 지금 꺼져 있다는 사실 자체를 봐야 한다) `is_active`가 필요하다. 참가자에게는
# 그 필드를 보여줄 이유가 없다 — 공개 목록은 애초에 활성 종류만 돌려준다.


class OperatorDeliverableTypeOut(Schema):
    id: int
    name: str
    minimum_prize: int
    is_active: bool


# DeliverableType.minimum_prize는 Django PositiveIntegerField로, Postgres의
# `integer`(4바이트) 컬럼이다 — 상한을 안 걸면 그 열의 실제 상한(2**31-1)을
# 넘는 입력이 `DataError: integer out of range`로 500이 된다(코드리뷰 지적,
# 재현됨). `policies.services._FIELD_BOUNDS`가 withholding_minor_income_exempt_won
# 에 같은 상한을 명시해 둔 것과 같은 이유로, 여기서도 4xx가 나야 할 자리에서
# 500이 나지 않게 한다.
_POSITIVE_INT_MAX = 2**31 - 1


class DeliverableTypeCreateIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    minimum_prize: int = Field(ge=0, le=_POSITIVE_INT_MAX)
    # 정책 변경과 같은 규율(#76) — 새 종류를 추가하는 것도 근거가 남아야 한다.
    reason: str


class DeliverableTypeUpdateIn(Schema):
    minimum_prize: int = Field(ge=0, le=_POSITIVE_INT_MAX)
    reason: str


class DeactivateDeliverableTypeIn(Schema):
    reason: str


class DeliverableTypeChangeOut(Schema):
    id: int
    deliverable_type_id: int
    operator_username: str
    action: str
    reason: str
    before: dict
    after: dict
    changed_at: datetime


# --- Category 운영자 관리 (#231) — DeliverableType과 같은 무게(위 주석 참고), 다만
# minimum_prize가 없는 대신 이름을 고칠 수 있다. `CategoryOut`(공개, id·name만)과 갈라
# 두는 이유도 위 `OperatorDeliverableTypeOut`과 같다 — 운영자는 비활성 Category도 봐야
# 한다.


class OperatorCategoryOut(Schema):
    id: int
    name: str
    is_active: bool


class CategoryCreateIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    reason: str


class CategoryRenameIn(Schema):
    name: str = Field(min_length=1, max_length=100)
    reason: str


class DeactivateCategoryIn(Schema):
    reason: str


class CategoryChangeOut(Schema):
    id: int
    category_id: int
    operator_username: str
    action: str
    reason: str
    before: dict
    after: dict
    changed_at: datetime


# --- 무료 공모전 개최 권한 (#414, ADR-0048) ---------------------------------


class HostingPermissionAccountOut(Schema):
    """계정 검색 결과 한 줄 — 지금 개최 권한이 있는지까지 함께 보여준다(운영자가
    검색 결과에서 바로 켜고 끌 대상을 고를 수 있어야 한다)."""

    user_id: int
    email: str
    nickname: str
    is_granted: bool


class SetHostingPermissionIn(Schema):
    granted: bool
    reason: str


class HostingPermissionSelfOut(Schema):
    """로그인한 사용자 본인의 개최 권한 상태 (#415) — 공개 앱의 무료 공모전
    만들기 화면이 진입 전에 확인한다(권한이 없으면 안내를 보인다)."""

    is_granted: bool


class HostingPermissionChangeOut(Schema):
    id: int
    user_id: int
    user_email: str
    operator_username: str
    action: str
    reason: str
    changed_at: datetime


class OperatorFreeContestWinnerOut(Schema):
    """무료 공모전 목록 한 줄의 수상자 — 「운영팀 알림 보내기」가 그대로 받는
    사람으로 채워 쓰는 값 모양이다(#418 `RecipientOut`과 같은 필드)."""

    user_id: int
    email: str
    nickname: str


class OperatorFreeContestOut(Schema):
    """운영자 앱 무료 공모전 목록 한 줄 (#420) — 상태·마감·수상 여부. Award가
    없으면(아직 심사 중이거나, 심사 기간 안에 고르지 않고 끝났으면) `winner`가
    비어 있다."""

    id: int
    title: str
    status: str
    deadline_at: datetime
    judging_ends_at: datetime | None
    winner: OperatorFreeContestWinnerOut | None


class QuoteIn(Schema):
    deliverable_type_ids: list[int]


class QuoteOut(Schema):
    deliverable_type_ids: list[int]
    minimum_total: int


class RequirementIn(Schema):
    text: str = Field(max_length=500)
    grade: str  # "required" | "optional"
    #: 배점 1~10(완성도에만 쓴다, #904 ADR-0073). 없으면 등급별 기본값(필수 2·선택 1).
    points: int | None = Field(default=None, ge=1, le=10)


class RequirementOut(Schema):
    id: int
    text: str
    grade: str
    points: int
    order: int


class ContestImageOut(Schema):
    """ContestImage 하나 (#234/#235, ADR-0031/0032).

    `url`·`thumbnail_url`은 백엔드가 이미 조립한 서명 없는 공개 주소다
    (`ContestImage.url`/`.thumbnail_url` 프로퍼티, `storage.public.
    compose_public_image_url`) — 화면은 "무엇을 보여줄지"를 다시 판정하지
    않는다. 목록은 `thumbnail_url`을, 상세는 `url`을 그대로 쓴다(spec #225 AC).
    최적화 전이거나(스캔 한 회차의 틈) 실패가 상한에 이르러 「최적화 불가」로
    확정됐으면 둘 다 원본을 가리킨다 — 화면이 "최적화됐는가"를 다시 판정할
    필요가 없다.
    """

    id: int
    url: str
    thumbnail_url: str
    order: int


class ContestImageUploadUrlIn(Schema):
    content_type: str


class ContestImageUploadUrlOut(Schema):
    object_key: str
    upload_url: str
    method: str
    # presigned POST(#234)의 서명된 정책 필드 — multipart/form-data 본문에
    # `file`보다 먼저 실어야 한다. PUT 이었던 시절에는 없었다(빈 dict).
    fields: dict[str, str]
    expires_at: str


class ContestImageCreateIn(Schema):
    object_key: str = Field(max_length=600)


class ContestImageReorderIn(Schema):
    order: int = Field(ge=0)


class ContestCreateIn(Schema):
    title: str = Field(max_length=200)
    category_id: int
    deliverable_type_ids: list[int]
    description: str = ""
    # Prize는 Sponsor가 실제로 예치하는 금액이다 — 0 이하는 개최로 성립하지 않는다.
    # 스키마에서 막지 않으면 음수가 PositiveIntegerField의 DB CHECK에 걸려 422 대신
    # 500이 난다.
    prize: int = Field(gt=0)
    deadline_at: datetime
    requirements: list[RequirementIn] = []


class FreeContestCreateIn(Schema):
    """무료 공모전 초안 생성 입력 (#415, ADR-0048) — `ContestCreateIn`과 달리
    `prize`가 없다: 무료 공모전은 상금·결제·Escrow가 없으므로 애초에 받지
    않는다(0을 받아 무시하는 것이 아니라 필드 자체가 없다)."""

    title: str = Field(max_length=200)
    category_id: int
    deliverable_type_ids: list[int]
    description: str = ""
    deadline_at: datetime
    requirements: list[RequirementIn] = []
    # 「클래스에서 들여오기」 허용 (#547, ADR-0054).
    allows_classroom_import: bool = False


class ContestUpdateIn(Schema):
    """Contest 브리프를 고치는 요청 (#113, 부모 #110; 제출 기간 중 편집은 #473,
    ADR-0051).

    전부 선택 필드다 — Sponsor가 한 화면에서 한 번에 몇 개를 고치든, 건드리지
    않은 필드는 `None`으로 와서 그대로 둔다(부분 갱신). `deliverable_type_ids`가
    `None`이 아니라 빈 리스트로 오면 `create_contest`와 같은 이유로 422다 —
    산출물 종류를 전부 비우는 것은 유효한 개최 상태가 아니다.

    DRAFT뿐 아니라 제출을 받는 동안(PUBLISHED)에도 쓰인다 — 게이트는
    `_get_owned_content_editable_contest`가 진다(소유자가 아니면 404, 마감
    이후(CLOSED 이후)면 409). **`prize`는 PUBLISHED에서는 받지 않는다** — 이미
    결제·Escrow가 확정한 금액이라 `contests.api.update_contest`가 422로
    거절한다. `deadline_at`은 지금 시각보다 뒤여야 한다(이미 지난 시각은 422).
    """

    title: str | None = Field(default=None, max_length=200)
    category_id: int | None = None
    deliverable_type_ids: list[int] | None = None
    description: str | None = None
    prize: int | None = Field(default=None, gt=0)
    deadline_at: datetime | None = None
    # 「클래스에서 들여오기」 허용 (#547) — 무료 공모전만 받는다(유료는 422).
    allows_classroom_import: bool | None = None


class ContestOut(Schema):
    id: int
    title: str
    category: CategoryOut
    deliverable_types: list[DeliverableTypeOut]
    description: str
    prize: int
    deadline_at: datetime
    status: str
    required_minimum_prize: int
    is_underfunded: bool
    # 무료 공모전인가(#415, ADR-0048) — 참이면 상금·결제·Escrow가 없다. 화면은
    # 이 값으로 「무료 공모전」 표시를 붙이고 상금 관련 표시를 감춘다.
    is_free: bool = False
    # 「클래스에서 들여오기」 허용 (#547, ADR-0054) — 무료 공모전에서만 참일 수 있다.
    allows_classroom_import: bool = False
    requirements: list[RequirementOut]
    # Sponsor가 붙인 참고 이미지 (#234, ADR-0032) — 순서대로 온다. 빈 목록이면
    # 화면이 "이미지가 없는 게 의도됐다"로 그린다(spec #225 user story 15).
    images: list[ContestImageOut] = []
    # 유찰 재개최(#22, ADR-0001)로 만들어진 사본이면 원본 Contest의 id를 가리킨다.
    # 원본이면 None이다.
    source_contest_id: int | None = None
    created_at: datetime
    # 심사기간 종료 시각(#13, ADR-0003) — CLOSED로 전이하기 전에는 아직 null이다.
    # deadline_at처럼 "언제까지"를 알려주는 사실 정보라 공개해도 무방하다.
    #
    # judging_extension_count·refund_disabled는 **일부러 여기 넣지 않는다** —
    # Sponsor가 유료 연장을 몇 번 샀는지, 환불이 잠겼는지는 그 Sponsor의 상업적
    # 정보다(#13 리뷰 지적 8). 이 스키마는 인증 없이도 누구나 받는 공개 목록/상세
    # 응답에 그대로 쓰이므로(contests.api.list_contests/get_contest), 여기 넣으면
    # 익명 방문자도 볼 수 있게 된다. 이 값들은 JudgingExtensionPaymentOut(연장
    # 확정 응답, Sponsor 본인 인증 필요)과 Django admin(운영자 전용)에서만 노출한다.
    judging_ends_at: datetime | None
    # 실제 Submission 수 (#106, spec #105). **개별 Submission을 여는 것이
    # 아니다** — ADR-0014가 감추는 것은 진행 중 개별 제출물이고, 이 필드는 집계
    # 하나뿐이다(마감 전에도 노출된다). 0도 그대로 싣는다 — "아직 참가작이
    # 없습니다"라는 문구를 만드는 것은 화면의 몫이지 이 스키마의 몫이 아니다
    # (숫자와 문구를 다른 층에 둔다는 것이 #106 인수조건).
    #
    # 이 값은 항상 `contests.api._serialize_contest` 호출부가 미리 annotate하거나
    # (list_contests/get_contest/get_home_curation) 새로 만든 Contest에 0으로
    # 채워 넣은(`create_contest`/`reopen_contest`) `Contest.submission_count`
    # 에서 온다 — 화면과 마찬가지로 이 스키마도 따로 세지 않는다.
    submission_count: int
    # 누적 조회수(#446, spec #444) — `Contest.view_count`(DB)를 그대로 싣는다.
    # `contests.view_tracking`이 Redis로 실시간 집계하는 값과 최대 10분 차이가
    # 날 수 있다(`contests.view_flush` 옮기기 스캔 주기) — 개최자 지표 화면
    # (`ViewMetricsOut.view_count`)도 같은 DB 값을 읽으므로 두 화면이 서로
    # 다른 숫자를 보이지 않는다. #109 시절에는 조회수가 Sponsor 전용이라 이
    # 스키마(공개 목록·상세·홈 큐레이션이 함께 쓴다)에 없었다 — 지금은
    # 공개 카드에도 보이는 값이라 여기 있다.
    view_count: int = 0
    # 이 응답을 받은 사람이 이 Contest의 Sponsor 본인인가 (#164). `SubmissionOut.
    # is_owner`(submissions/schemas.py)와 같은 패턴 — 공개 상세는 인증 없이도
    # 응답하므로 익명·타인에게는 항상 False다. 값의 정확도를 보장하는 것은
    # `contests.api.get_contest` 하나뿐이다(auth_user를 실제로 넘긴다) — 목록·홈
    # 큐레이션처럼 "이 화면에 자기 것이 섞여 있는가"가 의미 없는 자리는 계산 비용을
    # 아끼려 기본값 False를 그대로 둔다. 프론트가 소유자 CTA를 감추는 유일한 근거는
    # 이 필드이므로, 새 호출부를 추가할 때 "내 것인지가 화면에 드러나는가"를 먼저
    # 따져야 한다.
    is_owner: bool = False
    # 이 응답을 받은 사람이 이미 이 Contest에 Submission을 낸 적이 있는가 (#245).
    # `is_owner`와 같은 자리·같은 이유로 계산한다 — 공개 상세는 인증 없이도
    # 응답하므로 익명 방문자에게는 항상 False고, `contests.api.get_contest`만
    # `auth_user`를 실제로 넘겨 정확한 값을 낸다. 공개 상세의 제출 CTA가 "제출한
    # 사람에게는 문구가 다르다"(수정임을 누르기 전에 알린다)를 판정하는 유일한
    # 근거다 — 화면이 별도로 `GET .../submissions/me`를 불러 재판정하지 않는다
    # (이 필드가 이미 하는 조회를 화면에서 다시 하면 익명 방문자에게는 401을
    # 낳는 별도 인증 필요 호출이 하나 더 생긴다).
    has_own_submission: bool = False
    # 개최자의 공개용 표시 이름 (#447) — 비어 있으면 null이다. 실명·이메일은
    # 어떤 경우에도 여기 싣지 않는다(SponsorProfile.display_name만 읽는다,
    # `contests.api._serialize_contest`). 공개 목록(list_contests)·랜딩
    # 큐레이션(get_home_curation)이 인증 없이도 이 스키마를 그대로 쓰므로
    # 익명 방문자도 이 필드를 받는다 — 그래서 공개해도 되는 값만 담는다.
    sponsor_display_name: str | None = None


class HomeCurationGroupOut(Schema):
    """홈의 한 묶음 — 큐레이션 식별자와 그 안의 공모전들 (#94, spec #92).

    `MySponsoredContestOut.next_action`과 같은 이유로 `bucket`의 타입이 `str`가
    아니라 `HomeCurationBucket`이다 — 생성된 프론트 타입에서 4개짜리 리터럴
    유니온이 되고, 값이 하나 늘면 번역표를 가진 파일(`Record<Bucket, …>`)에서
    `tsc --noEmit`이 빌드타임에 잡는다.

    `contests`가 빈 배열이어도 이 스키마의 인스턴스 자체는 항상 존재한다 —
    `GET /api/contests/home`이 네 묶음을 항상 다 돌려주므로, 어떤 묶음이 비어
    있어도 화면이 그 섹션을 통째로 지우지 않고 "비어 있다"고 보여줄 수 있다
    (#94 인수조건).
    """

    bucket: HomeCurationBucket
    contests: list[ContestOut]


class InitiateJudgingExtensionIn(Schema):
    pass


class ConfirmJudgingExtensionIn(Schema):
    # fake PG 전용 시나리오 선택. 실제 어댑터에서는 무시된다(payments.schemas의
    # ConfirmPaymentIn과 같은 원칙, ADR-0007).
    simulate: str | None = None
    # 결제 건 식별자(#86, payments.schemas.ConfirmPaymentIn과 같은 이유) —
    # PGAdapter.confirm 계약에 이 필드가 생겼는데 이 두 번째 호출부가 안 넓히면
    # #87이 실물 어댑터로 갈아끼우는 순간 연장 결제만 조용히 이 값 없이
    # confirm을 호출하게 된다. FakePGAdapter는 이 값을 무시하므로 optional이다.
    payment_key: str | None = None


class JudgingExtensionPaymentOut(Schema):
    """payments.schemas.PaymentOut과 같은 형태 — 결제 시도 하나의 현재 상태."""

    order_id: str
    contest_id: int
    amount: int
    extension_number: int
    status: str
    checkout_url: str | None = None
    created_at: datetime
    # 이 응답을 만드는 시점 Contest의 최신 심사기간 상태(Sponsor 본인에게만
    # 노출된다 — 이 엔드포인트들은 jwt_auth + sponsor 소유 확인을 거친다).
    judging_ends_at: datetime | None
    judging_extension_count: int
    refund_disabled: bool


class RequirementCreateIn(Schema):
    text: str = Field(min_length=1, max_length=500)
    grade: str  # "required" | "optional"
    #: 배점 1~10(#904). 없으면 등급별 기본값(필수 2·선택 1).
    points: int | None = Field(default=None, ge=1, le=10)


class RequirementPointsIn(Schema):
    """배점만 고친다(#904, ADR-0073) — 마감 뒤에도 열려 있고 변경 이력·알림을 남기지 않는다."""

    points: int = Field(ge=1, le=10)


class RequirementUpdateIn(Schema):
    text: str | None = Field(default=None, min_length=1, max_length=500)
    grade: str | None = None
    # Requirement.order는 PositiveIntegerField(0 허용)라 DB CHECK가 "order" >= 0
    # 이다. ContestCreateIn.prize(위 Field(gt=0))와 같은 이유로 여기서 막지 않으면
    # 음수 order가 422가 아니라 IntegrityError -> 500으로 샌다.
    order: int | None = Field(default=None, ge=0)


class RequirementChatMessageIn(Schema):
    message: str = Field(min_length=1, max_length=2000)


class RequirementProposalOut(Schema):
    text: str
    grade: str


class RequirementChatTurnOut(Schema):
    role: str
    content: str
    created_at: datetime


class RequirementChatResponseOut(Schema):
    reply: str
    proposed_requirements: list[RequirementProposalOut]
    messages: list[RequirementChatTurnOut]


class ContestReopenIn(Schema):
    """유찰 재개최 시 새로 지정하는 값 — Prize와 마감기한뿐이다(#22).

    요구사항·체크리스트·DeliverableType·Category·제목·설명은 원본에서 그대로
    복제되므로 여기서 다시 받지 않는다(ADR-0001 — "요구사항 명세를 처음부터
    다시 쓰지 않는다").
    """

    prize: int = Field(gt=0)
    deadline_at: datetime


class MySponsoredContestOut(Schema):
    """「내 공모전」의 한 행 (#81) — Sponsor 가 자기가 연 공모전을 볼 때 받는 것.

    참가자 쪽 `MyParticipationOut` 과 같은 모양이다: **도메인 상태가 아니라
    「다음 행동」이 주인공**이고, 그 판정은 백엔드가 한다.

    `next_action` 의 타입이 `str` 이 아니라 `SponsorNextAction` 인 것이 중요하다 —
    생성된 프론트 타입에서 12개짜리 리터럴 유니온이 되고, 값이 하나 늘면 번역표를
    가진 파일에서 `tsc --noEmit` 이 빌드타임에 잡는다. `str` 로 두면 `string` 이
    되어 그 안전망이 통째로 사라진다(#74 에서 실제로 겪고 고친 실수다).

    **`is_holding_distribution` 같은 이름을 따로 두지 않는다.** 보류는 「다음
    행동」의 한 값이다 — 별도 불리언을 두면 화면이 두 값을 조합해 문장을 만들게
    되고, 그 조합은 다시 화면의 파생 로직이다.
    """

    contest_id: int
    title: str
    prize: int
    status: str
    deadline_at: datetime
    judging_ends_at: datetime | None = None
    # 몇 명이 냈는지가 그 자리에서 보여야 심사하러 갈지 판단할 수 있다.
    submission_count: int
    next_action: SponsorNextAction
    # 「수정하기」를 보일지 — 수정 게이트와 같은 판정(`Contest.is_content_editable`, #881).
    # 화면이 `status` 를 직접 비교하지 않는다.
    can_edit: bool
    created_at: datetime

    @staticmethod
    def resolve_contest_id(obj) -> int:
        return obj.id

    @staticmethod
    def resolve_can_edit(obj) -> bool:
        return obj.is_content_editable

    @staticmethod
    def resolve_submission_count(obj) -> int:
        # 목록 질의가 `annotate` 로 붙여 준다 — 행마다 세면 N+1 이다.
        return obj.submission_count

    @staticmethod
    def resolve_next_action(obj) -> str:
        # `now` 는 목록 엔드포인트가 요청 스코프에서 **한 번** 구해 각 행에
        # 붙여 둔 값이다 — 여기서 `Clock.now()` 를 부르면 행마다 ClockOverride
        # 조회가 나가고, 게다가 한 화면 안에서 행마다 다른 시각으로 판정하게
        # 된다(마감 직전 목록에서 실제로 갈릴 수 있다).
        return sponsor_next_action_for(obj, now=obj.judged_as_of)


class MySponsoredContestPageOut(Schema):
    """「내 공모전」 한 페이지 (#152) — 운영자 지급 큐의 `OperatorPayoutPageOut`
    (payouts/schemas.py, #151)과 같은 모양이다.

    `count` 는 **전체** 건수다(이 페이지의 길이가 아니다). `next` 는 「마지막으로
    본 행 다음부터」를 가리키는 커서이고, 더 없으면 null 이다 — 「더 있는가」를
    받은 수와 전체 건수의 비교가 아니라 **다음 커서의 유무**로 판정한다(#150 이
    적은 증상 중 하나다).
    """

    items: list[MySponsoredContestOut]
    count: int
    next: str | None

