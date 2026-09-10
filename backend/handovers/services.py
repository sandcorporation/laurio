"""Handover 도메인 로직 — Escrow 해제 (#14, ADR-0003, ADR-0004).

API 레이어(`handovers.api`)와 내부 스캔 엔드포인트에서만 호출된다 — 테스트의 유일한
시임은 HTTP이므로 여기 함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

핵심 규율(ADR-0003과 같은 조건부 UPDATE): `Handover.status`를 `UPDATE ... WHERE
id=? AND status='pending_acceptance'`로만 `released`로 전이시키고, rowcount가 1일
때만 원장에 분개를 남긴다. 이 규율이 두 가지 흐름을 동시에 안전하게 만든다:

- Sponsor의 수동 인수 확인과 스케줄러 틱(정해진 기간 경과)이 동시에 도착한다 —
  먼저 도착한 쪽이 rowcount 1을 가져가고, 나중 것은 이미 바뀐 상태를 보고 조용히
  넘어간다(분개가 두 번 남지 않는다).
- 같은 틱이 두 번 스캔해도(워커가 겹쳐 돌아도) 정확히 한 번만 해제된다.

Escrow 해제 분개는 실질적인 계정 간 이동이 아니다 — Prize는 이미 결제 확정 시점에
개발자 미지급금(Escrow)으로 잡혀 있다(`payments.services.mark_paid`). 이 분개는
"이 금액이 이 Award에 대해 확정적으로 해제됐다"는 사실을 감사 로그에 남기기 위한
마커로, 같은 계정(개발자 미지급금)에 동일 금액을 차/대변 양쪽에 기록해 잔액에는
영향을 주지 않는다. 실제 지급을 위한 수수료·원천징수 공제 분개는 별개의 Payout
흐름(#15)이 남긴다.
"""

from __future__ import annotations

from django.db import transaction

from core.clock import Clock
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry

from .models import Handover


def release_escrow(handover: Handover, *, released_via: str, now=None) -> Handover:
    """Escrow를 해제한다. 이미 해제되어 있으면 아무 것도 다시 하지 않는다."""

    now = now if now is not None else Clock.now()

    with transaction.atomic():
        updated = Handover.objects.filter(
            pk=handover.pk, status=Handover.Status.PENDING_ACCEPTANCE
        ).update(status=Handover.Status.RELEASED, released_via=released_via, released_at=now)

        handover = Handover.objects.select_related(
            "award__contest", "award__submission__contestsubmission__developer"
        ).get(pk=handover.pk)

        if updated != 1:
            # 이미 released다 — 다른 채널(수동 인수확인/타임아웃 스캔)이 먼저
            # 이겼거나 재전송이다. 원장에는 이미 반영되어 있으므로 다시 손대지 않는다.
            return handover

        award = handover.award
        contest = award.contest
        prize = contest.prize

        entry = post_journal_entry(
            contest_id=contest.ledger_id,
            memo=(
                f"Contest #{contest.id} Escrow 해제 확정 — Award #{award.id} "
                f"(상금 {prize:,}원, {released_via})"
            ),
            lines=[
                LineInput(account=Account.DEVELOPER_PAYABLE, side=EntrySide.DEBIT, amount=prize),
                LineInput(account=Account.DEVELOPER_PAYABLE, side=EntrySide.CREDIT, amount=prize),
            ],
        )

        Handover.objects.filter(pk=handover.pk).update(escrow_release_journal_entry_id=entry.id)
        handover.escrow_release_journal_entry_id = entry.id

    return handover
