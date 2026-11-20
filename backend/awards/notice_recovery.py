"""결과 알림 복구 스캔 — 선정(#19, #138). 즉시 경로가 커밋 직후 보내고, 이 스캔은 프로세스가 죽어 남은 것만
쓸어 담는다. `result_notice_sent_at` 이 비어 있으면 아직이다. 스캔 이름은 처음 그대로다 — #1086 에서
`contests.lifecycle_notifications` 에서 행을 가진 이 앱으로 옮겼다(공모전 앱이 위 앱 모델을 읽지 않게).
"""

from __future__ import annotations

from contests.lifecycle_notifications import notify_award_result
from core.scans import ScanSpec

from .models import Award


def _pending_award_notices(as_of, ctx):
    return Award.objects.filter(result_notice_sent_at__isnull=True).select_related(
        "submission__contestsubmission__developer__user", "contest"
    )


def _recover_award_notice(award, as_of, ctx):
    notify_award_result(award)
    award.refresh_from_db(fields=["result_notice_sent_at"])
    if award.result_notice_sent_at is None:
        return None
    return {"event": "award_result_notice_recovered", "award_id": award.id}


NOTICE_RECOVERY_SCAN = ScanSpec(
    name="award-result-notice-recovery",
    candidates=_pending_award_notices,
    handle_row=_recover_award_notice,
    batch_size=200,
)
