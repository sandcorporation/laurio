"""Payout 도메인 로직 (#15, #50, ADR-0003, ADR-0004, ADR-0008, ADR-0020).

API 레이어(`payouts.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로 여기
함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

핵심 규율(`payments.services`와 같은 조건부 UPDATE): `Payout.status`를
`UPDATE ... WHERE idempotency_key=? AND status='requested'`로만 확정시키고,
rowcount가 1일 때만 원장에 수수료·원천징수 공제 분개를 남긴다. 이 하나의 규율이
세 가지 장애 흐름을 동시에 막는다:

- 같은 웹훅이 두 번 온다 — 두 번째 UPDATE는 rowcount 0이라 아무 것도 하지 않는다.
- 웹훅이 동기 confirm보다 먼저 도착한다 — 먼저 도착한 쪽이 이기고, 나중 것은
  이미 바뀐 상태를 보고 조용히 넘어간다.
- confirm 호출이 타임아웃됐지만 실제로는 성공했다 — 호출자는 `query_status`로
  진짜 결과를 확인한 뒤에만 이 함수들을 부른다(`payouts.api`).

지급 확정은 항상 CONFIRMED_IDENTITY_PENDING을 거친다 — 주민등록번호는 가입
시점이 아니라 Payout이 확정된 시점에만 수집하므로(ADR-0008), 확정되는 순간에는
아직 신원 정보가 없는 것이 정상 경로다. 원장 분개는 CONFIRMED_IDENTITY_PENDING
진입 시점에 이미 남는다 — 신원 정보 유무도, Seller 등록 여부도 금액이 원장에서
사라지거나 다시 계산되게 만들지 않는다.

**Seller 등록은 이 확정 시점에만 시작된다**(ADR-0020) — `ensure_seller_registered`가
`advance`에서 자동으로 호출된다. 이미 부분 승인된 Seller가 있으면(두 번째
Payout부터) 어댑터를 다시 부르지 않고 그대로 통과한다. 아직 부분 승인이 아니면
(한도 초과·심사 필요·거절 어느 쪽이든) `CONFIRMED_SELLER_PENDING`에 머문다 —
`CONFIRMED_IDENTITY_PENDING`("신원 대기")과는 다른 것을 기다리는 별개 상태다.
`submit_identity`와 `retry_seller_registration`이 이 두 대기를 마저 풀어 CONFIRMED로
옮긴다.
"""

from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from policies.models import PlatformPolicy
from policies.services import get_current_policy
from verification.crypto import encrypt

from .adapters import SellerError, get_seller_adapter
from .models import Payout, Seller, TaxIdentity
from .targets import PayoutTarget

logger = logging.getLogger(__name__)

# REQUESTED든 그 이후 확정 상태든 "아직 실패로 끝나지 않은" 시도는 활성으로 본다
# — models.Payout.Meta.constraints의 unique_active_payout_per_handover와 정확히
# 같은 집합이어야 한다(그쪽은 DB 레벨 최후 방어선, 이건 애플리케이션 레벨 조회
# 기준). FAILED만 빠진다 — 그래야 실패한 시도 뒤에 새 REQUESTED를 만들 수 있다.
# CONFIRMED_SELLER_PENDING도 활성이다 — Seller 등록이 안 끝났을 뿐 지급 자체는
# 이미 확정되어 원장에 분개가 남아 있다(#50).
_ACTIVE_PAYOUT_STATUSES = [
    Payout.Status.REQUESTED,
    Payout.Status.CONFIRMED_IDENTITY_PENDING,
    Payout.Status.CONFIRMED_SELLER_PENDING,
    Payout.Status.CONFIRMED,
]


