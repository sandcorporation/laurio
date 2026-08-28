"""Payout 도메인 로직 (#15, ADR-0003, ADR-0004, ADR-0008).

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
아직 신원 정보가 없는 것이 정상 경로다. `submit_identity`가 뒤이어 CONFIRMED로
마저 옮긴다. 원장 분개는 CONFIRMED_IDENTITY_PENDING 진입 시점에 이미 남는다 —
신원 정보 유무는 세무 신고 가능 여부를 가릴 뿐 금액이 원장에서 사라지지도,
다시 계산되지도 않는다.
"""

from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError, transaction

from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry
from verification.crypto import encrypt

from .models import Payout, TaxIdentity

# REQUESTED든 그 이후 확정 상태든 "아직 실패로 끝나지 않은" 시도는 활성으로 본다
# — models.Payout.Meta.constraints의 unique_active_payout_per_handover와 정확히
# 같은 집합이어야 한다(그쪽은 DB 레벨 최후 방어선, 이건 애플리케이션 레벨 조회
# 기준). FAILED만 빠진다 — 그래야 실패한 시도 뒤에 새 REQUESTED를 만들 수 있다.
_ACTIVE_PAYOUT_STATUSES = [
    Payout.Status.REQUESTED,
    Payout.Status.CONFIRMED_IDENTITY_PENDING,
    Payout.Status.CONFIRMED,
]


def _compute_amounts(prize_amount: int) -> tuple[int, int, int]:
    """(플랫폼 수수료, 원천징수, 실지급액)을 원 단위 정수로 계산한다.

    bp(1/10000) 단위 정수 비율로 계산해 float 오차를 피한다(ADR-0004). 수수료와
    원천징수는 내림으로 계산하고, 실지급액은 나머지 전부를 가져간다 — 반올림으로
    셋의 합이 prize_amount와 어긋나는 사고를 구조적으로 없앤다(ADR-0004의 1/N
    나머지 처리와 같은 정신: 단수가 어딘가로 사라지지 않는다).
    """

    fee = prize_amount * settings.PAYOUT_PLATFORM_FEE_BPS // 10_000
    withholding = prize_amount * settings.PAYOUT_WITHHOLDING_TAX_BPS // 10_000
    net = prize_amount - fee - withholding
    return fee, withholding, net


def get_or_create_payout(handover=None, *, distribution_share=None) -> Payout:
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
    """

    if (handover is None) == (distribution_share is None):
        raise ValueError("handover 또는 distribution_share 중 정확히 하나만 넘겨야 한다.")

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
            fee, withholding, net = _compute_amounts(prize_amount)

            try:
                return Payout.objects.create(
                    handover=locked,
                    prize_amount=prize_amount,
                    platform_fee_amount=fee,
                    withholding_tax_amount=withholding,
                    net_amount=net,
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
        fee, withholding, net = _compute_amounts(prize_amount)

        try:
            return Payout.objects.create(
                distribution_share=locked,
                prize_amount=prize_amount,
                platform_fee_amount=fee,
                withholding_tax_amount=withholding,
                net_amount=net,
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


def mark_confirmed(idempotency_key) -> Payout:
    """지급을 확정한다(CONFIRMED_IDENTITY_PENDING). 이미 확정되어 있으면 그대로
    돌려준다.

    이겼을 때만(rowcount==1) 원장에 수수료·원천징수 공제 분개를 남긴다. 원천징수는
    반드시 원천징수 예수금 계정에 계상된다(ADR-0004/0008) — 국세청에 낼 남의
    돈이므로 플랫폼 수수료 수익과 섞이지 않는다.
    """

    with transaction.atomic():
        updated = Payout.objects.filter(
            idempotency_key=idempotency_key, status=Payout.Status.REQUESTED
        ).update(status=Payout.Status.CONFIRMED_IDENTITY_PENDING)
        payout = Payout.objects.select_related(
            "handover__award__contest", "distribution_share__distribution__contest"
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
    """주민등록번호를 암호화해 별도 테이블에 저장하고 지급을 최종 확정한다.

    `TaxIdentity`를 `update_or_create`로 upsert한다 — 재제출은 항상 최신 값으로
    덮어쓴다. 이미 있는 값을 그대로 다시 보내면(재전송) 같은 값으로 덮어쓸 뿐이라
    안전하고, 실수로 잘못 입력한 값을 보냈다면(오타) 정정할 수 있는 유일한
    경로이기도 하다 — TaxIdentity는 append-only 원장이 아니라 세무 신고용
    현재값 저장소이므로, "이미 있으면 그대로 돌려주고 두 번째 값은 버린다"는
    구 정책은 오타를 API로 영영 고칠 수 없게 만든다(#15 리뷰 지적 4). Payout
    상태는 CONFIRMED_IDENTITY_PENDING일 때만 CONFIRMED로 전이한다 — 이미
    CONFIRMED인 뒤의 정정 제출은 상태를 다시 건드리지 않는다(원장 분개는
    mark_confirmed 시점에 이미 끝났고, 신원 정보 자체는 원장에 영향을 주지
    않는다).
    """

    with transaction.atomic():
        TaxIdentity.objects.update_or_create(
            payout=payout,
            defaults={
                "resident_registration_number_encrypted": encrypt(resident_registration_number)
            },
        )
        Payout.objects.filter(
            pk=payout.pk, status=Payout.Status.CONFIRMED_IDENTITY_PENDING
        ).update(status=Payout.Status.CONFIRMED)

    payout.refresh_from_db()
    return payout
