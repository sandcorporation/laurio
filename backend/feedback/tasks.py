"""제보 Celery 태스크 (#1366) — 접수 알림을 요청 밖에서 보낸다."""

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(name="feedback.send_feedback_notice", ignore_result=True)
def send_feedback_notice(report_id: int) -> None:
    """알림 목적지로 한 건 보내고 전달 표시를 찍는다. 재시도하지 않는다 — 못 보낸 제보는 자동화가 집는다."""

    from ops_metrics import alerts

    from .models import FeedbackReport
    from .services import mark_forwarded, notice_line

    url = settings.FEEDBACK_NOTICE_WEBHOOK_URL
    if not url:
        return
    try:
        report = FeedbackReport.objects.get(pk=report_id)
        alerts.post_webhook(url, notice_line(report))
        mark_forwarded(report_id)
    except Exception as exc:  # noqa: BLE001
        # 주소가 예외 문장에 섞일 수 있어 종류만 남긴다.
        logger.warning("제보 #%s 알림을 보내지 못했다: %s", report_id, type(exc).__name__)