def _withholding_exempt_threshold(policy: PlatformPolicy) -> int:
    """이 정책에서 원천징수가 면제되는 지급액의 상한(원)을 구조적으로 유도한다.

    과세최저한(기타소득금액이 `withholding_minor_income_exempt_won`원 이하)을
    필요경비율(`withholding_necessary_expense_bps`)로 지급액 기준으로 환산한다.
    기본값(필요경비 80%, 과세최저한 5만원)에서는 250,000원이 나온다.

    **`withholding_tax_bps`(원천징수율)는 이 계산에 전혀 관여하지 않는다** —
    코드리뷰 지적 3: 임계값이 원천징수율에서 유도되면, 원천징수율만 바꿔도(예:
    사업소득 세율 3.3%로 되돌리는 실수) 임계값이 그 의도와 무관하게 조용히
    따라 바뀐다. 임계값은 오직 "소득 중 몇 %가 과세 대상인가"(필요경비율)에서만
    나오므로, 원천징수율을 얼마로 바꾸든 이 임계값은 흔들리지 않는다 — 두 값이
    실수로 따로 움직여 조용히 틀려지는 경로 자체가 없다.

    `withholding_necessary_expense_bps`는 `PlatformPolicy`의 CheckConstraint가
    9999(<100%) 이하로 강제하므로 아래 나눗셈은 0으로 나누지 않는다.
    """

    remaining_bps = 10_000 - policy.withholding_necessary_expense_bps
    return policy.withholding_minor_income_exempt_won * 10_000 // remaining_bps


def _compute_amounts(prize_amount: int, policy: PlatformPolicy) -> tuple[int, int, int, int, bool]:
    """(플랫폼 수수료, 원천징수, 실지급액, 적용된 원천징수율bp, 면제 여부)를 계산한다.

    `policy`가 이 계산의 유일한 요율 출처다(#75, ADR-0023) — 호출자가 요청(또는
    스캔) 스코프당 한 번 읽은 `PlatformPolicy`를 넘겨야 한다.

    bp(1/10000) 단위 정수 비율로 계산해 float 오차를 피한다(ADR-0004). 수수료와
    원천징수는 내림으로 계산하고, 실지급액은 나머지 전부를 가져간다 — 반올림으로
    셋의 합이 prize_amount와 어긋나는 사고를 구조적으로 없앤다(ADR-0004의 1/N
    나머지 처리와 같은 정신: 단수가 어딘가로 사라지지 않는다). `PlatformPolicy`의
    CheckConstraint(`platform_fee_bps + withholding_tax_bps <= 10000`)가
    net_amount >= 0을 항상 보장한다(코드리뷰 지적 1) — floor(a)+floor(b) <=
    floor(a+b)이므로 fee+withholding <= prize_amount다.

    과세최저한 이하면(`_withholding_exempt_threshold`) 원천징수는 0이고, 반환하는
    "적용된 요율"도 0이다 — 정책의 명목 요율을 그대로 반환하면 "이 요율을
    적용했다"는 기록과 "0원 뗐다"는 금액이 모순된다(코드리뷰 지적 2). 지급액이
    임계값과 정확히 같아도 면제다(그 위에서만 붙는다).
    """

    fee = prize_amount * policy.platform_fee_bps // 10_000
    exempt = prize_amount <= _withholding_exempt_threshold(policy)
    if exempt:
        withholding = 0
        applied_withholding_bps = 0
    else:
        withholding = prize_amount * policy.withholding_tax_bps // 10_000
        applied_withholding_bps = policy.withholding_tax_bps
    net = prize_amount - fee - withholding
    return fee, withholding, net, applied_withholding_bps, exempt


