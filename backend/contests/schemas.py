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


class ContestListFilters(Schema):
    """`GET /api/contests` 의 필터·정렬 쿼리 (#39).

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
    """

    category: int | None = None
    deliverable_type: int | None = None
    sort: ContestSort = ContestSort.DEADLINE
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
    # 예약된 Assignment Category(#213, ADR-0033)인가 — 화면이 이 값 하나로 편집·감추기
    # 버튼을 꺼서, "왜 이 행만 안 먹히지"를 백엔드 422 메시지에서 처음 알게 하지 않는다.
    is_reserved: bool


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


class QuoteIn(Schema):
    deliverable_type_ids: list[int]


class QuoteOut(Schema):
    deliverable_type_ids: list[int]
    minimum_total: int


class RequirementIn(Schema):
    text: str = Field(max_length=500)
    grade: str  # "required" | "optional"


class RequirementOut(Schema):
    id: int
    text: str
    grade: str
    order: int


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


class ContestUpdateIn(Schema):
    """DRAFT Contest를 고치는 요청 (#113, 부모 #110).

    전부 선택 필드다 — Sponsor가 한 화면에서 한 번에 몇 개를 고치든, 건드리지
    않은 필드는 `None`으로 와서 그대로 둔다(부분 갱신). `deliverable_type_ids`가
    `None`이 아니라 빈 리스트로 오면 `create_contest`와 같은 이유로 422다 —
    산출물 종류를 전부 비우는 것은 유효한 개최 상태가 아니다.

    결제가 문을 닫기 전(DRAFT)에만 이 스키마가 쓰인다 — 게이트는
    `_get_owned_draft_contest`가 진다(소유자가 아니면 404, DRAFT가 아니면 409).
    """

    title: str | None = Field(default=None, max_length=200)
    category_id: int | None = None
    deliverable_type_ids: list[int] | None = None
    description: str | None = None
    prize: int | None = Field(default=None, gt=0)
    deadline_at: datetime | None = None


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
    requirements: list[RequirementOut]
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
    # 이 응답을 받은 사람이 이 Contest의 Sponsor 본인인가 (#164). `SubmissionOut.
    # is_owner`(submissions/schemas.py)와 같은 패턴 — 공개 상세는 인증 없이도
    # 응답하므로 익명·타인에게는 항상 False다. 값의 정확도를 보장하는 것은
    # `contests.api.get_contest` 하나뿐이다(auth_user를 실제로 넘긴다) — 목록·홈
    # 큐레이션처럼 "이 화면에 자기 것이 섞여 있는가"가 의미 없는 자리는 계산 비용을
    # 아끼려 기본값 False를 그대로 둔다. 프론트가 소유자 CTA를 감추는 유일한 근거는
    # 이 필드이므로, 새 호출부를 추가할 때 "내 것인지가 화면에 드러나는가"를 먼저
    # 따져야 한다.
    is_owner: bool = False


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
    created_at: datetime

    @staticmethod
    def resolve_contest_id(obj) -> int:
        return obj.id

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


# --- Assignment(ADR-0028, #207) — 상금·결제·Award·Escrow가 전혀 나오지 않는다 ------------


class AssignmentCreateIn(Schema):
    """`ContestCreateIn`과 같은 자리지만 `category_id`·`prize`가 없다 — Category는
    `contests.assignment_category`가 자동 배정하고(스펙 #197), Prize는 0으로 고정된다
    (ADR-0028)."""

    title: str = Field(max_length=200)
    deliverable_type_ids: list[int]
    description: str = ""
    deadline_at: datetime
    requirements: list[RequirementIn] = []


class AssignmentUpdateIn(Schema):
    """DRAFT·ASSIGNMENT_OPEN Assignment를 고치는 요청(#207/#217) — `ContestUpdateIn`과
    달리 `prize`·`category_id`가 없다. 전부 선택 필드다(부분 갱신, `ContestUpdateIn`과
    같은 규율) — `requirements`가 `None`(필드를 아예 보내지 않음)이면 기존 체크리스트를
    건드리지 않는다.

    `requirements`가 있으면(빈 리스트 포함) **통째 교체**다(#217) — 기존 항목을 부분
    수정하는 것이 아니라 옛 항목을 전부 지우고 새 목록으로 다시 만든다. 그래서 이
    리스트 안의 개별 항목에는 `id`가 없다(`RequirementIn`은 생성 스키마와 같은 모양 —
    `text`·`grade`뿐이다) — 통째 교체이므로 "이 id의 항목을 이렇게 고친다"는 요청
    자체가 성립하지 않는다."""

    title: str | None = Field(default=None, max_length=200)
    description: str | None = None
    deliverable_type_ids: list[int] | None = None
    deadline_at: datetime | None = None
    requirements: list[RequirementIn] | None = None


