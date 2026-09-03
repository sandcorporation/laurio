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
    policy=None,
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
    elif _request_real_transfer(payout, seller, adapter):
        has_identity = TaxIdentity.objects.filter(payout=payout).exists()
        target = S.CONFIRMED if has_identity else S.CONFIRMED_IDENTITY_PENDING
    else:
        target = original

    if target != original:
        Payout.objects.filter(pk=payout.pk, status=original).update(status=target)
    payout.refresh_from_db()
    return payout