def get_or_create_payout(target: PayoutTarget, *, policy: PlatformPolicy | None = None) -> Payout:
    """이 지급 사유(Handover 또는 DistributionShare 의 `payout_target()`)에 대한 활성
    Payout 을 멱등하게 만든다.

    활성(REQUESTED/CONFIRMED_IDENTITY_PENDING/CONFIRMED_SELLER_PENDING/CONFIRMED)이 이미
    있으면 그대로 돌려준다 — 중복 클릭·재요청이 새 idempotency_key를 계속 만들어내지
    않는다(payments.api.initiate_payment와 같은 관용구). 가장 최근 시도가 FAILED뿐이면
    (토스가 거절했거나 fake 시나리오로 실패를 흉내낸 경우) 새 REQUESTED 행을 만들어
    재시도를 허용한다 — Escrow에 갇힌 상금이 재시도 경로 없이 영구히 묶이는 사고를 막는다.

    사유 행을 `select_for_update`로 잠가 동시 요청을 직렬화한다(payments.api.
    initiate_payment가 Contest를 잠그는 것과 같은 이유) — 잠금 없이 조회-후-생성하면 두
    요청이 동시에 "활성 Payout 없음"을 보고 각자 새 행을 만들어, unique 제약이 최후에
    하나만 통과시켜도 나머지 하나는 예외로 죽는다. 네트워크 호출(어댑터)은 이 함수
    밖에서 한다 — 이 함수는 순수 DB 쓰기만 하므로 트랜잭션 안에서도 안전하다.

    두 경로의 차이(잠그는 행·금액 출처·FK 이름)는 `PayoutTarget` 이 들고 오고(#129),
    나머지는 한 본문이다 — 전에는 50줄이 두 번 적혀 있었다.

    `policy`는 호출자가 요청(또는 스캔) 스코프당 한 번 읽어 넘겨야 한다(#75,
    ADR-0023) — 생략하면 이 호출 하나를 위해 새로 한 번 읽는다(단독 호출 편의용).
    """

    if policy is None:
        policy = get_current_policy()

    with transaction.atomic():
        locked = target.lock()
        fk = {target.fk_name: locked}
        active = Payout.objects.filter(**fk, status__in=_ACTIVE_PAYOUT_STATUSES).order_by(
            "-created_at"
        )
        existing = active.first()
        if existing is not None:
            return existing

        prize_amount = target.prize_amount_of(locked)
        fee, withholding, net, applied_withholding_bps, exempt = _compute_amounts(
            prize_amount, policy
        )

        try:
            # 중첩 atomic(세이브포인트)으로 감싼다(payments.api.initiate_payment와 같은
            # 이유, 코드리뷰 지적 1) — IntegrityError가 나면 Postgres는 세이브포인트가
            # 없는 바깥 트랜잭션 전체를 "aborted" 상태로 만들어 그 뒤의 어떤 쿼리도
            # 커밋 전까지 막아버린다. 세이브포인트가 없으면 아래 except 절의 조회조차
            # `TransactionManagementError`로 실패해, 방어적 안전망이 오히려 원인을 덮는
            # 새 500을 만든다.
            with transaction.atomic():
                return Payout.objects.create(
                    **fk,
                    prize_amount=prize_amount,
                    platform_fee_amount=fee,
                    withholding_tax_amount=withholding,
                    net_amount=net,
                    platform_fee_bps=policy.platform_fee_bps,
                    withholding_tax_bps=applied_withholding_bps,
                    withholding_exempt=exempt,
                    status=Payout.Status.REQUESTED,
                )
        except IntegrityError:
            # unique_active_payout_per_* 에 걸렸다 — 위 잠금에도 불구하고 도달했다면
            # 방어적 안전망이다. 이미 있는 활성 Payout을 그대로 돌려준다.
            existing = active.first()
            if existing is not None:
                return existing
            raise


