"""운영자 API — `/api/operator/feedback-...` (#1238 권한, #1239 제보).

`OperatorAuth` 가 라우터 전체에 걸려 있다. 권한 켜기·끄기는 개최 권한과 같이 최고 운영자만 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.http import HttpRequest
from ninja import Field, Router, Schema

from core.operator_auth import OperatorAuth, SuperuserOperatorAuth

from . import screenshots, services
from .models import FeedbackPermission, FeedbackPermissionChange, FeedbackReport

operator_router = Router(tags=["operator", "feedback"], auth=OperatorAuth())
_SUPERUSER = SuperuserOperatorAuth()


class OperatorErrorOut(Schema):
    detail: str
    code: str


class FeedbackPermissionAccountOut(Schema):
    user_id: int
    email: str
    nickname: str
    is_granted: bool


class SetFeedbackPermissionIn(Schema):
    granted: bool
    reason: str


class FeedbackPermissionChangeOut(Schema):
    id: int
    user_id: int
    user_email: str
    operator_username: str
    action: str
    reason: str
    changed_at: datetime


def _nickname_for(user: AbstractBaseUser) -> str:
    account = user.social_accounts.exclude(nickname="").order_by("id").first()
    return account.nickname if account is not None else ""


def _account(user: AbstractBaseUser, *, granted: bool) -> FeedbackPermissionAccountOut:
    return FeedbackPermissionAccountOut(
        user_id=user.pk, email=user.email, nickname=_nickname_for(user), is_granted=granted
    )


@operator_router.get(
    "/feedback-permissions/search", response={200: list[FeedbackPermissionAccountOut]}
)
def search_feedback_permission_accounts(request: HttpRequest, q: str = ""):
    rows = []
    for user in services.search_accounts(q):
        permission = getattr(user, "feedback_permission", None)
        rows.append(_account(user, granted=permission is not None and permission.is_granted))
    return 200, rows


@operator_router.get(
    "/feedback-permissions/changes", response={200: list[FeedbackPermissionChangeOut]}
)
def list_feedback_permission_changes(request: HttpRequest):
    changes = FeedbackPermissionChange.objects.select_related("operator", "user").order_by(
        "-changed_at", "-id"
    )[:200]
    return 200, [
        FeedbackPermissionChangeOut(
            id=change.id,
            user_id=change.user_id,
            user_email=change.user.email,
            operator_username=change.operator.username,
            action=change.action,
            reason=change.reason,
            changed_at=change.changed_at,
        )
        for change in changes
    ]


@operator_router.get("/feedback-permissions", response={200: list[FeedbackPermissionAccountOut]})
def list_feedback_permission_accounts(request: HttpRequest):
    granted = (
        FeedbackPermission.objects.filter(is_granted=True)
        .select_related("user")
        .order_by("user__email", "user_id")
    )
    return 200, [_account(permission.user, granted=True) for permission in granted]


@operator_router.post(
    "/feedback-permissions/{user_id}",
    response={
        200: FeedbackPermissionAccountOut,
        404: OperatorErrorOut,
        409: OperatorErrorOut,
        422: OperatorErrorOut,
    },
    auth=_SUPERUSER,
)
def set_feedback_permission(request: HttpRequest, user_id: int, payload: SetFeedbackPermissionIn):
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return 404, {"detail": "계정을 찾을 수 없습니다.", "code": "not_found"}
    try:
        permission = services.set_permission(
            user=user, operator=request.auth, granted=payload.granted, reason=payload.reason
        )
    except services.FeedbackValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    except services.FeedbackConflictError as exc:
        return 409, {"detail": str(exc), "code": "unchanged"}
    return 200, _account(user, granted=permission.is_granted)


# --- 제보 (#1239) ---------------------------------------------------------------


class OperatorFeedbackHistoryOut(Schema):
    from_status: str
    to_status: str
    note: str
    actor: str
    changed_at: datetime


class OperatorFeedbackReportRowOut(Schema):
    id: int
    kind: str
    app: str
    status: str
    body: str
    reporter_id: int
    reporter_email: str
    has_screenshot: bool
    received_at: datetime
    closed_at: datetime | None
    forwarded_at: datetime | None


class OperatorFeedbackReportOut(OperatorFeedbackReportRowOut):
    page_url: str
    user_agent: str
    screen_width: int | None
    screen_height: int | None
    resolution_note: str
    # 열 때마다 짧게 발급한다 — 없거나 보관 기한이 지나 지웠으면 null.
    screenshot_url: str | None
    history: list[OperatorFeedbackHistoryOut]


class ChangeFeedbackStatusIn(Schema):
    status: Literal["received", "in_progress", "deployed", "declined"]
    note: str = Field("", max_length=4000)


def _report_row(report: FeedbackReport) -> OperatorFeedbackReportRowOut:
    return OperatorFeedbackReportRowOut(
        id=report.pk,
        kind=report.kind,
        app=report.app,
        status=report.status,
        body=report.body,
        reporter_id=report.reporter_id,
        reporter_email=report.reporter.email,
        has_screenshot=bool(report.screenshot_key),
        received_at=report.received_at,
        closed_at=report.closed_at,
        forwarded_at=report.forwarded_at,
    )


def _report_detail(report: FeedbackReport) -> OperatorFeedbackReportOut:
    screenshot_url = (
        screenshots.request_download_url(report.screenshot_key).url if report.screenshot_key else None
    )
    return OperatorFeedbackReportOut(
        **_report_row(report).dict(),
        page_url=report.page_url,
        user_agent=report.user_agent,
        screen_width=report.screen_width,
        screen_height=report.screen_height,
        resolution_note=report.resolution_note,
        screenshot_url=screenshot_url,
        history=[
            OperatorFeedbackHistoryOut(
                from_status=change.from_status,
                to_status=change.to_status,
                note=change.note,
                actor=change.actor_label,
                changed_at=change.changed_at,
            )
            for change in report.status_changes.all()
        ],
    )


@operator_router.get("/feedback-reports", response={200: list[OperatorFeedbackReportRowOut]})
def list_feedback_reports(
    request: HttpRequest, status: str = "", app: str = "", kind: str = ""
):
    reports = FeedbackReport.objects.select_related("reporter").order_by("-received_at", "-id")
    if status:
        reports = reports.filter(status=status)
    if app:
        reports = reports.filter(app=app)
    if kind:
        reports = reports.filter(kind=kind)
    return 200, [_report_row(report) for report in reports[:200]]


@operator_router.get(
    "/feedback-reports/{report_id}",
    response={200: OperatorFeedbackReportOut, 404: OperatorErrorOut},
)
def get_feedback_report(request: HttpRequest, report_id: int):
    report = FeedbackReport.objects.select_related("reporter").filter(pk=report_id).first()
    if report is None:
        return 404, {"detail": "제보를 찾을 수 없습니다.", "code": "not_found"}
    return 200, _report_detail(report)


@operator_router.post(
    "/feedback-reports/{report_id}/status",
    response={
        200: OperatorFeedbackReportOut,
        404: OperatorErrorOut,
        409: OperatorErrorOut,
        422: OperatorErrorOut,
    },
)
def change_feedback_status(request: HttpRequest, report_id: int, payload: ChangeFeedbackStatusIn):
    try:
        report = services.change_status(
            report_id=report_id,
            to_status=payload.status,
            note=payload.note,
            operator=request.auth,
            actor_label=request.auth.get_username(),
        )
    except services.FeedbackNotFoundError as exc:
        return 404, {"detail": str(exc), "code": "not_found"}
    except services.FeedbackConflictError as exc:
        return 409, {"detail": str(exc), "code": "unchanged"}
    except services.FeedbackValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    return 200, _report_detail(report)
