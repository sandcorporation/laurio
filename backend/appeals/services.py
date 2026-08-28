"""Appeal 도메인 로직 (#21, ADR-0004, ADR-0006).

API 레이어(`appeals.api`)에서만 호출된다 — 테스트의 유일한 시임은 HTTP이므로 여기
함수를 테스트에서 직접 부르지 않는다(`CLAUDE.md`).

**재채점 경로는 이 파일 어디에도 없다** — `scoring.services`/`scoring.adapters`를
import하지 않는다. 이의를 인용해도 `Score.percentage`나 `reasoning`은 절대
바뀌지 않는다(AppendOnlyModel이 애초에 수정 자체를 막는다, ADR-0006). 인용의
유일한 효과는 원장에 새 정정 분개가 남는 것뿐이다.

핵심 규율(core.transitions.claim_transition과 같은 조건부 UPDATE): `Appeal.status`를
`UPDATE ... WHERE id=? AND status='pending'`로만 확정시키고, rowcount가 1일 때만
정정 분개를 남긴다 — 같은 심판 요청이 두 번(재전송·중복 클릭) 들어와도 정정 분개가
두 번 남지 않는다.
"""

from __future__ import annotations

from django.db import transaction

from core.clock import Clock
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry

from .models import Appeal


def uphold_appeal(appeal: Appeal, *, correction_amount: int, ruling_note: str, now=None) -> Appeal:
    """이의를 인용한다. 이미 심판이 끝나 있으면(rowcount!=1) 아무 것도 다시 하지
    않고 현재 상태를 그대로 돌려준다.

    정정 분개는 플랫폼 수수료 수익에서 개발자 미지급금으로 금액을 옮긴다 —
    이미 확정 배분된 다른 Developer들의 몫을 되돌리는 대신(ADR-0006), 플랫폼이
    자신의 채점 오판 비용을 부담하는 쪽을 택한다. 기존 분개는 하나도 건드리지
    않고 이 분개만 새로 추가된다(append-only, ADR-0004).
    """

    now = now if now is not None else Clock.now()

    with transaction.atomic():
        updated = Appeal.objects.filter(pk=appeal.pk, status=Appeal.Status.PENDING).update(
            status=Appeal.Status.UPHELD,
            ruling_note=ruling_note,
            correction_amount=correction_amount,
            ruled_at=now,
        )
        appeal = Appeal.objects.select_related("submission__contest").get(pk=appeal.pk)

        if updated != 1:
            # 이미 인용·기각되어 있다 — 재전송이거나 경합에서 졌다. 원장에는
            # 이미 반영되어 있거나(먼저 인용됐다면) 애초에 없어야 한다(기각됐다면).
            return appeal

        contest = appeal.submission.contest
        entry = post_journal_entry(
            contest_id=contest.ledger_id,
            memo=(
                f"Contest #{contest.id} Submission #{appeal.submission_id} 이의제기 "
                f"#{appeal.id} 인용 — 정정 {correction_amount:,}원 (AI 판정 -> 이의 "
                f"인용 -> 정정)"
            ),
            lines=[
                LineInput(
                    account=Account.PLATFORM_FEE_REVENUE,
                    side=EntrySide.DEBIT,
                    amount=correction_amount,
                ),
                LineInput(
                    account=Account.DEVELOPER_PAYABLE,
                    side=EntrySide.CREDIT,
                    amount=correction_amount,
                ),
            ],
        )

        Appeal.objects.filter(pk=appeal.pk).update(correction_journal_entry_id=entry.id)
        appeal.correction_journal_entry_id = entry.id

    return appeal


def reject_appeal(appeal: Appeal, *, ruling_note: str, now=None) -> Appeal:
    """이의를 기각한다. 원장에는 아무 것도 남기지 않는다 — 돈이 움직이지 않았다.

    이미 심판이 끝나 있으면(rowcount!=1) 아무 것도 다시 하지 않는다.
    """

    now = now if now is not None else Clock.now()

    Appeal.objects.filter(pk=appeal.pk, status=Appeal.Status.PENDING).update(
        status=Appeal.Status.REJECTED, ruling_note=ruling_note, ruled_at=now
    )
    appeal.refresh_from_db()
    return appeal
