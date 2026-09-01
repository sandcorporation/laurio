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
`mark_confirmed`에서 자동으로 호출된다. 이미 부분 승인된 Seller가 있으면(두 번째
Payout부터) 어댑터를 다시 부르지 않고 그대로 통과한다. 아직 부분 승인이 아니면
(한도 초과·심사 필요·거절 어느 쪽이든) `CONFIRMED_SELLER_PENDING`에 머문다 —
`CONFIRMED_IDENTITY_PENDING`("신원 대기")과는 다른 것을 기다리는 별개 상태다.
`submit_identity`와 `retry_seller_registration`이 이 두 대기를 마저 풀어 CONFIRMED로
옮긴다.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from policies.models import PlatformPolicy
from policies.services import get_current_policy
from verification.crypto import encrypt

from .adapters import get_seller_adapter
from .models import Payout, Seller, TaxIdentity

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


def get_or_create_payout(handover=None, *, distribution_share=None, policy: PlatformPolicy | None = None) -> Payout:
    """이 Handover(또는 DistributionShare)에 대한 활성 Payout을 멱등하게 만든다.

    정확히 하나만 넘겨야 한다 — 어느 쪽이든 그 대상이 Payout이 실제로 가리키는
    지급 사유가 된다(`payouts.models.Payout.payout_exactly_one_target`과 같은
    불변식). `distribution_share`는 #16 — Distribution(무응답 1/N 배분)이 Award
    없이도 이 경로를 그대로 재사용할 수 있게 하는 두 번째 대상이다.

    활성(REQUESTED/CONFIRMED_IDENTITY_PENDING/CONFIRMED)이 이미 있으면 그대로
    돌려준다 — 중복 클릭·재요청이 새 idempotency_key를 계속 만들어내지 않는다
    (payments.api.initiate_payment와 같은 관용구). 가장 최근 시도가 FAILED뿐이면
    (토스가 거절했거나 fake 시나리오로 실패를 흉내낸 경우) 새 REQUESTED 행을
    만들어 재시도를 허용한다 — Escrow에 갇힌 상금이 재시도 경로 없이 영구히
    묶이는 사고를 막는다.

    대상 행을 `select_for_update`로 잠가 동시 요청을 직렬화한다
    (payments.api.initiate_payment가 Contest를 잠그는 것과 같은 이유) — 잠금
    없이 조회-후-생성하면 두 요청이 동시에 "활성 Payout 없음"을 보고 각자 새
    행을 만들어, unique 제약이 최후에 하나만 통과시켜도 나머지 하나는 예외로
    죽는다. 네트워크 호출(어댑터)은 이 함수 밖(API 레이어)에서 한다 — 이 함수는
    순수 DB 쓰기만 하므로 트랜잭션 안에서도 안전하다("외부 네트워크 호출을
    transaction.atomic() 안에 넣지 않는다"는 lessons-learned 원칙).

    `policy`는 호출자가 요청(또는 스캔) 스코프당 한 번 읽어 넘겨야 한다(#75,
    ADR-0023) — 생략하면 이 호출 하나를 위해 새로 한 번 읽는다(단독 호출 편의용,
    `core.transitions.claim_transition`이 `now`를 생략 가능하게 둔 것과 같은
    관용구). `distributions.services.run_due_distributions`처럼 여러 몫을 순회하며
    이 함수를 반복 호출하는 곳은 반드시 미리 읽은 값을 넘겨야 한다 — 그러지
    않으면 몫 수만큼 정책 조회가 나간다.
    """

    if (handover is None) == (distribution_share is None):
        raise ValueError("handover 또는 distribution_share 중 정확히 하나만 넘겨야 한다.")

    if policy is None:
        policy = get_current_policy()

    if handover is not None:
        from handovers.models import Handover

        with transaction.atomic():
            locked = Handover.objects.select_for_update().get(pk=handover.pk)
            existing = (
                Payout.objects.filter(handover=locked, status__in=_ACTIVE_PAYOUT_STATUSES)
                .order_by("-created_at")
                .first()
            )
            if existing is not None:
                return existing

            prize_amount = locked.award.contest.prize
            fee, withholding, net, applied_withholding_bps, exempt = _compute_amounts(
                prize_amount, policy
            )

            try:
                # 중첩 atomic(세이브포인트)으로 감싼다(payments.api.initiate_payment와
                # 같은 이유, 코드리뷰 지적 1) — IntegrityError가 나면 Postgres는
                # 세이브포인트가 없는 바깥 트랜잭션 전체를 "aborted" 상태로 만들어
                # 그 뒤의 어떤 쿼리도 커밋 전까지 막아버린다. 세이브포인트가 없으면
                # 아래 except 절의 조회(existing = Payout.objects.filter(...))조차
                # `TransactionManagementError`로 실패해, 방어적 안전망이 오히려
                # 원인을 덮는 새 500을 만든다.
                with transaction.atomic():
                    return Payout.objects.create(
                        handover=locked,
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
                # unique_active_payout_per_handover에 걸렸다 — 위 잠금에도
                # 불구하고 도달했다면 방어적 안전망이다(payments.api.
                # initiate_payment와 같은 이유). 이미 있는 활성 Payout을 그대로
                # 돌려준다.
                existing = (
                    Payout.objects.filter(handover=locked, status__in=_ACTIVE_PAYOUT_STATUSES)
                    .order_by("-created_at")
                    .first()
                )
                if existing is not None:
                    return existing
                raise

    from distributions.models import DistributionShare

    with transaction.atomic():
        locked = DistributionShare.objects.select_for_update().get(pk=distribution_share.pk)
        existing = (
            Payout.objects.filter(
                distribution_share=locked, status__in=_ACTIVE_PAYOUT_STATUSES
            )
            .order_by("-created_at")
            .first()
        )
        if existing is not None:
            return existing

        prize_amount = locked.amount
        fee, withholding, net, applied_withholding_bps, exempt = _compute_amounts(
            prize_amount, policy
        )

        try:
            # 세이브포인트로 감싼다 — 위 handover 분기와 같은 이유(코드리뷰 지적 1).
            with transaction.atomic():
                return Payout.objects.create(
                    distribution_share=locked,
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
            # unique_active_payout_per_distribution_share에 걸렸다 — 위와 같은
            # 방어적 안전망이다.
            existing = (
                Payout.objects.filter(
                    distribution_share=locked, status__in=_ACTIVE_PAYOUT_STATUSES
                )
                .order_by("-created_at")
                .first()
            )
            if existing is not None:
                return existing
            raise


def _resolve_contest(payout: Payout):
    """이 Payout이 어느 지급 사유(Handover 또는 DistributionShare)를 통해 어느
    Contest에 속하는지 판정한다. `payout_exactly_one_target` 제약이 이미 정확히
    하나만 채워짐을 보장하므로 분기는 여기서 끝난다.
    """

    if payout.handover_id is not None:
        return payout.handover.award.contest
    return payout.distribution_share.distribution.contest


def _resolve_developer(payout: Payout):
    """이 Payout을 받을 `accounts.DeveloperProfile` — `_resolve_contest`와 같은
    이유로 두 경로(Handover/DistributionShare) 중 하나를 통해서만 판정된다.
    Seller는 이 Developer 단위로 등록된다(한 Developer가 여러 Contest를 이겨도
    등록은 한 번).
    """

    if payout.handover_id is not None:
        return payout.handover.award.submission.developer
    return payout.distribution_share.submission.developer


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
    if existing is not None and existing.status == Seller.Status.PARTIALLY_APPROVED:
        return existing

    adapter = get_seller_adapter()
    result = adapter.register(developer_id=developer.id, simulate=simulate, policy=policy)

    seller, _created = Seller.objects.update_or_create(
        developer=developer,
        defaults={
            # 거절 응답이 빈 seller_id를 줄 수 있다 — 이전에 이미 받은 식별자가
            # 있으면 지우지 않는다(재시도로 같은 등록 건을 이어가는 실물 벤더의
            # 모양을 흉내낸다).
            "seller_id": result.seller_id or (existing.seller_id if existing else ""),
            "status": result.status,
            "weekly_limit_amount": result.weekly_limit_amount,
        },
    )
    return seller


def mark_confirmed(
    idempotency_key,
    *,
    seller_simulate: str | None = None,
    policy: PlatformPolicy | None = None,
) -> Payout:
    """지급을 확정한다(CONFIRMED_IDENTITY_PENDING, 또는 Seller가 아직 준비되지
    않았으면 CONFIRMED_SELLER_PENDING). 이미 확정되어 있으면 그대로 돌려준다.

    이겼을 때만(rowcount==1) 원장에 수수료·원천징수 공제 분개를 남긴다. 원천징수는
    반드시 원천징수 예수금 계정에 계상된다(ADR-0004/0008) — 국세청에 낼 남의
    돈이므로 플랫폼 수수료 수익과 섞이지 않는다. **이 분개는 Seller 등록 결과와
    무관하게 항상 남는다** — 한도 초과·심사 지연·거절 어느 경로로도 확정된 금액이
    원장에서 사라지지 않는다(ADR-0004, #50 AC).

    `seller_simulate`는 fake Seller 어댑터 전용 시나리오 선택이다
    (`ConfirmPayoutIn.seller_simulate`와 같은 원칙, `payments.api.ConfirmPaymentIn.
    simulate`를 본뜬 관용구) — 실제 어댑터에서는 의미가 없다. 웹훅 경로는 이
    인자를 넘기지 않으므로 항상 기본(즉시 부분 승인) 시나리오로 등록을 시도한다.

    `policy`는 `ensure_seller_registered`로 그대로 전달된다(#78, ADR-0023) —
    스캔 스코프에서 이미 읽은 정책을 넘기지 않으면(단독 호출 편의용 기본값
    None) Seller 등록 시점에 한 번 더 읽는다.
    """

    with transaction.atomic():
        updated = Payout.objects.filter(
            idempotency_key=idempotency_key, status=Payout.Status.REQUESTED
        ).update(status=Payout.Status.CONFIRMED_IDENTITY_PENDING)
        payout = Payout.objects.select_related(
            "handover__award__contest",
            "handover__award__submission__developer",
            "distribution_share__distribution__contest",
            "distribution_share__submission__developer",
        ).get(idempotency_key=idempotency_key)

        if updated != 1:
            # 이미 확정(또는 그 이후)이거나 실패다 — 다른 채널이 먼저 이겼거나
            # 재전송이다. 원장에는 이미 반영되어 있거나 애초에 없어야 한다.
            return payout

        contest = _resolve_contest(payout)
        entry = post_journal_entry(
            contest_id=contest.ledger_id,
            memo=(
                f"Contest #{contest.id} Payout 확정 — 플랫폼 수수료 "
                f"{payout.platform_fee_amount:,}원 + 원천징수 "
                f"{payout.withholding_tax_amount:,}원 공제 (실지급액 "
                f"{payout.net_amount:,}원)"
            ),
            lines=[
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

        Payout.objects.filter(pk=payout.pk).update(journal_entry_id=entry.id)
        payout.journal_entry_id = entry.id

        # Seller 등록은 이 확정 시점에만 시작된다(ADR-0020) — 그 전에는 어떤
        # 신원 정보도 지급대행사에 넘기지 않는다. 이미 부분 승인된 Seller가
        # 있으면(두 번째 Payout부터) ensure_seller_registered가 어댑터를 다시
        # 부르지 않는다.
        developer = _resolve_developer(payout)
        seller = ensure_seller_registered(developer, simulate=seller_simulate, policy=policy)
        if seller.status != Seller.Status.PARTIALLY_APPROVED:
            Payout.objects.filter(
                pk=payout.pk, status=Payout.Status.CONFIRMED_IDENTITY_PENDING
            ).update(status=Payout.Status.CONFIRMED_SELLER_PENDING)
            payout.status = Payout.Status.CONFIRMED_SELLER_PENDING

    return payout


def mark_failed(idempotency_key) -> Payout:
    """지급을 실패로 확정한다. 이미 확정되어 있으면 그대로 돌려준다.

    REQUESTED에서 곧바로 FAILED로 가는 경로에는 원장에 아무 것도 남아 있지
    않다(mark_confirmed가 아직 지나지 않았으므로) — 돈이 움직이지 않았다.
    """

    Payout.objects.filter(idempotency_key=idempotency_key, status=Payout.Status.REQUESTED).update(
        status=Payout.Status.FAILED
    )
    return Payout.objects.get(idempotency_key=idempotency_key)


def submit_identity(payout: Payout, resident_registration_number: str) -> Payout:
    """주민등록번호를 암호화해 별도 테이블에 저장하고, 두 대기가 모두 풀렸으면
    지급을 최종 확정한다.

    `TaxIdentity`를 `update_or_create`로 upsert한다 — 재제출은 항상 최신 값으로
    덮어쓴다. 이미 있는 값을 그대로 다시 보내면(재전송) 같은 값으로 덮어쓸 뿐이라
    안전하고, 실수로 잘못 입력한 값을 보냈다면(오타) 정정할 수 있는 유일한
    경로이기도 하다 — TaxIdentity는 append-only 원장이 아니라 세무 신고용
    현재값 저장소이므로, "이미 있으면 그대로 돌려주고 두 번째 값은 버린다"는
    구 정책은 오타를 API로 영영 고칠 수 없게 만든다(#15 리뷰 지적 4).

    Payout 상태는 CONFIRMED_IDENTITY_PENDING 또는 CONFIRMED_SELLER_PENDING일
    때만 건드린다(이미 CONFIRMED인 뒤의 정정 제출은 상태를 다시 건드리지
    않는다 — 원장 분개는 mark_confirmed 시점에 이미 끝났고, 신원 정보 자체는
    원장에 영향을 주지 않는다). 신원은 항상 저장하지만, **Seller가 아직 부분
    승인이 아니면 CONFIRMED로 넘어가지 않고 CONFIRMED_SELLER_PENDING에
    남는다**(#50, ADR-0020) — 두 대기 중 하나라도 남아 있으면 최종 확정이 아니다.
    """

    with transaction.atomic():
        TaxIdentity.objects.update_or_create(
            payout=payout,
            defaults={
                "resident_registration_number_encrypted": encrypt(resident_registration_number)
            },
        )

        if payout.status in (
            Payout.Status.CONFIRMED_IDENTITY_PENDING,
            Payout.Status.CONFIRMED_SELLER_PENDING,
        ):
            developer = _resolve_developer(payout)
            seller = Seller.objects.filter(developer=developer).first()
            seller_ready = seller is not None and seller.status == Seller.Status.PARTIALLY_APPROVED
            target = Payout.Status.CONFIRMED if seller_ready else Payout.Status.CONFIRMED_SELLER_PENDING
            Payout.objects.filter(pk=payout.pk, status=payout.status).update(status=target)

    payout.refresh_from_db()
    return payout


def retry_seller_registration(payout: Payout, *, simulate: str | None = None) -> Payout:
    """CONFIRMED_SELLER_PENDING에서 Seller 등록을 다시 시도한다(#50, ADR-0020).

    부분 승인으로 넘어가면, 신원이 이미 제출되어 있으면 CONFIRMED로, 아직
    아니면 CONFIRMED_IDENTITY_PENDING으로 옮긴다(두 대기 중 남은 한쪽만
    보여준다). 여전히 부분 승인이 아니면(한도 초과·심사 필요·거절) 그대로
    CONFIRMED_SELLER_PENDING에 남는다 — 실패로 종결되지 않는다.
    """

    with transaction.atomic():
        locked = Payout.objects.select_for_update().get(pk=payout.pk)
        if locked.status != Payout.Status.CONFIRMED_SELLER_PENDING:
            return locked

        developer = _resolve_developer(locked)
        seller = ensure_seller_registered(developer, simulate=simulate)
        if seller.status == Seller.Status.PARTIALLY_APPROVED:
            has_identity = TaxIdentity.objects.filter(payout=locked).exists()
            target = Payout.Status.CONFIRMED if has_identity else Payout.Status.CONFIRMED_IDENTITY_PENDING
            Payout.objects.filter(
                pk=locked.pk, status=Payout.Status.CONFIRMED_SELLER_PENDING
            ).update(status=target)
            locked.status = target

    return locked
