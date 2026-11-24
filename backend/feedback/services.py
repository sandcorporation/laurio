"""제보 권한·제보 도메인 로직 (#1238).

API 레이어(`feedback.api`·`feedback.operator_api`)와 관리 명령에서만 부른다 — 시험의 시임은 HTTP 다.
권한은 `contests.hosting_permission_services` 와 같은 규율이다: 사유 없는 변경은 거부하고, 지금
값과 append-only 이력을 한 트랜잭션에서 남긴다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Q, QuerySet

from core.clock import Clock
from notifications.models import NotificationType
from notifications.services import create_notification
from ops_metrics import alerts

from . import screenshots
from .models import (
    MAX_BODY_CHARS,
    FeedbackPermission,
    FeedbackPermissionChange,
    FeedbackReport,
    FeedbackStatusChange,
)

logger = logging.getLogger(__name__)

# 계정당 24시간(굴러가는 창) 안에 만들 수 있는 제보 수.
DAILY_REPORT_LIMIT = 20
DAILY_WINDOW = timedelta(hours=24)


class FeedbackValidationError(Exception):
    """말이 안 되는 입력 — 호출자는 422 로 옮긴다."""


class FeedbackConflictError(Exception):
    """이미 그 상태다 — 호출자는 409 로 옮긴다."""


class FeedbackNotFoundError(Exception):
    """없는 제보 — 호출자는 404 로 옮긴다."""


class FeedbackRateLimitError(Exception):
    """하루 상한을 넘었다 — 호출자는 429 로 옮긴다."""


def is_granted(user: AbstractBaseUser) -> bool:
    return FeedbackPermission.objects.filter(user=user, is_granted=True).exists()


def search_accounts(query: str) -> QuerySet:
    """이메일·닉네임으로 찾는다(`contests.hosting_permission_services.search_accounts` 와 같은 길).
    빈 검색어는 아무것도 찾지 않는다."""

    stripped = query.strip()
    if not stripped:
        return get_user_model().objects.none()
    return (
        get_user_model()
        .objects.filter(Q(email__icontains=stripped) | Q(social_accounts__nickname__icontains=stripped))
        .distinct()
        .select_related("feedback_permission")
        .order_by("email", "id")[:50]
    )


def set_permission(
    *, user: AbstractBaseUser, operator: AbstractBaseUser, granted: bool, reason: str
) -> FeedbackPermission:
    reason = reason.strip()
    if not reason:
        raise FeedbackValidationError("이유(reason)를 남겨야 합니다.")

    with transaction.atomic():
        permission, _created = FeedbackPermission.objects.get_or_create(user=user)
        locked = FeedbackPermission.objects.select_for_update().get(pk=permission.pk)
        if locked.is_granted == granted:
            state = "있습니다" if granted else "없습니다"
            raise FeedbackConflictError(f"이미 제보 권한이 {state}.")

        locked.is_granted = granted
        locked.save(update_fields=["is_granted", "updated_at"])
        FeedbackPermissionChange.objects.create(
            user=user,
            operator=operator,
            action=(
                FeedbackPermissionChange.Action.GRANTED
                if granted
                else FeedbackPermissionChange.Action.REVOKED
            ),
            reason=reason,
            changed_at=Clock.now(),
        )
    return locked


@dataclass(frozen=True)
class NewReport:
    kind: str
    body: str
    app: str
    page_url: str
    user_agent: str
    screen_width: int | None
    screen_height: int | None
    screenshot_key: str


def create_report(*, reporter: AbstractBaseUser, data: NewReport) -> FeedbackReport:
    body = data.body.strip()
    if not body:
        raise FeedbackValidationError("내용을 적어야 합니다.")
    if len(body) > MAX_BODY_CHARS:
        raise FeedbackValidationError(f"내용은 {MAX_BODY_CHARS:,}자까지 적을 수 있습니다.")

    if data.screenshot_key:
        screenshots.attach_check(data.screenshot_key, reporter.pk)
        if FeedbackReport.objects.filter(screenshot_key=data.screenshot_key).exists():
            raise FeedbackValidationError("이미 다른 제보에 붙은 스크린샷입니다.")

    now = Clock.now()
    with transaction.atomic():
        # 같은 계정의 동시 요청이 상한을 함께 넘지 않게 계정 행을 잠근다.
        get_user_model().objects.select_for_update().filter(pk=reporter.pk).first()
        recent = FeedbackReport.objects.filter(
            reporter=reporter, received_at__gt=now - DAILY_WINDOW
        ).count()
        if recent >= DAILY_REPORT_LIMIT:
            raise FeedbackRateLimitError(
                f"제보는 하루 {DAILY_REPORT_LIMIT}건까지 보낼 수 있습니다."
            )
        report = FeedbackReport.objects.create(
            reporter=reporter,
            kind=data.kind,
            body=body,
            app=data.app,
            page_url=data.page_url[:2048],
            user_agent=data.user_agent[:512],
            screen_width=data.screen_width,
            screen_height=data.screen_height,
            screenshot_key=data.screenshot_key,
            received_at=now,
        )
        report_id = report.pk
        transaction.on_commit(lambda: _send_notice(report_id))
        return report


def notice_line(report: FeedbackReport) -> str:
    """알림 한 줄 — 번호·종류·앱 갈래만. 본문·제보자·주소·스크린샷은 넣지 않는다."""

    return f"📮 [Codemit] 새 제보 #{report.pk} · {report.get_kind_display()} · {report.app}"


def _send_notice(report_id: int) -> None:
    """접수가 커밋된 뒤 알림 목적지로 한 건 보낸다 — 보내면 전달 표시를 찍는다. 실패는 삼킨다.

    요청 스레드에서 짧은 소켓 한도(`OPS_ALERT_DISCORD_TIMEOUT_SECONDS`)로 보낸다.
    """

    url = settings.FEEDBACK_NOTICE_WEBHOOK_URL
    if not url:
        return
    try:
        report = FeedbackReport.objects.get(pk=report_id)
        alerts.post_webhook(url, notice_line(report))
        mark_forwarded(report_id)
    except Exception as exc:  # noqa: BLE001 - 접수는 이미 커밋됐다. 못 보낸 제보는 자동화가 집는다.
        # 주소가 예외 문장에 섞일 수 있어 종류만 남긴다.
        logger.warning("제보 #%s 알림을 보내지 못했다: %s", report_id, type(exc).__name__)


# --- 상태 바꾸기 (#1239) ------------------------------------------------------

COMMAND_ACTOR_LABEL = "대장(명령)"
CLOSED_STATUSES = frozenset({FeedbackReport.Status.DEPLOYED, FeedbackReport.Status.DECLINED})


def change_status(
    *,
    report_id: int,
    to_status: str,
    note: str,
    operator: AbstractBaseUser | None,
    actor_label: str,
) -> FeedbackReport:
    """운영자 화면과 관리 명령이 함께 부르는 단 하나의 길 — 이력 한 줄과 제보자 알림 한 건.

    같은 상태로는 바꾸지 않는다(409) — 알림이 헛되이 나가지 않게. 처리 글이 있으면 제보의
    「처리 글」도 그것으로 바꾼다. 배포됨·반려로 들어가면 종결 시각을 찍고, 다시 열면 지운다.
    """

    if to_status not in FeedbackReport.Status.values:
        raise FeedbackValidationError("알 수 없는 상태입니다.")
    note = note.strip()
    now = Clock.now()

    with transaction.atomic():
        report = FeedbackReport.objects.select_for_update().filter(pk=report_id).first()
        if report is None:
            raise FeedbackNotFoundError("제보를 찾을 수 없습니다.")
        if report.status == to_status:
            raise FeedbackConflictError("이미 그 상태입니다.")

        from_status = report.status
        report.status = to_status
        if note:
            report.resolution_note = note
        report.closed_at = now if to_status in CLOSED_STATUSES else None
        report.save(update_fields=["status", "resolution_note", "closed_at"])
        FeedbackStatusChange.objects.create(
            report=report,
            changed_by=operator,
            actor_label=actor_label,
            from_status=from_status,
            to_status=to_status,
            note=note,
            changed_at=now,
        )
        notify_reporter(report)
    return report


# --- 대장 전달(#1240 이 부르는 관리 명령의 몫) -------------------------------

# take 로 집은 뒤 이만큼 지나도 전달 표시가 없으면 다시 집힌다 — 전달이 중간에 죽은 경우.
TAKE_LEASE = timedelta(minutes=15)


def _pending(now) -> QuerySet:
    return FeedbackReport.objects.filter(forwarded_at__isnull=True).filter(
        Q(taken_at__isnull=True) | Q(taken_at__lte=now - TAKE_LEASE)
    )


def pending_reports(limit: int) -> list[FeedbackReport]:
    """아직 전달되지 않았고 지금 누가 집고 있지 않은 제보 — 읽기만 한다."""

    return list(_pending(Clock.now()).order_by("received_at", "id")[:limit])


def take_reports(limit: int) -> list[FeedbackReport]:
    """전달할 제보를 집는다 — 같은 제보를 두 번 내지 않게 집은 시각을 조건부로 찍는다."""

    now = Clock.now()
    taken: list[FeedbackReport] = []
    with transaction.atomic():
        candidates = (
            _pending(now).select_for_update(skip_locked=True).order_by("received_at", "id")[:limit]
        )
        for report in candidates:
            report.taken_at = now
            report.save(update_fields=["taken_at"])
            taken.append(report)
    return taken


def untake_report(report_id: int) -> bool:
    """전달에 실패한 제보를 바로 다시 집히게 한다. 이미 전달된 것은 건드리지 않는다."""

    return bool(
        FeedbackReport.objects.filter(pk=report_id, forwarded_at__isnull=True).update(taken_at=None)
    )


def mark_forwarded(report_id: int) -> bool:
    """전달을 마쳤다고 표시한다. 이미 표시된 것이면 False."""

    return bool(
        FeedbackReport.objects.filter(pk=report_id, forwarded_at__isnull=True).update(
            forwarded_at=Clock.now()
        )
    )


def notify_reporter(report: FeedbackReport) -> None:
    """보낸 앱의 벨에 뜨는 유형으로 제보자에게 알린다."""

    notification_type = (
        NotificationType.CLASSROOM_FEEDBACK_STATUS_CHANGED
        if report.app == FeedbackReport.App.CLASSROOM
        else NotificationType.FEEDBACK_STATUS_CHANGED
    )
    create_notification(
        recipient=report.reporter,
        notification_type=notification_type,
        context={
            "report_id": report.pk,
            "status": report.status,
            "status_label": report.get_status_display(),
        },
    )