def ensure_seller_registered(
    developer, *, simulate: str | None = None, policy: PlatformPolicy | None = None
) -> Seller:
    """이 Developer의 Seller 등록을 멱등하게 보장한다(#50, ADR-0020).

    이미 부분 승인된 Seller가 있으면 그대로 돌려주고 어댑터를 다시 부르지
    않는다 — `seller_id`가 Developer에 남아 두 번째 Payout부터는 재등록하지
    않는다는 요구가 여기서 지켜진다. 그 외(등록 전/심사 대기/거절)에는 등록
    (또는 재시도)을 어댑터에 요청하고 결과를 그대로 반영한다 — 한도 초과·심사
    필요·거절 어느 쪽도 예외를 던지지 않는다(정상 응답의 한 갈래다, ADR-0020).

    `policy`는 호출 스코프에서 이미 읽은 `PlatformPolicy`를 어댑터까지
    그대로 전달하는 자리다(#78, ADR-0023) — `get_or_create_payout`이 이미
    쓰는 것과 같은 관용구. `distributions.services.run_due_distributions`처럼
    한 스캔에서 여러 Developer를 순회하는 호출자는 반드시 넘겨야 한다 —
    생략하면 어댑터가 Developer 수만큼 정책을 다시 읽는다.
    """

    existing = Seller.objects.filter(developer=developer).first()
    if existing is not None and existing.status in Seller.READY_STATUSES:
        return existing

    adapter = get_seller_adapter()
    try:
        result = adapter.register(developer_id=developer.id, simulate=simulate, policy=policy)
    except SellerError:
        # 벤더 쪽 일시 오류(5xx·rate limit·타임아웃·네트워크)다 — 등록이 실제로
        # 어떻게 됐는지 알 수 없다(코드리뷰 지적 3/6). 이 함수는 advance의
        # transaction.atomic() 블록 안에서도 호출되므로, 여기서 예외를 그대로
        # 올려보내면 이미 커밋 대기 중이던 원장 분개(수수료·원천징수 공제)까지
        # 롤백된다 — ADR-0020의 "Seller 등록 결과와 무관하게 분개는 항상
        # 남는다"가 깨진다. 예외를 여기서 흡수하고 기존 상태를 그대로 돌려준다
        # (처음 시도라 기존 Seller 행이 없으면 PENDING 행만 만들어 다음
        # 재시도를 받을 수 있게 한다).
        logger.exception(
            "Seller 등록 어댑터 호출이 실패했다(developer_id=%s) — 원장 분개는 그대로 "
            "두고 기존 Seller 상태를 유지한다.",
            developer.id,
        )
        if existing is not None:
            return existing
        seller, _created = Seller.objects.get_or_create(developer=developer)
        return seller

    if result.status == "pending":
        # "pending"은 등록 자체를 아직 시도하지 않았거나(필수 정보 누락),
        # 벤더가 우리 seller_id를 더는 인식하지 못한다(GET 404, 코드리뷰
        # 지적 6, 4차)는 뜻이다 — 어느 쪽이든 "지킬 유효한 seller_id가
        # 없다"는 사실은 같다. 옛 seller_id를 그대로 보존하면 다음
        # register() 호출이 existing.seller_id를 보고 다시 그 죽은
        # seller_id로 조회(_query_seller_status)를 반복해 영원히 404를
        # 받고, 새 POST로 넘어갈 길이 없어진다.
        stored_seller_id = ""
    else:
        # 거절 응답이 빈 seller_id를 줄 수 있다 — 이전에 이미 받은 식별자가
        # 있으면 지우지 않는다(재시도로 같은 등록 건을 이어가는 실물 벤더의
        # 모양을 흉내낸다).
        stored_seller_id = result.seller_id or (existing.seller_id if existing else "")

    seller, _created = Seller.objects.update_or_create(
        developer=developer,
        defaults={
            "seller_id": stored_seller_id,
            "status": result.status,
            "weekly_limit_amount": result.weekly_limit_amount,
        },
    )

    if seller.status in Seller.READY_STATUSES:
        # 이 Developer의 *다른* Payout(별개 Contest 수상)이 CONFIRMED_SELLER_
        # PENDING에 남아 있을 수 있다(코드리뷰 지적 5, 4차) — 지금 이 호출이
        # 등록한 것은 이 Developer 단위의 Seller 하나이지 "이 Payout" 이
        # 아니다. advance_seller_pending_payouts를 여기서 부르지 않으면,
        # advance 가 처리하는 건 자기 자신의 Payout뿐이고 나머지는
        # 아무도 전진시키지 않는데도 화면은 "실이체 확인 중"이라 말하고
        # 재시도 버튼도 안 뜬다(Seller.status는 이미 READY라 "거절"도
        # "transfer_status=failed"도 아니기 때문이다) — 조용한 정체다.
        advance_seller_pending_payouts(developer)

    return seller


