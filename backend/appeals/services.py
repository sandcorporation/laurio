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

import logging

from django.db import transaction

from core.clock import Clock
from ledger.models import Account, EntrySide
from ledger.services import LineInput, post_journal_entry

from .models import Appeal, AppealRuling

logger = logging.getLogger(__name__)


def uphold_appeal(
    appeal: Appeal, *, ruled_by, correction_amount: int, ruling_note: str, now=None
) -> Appeal:
    """이의를 인용한다. 이미 심판이 끝나 있으면(rowcount!=1) 아무 것도 다시 하지
    않고 현재 상태를 그대로 돌려준다.

    정정 분개는 플랫폼 수수료 수익에서 개발자 미지급금으로 금액을 옮긴다 —
    이미 확정 배분된 다른 Developer들의 몫을 되돌리는 대신(ADR-0006), 플랫폼이
    자신의 채점 오판 비용을 부담하는 쪽을 택한다. 기존 분개는 하나도 건드리지
    않고 이 분개만 새로 추가된다(append-only, ADR-0004).

    `ruled_by` 는 필수다 — 신원 없는 심판이 저장될 수 있는 경로를 남기지 않는다.
    `AppealRuling` 은 조건부 UPDATE 를 이긴 뒤에만 만들어지므로, 정정 분개와 마찬가지로
    정확히 한 번만 생긴다(그리고 OneToOne 이 그것을 스키마로 한 번 더 막는다).
    """

    now = now if now is not None else Clock.now()

    with transaction.atomic():
        updated = Appeal.objects.filter(pk=appeal.pk, status=Appeal.Status.PENDING).update(
            status=Appeal.Status.UPHELD
        )
        appeal = Appeal.objects.select_related("submission__contestsubmission__contest").get(pk=appeal.pk)

        if updated != 1:
            # 이미 인용·기각되어 있다 — 재전송이거나 경합에서 졌다. 원장에는
            # 이미 반영되어 있거나(먼저 인용됐다면) 애초에 없어야 한다(기각됐다면).
            return appeal

        contest = appeal.submission.contestsubmission.contest
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

        AppealRuling.objects.create(
            appeal=appeal,
            ruled_by=ruled_by,
            decision=AppealRuling.Decision.UPHELD,
            note=ruling_note,
            ruled_at=now,
            correction_amount=correction_amount,
            correction_journal_entry_id=entry.id,
        )

    _notify_ruled(appeal)
    return appeal


def reject_appeal(appeal: Appeal, *, ruled_by, ruling_note: str, now=None) -> Appeal:
    """이의를 기각한다. 원장에는 아무 것도 남기지 않는다 — 돈이 움직이지 않았다.

    돈이 움직이지 않아도 신원은 남긴다. "왜 기각했는가"와 "누가 기각했는가"는
    인용만큼이나 감사 대상이다 — Developer 에게는 이쪽이 더 아픈 결정이다.

    이미 심판이 끝나 있으면(rowcount!=1) 아무 것도 다시 하지 않는다.
    """

    now = now if now is not None else Clock.now()

    with transaction.atomic():
        updated = Appeal.objects.filter(pk=appeal.pk, status=Appeal.Status.PENDING).update(
            status=Appeal.Status.REJECTED
        )
        if updated == 1:
            AppealRuling.objects.create(
                appeal=appeal,
                ruled_by=ruled_by,
                decision=AppealRuling.Decision.REJECTED,
                note=ruling_note,
                ruled_at=now,
            )

    appeal.refresh_from_db()
    _notify_ruled(appeal)
    return appeal


def _notify_ruled(appeal: Appeal) -> None:
    """이의가 심판됐음을 낸 사람에게 알린다 (#74).

    **심판자 개인의 이름은 담지 않는다** — #61 이 열람 기록에 대해 세운 것과 같은
    이유다. 결과와 이유는 주되 운영자 신원을 참가자에게 흘리지 않는다(ADR-0018
    이 서로소로 갈라놓은 두 경계 사이에 새 문제가 생긴다).

    알림 실패가 심판을 되돌리면 안 된다 — 심판은 원장에 정정 분개를 남기는
    되돌릴 수 없는 행위이고, 통지는 그것을 전할 뿐이다. 어떤 예외도 호출자에게
    전파하지 않는다(notifications 의 `_safe_notify` 와 같은 규율).

    트랜잭션 **밖**에서 부른다 — 알림 생성이 심판의 원자성 안에 들어가면
    알림 쪽 실패가 정정 분개까지 롤백시킨다.
    """

    try:
        from notifications.models import NotificationType
        from notifications.services import create_notification

        ruling = getattr(appeal, "ruling", None)
        create_notification(
            recipient=appeal.submission.contestsubmission.developer.user,
            notification_type=NotificationType.APPEAL_RULED,
            context={
                "appeal_id": appeal.id,
                "submission_id": appeal.submission_id,
                "decision": appeal.status,
                "ruling_note": ruling.note if ruling else "",
                "correction_amount": ruling.correction_amount if ruling else None,
            },
        )
    except Exception:  # noqa: BLE001 - 알림 실패가 심판을 되돌리면 안 된다.
        logger.exception(
            "Appeal(pk=%s) 심판 완료 알림 생성 중 예외 — 심판 자체는 그대로 둔다",
            appeal.id,
        )
