from __future__ import annotations

from datetime import datetime
from uuid import UUID

from ninja import Field, Schema


class PayoutOut(Schema):
    idempotency_key: UUID
    contest_id: int
    prize_amount: int
    platform_fee_amount: int
    withholding_tax_amount: int
    net_amount: int
    status: str
    has_identity: bool
    # Seller 등록에 필요한 전화번호를 이미 제출했는가(#57 코드리뷰 지적 12,
    # 3차) — has_identity와 같은 원칙이다. 프런트가 이 값 대신 seller_status가
    # null/pending인지로 폼 노출 여부를 추론하면, 전화번호 말고 다른 정보
    # (예: 이메일)가 없어 register()가 계속 "pending"을 돌려주는 경우에도
    # 폼이 계속 다시 나타난다 — 이미 제출한 값을 또 내라고 요구하는 꼴이다.
    has_seller_phone: bool
    # 지급용 이메일을 이미 제출했는가(#168) — has_seller_phone 과 같은 원칙이다.
    # 화면이 이 값과 has_seller_phone 두 사실만으로 "무엇이 비었는지"를 구성한다 —
    # 그 문구는 Hold 번역표가 아니라 화면이 소유한다(#168 구현 결정).
    has_seller_email: bool
    # Seller가 아직 등록되지 않았으면 None. 있으면 "pending" |
    # "approval_required" | "partially_approved" | "under_review" | "approved"
    # | "rejected" 중 하나(#50, #57, ADR-0020) — 두 대기(신원/Seller) 중 이쪽이
    # 무엇을 기다리는지 Developer·Operator가 조회할 수 있어야 한다.
    seller_status: str | None
    # 실이체(벤더 이체 API) 자체의 진행 상태(#57 코드리뷰 지적 1/4) —
    # "not_requested" | "requested" | "completed" | "failed" 중 하나. `status`
    # (두 대기가 풀렸는가)와는 다른 축이다 — Seller가 이미 READY여도 실이체
    # 자체가 벤더 쪽 사유로 거절되면 이 값이 "failed"가 되고, 그때는
    # `status`가 confirmed_seller_pending에 머문다(실패로 종결되지 않는다,
    # ADR-0004). "지급이 완료되었습니다"라고 말해도 되는지는 이 값도 함께
    # 봐야 한다.
    transfer_status: str
    # Developer가 다음에 무엇을 해야 하는지(또는 왜 아직 기다려야 하는지)를
    # 사람이 읽을 수 있는 한국어 문장으로 준다 — 침묵은 상금이 사라진 것으로
    # 읽힌다(#50 AC).
    #
    # **이름이 `next_action` 이었다가 바뀌었다(#74).** 「내 참가 현황」이
    # `next_action` 을 **타입 있는 enum** 으로 쓰기 시작했는데(submissions.
    # participation.NextAction), 같은 API 안에 같은 이름의 두 계약 — 하나는
    # 판정값, 하나는 한국어 문장 — 이 공존하면 생성된 타입을 읽는 사람이 어느
    # 쪽인지 알 수 없다. 그리고 "문구를 서버가 소유한다" 는 #74 심문에서
    # 명시적으로 택하지 않은 쪽이다(문구 하나 고치는 데 백엔드 배포가 필요해지고
    # i18n 을 나중에 넣기 어려워진다). 이 필드는 #50 이 먼저 만든 것이라 지금
    # 지우지 않고 이름만 자기가 무엇인지 말하게 바꾼다 — 지급 화면을 만드는
    # 슬라이스가 이 자리에 enum 을 더하고 문구를 프론트로 옮긴다.
    next_action_message: str
    created_at: datetime


