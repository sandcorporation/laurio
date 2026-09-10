"""Payout 의 Hold — 확정된 Payout 을 지금 붙들고 있는 것과 그것을 풀 차례가 누구에게
있는가 (#130, CONTEXT.md 「Hold」, #116).

Developer 의 지급 화면 문구·운영자 큐의 `blocked_on`·「내 참가 현황」의 NextAction 은 같은
네 사실(Payout.status · transfer_status · Seller 상태 · 신원 제출 여부)을 세 어휘로
재파생하고 있었고, 「신원이 실이체보다 앞선다」 같은 규칙이 세 곳에 서로 맞춰 달라는
주석과 함께 따로 적혀 있었다. 이 module 이 그 결정을 한 번만 한다 — `hold_of` 가 Hold 를
내고, 세 렌더러는 Hold → 문구 번역표만 갖는다. 번역표는 `HoldKind` 전체를 덮어야
하며(모듈 로드 시 검사) 새 값이 생기면 그 자리에서 터진다.

Hold 는 읽을 때 계산하고 저장하지 않는다 — 네 사실 중 하나가 바뀔 때마다 같이 갱신해야
하는 파생값을 두면 언젠가 갈린다.

정의되지 않은 조합은 Operator 의 차례다 — 돈은 움직이지 않고 사람이 본다(ADR-0025 가
「도달 불가여야 하는 곳에 도달했다면 불변식이 깨진 것」에 대해 세운 규율).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from core.coverage import assert_covers

from .models import Payout, Seller

logger = logging.getLogger(__name__)


class HoldKind(str, Enum):
    # 확정 전 — 붙드는 것이 없다.
    REQUESTED = "requested"
    # 주민등록번호 미제출 — Developer 의 차례.
    IDENTITY = "identity"
    # 신원은 냈고 전진(실이체 확정)을 기다린다.
    IDENTITY_RECORDED = "identity_recorded"
    # Seller 등록에 연락처(전화번호·이메일 중 하나 이상)가 필요하다 — Developer 의
    # 차례(#168). 전화번호만 없든 이메일만 없든 둘 다 없든 Developer 가 갈 화면은
    # 같다 — 갈래를 나누지 않는다.
    SELLER_CONTACT = "seller_contact"
    # 지급대행사의 본인인증 문자 — Developer 의 차례.
    SELLER_AUTH = "seller_auth"
    # 지급대행사 심사 중 — 벤더의 차례.
    SELLER_REVIEW = "seller_review"
    # 수취인 등록 거절 — Operator 의 차례.
    SELLER_REJECTED = "seller_rejected"
    # 연락처는 다 있는데 등록이 벤더 오류로 접수되지 못했다 — 자력 회복 스캔
    # (#178, `payouts.recovery`)이 다시 시도하는 중이다. 벤더의 차례다: 우리가
    # 계속 다시 부르고 있고, 사람이 할 일은 아직 없다.
    SELLER_PENDING = "seller_pending"
    # 위 자력 회복 스캔이 상한(`MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS`)만큼
    # 재시도하고도 등록을 접수시키지 못했다 — 계속 벤더의 차례라고 말하면
    # 아무도 다시 보지 않는다(#178). Operator 의 차례.
    SELLER_REGISTRATION_STUCK = "seller_registration_stuck"
    # Seller 는 READY, 실이체 확인 중 — 벤더의 차례.
    TRANSFER_CONFIRMING = "transfer_confirming"
    # Seller 는 READY 인데 실이체가 거절됐다 — Developer 가 다시 시도할 수 있다.
    TRANSFER_RETRY = "transfer_retry"
    # 신원은 냈는데 실이체가 실패로 확인됐다 — 다시 시도할 수 있다.
    TRANSFER_RETRY_IDENTITY_RECORDED = "transfer_retry_identity_recorded"
    # CONFIRMED 뒤 뒤늦게 실이체 실패가 확인됐다 — 자기 서비스 재시도 경로가 아직 없다
    # (ADR-0008 의 한계) — Operator 의 차례.
    TRANSFER_OPERATOR = "transfer_operator"
    COMPLETE = "complete"
    # 벤더가 거절해 이 시도가 끝났다 — 새 요청을 낼 수 있다(Developer 의 차례).
    FAILED = "failed"
    # 표에 없는 조합 — Operator 의 차례.
    UNKNOWN = "unknown"


class Turn(str, Enum):
    DEVELOPER = "developer"
    VENDOR = "vendor"
    OPERATOR = "operator"
    NONE = "none"


TURN_OF: dict[HoldKind, Turn] = {
    HoldKind.REQUESTED: Turn.NONE,
    HoldKind.IDENTITY: Turn.DEVELOPER,
    HoldKind.IDENTITY_RECORDED: Turn.VENDOR,
    HoldKind.SELLER_CONTACT: Turn.DEVELOPER,
    HoldKind.SELLER_AUTH: Turn.DEVELOPER,
    HoldKind.SELLER_REVIEW: Turn.VENDOR,
    HoldKind.SELLER_REJECTED: Turn.OPERATOR,
    HoldKind.SELLER_PENDING: Turn.VENDOR,
    HoldKind.SELLER_REGISTRATION_STUCK: Turn.OPERATOR,
    HoldKind.TRANSFER_CONFIRMING: Turn.VENDOR,
    HoldKind.TRANSFER_RETRY: Turn.DEVELOPER,
    HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED: Turn.DEVELOPER,
    HoldKind.TRANSFER_OPERATOR: Turn.OPERATOR,
    HoldKind.COMPLETE: Turn.NONE,
    HoldKind.FAILED: Turn.DEVELOPER,
    HoldKind.UNKNOWN: Turn.OPERATOR,
}

# 운영자 큐의 거친 축 — identity | seller | transfer | operator | None. 세밀 Hold 에서
# 파생하므로 큐 필터(`blocked_on=`)는 그대로 호환된다.
BLOCKED_ON_OF: dict[HoldKind, str | None] = {
    HoldKind.REQUESTED: None,
    HoldKind.IDENTITY: "identity",
    HoldKind.IDENTITY_RECORDED: "identity",
    HoldKind.SELLER_CONTACT: "seller",
    HoldKind.SELLER_AUTH: "seller",
    HoldKind.SELLER_REVIEW: "seller",
    HoldKind.SELLER_REJECTED: "seller",
    HoldKind.SELLER_PENDING: "seller",
    # Turn 은 Operator 지만 거친 축은 그대로 "seller" 다(SELLER_REJECTED 와
    # 같은 이유) — 무엇이 막고 있는지(Seller 등록)는 바뀌지 않았고, 누구
    # 차례인지만 바뀌었다. 운영자 큐의 "Seller" 탭에서 계속 보인다.
    HoldKind.SELLER_REGISTRATION_STUCK: "seller",
    HoldKind.TRANSFER_CONFIRMING: "transfer",
    HoldKind.TRANSFER_RETRY: "transfer",
    HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED: "transfer",
    HoldKind.TRANSFER_OPERATOR: "transfer",
    HoldKind.COMPLETE: None,
    HoldKind.FAILED: None,
    HoldKind.UNKNOWN: "operator",
}


def assert_covers_all_kinds(table, *, name: str) -> None:
    """번역표(`table`)가 `HoldKind` 전체를 덮는지 — 값이 하나 늘거나 오타로 하나
    빠지면 모듈 로드 시점에 바로 터진다.

    이 파일의 세 번역표(`TURN_OF`·`BLOCKED_ON_OF`·`NEXT_ACTION_MESSAGES`)와
    `submissions.participation`의 액션 표가 이 얇은 래퍼를 지난다 — 전부
    `HoldKind` 만 검사하므로 그 자리에 고정한다. 일반화된 원시 도구는
    `core.coverage.assert_covers`(#176)다 — `expected`를 호출자가 고를 수 있게
    열어 두면, 이 파일의 호출부가 실수로 그 인자를 빠뜨렸을 때 조용히
    `HoldKind`와 비교해 버리는 함정이 생긴다(#176 코드리뷰 지적) — 그래서 이
    래퍼는 `HoldKind`를 하드코딩해 그 함정 자체를 없앤다. `payouts.adapters_toss`
    의 벤더 상태 분류표·`payouts.schemas`의 배지 필드 표는 `HoldKind`가 아닌
    다른 값을 검사하므로 이 래퍼가 아니라 `core.coverage.assert_covers`를
    직접 부른다.
    """

    assert_covers(table, HoldKind, name=name)


assert_covers_all_kinds(TURN_OF, name="TURN_OF")
assert_covers_all_kinds(BLOCKED_ON_OF, name="BLOCKED_ON_OF")


@dataclass(frozen=True)
class Hold:
    kind: HoldKind
    turn: Turn
    # 문구 뉘앙스용 — 신원 미제출 상태에서 실이체 실패도 함께 확인됐는가 등.
    transfer_failed: bool

    @property
    def blocked_on(self) -> str | None:
        return BLOCKED_ON_OF[self.kind]


# Hold → 사람이 읽을 문장의 번역표(#50 AC, #130) — 침묵은 상금이 사라진 것으로
# 읽힌다. 원래 `payouts.api` 에 있었는데(#130), #169 가 지급 알림 스캔에서도 같은
# 문구를 재사용해야 해서 이 모듈로 옮겼다 — `hold_of` 를 이미 소유한 이 모듈이
# 그 결과를 사람이 읽을 문장으로 바꾸는 규칙까지 한 곳에서 갖는다. 두 곳(화면·
# 알림)이 각자 번역표를 가지면 #130 이 세 렌더러에서 하나로 모은 것을 다시
# 쪼개는 셈이다.
NEXT_ACTION_MESSAGES: dict[HoldKind, str] = {
    HoldKind.REQUESTED: "지급 확인 절차가 진행 중입니다. 잠시만 기다려주세요.",
    HoldKind.IDENTITY: "세무 신고를 위해 주민등록번호를 제출해주세요.",
    HoldKind.IDENTITY_RECORDED: "세무 신고를 위해 주민등록번호를 제출해주세요.",
    # #168 — 전화번호 전용이던 문구를 연락처(전화번호·이메일) 전반으로 넓힌다.
    # 무엇이 구체적으로 비었는지는 이 번역표가 아니라 화면이 `has_seller_phone`·
    # `has_seller_email` 두 사실로 만든다(#168 구현 결정) — 이미 낸 것을 다시
    # 내라고 하지 않기 위해서다.
    HoldKind.SELLER_CONTACT: "지급대행사 수취인 등록에 연락처 정보가 필요합니다 — 아래에서 제출해주세요.",
    HoldKind.SELLER_AUTH: (
        "지급대행사(토스페이먼츠)가 보낸 본인인증 문자로 인증을 완료해주세요 — "
        "이미 본인확인을 하셨더라도 지급대행사 자체 의무라 다시 인증이 "
        "필요합니다. 인증이 끝나면 자동으로 다음 단계로 넘어갑니다."
    ),
    HoldKind.SELLER_REVIEW: (
        "지급대행사 심사가 진행 중입니다(주간 지급 한도 초과 또는 추가 확인 "
        "요청) — 상금은 안전하게 보관되어 있으며 심사가 끝나면 자동으로 다음 "
        "단계로 넘어갑니다."
    ),
    HoldKind.SELLER_REJECTED: (
        "지급대행사 수취인 등록이 거절되었습니다. 상금은 원장에 그대로 "
        "남아 있습니다 — 운영자에게 문의해주세요."
    ),
    # #178 — "진행 중"이 아니라 "접수되지 않았다"가 사실이다. 자력 회복
    # 스캔(`payouts.recovery`)이 다시 시도하고 있다는 것까지 정직하게 말한다 —
    # 「완료되면 자동으로 넘어갑니다」는 그 스캔이 실제로 돌고 있어야만 참이다.
    HoldKind.SELLER_PENDING: (
        "지급대행사 수취인 등록 요청이 아직 접수되지 않았습니다 — 시스템이 "
        "자동으로 다시 시도하고 있습니다. 완료되면 자동으로 다음 단계로 "
        "넘어갑니다."
    ),
    # #178 — 위 자력 회복이 상한만큼 시도하고도 풀지 못했다. 계속 "자동으로
    # 넘어갑니다"라고 말하면 침묵을 상금이 사라진 것으로 읽게 만든다.
    HoldKind.SELLER_REGISTRATION_STUCK: (
        "지급대행사 수취인 등록이 반복적으로 접수되지 않았습니다. 상금은 "
        "원장에 그대로 남아 있습니다 — 운영자가 확인 후 다시 진행합니다."
    ),
    HoldKind.TRANSFER_CONFIRMING: "실이체 확인이 진행 중입니다. 잠시만 기다려주세요.",
    HoldKind.TRANSFER_RETRY: (
        "지급대행사 등록은 끝났지만 실제 이체가 거절되었습니다 — 상금은 "
        "원장에 그대로 남아 있습니다. 아래에서 다시 시도해주세요."
    ),
    # #181 — 이 갈래는 정의상 주민등록번호가 이미 제출된 상태다("_RECORDED").
    # 옛 문구는 옆 갈래(신원 미제출 + 이체 실패)가 빌려 쓰려고 쓴 것을 그대로
    # 자기 이름의 갈래에도 붙여 둔 것이었다 — 이미 낸 사람에게 계속 내라고
    # 말하는 거짓이었다. 이 갈래 자신의 사실(이체만 다시 시도하면 된다)을 말한다.
    HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED: (
        "실제 이체가 실패로 확인되었습니다 — 상금은 원장에 그대로 남아 "
        "있습니다. 아래에서 다시 시도해주세요."
    ),
    HoldKind.TRANSFER_OPERATOR: (
        "지급이 확정되었지만 실제 이체가 실패로 확인되었습니다 — 상금은 "
        "원장에 그대로 남아 있습니다. 운영자가 확인 후 다시 진행합니다."
    ),
    HoldKind.COMPLETE: "지급이 완료되었습니다.",
    HoldKind.FAILED: "지급 요청이 실패했습니다. 다시 시도해주세요.",
    HoldKind.UNKNOWN: "지급 상태를 확인하는 중입니다. 운영자가 확인 후 안내드립니다.",
}
assert_covers_all_kinds(NEXT_ACTION_MESSAGES, name="NEXT_ACTION_MESSAGES")

# 신원 미제출 상태에서 실이체 실패도 함께 확인된 경우 — 신원 제출을 막을 이유는 없지만
# (독립적인 두 축), 실이체가 실패했다는 사실을 감추지 않는다(#57 코드리뷰 지적 4).
#
# **독립된 문구다 — 빌려 쓰지 않는다(#181).** 예전에는 이 문구를
# `NEXT_ACTION_MESSAGES[HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED]`에서 빌려 왔는데,
# 그 갈래는 정의상 신원이 이미 제출된 상태라 자기 이름의 문구가 "주민등록번호를
# 계속 제출해주세요"를 말하는 거짓이 됐다(#181이 고친 회귀). 이 문구(신원 미제출 +
# 이체 실패)만 신원 제출을 안내해야 하므로 독립적으로 적는다 — 다른 갈래의 문구가
# 바뀌어도 이 문구는 따라 흔들리지 않는다.
_IDENTITY_AFTER_TRANSFER_FAILURE_MESSAGE = (
    "세무 신고를 위해 주민등록번호를 제출해주세요 — 그리고 실제 이체가 실패로 "
    "확인되었습니다. 상금은 원장에 그대로 남아 있으니 이체는 아래에서 다시 "
    "시도할 수 있습니다."
)


def next_action_message(hold: "Hold") -> str:
    """이 Hold 에 대해 사람이 읽을 다음 행동 문구 — 지급 화면과 지급 알림 스캔(#169)이
    같이 쓴다."""

    if hold.kind is HoldKind.IDENTITY and hold.transfer_failed:
        return _IDENTITY_AFTER_TRANSFER_FAILURE_MESSAGE
    return NEXT_ACTION_MESSAGES[hold.kind]


# 자력 회복 스캔(`payouts.recovery`, #178)이 벤더 오류를 몇 번까지 다시 시도한 뒤
# Operator 의 차례로 넘기는가. 스캔 기본 주기(`core.scans.DEFAULT_INTERVAL_SECONDS`,
# 60초) 기준으로 5회면 약 5분 — 일시적 벤더 5xx·네트워크 오류가 몇 분 안에 걷히는
# 것은 자동으로 회복시키고, 그래도 안 풀리면(자격증명 오류처럼 재시도로는 절대
# 안 풀리는 원인일 수 있다) 더 기다리지 않고 사람에게 넘긴다 — 상금이 조용히
# 묶이는 시간을 최소로 좁힌다. 시도 횟수 상한이지 시간 간격이 아니다 — 스캔이
# 아니라 Developer의 연락처 재제출(`submit_seller_contact`)로도 재시도가 걸릴 수
# 있어(#168), 시간 기준이면 그 경로가 상한을 우회한다.
MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS = 5


def hold_of(payout: Payout, *, seller: Seller | None, has_identity: bool) -> Hold:
    """네 사실에서 Hold 하나를 읽어 낸다. 조회를 내지 않는다 — 호출부가 Seller 와 신원
    제출 여부를 미리 가져온다(목록에서 행마다 조회하지 않기 위해)."""

    S = Payout.Status
    T = Payout.TransferStatus
    status = payout.status
    transfer_failed = payout.transfer_status == T.FAILED
    seller_ready = seller is not None and seller.status in Seller.READY_STATUSES

    if status == S.REQUESTED:
        kind = HoldKind.REQUESTED
    elif status == S.FAILED:
        kind = HoldKind.FAILED
    elif status == S.CONFIRMED:
        kind = HoldKind.TRANSFER_OPERATOR if transfer_failed else HoldKind.COMPLETE
    elif status == S.CONFIRMED_IDENTITY_PENDING:
        # 신원 미제출이 실이체 재시도보다 앞선다 — 이 상태의 뜻이 「신원 대기」이고,
        # 신원 미제출과 실이체 실패는 서로 다른 둘을 동시에 기다리는 것이지 하나가
        # 다른 하나를 대체하지 않는다(#57 코드리뷰 지적 3, 4차).
        if not has_identity:
            kind = HoldKind.IDENTITY
        elif transfer_failed:
            kind = HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED
        else:
            kind = HoldKind.IDENTITY_RECORDED
    elif status == S.CONFIRMED_SELLER_PENDING:
        if seller_ready:
            kind = HoldKind.TRANSFER_RETRY if transfer_failed else HoldKind.TRANSFER_CONFIRMING
        elif seller is not None and seller.status == Seller.Status.UNDER_REVIEW:
            kind = HoldKind.SELLER_REVIEW
        elif seller is not None and seller.status == Seller.Status.REJECTED:
            kind = HoldKind.SELLER_REJECTED
        elif seller is not None and seller.status == Seller.Status.APPROVAL_REQUIRED:
            kind = HoldKind.SELLER_AUTH
        elif (seller is None or seller.status == Seller.Status.PENDING) and not (
            seller is not None and seller.phone_number and seller.email
        ):
            # PENDING 이면서 전화번호나 이메일 중 하나라도 없다 — 「우리가 응답을
            # 기다린다」가 아니라 「Developer 가 낼 것이 있다」(#57 추가 인수조건,
            # #168 이 이메일까지 넓힌다). 이메일이 없는 것만으로도 이 갈래다 —
            # 이전에는 벤더의 차례로 잘못 읽혔다(#168 이 닫는 회귀).
            kind = HoldKind.SELLER_CONTACT
        elif (
            seller is not None
            and seller.status == Seller.Status.PENDING
            and seller.registration_error_count >= MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS
        ):
            # 연락처는 다 있다(위 SELLER_CONTACT 분기를 지났다) — 그런데도
            # seller_id 가 없다는 것은 등록이 벤더 오류로 계속 접수되지
            # 못했다는 뜻이고, 자력 회복 스캔이 상한만큼 다시 시도하고도
            # 풀지 못했다(#178). 더 기다리게 하지 않고 Operator 의 차례로
            # 넘긴다.
            kind = HoldKind.SELLER_REGISTRATION_STUCK
        else:
            kind = HoldKind.SELLER_PENDING
    else:
        logger.error(
            "Hold 표에 없는 Payout 조합 — status=%r transfer_status=%r seller=%r has_identity=%r "
            "(idempotency_key=%s). 돈은 움직이지 않고 Operator 의 차례로 표시한다.",
            status,
            payout.transfer_status,
            seller.status if seller is not None else None,
            has_identity,
            payout.idempotency_key,
        )
        kind = HoldKind.UNKNOWN

    return Hold(kind=kind, turn=TURN_OF[kind], transfer_failed=transfer_failed)


# --- 같은 표를 SQL 로 묻는 길 (#149) --------------------------------------------------
#
# 운영자 큐는 「무엇에 막혀 있는가」로 좁힌 목록을 페이지 단위로 읽는다. 그 좁히기를
# 파이썬에서 하면 필터가 응답만 줄이고 질의는 그대로라, 막혀 있지도 않은 Payout 까지
# 전부 가져온 뒤 버리게 된다(#149 가 고치는 것). 그래서 **같은 표를 SQL 에서도** 물어야
# 한다.
#
# **표를 옮겨 적는 것이 위험한 이유를 알고 한다.** #130 이 세 렌더러의 재파생을 `hold_of`
# 하나로 모은 이유가 「같은 규칙이 세 곳에 서로 맞춰 달라는 주석과 함께 따로 적혀
# 있었다」였다. 그래서 여기 Q 는 **거친 축(`blocked_on`)까지만** 내려간다 — `HoldKind`
# 열다섯 갈래는 여전히 `hold_of` 만 안다 — 그리고 두 표현이 모든 조합에서 같은 답을
# 낸다는 것을 `tests/test_operator_payout_queue.py` 의 빠짐없음 테스트가 증명한다
# (#141 이 `Contest.Status` 에 쓴 관용구). 조합이 하나 늘거나 표가 바뀌면 그 테스트가
# 그 자리에서 터진다.
#
# `HoldKind.SELLER_CONTACT` 과 `SELLER_PENDING` 을 가르는 다섯 번째 사실(전화번호·
# 이메일 제출 여부)은 여기 없다 — 둘 다 `blocked_on == "seller"` 라 이 축에서는
# 구별되지 않는다. 전화번호는 애초에 암호화되어 저장돼(`Seller.phone_number_encrypted`)
# SQL 이 읽을 수도 없다. 「거친 축까지만」이 편의가 아니라 가능한 최대치라는 뜻이다.

_STATUS_VALUES = list(Payout.Status.values)


def with_hold_facts(payouts):
    """`blocked_on_q` 가 읽는 사실을 질의에 붙인다 — Seller 상태와 신원 제출 여부.

    `Payout.seller` 는 FK 가 아니라 Developer 를 거쳐 찾는 속성이라(한 Developer 는
    Contest 를 여러 번 이길 수 있고 등록은 한 번뿐이다) `select_related` 로는 안 붙는다.
    Award 경로와 Distribution 경로 중 채워진 쪽을 `Coalesce` 로 고른다 —
    `payout_exactly_one_target` 이 정확히 하나만 채워져 있음을 보장한다.
    """

    from django.db.models import Exists, OuterRef, Subquery
    from django.db.models.functions import Coalesce

    from .models import TaxIdentity

    def _seller_status_via(developer_path: str):
        return Subquery(
            Seller.objects.filter(developer_id=OuterRef(developer_path)).values("status")[:1]
        )

    return payouts.annotate(
        identity_submitted=Exists(TaxIdentity.objects.filter(payout=OuterRef("pk"))),
        seller_status=Coalesce(
            _seller_status_via("handover__award__submission__contestsubmission__developer_id"),
            _seller_status_via("distribution_share__submission__contestsubmission__developer_id"),
        ),
    )


def with_seller_registration_status(payouts):
    """운영자 큐 전용 추가 사실(#178, `OperatorPayoutOut.seller_registration_status`).

    `with_hold_facts` 의 `seller_status` 만으로는 「연락처를 아직 못 받았다」·
    「연락처는 있는데 등록이 벤더 오류로 접수 안 됐다(재시도 중)」·「재시도를
    포기했다」 셋이 구별되지 않는다 — 셋 다 `Seller.Status.PENDING` 이다. 이
    함수가 Seller 의 나머지 사실(등록 식별자·연락처 존재·오류 횟수)을 SQL 에서
    추가로 물어 온다 — `test_operator_payout_queue_does_not_query_per_row`(#91)가
    이미 강제하듯, 행마다 `Payout.seller` 를 다시 읽으면 페이지 안 행 수만큼
    질의가 늘어난다.

    판정 규칙은 `hold_of` 의 `SELLER_REGISTRATION_STUCK`/`SELLER_PENDING` 분기와
    **같아야 한다** — 둘이 갈리면 큐 목록(SQL)과 단건 조회(파이썬)가 다른 답을
    낸다. 표를 옮겨 적는 위험은 `blocked_on_q` 위의 주석과 같다.

    **`with_hold_facts` 뒤에 이어 붙여야 한다** — Seller 상태 자체는 다시
    묻지 않고 그 함수가 이미 annotate 해 둔 `seller_status` 를 그대로 쓴다
    (호출부 둘 다 이미 `with_hold_facts(...)` 뒤에 이 함수를 잇는다). 여기서
    또 같은 Subquery/Coalesce 쌍을 새로 만들면 페이지·응답 하나마다 같은
    Seller 상태 질의가 두 번 실행된다.
    """

    from django.db.models import Case, CharField, OuterRef, Q, Subquery, Value, When
    from django.db.models.functions import Coalesce

    def _seller_field_via(developer_path: str, field: str):
        return Subquery(
            Seller.objects.filter(developer_id=OuterRef(developer_path)).values(field)[:1]
        )

    def _seller_field(field: str, default):
        return Coalesce(
            _seller_field_via("handover__award__submission__contestsubmission__developer_id", field),
            _seller_field_via("distribution_share__submission__contestsubmission__developer_id", field),
            Value(default),
        )

    annotated = payouts.annotate(
        _seller_id_for_registration=_seller_field("seller_id", ""),
        # 값을 복호화하지 않는다 — 이 판정에 필요한 것은 「제출됐는가」(빈
        # 문자열이 아닌가)뿐이고, 그건 암호문 자체의 존재로 답할 수 있다
        # (`Seller.phone_number` setter — 값이 없으면 암호문도 빈 문자열이다).
        _seller_phone_for_registration=_seller_field("phone_number_encrypted", ""),
        _seller_email_for_registration=_seller_field("email", ""),
        _seller_errors_for_registration=_seller_field("registration_error_count", 0),
    )

    pending_unaccepted = (
        Q(seller_status=Seller.Status.PENDING)
        & Q(_seller_id_for_registration="")
        & ~Q(_seller_phone_for_registration="")
        & ~Q(_seller_email_for_registration="")
    )

    return annotated.annotate(
        seller_registration_status=Case(
            When(
                pending_unaccepted
                & Q(_seller_errors_for_registration__gte=MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS),
                then=Value("stuck"),
            ),
            When(pending_unaccepted, then=Value("retrying")),
            default=Value(None),
            output_field=CharField(null=True),
        )
    )


def blocked_on_q(value: str | None):
    """`with_hold_facts` 를 거친 질의에서 「`blocked_on` 이 이 값인 행」을 고르는 Q.

    `value=None` 은 「아무것에도 막혀 있지 않다」 — 큐가 통째로 배제하는 쪽이다.
    위 `BLOCKED_ON_OF` 표를 `hold_of` 의 분기 순서 그대로 옮긴 것이다:

    - REQUESTED · FAILED — 확정 전이거나 끝났다. 붙드는 것이 없다
    - CONFIRMED — 실이체가 실패로 확인됐으면 `transfer`, 아니면 완료(None)
    - CONFIRMED_IDENTITY_PENDING — 신원을 냈고 실이체가 실패했을 때만 `transfer`,
      그 밖에는 `identity`(신원 미제출이 실이체 재시도보다 앞선다)
    - CONFIRMED_SELLER_PENDING — Seller 가 READY 면 남은 것은 실이체뿐이라 `transfer`,
      아니면 `seller`
    - 표에 없는 status — `operator`. 열거하지 않고 **여집합**으로 잡는다: 알 수 없는
      값이 새 갈래로 조용히 사라지는 것이 이 표가 가장 막고 싶어 하는 일이다
    """

    from django.db.models import Q

    S = Payout.Status
    transfer_failed = Q(transfer_status=Payout.TransferStatus.FAILED)
    seller_ready = Q(seller_status__in=list(Seller.READY_STATUSES))
    # **NULL 을 손으로 적는다.** `seller_status` 는 컬럼이 아니라 Subquery 주석이라
    # 등록이 아직 시작되지 않은 Payout 에서 NULL 이고, SQL 의 `NOT (x IN (...))` 는
    # NULL 에 대해 참이 아니라 **NULL** 이다 — 그대로 뒀으면 「Seller 가 아예 없는」
    # Payout 이 seller 큐에서 통째로 사라졌을 것이다. 그게 큐에 가장 먼저 떠야 할
    # 행이다(등록조차 시작되지 않았다는 뜻이므로).
    seller_not_ready = Q(seller_status__isnull=True) | ~seller_ready
    identity_recorded_and_transfer_failed = Q(identity_submitted=True) & transfer_failed

    if value is None:
        return (
            Q(status=S.REQUESTED)
            | Q(status=S.FAILED)
            | (Q(status=S.CONFIRMED) & ~transfer_failed)
        )
    if value == "identity":
        return Q(status=S.CONFIRMED_IDENTITY_PENDING) & ~identity_recorded_and_transfer_failed
    if value == "seller":
        return Q(status=S.CONFIRMED_SELLER_PENDING) & seller_not_ready
    if value == "transfer":
        return (
            (Q(status=S.CONFIRMED_IDENTITY_PENDING) & identity_recorded_and_transfer_failed)
            | (Q(status=S.CONFIRMED_SELLER_PENDING) & seller_ready)
            | (Q(status=S.CONFIRMED) & transfer_failed)
        )
    if value == "operator":
        return ~Q(status__in=_STATUS_VALUES)
    raise ValueError(f"blocked_on 표에 없는 값: {value!r}")


BLOCKED_ON_VALUES: tuple[str, ...] = tuple(
    # 표에서 뽑는다 — 손으로 적어 두면 갈래가 늘 때 큐만 조용히 옛 목록을 쓴다.
    dict.fromkeys(value for value in BLOCKED_ON_OF.values() if value is not None)
)


def blocked_q():
    """막혀 있는 행 전부 — 큐가 보여주는 것의 전체다. `blocked_on=None` 의 여집합이라
    표에 없는 status 도 빠짐없이 들어온다(그쪽은 `operator` 로 분류된다)."""

    return ~blocked_on_q(None)


def with_blocked_on(payouts):
    """`blocked_on` 값 자체를 질의에 붙인다 — 위 Q 들에서 **파생**하므로 표가 셋이 되지
    않는다. 이 값이 주석이라야 페이지를 자른 뒤에 파이썬으로 다시 계산하지 않는다."""

    from django.db.models import Case, CharField, Value, When

    return payouts.annotate(
        blocked_on_value=Case(
            *(When(blocked_on_q(value), then=Value(value)) for value in BLOCKED_ON_VALUES),
            default=Value(None),
            output_field=CharField(null=True),
        )
    )


def blocked_on_of_row(payout) -> str | None:
    """`with_blocked_on` 이 붙인 값을 읽는다 — 표 밖의 조합이면 그 자리에서 소리를 낸다.

    `hold_of` 의 마지막 `else` 가 내던 ERROR 를 이 경로에서도 잃지 않기 위해서다.
    도달 불가여야 하는 곳에 도달했다면 불변식이 깨진 것이고, 큐에 조용히 한 줄 더
    뜨는 것으로 끝나서는 안 된다(ADR-0025).
    """

    value = payout.blocked_on_value
    if value == "operator":
        logger.error(
            "Hold 표에 없는 Payout 조합이 운영자 큐에 떴다 — status=%r transfer_status=%r "
            "(idempotency_key=%s). 돈은 움직이지 않고 Operator 의 차례로 표시한다.",
            payout.status,
            payout.transfer_status,
            payout.idempotency_key,
        )
    return value


def _confirmation_journal(payout: Payout):
    """첫 홈에서 남기는 수수료·원천징수 공제 분개. 원천징수는 반드시 원천징수 예수금 계정에
    계상된다(ADR-0004/0008) — 국세청에 낼 남의 돈이므로 플랫폼 수수료 수익과 섞이지 않는다.
    **이 분개는 Seller 등록 결과와 무관하게 항상 남는다** — 한도 초과·심사 지연·거절 어느
    경로로도 확정된 금액이 원장에서 사라지지 않는다(ADR-0004, #50 AC)."""

    from ledger.models import Account, EntrySide
    from ledger.services import LineInput

    contest = payout.contest
    return (
        contest.ledger_id,
        (
            f"Contest #{contest.id} Payout 확정 — 플랫폼 수수료 "
            f"{payout.platform_fee_amount:,}원 + 원천징수 "
            f"{payout.withholding_tax_amount:,}원 공제 (실지급액 "
            f"{payout.net_amount:,}원)"
        ),
        [
            LineInput(
                account=Account.DEVELOPER_PAYABLE,
                side=EntrySide.DEBIT,
                amount=payout.platform_fee_amount + payout.withholding_tax_amount,
            ),
            LineInput(
                account=Account.PLATFORM_FEE_REVENUE,
                side=EntrySide.CREDIT,
                amount=payout.platform_fee_amount,
            ),
            LineInput(
                account=Account.WITHHOLDING_TAX_PAYABLE,
                side=EntrySide.CREDIT,
                amount=payout.withholding_tax_amount,
            ),
        ],
    )


# ---- 실이체 장부 (#135) — attempt 를 벤더 거래의 유일한 키로 끝까지 끌고 간다 ------------------
#
# 벤더 호출 전에 선점(claim)한 시도가 벤더에 닿기도 전에 끊겼을 때(예: ConnectionError), 얼마나
# 지나야 그 선점을 포기하고 재선점할 수 있게 하는가(코드리뷰 지적 6, 5차) —
# notifications.services.STUCK_QUEUED_THRESHOLD 와 같은 관용구. 재시도/웹훅 재수신처럼 사람이
# 다시 트리거하는 경로에서만 재선점이 일어나므로 여유 있게 잡아 "진짜 멈춘 것"만 되찾는다.
_TRANSFER_CLAIM_STALE_AFTER_SECONDS = 60


def _claim_transfer_attempt(payout: Payout) -> Payout | None:
    """벤더를 부르기 전에 이 시도를 선점한다 — `claim_transition` 과 같은 조건부 UPDATE + rowcount
    관용구(ADR-0003). 벤더 호출 지점을 선점하는 것만이 모든 경로(확정 엔드포인트·재시도·웹훅·
    sweep·Distribution)를 한 곳에서 닫는다 — 어떤 조합으로도 한 attempt 에 POST 는 한 번이다.

    선점에 성공하면(NOT_REQUESTED/FAILED 에서, 또는 오래 멈춘 REQUESTED 에서 REQUESTED 로) 새
    `transfer_attempt` 가 반영된 신선한 Payout 을, 실패하면(다른 호출이 이미 REQUESTED/COMPLETED
    로 선점해 두었다) None 을 돌려준다. 새 attempt 를 선점할 때마다 `vendor_payout_id` 를
    비운다(코드리뷰 지적 2, 5차) — 그러지 않으면 새 시도의 조회가 이전 시도의 벤더 id 로 가서
    시도 N 의 타임아웃이 시도 N-1 의 결과로 잘못 확정된다. `transfer_claimed_at` 도 함께 찍는다.
    """

    from datetime import timedelta

    from django.db.models import F, Q

    from core.clock import Clock
    from core.transitions import claim_transition

    T = Payout.TransferStatus
    now = Clock.now()
    claim_extra = {
        "transfer_attempt": F("transfer_attempt") + 1,
        "vendor_payout_id": "",
        "transfer_claimed_at": now,
    }

    won = claim_transition(
        Payout, payout.pk, from_state=T.NOT_REQUESTED, to_state=T.REQUESTED,
        state_field="transfer_status", now=now, extra_fields=claim_extra,
    ) or claim_transition(
        Payout, payout.pk, from_state=T.FAILED, to_state=T.REQUESTED,
        state_field="transfer_status", now=now, extra_fields=claim_extra,
    )

    if not won:
        # REQUESTED 에서 멈춘 채로 오래 남아 있으면 재선점한다 — 벤더에 닿기도 전에 끊긴 요청은
        # 벤더가 이 시도 자체를 모르므로 query_status 로도 절대 풀리지 않는다. 시각 범위 조건은
        # claim_transition 이 못 담으므로 raw 조건부 UPDATE 다 — `transfer_claimed_at` 을 조건에
        # 넣었으므로 여러 호출이 동시에 집어도 정확히 하나만 이긴다.
        stale_before = now - timedelta(seconds=_TRANSFER_CLAIM_STALE_AFTER_SECONDS)
        reclaimed = (
            Payout.objects.filter(pk=payout.pk, transfer_status=T.REQUESTED)
            .filter(Q(transfer_claimed_at__isnull=True) | Q(transfer_claimed_at__lte=stale_before))
            .update(**claim_extra)
        )
        won = reclaimed == 1

    if not won:
        return None
    payout.refresh_from_db()
    return payout


def _record_transfer_result(payout: Payout, result_status: str, attempt: int) -> bool:
    """벤더 결과를 `Payout.transfer_status` 에 기록하고, COMPLETED 로 확정됐는지를 돌려준다.

    Payout 의 현재 `transfer_attempt` 와 일치할 때만, 그리고 아직 COMPLETED 가 아닐 때만
    기록한다(코드리뷰 지적 3, 5차) — 새 시도가 이미 선점한 뒤에도 낡은(또는 경합에서 진) 시도의
    결과가 뒤늦게 도착해 진행 중이거나 이미 확정된 시도를 덮어쓰지 않는다.
    """

    T = Payout.TransferStatus
    target = {"paid": T.COMPLETED, "failed": T.FAILED}.get(result_status, T.REQUESTED)
    updated = (
        Payout.objects.filter(pk=payout.pk, transfer_attempt=attempt)
        .exclude(transfer_status=T.COMPLETED)
        .update(transfer_status=target)
    )
    if updated:
        payout.transfer_status = target
    else:
        payout.refresh_from_db(fields=["transfer_status", "transfer_attempt"])
    return payout.transfer_status == T.COMPLETED


def _transfer_request(payout: Payout, seller):
    from .adapters import TransferRequest

    return TransferRequest(
        idempotency_key=str(payout.idempotency_key),
        amount=payout.net_amount,
        seller_id=(seller.seller_id if seller is not None else "") or "",
        vendor_ref=f"{payout.idempotency_key}-{payout.transfer_attempt}",
        vendor_payout_id=payout.vendor_payout_id or "",
    )


def _apply_vendor_result(payout: Payout, result, *, attempt: int) -> bool:
    """벤더 응답을 이 attempt 에 남긴다 — 벤더가 준 자기 id 는 같은 attempt 일 때만 저장한다."""

    if result.vendor_payout_id:
        Payout.objects.filter(pk=payout.pk, transfer_attempt=attempt).update(
            vendor_payout_id=result.vendor_payout_id
        )
        payout.vendor_payout_id = result.vendor_payout_id
    return _record_transfer_result(payout, result.status, attempt)


def _request_real_transfer(payout: Payout, seller, adapter, *, simulate: str | None = None) -> bool:
    """Seller 가 READY 인 Payout 의 실이체를 요청하고 결과를 남긴다. COMPLETED 로 확정됐으면 True.

    이미 COMPLETED 면 벤더를 다시 부르지 않는다(코드리뷰 지적 2, 3차). 선점에 지면(다른 호출이
    같은 Payout 을 진행 중이다) 벤더를 부르지 않고 그 attempt 의 상태만 조회한다 — 이중 지급
    방지를 벤더의 Idempotency-Key 보존 기간에만 맡기지 않는다. 벤더 HTTP 는 트랜잭션 밖이다.

    타임아웃·명시적 거절 어느 쪽이든 「모른다」는 재확인으로, 그것마저 실패하면 pending 으로
    남긴다(`reconcile_after_timeout`) — 실패로 단정해 돈이 두 번 나가거나 영영 안 나가는 경로를
    만들지 않는다.
    """

    from payments.charges import reconcile_after_timeout

    from .adapters import PayoutError, PayoutTimeoutError, VendorResult

    T = Payout.TransferStatus
    payout.refresh_from_db()
    if payout.transfer_status == T.COMPLETED:
        return True

    claimed = _claim_transfer_attempt(payout)
    if claimed is None:
        payout.refresh_from_db(fields=["transfer_status", "transfer_attempt", "vendor_payout_id"])
        if payout.transfer_status == T.COMPLETED:
            return True
        if payout.transfer_status == T.FAILED:
            return False
        # 다른 호출이 이 attempt 를 진행 중이다 — 조회만 한다(POST 없음).
        result = reconcile_after_timeout(
            lambda: adapter.query_status(_transfer_request(payout, seller)),
            on_unknown=VendorResult(status="pending"),
            context=f"실이체 재확인(idempotency_key={payout.idempotency_key}, 선점 경합)",
        )
        return _apply_vendor_result(payout, result, attempt=payout.transfer_attempt)

    request = _transfer_request(claimed, seller)
    try:
        result = adapter.confirm(request, simulate=simulate)
    except PayoutTimeoutError:
        result = reconcile_after_timeout(
            lambda: adapter.query_status(request),
            on_unknown=VendorResult(status="pending"),
            context=f"실이체 재확인(idempotency_key={payout.idempotency_key}, attempt={claimed.transfer_attempt})",
        )
    except PayoutError as exc:
        # 자격증명 오류(401/403)처럼 재시도해도 풀리지 않는 원인이면 이 로그가 유일한 단서다
        # (코드리뷰 지적 13, 3차). 실패로 단정하지 않고 조회로 확정한다.
        logger.warning(
            "실이체 confirm()이 예외를 던졌다(idempotency_key=%s): %s — query_status로 재확인한다.",
            payout.idempotency_key,
            exc,
        )
        result = reconcile_after_timeout(
            lambda: adapter.query_status(request),
            on_unknown=VendorResult(status="pending"),
            context=f"실이체 재확인(idempotency_key={payout.idempotency_key}, confirm 거절 뒤)",
        )
    return _apply_vendor_result(claimed, result, attempt=claimed.transfer_attempt)


def advance(
    payout: Payout,
    *,
    register_seller: bool,
    adapter=None,
    confirm_with_vendor: bool = False,
    simulate: str | None = None,
    seller_simulate: str | None = None,
    confirmed_by_vendor: bool | None = None,
) -> Payout:
    """사실이 바뀐 뒤 Payout 을 다음 상태로 전진시킨다 — 사실 대조(reconcile) 한 곳 (#131, #133, #135).

    입구(확정·자체 웹훅·주민등록번호 제출·Seller 재시도·실물 웹훅·sweep·Distribution 몫 지급)는
    새 사실만 기록하고 이 함수를 부른다. 이 함수는 네 축(status · transfer_status · Seller READY
    · TaxIdentity)을 지금 다시 읽어 목표를 정한다 — 어떤 순서로 사실이 도착하든 마지막 advance 가
    같은 답을 낸다.

    **첫 홈(REQUESTED → 확정)**은 두 가지 사실 중 하나로 열린다. `confirm_with_vendor=True`(확정
    엔드포인트·Distribution)면 여기서 벤더에 묻는다 — Seller 가 이미 READY 면 그 물음이 곧 첫
    실이체 시도이고(`_request_real_transfer`), 아니면 수취인 없는 요청을 보내 벤더 규약대로 내부
    확정을 받는다. `confirmed_by_vendor`(웹훅)는 벤더가 이미 말해 준 결과다. True 면
    `UPDATE … WHERE status='requested'` 로 이긴 호출만 같은 트랜잭션에서 수수료·원천징수 공제
    분개를 남기고(`payments.charges.claim_and_post`) 두 대기로 들어간다; False 면 FAILED 로
    끝난다(원장에는 아무것도 없다 — 돈이 움직이지 않았다). pending 이면 확정하지 않는다.

    **두 대기 규칙(ADR-0020)**: Seller 가 READY 가 아니면 CONFIRMED_SELLER_PENDING. READY 면
    실이체를 요청하고, 그것이 COMPLETED 로 확정됐을 때만 신원 유무에 따라 CONFIRMED /
    CONFIRMED_IDENTITY_PENDING 으로 — Seller 가 READY 라는 사실만으로 전진시키면 벤더가
    실이체를 거절해도 「지급 완료」라고 말하게 된다(#57 코드리뷰 지적 1). 실이체가 아직
    안 풀렸으면 제자리다 — CIP 를 CSP 로 뭉치면 「신원은 이미 냈다」는 사실이 사라진다.

    `register_seller` — 이 입구가 Seller 등록을 촉발하는가. 확정과 재시도는 그렇고(ADR-0020:
    등록은 확정 시점에 시작된다), 신원 제출·웹훅·sweep 은 이미 있는 Seller 를 읽기만 한다.

    벤더 HTTP(Seller 등록·실이체)는 어떤 트랜잭션 밖에서 한다(코드리뷰 지적 7, 5차). 쓰기는
    `UPDATE … WHERE pk AND status=<읽은 값>` 한 번이고 rowcount 0 이면 다른 입구가 먼저
    전진시킨 것이니 아무것도 하지 않는다. adapter 는 주입받는다 — 없으면 설정의 것을 쓴다.
    """

    from payments.charges import Outcome, claim_and_post, reconcile_after_timeout

    from .adapters import PayoutTimeoutError, VendorResult, get_adapter
    from .models import TaxIdentity
    from .services import ensure_seller_registered

    if adapter is None:
        adapter = get_adapter()

    S = Payout.Status
    T = Payout.TransferStatus
    payout.refresh_from_db()

    if payout.status == S.REQUESTED:
        if confirmed_by_vendor is None and confirm_with_vendor:
            seller = payout.seller
            if seller is not None and seller.status in Seller.READY_STATUSES:
                # 첫 확정이 곧 첫 실이체 시도다 — 벤더가 받아들였는가를 실이체 결과로 안다.
                _request_real_transfer(payout, seller, adapter, simulate=simulate)
                payout.refresh_from_db()
                if payout.transfer_status == T.COMPLETED:
                    confirmed_by_vendor = True
                elif payout.transfer_status == T.FAILED:
                    confirmed_by_vendor = False
                else:
                    return payout  # pending — 확정하지 않는다
            else:
                request = _transfer_request(payout, None)
                try:
                    result = adapter.confirm(request, simulate=simulate)
                except PayoutTimeoutError:
                    result = reconcile_after_timeout(
                        lambda: adapter.query_status(request),
                        on_unknown=VendorResult(status="pending"),
                        context=f"지급 확정 재확인(idempotency_key={payout.idempotency_key})",
                    )
                outcome = Outcome.parse(result.status)
                if outcome is Outcome.PENDING:
                    return payout
                confirmed_by_vendor = outcome is Outcome.PAID
        if confirmed_by_vendor is None:
            return payout
        payout, _claimed = claim_and_post(
            Payout.objects.with_target(),
            filters={"pk": payout.pk},
            from_status=S.REQUESTED,
            to_status=S.CONFIRMED_IDENTITY_PENDING if confirmed_by_vendor else S.FAILED,
            journal=_confirmation_journal if confirmed_by_vendor else None,
        )

    original = payout.status
    if original not in (S.CONFIRMED_IDENTITY_PENDING, S.CONFIRMED_SELLER_PENDING):
        return payout

    developer = payout.developer
    if register_seller:
        seller = ensure_seller_registered(developer, simulate=seller_simulate)
        # ensure_seller_registered 가 Seller 를 막 READY 로 만들면 그 안에서 sweep 이 이
        # Payout 을 이미 전진시켰을 수 있다 — 낡은 값으로 판단하지 않도록 다시 읽는다.
        payout.refresh_from_db()
        original = payout.status
        if original not in (S.CONFIRMED_IDENTITY_PENDING, S.CONFIRMED_SELLER_PENDING):
            return payout
    else:
        seller = Seller.objects.filter(developer=developer).first()

    seller_ready = seller is not None and seller.status in Seller.READY_STATUSES
    if not seller_ready:
        target = S.CONFIRMED_SELLER_PENDING
    elif _request_real_transfer(payout, seller, adapter):
        has_identity = TaxIdentity.objects.filter(payout=payout).exists()
        target = S.CONFIRMED if has_identity else S.CONFIRMED_IDENTITY_PENDING
    else:
        target = original

    if target != original:
        Payout.objects.filter(pk=payout.pk, status=original).update(status=target)
    payout.refresh_from_db()
    return payout


def retry_confirmed_transfer(payout: Payout, *, adapter=None) -> Payout:
    """`HoldKind.TRANSFER_OPERATOR`(CONFIRMED 뒤 뒤늦게 실이체 실패가 확인된 Payout)의
    실이체를 다시 시도한다(#182 — 운영자 표면의 새 진입점).

    벤더를 부르는 코드는 새로 만들지 않는다 — 다른 모든 실이체 재시도가 쓰는
    `_request_real_transfer` 그대로다. `advance()`는 `status` 가
    `CONFIRMED_IDENTITY_PENDING`/`CONFIRMED_SELLER_PENDING` 일 때만 이 상태를
    다시 진행시키는데(위 early return), CONFIRMED 로 이미 넘어간 뒤에는 그
    조건에 걸리지 않아 이 상태(#57/ADR-0008 이 "자기 서비스 재시도 경로가 아직
    없다"고 적어 둔 바로 그 자리)를 아무도 다시 부를 수 없었다 — 이 함수가 그
    진입로를 연다.

    `status` 는 이미 CONFIRMED 였으므로 성공해도 되돌리지 않는다(ADR-0004,
    `TransferStatus` 의 독스트링 — 원장 분개는 확정 시점에 이미 남았고 이
    필드는 실이체 자체의 진행만 기록한다). Seller 가 READY 가 아니면(웹훅으로
    거절이 뒤늦게 들어온 경우 등) 아무 것도 하지 않고 그대로 돌려준다 — 이
    함수는 호출부(`payouts.services.retry_payout_for_operator`)가 Hold 로 미리
    걸러 준 상태에서만 불린다는 전제이지만, 그 전제가 깨져도 안전하게 아무
    일도 하지 않는다.
    """

    from .adapters import get_adapter as _get_adapter

    T = Payout.TransferStatus
    payout.refresh_from_db()
    if payout.status != Payout.Status.CONFIRMED or payout.transfer_status != T.FAILED:
        return payout

    seller = payout.seller
    if seller is None or seller.status not in Seller.READY_STATUSES:
        return payout

    _request_real_transfer(payout, seller, adapter or _get_adapter())
    payout.refresh_from_db()
    return payout