class AssignmentOut(Schema):
    """`ContestOut`과 같은 자리지만 상금·결제·Award·Escrow에 닿는 필드가 하나도 없다
    (스펙 #197 인수조건 — 과제 화면에 그 개념이 전혀 나타나지 않는다).

    `invite_code`는 열리기 전(DRAFT)에는 null이고, 연 뒤에는 활성 InviteCode의 값이다
    (재발급(#209) 후에는 언제나 최신 값 하나 — 옛 코드는 비활성화될 뿐 응답에
    나타나지 않는다).

    `submission_count`는 「첫 제출이 문을 닫는다」(#209)를 화면이 미리 알 수 있게
    한다 — Sponsor가 PATCH를 시도해 409를 받고서야 이유를 아는 것이 아니라, 제출이
    1건이라도 있으면 화면이 애초에 편집 폼 대신 잠금 안내를 보여준다.

    `is_editable`은 그 판정을 화면 대신 **백엔드가 직접 계산해 실어 보낸다**(#209
    코드리뷰 지적). `EDITABLE`(status)과 "ASSIGNMENT_OPEN이면서 제출 0건"이라는 두
    조건이 합쳐진 값인데, 프론트가 `status === "draft" || status === "assignment_open"`
    처럼 그 규칙을 화면에서 다시 적으면 백엔드가 규칙을 하나 더 얹을 때마다(이번
    티켓이 바로 그 경우다) 화면이 따로 갱신되지 않는 한 어긋난다 — 그러면 이미
    `_get_owned_editable_assignment`가 409로 막는 상태인데도 화면은 편집 폼을 계속
    보여주는 fail-open이 생긴다. `is_owner`가 이미 같은 자리에서 같은 이유로
    계산되어 나가는 값이라 그 옆에 나란히 둔다.
    """

    id: int
    title: str
    deliverable_types: list[DeliverableTypeOut]
    description: str
    deadline_at: datetime
    status: str
    requirements: list[RequirementOut]
    created_at: datetime
    invite_code: str | None = None
    is_owner: bool = False
    submission_count: int = 0
    is_editable: bool = False


class AssignmentSubmissionScoreOut(Schema):
    """Sponsor 가 보는 채점 결과 — Developer 자신이 보는 `submissions.schemas.OwnScoreOut`과
    같은 자리이지만 이의 관련 필드(`appeal_deadline`·`can_appeal`)가 없다. 과제에는
    이의제기가 없다(스펙 #197 Out of Scope) — Sponsor 화면에 그 개념을 만들 이유가 없다.

    `prompt`는 여기도 없다 — 소스가 통째로 임베드돼 있어 응답 크기 상한이 사라진다
    (`OwnScoreOut`과 같은 이유, #72). 소스를 직접 보는 경로는 따로 있다(#211, ADR-0022).
    """

    percentage: str
    model_version: str
    reasoning: list[dict]
    created_at: datetime


class AssignmentSubmissionOut(Schema):
    """Sponsor 의 제출 목록 한 행(#210) — 채점 전에는 `score`가 null이다(빈 배열도 0도
    아니다: "아직 안 됐다"와 "0점"은 다른 사실이다)."""

    submission_id: int
    developer_id: int
    # 탈퇴한 학생은 없다 — Assignment 는 Developer 탈퇴로 Submission 이 사라지지
    # 않는다. `display_name`이 비어 있을 수 있는 것은 오히려 Sponsor 쪽이다(#212,
    # ADR-0025) — 이 화면은 이름이 빈 학생을 다루지 않는다.
    developer_display_name: str
    created_at: datetime
    score: AssignmentSubmissionScoreOut | None = None