def _request_real_transfer_if_ready(payout: Payout) -> bool:
    """Seller가 방금 지급 가능 상태(READY_STATUSES)가 된 시점에 실제 이체를
    요청하고, 그 결과를 `Payout.transfer_status`에 남긴다(#57).

    **반환값이 계약이다.** `True`는 실이체가 COMPLETED로 확정됐다는 뜻이고,
    그때만 호출자가 `Payout.status`를 CONFIRMED_IDENTITY_PENDING/CONFIRMED로
    전진시켜야 한다(코드리뷰 지적 1) — 이전 버전은 이 반환값을 보지 않고
    Seller.status가 READY라는 사실만으로 `status`를 전진시켜, 벤더가 실이체
    자체를 거절해도 화면이 "지급이 완료되었습니다"라고 잘못 말했다.

    **토스 실물 연동을 붙이며 알게 된 순서 문제**(ADR-0008에도 남긴다): 토스
    지급대행의 실제 이체 API는 이미 등록된 sellerId를 요구하는데, 이 저장소의
    기존 순서(#50, ADR-0020)는 Payout이 먼저 확정되고 그 *뒤에* Seller
    등록이 시작된다 — 그래서 최초 확정 시점(`advance`)에는 아직
    sellerId가 없어 실물 어댑터가 이체를 요청할 수 없다.

    `payouts.adapters_toss.TossPayoutAdapter.confirm`은 이 순서를 그대로
    받아들인다 — Seller가 준비되지 않았으면 벤더를 부르지 않고 "paid"(Laurio
    내부 확정)만 돌려주고, 준비됐으면 실제로 벤더를 부른다. 그래서 Seller가
    나중에(재시도·웹훅으로) 준비되는 순간 이 함수가 `confirm`을 **한 번 더**
    불러 그제서야 실제 이체를 시도한다 — Fake 어댑터는 이 재호출에서도 항상
    "paid"를 돌려주므로(기본 시나리오) 기존 #50/#15 테스트의 관찰 가능한
    동작은 전혀 바뀌지 않는다(Fake의 `PayoutRequestResult`는 항상 즉시
    COMPLETED에 해당하는 "paid"이므로 `True`가 나오고, 기존 테스트가 기대하던
    CONFIRMED 전이가 그대로 일어난다).

    실패(FAILED)해도 크래시하거나 Payout을 되돌리지 않는다 — 원장 분개는 이미
    남아 있고(ADR-0004), 다음 재시도(재시도 엔드포인트 또는 웹훅)가 다시
    이 함수를 거친다. `PayoutTimeoutError`는 `PayoutError`의 서브클래스라
    (코드리뷰 지적 5) `query_status`가 또 타임아웃해도 이 함수 밖으로 새지
    않는다 — 벗어나면 호출자의 `transaction.atomic()`이 이미 커밋 대기 중이던
    원장 분개까지 롤백시킨다.
    """

    # 이미 COMPLETED면 벤더를 다시 부르지 않는다(코드리뷰 지적 2, 3차) --
    # advance/submit_identity/retry_seller_registration/
    # advance_seller_pending_payouts 네 경로 모두 이 함수를 다시 부를 수
    # 있고, 그중 어느 것도 "이미 완료됐는가"를 스스로 확인하지 않았다.
    # 이중 지급 방지를 토스의 Idempotency-Key 보존 기간에만 맡기지 않는다 --
    # 우리 쪽에서 먼저 걸러낸다.
    if payout.transfer_status == Payout.TransferStatus.COMPLETED:
        return True

    from .adapters import PayoutError, TransferOutcome, get_adapter

    adapter = get_adapter()
    try:
        outcome = adapter.confirm(idempotency_key=str(payout.idempotency_key))
    except PayoutError as exc:
        logger.warning(
            "실이체 confirm()이 예외를 던졌다(idempotency_key=%s): %s -- query_status로 "
            "재확인한다.",
            payout.idempotency_key,
            exc,
        )
        try:
            outcome = adapter.query_status(idempotency_key=str(payout.idempotency_key))
        except PayoutError as exc2:
            # 코드리뷰 지적 13(3차) -- 이전에는 이 두 예외를 로그 없이
            # 삼켰다. 자격증명 오류(401/403)처럼 재시도해도 절대 풀리지
            # 않는 원인이면 이 로그가 유일한 단서다 -- 로그가 없으면 Payout이
            # 영원히 "pending"에 머물러도 아무도 알아채지 못한다.
            logger.error(
                "실이체 confirm()과 query_status() 둘 다 실패했다"
                "(idempotency_key=%s): confirm=%s, query_status=%s",
                payout.idempotency_key,
                exc,
                exc2,
            )
            # 둘 다 실패해 지금 어느 attempt에 대한 이야기인지조차 신뢰할 수
            # 없다(코드리뷰 지적 5, 5차) — attempt=None으로 넘겨 record_
            # transfer_result가 아무것도 기록하지 않게 한다. 잘못된 attempt에
            # 기록하는 것보다 아무 것도 안 하는 편이 안전하다.
            outcome = TransferOutcome(status="pending", attempt=None)

    return record_transfer_result(payout, outcome.status, outcome.attempt)


