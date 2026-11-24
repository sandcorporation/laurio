"""제보 Celery 태스크 (#1366) — 접수 알림을 요청 밖에서 보낸다."""

import logging

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


MAX_RETRIES = 5
RETRY_BASE_SECONDS = 30  # 30초 → 1분 → 2분 → 4분 → 8분 (첫 시도부터 약 15분)


@shared_task(
    bind=True,
    name="feedback.send_feedback_notice",
    ignore_result=True,
    max_retries=MAX_RETRIES,
)
def send_feedback_notice(self, report_id: int) -> None:
    """알림 목적지로 한 건 보내고 전달 표시를 찍는다. 못 보내면 간격을 늘려 다시 보낸다."""

    from ops_metrics import alerts

    from .models import FeedbackReport
    from .services import mark_forwarded, notice_line

    url = settings.FEEDBACK_NOTICE_WEBHOOK_URL
    if not url:
        return
    report = FeedbackReport.objects.filter(pk=report_id).first()
    if report is None or report.forwarded_at is not None:
        return
    try:
        alerts.post_webhook(url, notice_line(report))
        mark_forwarded(report_id)
    except Exception as exc:  # noqa: BLE001
        attempts = self.request.retries + 1
        if self.request.retries >= MAX_RETRIES:
            # 주소가 예외 문장에 섞일 수 있어 종류만 남긴다.
            logger.warning(
                "제보 #%s 알림을 %s번 시도하고도 보내지 못했다: %s", report_id, attempts, type(exc).__name__
            )
            return
        raise self.retry(countdown=RETRY_BASE_SECONDS * 2**self.request.retries) from None
