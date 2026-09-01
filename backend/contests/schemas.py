from datetime import datetime
from enum import Enum

from ninja import Schema
from pydantic import Field
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
    """

    category: int | None = None
    deliverable_type: int | None = None
    sort: ContestSort = ContestSort.DEADLINE


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


class InitiateJudgingExtensionIn(Schema):
    pass


class ConfirmJudgingExtensionIn(Schema):
    # fake PG 전용 시나리오 선택. 실제 어댑터에서는 무시된다(payments.schemas의
    # ConfirmPaymentIn과 같은 원칙, ADR-0007).
    simulate: str | None = None


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
        return sponsor_next_action_for(obj, submission_count=obj.submission_count)