def record_transfer_result(payout: Payout, result_status: str, attempt: int | None) -> bool:
    """`PayoutAdapter.confirm()`/`query_status()`가 돌려준 `TransferOutcome`을
    `Payout.transfer_status`에 기록하고, COMPLETED로 확정됐는지를 돌려준다.

    **왜 별도 함수인가(코드리뷰 지적 1, 4차의 후속 발견)** — Seller가 이미
    READY인 Payout은 `payouts.api.confirm_payout`의 직접 호출이 실제 벤더
    호출을 선점(claim)해 이길 수 있다(`TossPayoutAdapter.confirm()`의 두
    갈래 동작). 그런데 그 호출은 `_request_real_transfer_if_ready`를 거치지
    않으므로, 이 함수로 결과를 기록하는 지점이 하나뿐이면 "이긴 호출의
    결과가 어디에도 안 남는" 구멍이 생긴다 — 이후 `_request_real_transfer_
    if_ready`가 다시 불려도 클레임에 져서(rowcount 0) 벤더를 또 부를 수
    없고, 결국 REQUESTED에 영원히 머문다. `confirm_payout`도 이 함수를
    직접 불러 자신이 얻은 결과를 기록해야 한다.

    **`attempt`가 None이면 아무 것도 기록하지 않는다**(코드리뷰 지적 5, 5차) —
    실제로 벤더를 부르지 않았거나(Seller가 아직 READY가 아니었다), 어느
    attempt에 대한 결과인지 신뢰할 수 없다는 뜻이다. 이때 기록하면 실이체를
    시도한 적도 없이 COMPLETED로 잘못 남거나, 엉뚱한 attempt를 덮어쓴다.

    **`attempt`가 채워져 있으면 Payout의 현재 `transfer_attempt`와 일치할
    때만, 그리고 아직 COMPLETED가 아닐 때만 기록한다**(코드리뷰 지적 3, 5차
    — `resolve_transfer_webhook`이 이미 쓰는 COMPLETED 제외 규율을 여기에도
    적용하고, attempt 불일치까지 함께 걸러낸다) — 그러지 않으면 새 시도가
    이미 선점한 뒤에도 낡은(또는 경합에서 진) 시도의 결과가 뒤늦게 도착해
    진행 중이거나 이미 확정된 시도를 덮어쓸 수 있다.
    """

    if attempt is None:
        return payout.transfer_status == Payout.TransferStatus.COMPLETED

    if result_status == "paid":
        target_transfer_status = Payout.TransferStatus.COMPLETED
    elif result_status == "failed":
        target_transfer_status = Payout.TransferStatus.FAILED
    else:
        target_transfer_status = Payout.TransferStatus.REQUESTED

    updated = (
        Payout.objects.filter(pk=payout.pk, transfer_attempt=attempt)
        .exclude(transfer_status=Payout.TransferStatus.COMPLETED)
        .update(transfer_status=target_transfer_status)
    )
    if updated:
        payout.transfer_status = target_transfer_status
    else:
        payout.refresh_from_db(fields=["transfer_status", "transfer_attempt"])

    return payout.transfer_status == Payout.TransferStatus.COMPLETED


def advance_seller_pending_payouts(developer) -> list[Payout]:
    """Seller가 웹훅(`seller.changed`)으로 방금 지급 가능 상태가 됐을 때, 이
    Developer의 CONFIRMED_SELLER_PENDING Payout들을 `advance` 로 밀어준다(#57, #132).

    실물 어댑터는 `retry_seller_registration`처럼 우리가 다시 register()를 불러야만
    상태가 갱신되는 게 아니라, 토스가 비동기로(웹훅) 최종 상태를 알려준다 — 그
    경로에서도 두 대기 판정과 실이체 시도가 똑같이 일어나야 한다. 벤더 HTTP 호출은
    락 없이 한다(코드리뷰 지적 13) — advance 의 규율이다.
    """

    from .progress import advance

    seller = Seller.objects.filter(developer=developer).first()
    if seller is None or seller.status not in Seller.READY_STATUSES:
        return []

    candidates = Payout.objects.filter(status=Payout.Status.CONFIRMED_SELLER_PENDING).for_developer(developer)

    advanced: list[Payout] = []
    for candidate in candidates:
        before = candidate.status
        after = advance(candidate, register_seller=False)
        if after.status != before:
            advanced.append(after)
    return advanced


