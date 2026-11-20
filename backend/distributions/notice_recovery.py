"""결과 알림 복구 스캔 — 배분 몫(#19, #138). 즉시 경로가 커밋 직후 보내고, 이 스캔은 프로세스가 죽어 남은 것만
쓸어 담는다. `result_notice_sent_at` 이 비어 있으면 아직이다. 스캔 이름은 처음 그대로다 — #1086 에서
`contests.lifecycle_notifications` 에서 행을 가진 이 앱으로 옮겼다(공모전 앱이 위 앱 모델을 읽지 않게).
"""

from __future__ import annotations

from contests.lifecycle_notifications import notify_distribution_shares
from core.scans import ScanSpec

from .models import DistributionShare


def _pending_share_notices(as_of, ctx):
    return DistributionShare.objects.filter(result_notice_sent_at__isnull=True).select_related(
        "submission__contestsubmission__developer__user", "distribution__contest"
    )


def _recover_share_notice(share, as_of, ctx):
    # notify_distribution_shares 는 (distribution, [submission, ...]) 모양을 기대한다 —
    # 몫 하나짜리 목록으로 그 함수를 그대로 재사용한다. 예산(ctx)도 넘겨 팬아웃에서도
    # 지켜지게 한다.
    notify_distribution_shares(share.distribution, [share.submission.contestsubmission], ctx=ctx)
    share.refresh_from_db(fields=["result_notice_sent_at"])
    if share.result_notice_sent_at is None:
        return None
    return {"event": "distribution_result_notice_recovered", "submission_id": share.submission_id}


NOTICE_RECOVERY_SCAN = ScanSpec(
    name="distribution-result-notice-recovery",
    candidates=_pending_share_notices,
    handle_row=_recover_share_notice,
    batch_size=200,
)