class ConfirmPayoutIn(Schema):
    # fake 토스 지급대행 전용 시나리오 선택. 실제 어댑터(PAYOUT_ADAPTER_MODE=real)
    # 에서는 무시된다 — FakePayoutAdapter만 이 값을 해석한다(ADR-0007).
    simulate: str | None = None
    # fake Seller 등록 어댑터 전용 시나리오 선택("success"(기본)/"limit_exceeded"/
    # "review_required"/"rejected"). 같은 원칙(ADR-0007) — 실제 어댑터에서는
    # 무시된다. Payout이 이 confirm 호출로 처음 확정될 때만 의미가 있다 — 이미
    # 확정된 뒤의 재호출은 이 값을 보지 않는다(payouts.progress.advance).
    seller_simulate: str | None = None


class SellerRegistrationRetryIn(Schema):
    # ConfirmPayoutIn.seller_simulate와 같은 원칙 — fake Seller 등록 어댑터
    # 전용 시나리오 선택이다.
    simulate: str | None = None


class WebhookIn(Schema):
    webhook_id: str
    idempotency_key: UUID
    status: str  # "paid" | "failed"
    # 토스(Fake 포함)만 계산할 수 있는 HMAC-SHA256 서명. 없거나 틀리면 401로
    # 거부되고, 원장·Payout 상태 어느 것도 건드리지 않는다(payments.webhook_security
    # 를 그대로 재사용, #9 리뷰 지적 2와 같은 이유).
    signature: str


class WebhookOut(Schema):
    received: bool
    idempotency_key: UUID
    status: str


class SellerWebhookOut(Schema):
    """`seller.changed` 실물 웹훅 응답(#57) — `WebhookOut`과 달리 Payout이
    아니라 Seller에 대한 것이라 idempotency_key(UUID)를 재사용하지 않는다."""

    received: bool
    seller_id: str
    status: str


class IdentitySubmitIn(Schema):
    # 형식만 검증한다(숫자로만 이루어진 13자리) — 실제 유효성(생년월일·성별 코드
    # 정합, 체크섬)까지 검사하는 건 이 티켓 범위 밖이다. 길이만 보고 통과시키면
    # "13자리 문자열"이면 뭐든(공백·기호 포함) 암호화되어 저장되고 만다(#15
    # 리뷰 지적 4) — 패턴으로 숫자만 허용한다.
    resident_registration_number: str = Field(pattern=r"^\d{13}$")


class SellerContactSubmitIn(Schema):
    """토스 셀러 등록(businessType=INDIVIDUAL)의 individual 객체가 요구하는
    연락처(전화번호·이메일)를 하나의 경로로 받는다(#57, #168). 옛 전화번호
    전용 스키마(`SellerPhoneSubmitIn`)를 넓힌 것이라 그 이름은 남기지 않는다.

    **둘 다 선택 입력이다** — 부분 제출을 허용한다(전화번호만, 이메일만).
    `None`은 "이 필드는 안 보냈다"(손대지 않는다)를 뜻하고, 엔드포인트가 둘 다
    `None`이면 422 로 거부한다(`accounts.schemas.ProfileIn`과 같은 "안 보냄"과
    "빈 값" 구분 관용구 — 다만 여기는 "빈 문자열로 지운다"는 개념 자체가 없다,
    연락처는 비우는 별도 API 가 없다). **빈 문자열도 "안 보냄"과 같이 취급하지
    않고 422 로 거부한다** — `email=""` 을 허용하면 그 요청이 "안 보냄"(None)과
    구분되지 않아 `payload.email is None` 가드를 조용히 통과하고, 이미 제출된
    이메일을 빈 값으로 덮어써 버린다(코드리뷰 지적) — 부분 제출이 "낸 것을
    보존한다"는 약속과 정반대다.

    전화번호는 숫자로만 이루어진 10~11자리(하이픈 없이)만 허용한다 —
    `IdentitySubmitIn.resident_registration_number`와 같은 원칙으로 형식만
    검증한다(빈 문자열도 이 패턴에 맞지 않아 자동으로 422 다). 이메일은 이
    저장소의 다른 이메일 필드(`accounts.MeOut.email`)와 같이 형식을 엄격히
    검증하지 않는다 — Django `EmailField`가 저장 시점의 최소한의 형태만
    본다. 다만 **비어 있지는 않아야 한다**(`min_length=1`)."""

    phone_number: str | None = Field(default=None, pattern=r"^\d{10,11}$")
    email: str | None = Field(default=None, min_length=1)