def resolve_transfer_webhook(idempotency_key, our_status: str) -> Payout:
    """실물 `payout.changed` 웹훅이 보고한 결과를 Payout에 반영한다(#57, 코드리뷰
    지적 1/4).

    Payout.status가 아직 REQUESTED면 기존 `advance`의
    조건부 UPDATE가 그대로 처리한다 — 원장 분개가 아직 없는 첫 확정
    경로다(#50/#15가 이미 검증). 이 함수가 새로 다루는 것은 **그 다음**이다:
    Payout이 이미 두 대기 어딘가로 넘어간 뒤(원장 분개는 이미 남아 있다)에
    실이체 자체의 결과가 지연 도착하는 경우다.

    이전 버전은 이 경우 "failed"를 그냥 버렸다(코드리뷰 지적 4) — Payout.status
    가 REQUESTED가 아니면 advance 가 조건에 안 맞아 아무 일도 하지
    않았고, 확정 이후 벤더가 진짜로 이체를 거절해도 Operator 큐에도 화면에도
    드러나지 않았다. `Payout.status`(두 대기가 풀렸는가)는 원장 사실이라
    되돌리지 않지만(ADR-0004), `transfer_status`는 별도 축이라 이 사실을
    그대로 기록해 화면에 드러낼 수 있다.

    "paid"가 CONFIRMED_SELLER_PENDING에 도착하면(이전에 `_request_real_transfer_
    if_ready`가 REQUESTED/pending으로 남겨 둔 실이체가 이 웹훅으로 뒤늦게
    COMPLETED로 확정된 경우) `advance_seller_pending_payouts`와 같은 규율로
    다음 상태로 밀어준다.
    """

    from .progress import advance

    payout = Payout.objects.get(idempotency_key=idempotency_key)

    if payout.status == Payout.Status.REQUESTED:
        # 첫 확정 경로 — 원장 분개가 아직 없다. 벤더 결과만 사실로 넘긴다(#133).
        if our_status == "paid":
            return advance(payout, confirmed_by_vendor=True, register_seller=True)
        if our_status == "failed":
            return advance(payout, confirmed_by_vendor=False, register_seller=False)
        return payout

    if our_status == "failed":
        # COMPLETED를 되돌리지 않는다(코드리뷰 지적 5, 3차) — 순서 보장이
        # 없는 웹훅 재전송·역순 도착 환경에서, 이미 실제로 성공한 뒤에 도착한
        # 오래된 FAILED가(예: 이전 시도의 지연된 사본) 방금 COMPLETED로 확정된
        # 사실을 지우면 "돈은 나갔는데 화면은 실패라고 말한다"는, 이 티켓이
        # 가장 경계하는 정반대 방향의 거짓말이 된다. COMPLETED가 이미
        # 아니었을 때만 FAILED를 반영한다 — 조건부 UPDATE 하나로 경합도
        # 안전하다.
        updated = (
            Payout.objects.filter(pk=payout.pk)
            .exclude(transfer_status=Payout.TransferStatus.COMPLETED)
            .update(transfer_status=Payout.TransferStatus.FAILED)
        )
        if updated:
            payout.transfer_status = Payout.TransferStatus.FAILED
        else:
            payout.refresh_from_db()
        return payout

    if our_status == "paid":
        # 사실(실이체 COMPLETED)만 기록하고 advance 에 맡긴다(#132) — 두 대기가 모두 풀렸으면
        # CONFIRMED 로, 신원이 아직이면 CONFIRMED_IDENTITY_PENDING 으로 간다.
        Payout.objects.filter(pk=payout.pk).update(transfer_status=Payout.TransferStatus.COMPLETED)
        return advance(payout, register_seller=False)

    # "pending"(REQUESTED/IN_PROGRESS) — 아직 확정할 수 없다. 기록만 하고
    # 조용히 넘어간다.
    return payout


