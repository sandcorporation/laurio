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

from .models import Payout, Seller

logger = logging.getLogger(__name__)


class HoldKind(str, Enum):
    # 확정 전 — 붙드는 것이 없다.
    REQUESTED = "requested"
    # 주민등록번호 미제출 — Developer 의 차례.
    IDENTITY = "identity"
    # 신원은 냈고 전진(실이체 확정)을 기다린다.
    IDENTITY_RECORDED = "identity_recorded"
    # Seller 등록에 전화번호가 필요하다 — Developer 의 차례.
    SELLER_PHONE = "seller_phone"
    # 지급대행사의 본인인증 문자 — Developer 의 차례.
    SELLER_AUTH = "seller_auth"
    # 지급대행사 심사 중 — 벤더의 차례.
    SELLER_REVIEW = "seller_review"
    # 수취인 등록 거절 — Operator 의 차례.
    SELLER_REJECTED = "seller_rejected"
    # 등록 접수 후 응답 대기 — 벤더의 차례.
    SELLER_PENDING = "seller_pending"
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
    HoldKind.SELLER_PHONE: Turn.DEVELOPER,
    HoldKind.SELLER_AUTH: Turn.DEVELOPER,
    HoldKind.SELLER_REVIEW: Turn.VENDOR,
    HoldKind.SELLER_REJECTED: Turn.OPERATOR,
    HoldKind.SELLER_PENDING: Turn.VENDOR,
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
    HoldKind.SELLER_PHONE: "seller",
    HoldKind.SELLER_AUTH: "seller",
    HoldKind.SELLER_REVIEW: "seller",
    HoldKind.SELLER_REJECTED: "seller",
    HoldKind.SELLER_PENDING: "seller",
    HoldKind.TRANSFER_CONFIRMING: "transfer",
    HoldKind.TRANSFER_RETRY: "transfer",
    HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED: "transfer",
    HoldKind.TRANSFER_OPERATOR: "transfer",
    HoldKind.COMPLETE: None,
    HoldKind.FAILED: None,
    HoldKind.UNKNOWN: "operator",
}


def assert_covers_all_kinds(table: dict, *, name: str) -> None:
    """번역표가 HoldKind 전체를 덮는지 — 값이 하나 늘면 모듈 로드 시 터진다."""

    missing = set(HoldKind) - set(table)
    if missing:
        raise RuntimeError(f"{name} 이 HoldKind 를 전부 덮지 않는다: {sorted(k.value for k in missing)}")


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
            seller is not None and seller.phone_number
        ):
            # PENDING 이면서 전화번호도 없다 — 「우리가 응답을 기다린다」가 아니라
            # 「Developer 가 낼 것이 있다」(#57 추가 인수조건).
            kind = HoldKind.SELLER_PHONE
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


def advance(
    payout: Payout,
    *,
    register_seller: bool,
    seller_simulate: str | None = None,
    confirmed_by_vendor: bool | None = None,
    policy=None,
) -> Payout:
    """사실이 바뀐 뒤 Payout 을 다음 상태로 전진시킨다 — 사실 대조(reconcile) 한 곳 (#131, #133).

    입구(확정·자체 웹훅·주민등록번호 제출·Seller 재시도·실물 웹훅·sweep·Distribution 몫 지급)는
    새 사실만 기록하고 이 함수를 부른다. 이 함수는 네 축(status · transfer_status · Seller READY
    · TaxIdentity)을 지금 다시 읽어 목표를 정한다 — 어떤 순서로 사실이 도착하든 마지막 advance 가
    같은 답을 낸다.

    **첫 홈만 외부 사실을 받는다** — `confirmed_by_vendor` 는 「벤더가 이 지급 요청을 받아들였는가」.
    REQUESTED 에서 True 면 `UPDATE … WHERE status='requested'` 로 이긴 호출만 같은 트랜잭션에서
    수수료·원천징수 공제 분개를 남기고(`payments.charges.claim_and_post`, ADR-0003·0004) 두 대기로
    들어간다; False 면 FAILED 로 끝난다(원장에는 아무것도 없다 — 돈이 움직이지 않았다). 그 뒤는
    전부 파생이다.

    **두 대기 규칙(ADR-0020)**: Seller 가 READY 가 아니면 CONFIRMED_SELLER_PENDING. READY 면
    실이체를 요청하고, 그것이 COMPLETED 로 확정됐을 때만 신원 유무에 따라 CONFIRMED /
    CONFIRMED_IDENTITY_PENDING 으로 — Seller 가 READY 라는 사실만으로 전진시키면 벤더가
    실이체를 거절해도 「지급 완료」라고 말하게 된다(#57 코드리뷰 지적 1). 실이체가 아직
    안 풀렸으면 제자리다 — CIP 를 CSP 로 뭉치면 「신원은 이미 냈다」는 사실이 사라진다.

    `register_seller` — 이 입구가 Seller 등록을 촉발하는가. 확정과 재시도는 그렇고(ADR-0020:
    등록은 확정 시점에 시작된다), 신원 제출·웹훅·sweep 은 이미 있는 Seller 를 읽기만 한다.

    벤더 HTTP(Seller 등록·실이체)는 어떤 트랜잭션 밖에서 한다(코드리뷰 지적 7, 5차) — 원장
    분개는 그 전에 이미 커밋돼 있다. 쓰기는 `UPDATE … WHERE pk AND status=<읽은 값>` 한 번이고
    rowcount 0 이면 다른 입구가 먼저 전진시킨 것이니 아무것도 하지 않는다.
    """

    from payments.charges import claim_and_post

    from .models import TaxIdentity
    from .services import _request_real_transfer_if_ready, ensure_seller_registered

    S = Payout.Status
    payout.refresh_from_db()

    if payout.status == S.REQUESTED:
        if confirmed_by_vendor is None:
            return payout
        if confirmed_by_vendor:
            payout, _claimed = claim_and_post(
                Payout.objects.with_target(),
                filters={"pk": payout.pk},
                from_status=S.REQUESTED,
                to_status=S.CONFIRMED_IDENTITY_PENDING,
                journal=_confirmation_journal,
            )
        else:
            payout, _claimed = claim_and_post(
                Payout.objects.with_target(),
                filters={"pk": payout.pk},
                from_status=S.REQUESTED,
                to_status=S.FAILED,
            )

    original = payout.status
    if original not in (S.CONFIRMED_IDENTITY_PENDING, S.CONFIRMED_SELLER_PENDING):
        return payout

    developer = payout.developer
    if register_seller:
        seller = ensure_seller_registered(developer, simulate=seller_simulate, policy=policy)
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
    elif _request_real_transfer_if_ready(payout):
        has_identity = TaxIdentity.objects.filter(payout=payout).exists()
        target = S.CONFIRMED if has_identity else S.CONFIRMED_IDENTITY_PENDING
    else:
        target = original

    if target != original:
        Payout.objects.filter(pk=payout.pk, status=original).update(status=target)
    payout.refresh_from_db()
    return payout