class ErrorOut(Schema):
    detail: str


class OperatorPayoutOut(Schema):
    """Operator가 Payout 하나가 무엇을 기다리는지 보는 표면(#50 AC).

    `blocked_on`은 "identity" | "seller" | "transfer"(#57 코드리뷰 지적 1 —
    Seller는 이미 READY인데 실이체 자체가 실패/미확정인 경우) | "operator"(Hold 표에
    없는 조합 — 사람이 봐야 한다, #130) | None(아무 것도 안 기다림 — 이미 CONFIRMED거나
    아직 REQUESTED/FAILED) 중 하나다. 값은 `payouts.progress.hold_of` 의 Hold 에서 나온다. 두 대기를
    한 상태로 뭉치지 않는다는 요구가 Operator 조회에서도 그대로 지켜져야 한다.
    """

    idempotency_key: UUID
    contest_id: int
    developer_user_id: int
    net_amount: int
    status: str
    transfer_status: str
    blocked_on: str | None
    seller_status: str | None
    has_identity: bool
    created_at: datetime

    # 네 값 모두 질의가 이미 알고 있다(#149) — `payouts.progress.with_hold_facts` ·
    # `with_blocked_on` 이 붙인 주석과 `with_target()` 의 select_related 다. 페이지를
    # 자른 뒤 행마다 다시 묻지 않는다는 것이 이 티켓의 요점이라, 여기 resolver 는
    # 조회를 내지 않는다.
    @staticmethod
    def resolve_contest_id(obj) -> int:
        return obj.contest.id

    @staticmethod
    def resolve_developer_user_id(obj) -> int:
        return obj.developer.user_id

    @staticmethod
    def resolve_has_identity(obj) -> bool:
        return obj.identity_submitted

    @staticmethod
    def resolve_blocked_on(obj):
        from .progress import blocked_on_of_row

        return blocked_on_of_row(obj)


class OperatorPayoutPageOut(Schema):
    """운영자 지급 큐 한 페이지 (#151).

    `count` 는 **전체** 건수다(이 페이지의 길이가 아니다) — 화면이 「막혀 있는 지급 N건」을
    말하고 홈 배지와 맞는지를 e2e 가 단언한다.

    `next` 는 「마지막으로 본 행 다음부터」를 가리키는 커서다. 더 없으면 null 이고, 그
    **행의 존재**로 판정한다 — 받은 수와 전체 건수를 비교하는 방식은 목록이 자라는 동안
    틀린다(#150 이 적은 증상 중 하나다).
    """

    items: list[OperatorPayoutOut]
    count: int
    next: str | None


class OperatorPayoutCountsOut(Schema):
    """운영자 홈의 지급 배지 숫자 (#149).

    이전에는 홈이 큐 목록 셋을 통째로 받아 `.length` 를 셌다 — Payout 전체를 세 번
    긁어 직렬화하고 숫자 셋만 남기고 버렸다. 건수는 건수로 답한다.

    필드 이름은 `BLOCKED_ON_OF` 의 값 집합과 같아야 한다 — 갈래가 하나 늘면 여기가
    모듈 로드 시점에 터진다(`assert_covers_all_kinds` 와 같은 규율).
    """

    identity: int
    seller: int
    transfer: int
    operator: int


def _assert_counts_cover_all_blocked_on_values() -> None:
    from .progress import BLOCKED_ON_VALUES

    declared = set(OperatorPayoutCountsOut.model_fields)
    missing = set(BLOCKED_ON_VALUES) - declared
    extra = declared - set(BLOCKED_ON_VALUES)
    if missing or extra:
        raise RuntimeError(
            "OperatorPayoutCountsOut 가 blocked_on 갈래와 어긋난다 — "
            f"빠진 것 {sorted(missing)}, 남는 것 {sorted(extra)}"
        )


_assert_counts_cover_all_blocked_on_values()