def submit_identity(payout: Payout, resident_registration_number: str) -> Payout:
    """주민등록번호를 암호화해 별도 테이블에 저장하고, 그 사실로 Payout 을 전진시킨다.

    `TaxIdentity`를 `update_or_create`로 upsert한다 — 재제출은 항상 최신 값으로
    덮어쓴다. 이미 있는 값을 그대로 다시 보내면(재전송) 같은 값으로 덮어쓸 뿐이라
    안전하고, 실수로 잘못 입력한 값을 보냈다면(오타) 정정할 수 있는 유일한
    경로이기도 하다 — TaxIdentity는 append-only 원장이 아니라 세무 신고용
    현재값 저장소다(#15 리뷰 지적 4).

    상태 판정은 `payouts.progress.advance` 가 한다(#131) — 이 입구는 사실(신원)만 기록한다.
    이미 CONFIRMED 인 뒤의 정정 제출은 상태를 건드리지 않는다(advance 가 두 대기 상태만 본다).
    """

    with transaction.atomic():
        TaxIdentity.objects.update_or_create(
            payout=payout,
            defaults={
                "resident_registration_number_encrypted": encrypt(resident_registration_number)
            },
        )
    # 벤더 HTTP 호출(실이체 확인)은 트랜잭션 밖 — TaxIdentity upsert 는 이미 커밋됐다.
    from .progress import advance

    return advance(payout, register_seller=False)


def retry_seller_registration(payout: Payout, *, simulate: str | None = None) -> Payout:
    """Seller 등록(또는 실이체)을 다시 시도한다(#50, ADR-0020) — 판정은 `advance` 가 한다(#132).

    CONFIRMED_SELLER_PENDING 이면 등록을 다시 시도하고(`register_seller=True`), 그 결과
    READY 면 실이체까지 확정될 때만 다음 상태로 간다. 여전히 READY 가 아니면(한도 초과·심사
    필요·거절) 그대로 남는다 — 실패로 종결되지 않는다.

    CONFIRMED_IDENTITY_PENDING 인데 실이체만 FAILED 인 경우도 받는다 — Seller 는 이미 READY
    였고 실이체 자체만 거절된 상태라, 프런트의 「다시 시도」가 여기로 온다(#57 코드리뷰 지적
    6, 3차). 이때는 등록을 다시 시도하지 않고 지금 Seller 를 읽는다(그 사이 웹훅으로
    REJECTED 가 됐을 수 있다 — 그러면 advance 가 Seller 대기로 옮긴다).

    벤더 HTTP 호출은 락 밖에서 한다(코드리뷰 지적 14, 3차) — advance 의 규율이다.
    """

    from .progress import advance

    current = Payout.objects.get(pk=payout.pk)
    if current.status == Payout.Status.CONFIRMED_SELLER_PENDING:
        return advance(current, register_seller=True, seller_simulate=simulate)
    if (
        current.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
        and current.transfer_status == Payout.TransferStatus.FAILED
    ):
        return advance(current, register_seller=False)
    return current


def submit_seller_phone(developer, phone_number: str) -> Seller:
    """토스 셀러 등록(businessType=INDIVIDUAL)의 individual 객체가 요구하는
    전화번호를 제출한다(#57).

    가입·제출 시점에는 어디에도 저장되지 않는 값이라(CLAUDE.md 도메인에 phone
    개념 자체가 없다) `TaxIdentity.resident_registration_number`와 같은 원칙으로
    별도 제출을 받는다 — Payout이 아직 확정되지 않았어도 미리 제출해 둘 수
    있다(Seller 자체는 여전히 확정 시점에만 등록을 시도한다, ADR-0020 —
    이 함수는 그 규율을 어기지 않는다. 값을 미리 저장만 해 둘 뿐 등록을
    앞당기지 않는다).

    이미 CONFIRMED_SELLER_PENDING에 머물던 Payout이 있으면(실물 어댑터가
    전화번호가 없어 PENDING에 계속 머물렀던 경우, `TossSellerAdapter.register`
    참고) 저장 직후 곧바로 재시도한다 — Developer가 전화번호를 내고 나서도
    "다시 시도" 버튼을 또 눌러야 한다면 그 자체가 침묵으로 읽힌다.
    """

    with transaction.atomic():
        seller, _created = Seller.objects.select_for_update().get_or_create(developer=developer)
        seller.phone_number = phone_number
        seller.save(update_fields=["phone_number_encrypted", "updated_at"])

    pending_payouts = Payout.objects.filter(status=Payout.Status.CONFIRMED_SELLER_PENDING).for_developer(developer)
    for pending_payout in pending_payouts:
        retry_seller_registration(pending_payout)

    seller.refresh_from_db()
    return seller
