"""제보 스크린샷 보관 기한 스캔 (#1239).

다른 학생의 이름·판정이 찍힐 수 있는 그림이라 오래 두지 않는다(#4335 5번). 종결(배포됨·반려) 30일 뒤,
또는 종결되지 않아도 받은 지 180일 뒤 객체를 지우고 키를 비운다. 제보 글·이력은 남긴다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Q, QuerySet

from core.scans import ScanSpec

from . import screenshots
from .models import FeedbackReport

AFTER_CLOSED = timedelta(days=30)
AFTER_RECEIVED = timedelta(days=180)


def _expired(as_of: datetime) -> Q:
    return Q(closed_at__lte=as_of - AFTER_CLOSED) | Q(received_at__lte=as_of - AFTER_RECEIVED)


def _candidates(as_of: datetime, ctx: dict) -> QuerySet:
    return FeedbackReport.objects.exclude(screenshot_key="").filter(_expired(as_of))


def _purge(report: FeedbackReport, as_of: datetime, ctx: dict) -> dict | None:
    key = report.screenshot_key
    # 객체를 먼저 지운다 — 키를 먼저 비우고 삭제가 실패하면 그림이 주인 없이 남는다. 삭제는 멱등이다.
    screenshots.delete(key)
    cleared = (
        FeedbackReport.objects.filter(pk=report.pk, screenshot_key=key)
        .filter(_expired(as_of))
        .update(screenshot_key="")
    )
    if not cleared:
        return None
    return {"report_id": report.pk}


FEEDBACK_SCREENSHOT_RETENTION_SCAN = ScanSpec(
    name="feedback-screenshot-retention",
    candidates=_candidates,
    handle_row=_purge,
    # 기한이 일 단위라 한 시간에 한 번이면 충분하다.
    interval_seconds=3600.0,
)
