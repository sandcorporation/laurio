"""제보자 API — `/api/feedback/...` (#1238).

공개 앱·강의실 앱 둘 다 BFF 프록시(`/api/backend/feedback/...`)로 부른다. 모든 엔드포인트가
로그인(`jwt_auth`)과 제보 권한(`FeedbackPermission.is_granted`)을 요구한다 — 권한이 없으면 403.
남의 제보는 존재하지 않는 것처럼 404 다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from django.http import HttpRequest
from django.shortcuts import get_object_or_404
from ninja import Field, Router, Schema
from ninja.errors import HttpError

from accounts.middleware import jwt_auth

from . import screenshots, services
from .models import MAX_BODY_CHARS, FeedbackReport, FeedbackStatusChange

router = Router(tags=["feedback"], auth=jwt_auth)

Kind = Literal["suggestion", "bug"]
App = Literal["contest", "classroom"]


def _require_permission(request: HttpRequest) -> None:
    if not services.is_granted(request.auth_user):
        raise HttpError(403, "제보 권한이 없습니다.")


class PermissionOut(Schema):
    granted: bool


class ScreenshotUploadUrlIn(Schema):
    content_type: str


class ScreenshotUploadUrlOut(Schema):
    object_key: str
    upload_url: str
    method: str
    fields: dict[str, str]
    expires_at: datetime


class FeedbackReportIn(Schema):
    kind: Kind
    body: str = Field(max_length=MAX_BODY_CHARS)
    app: App
    page_url: str = Field("", max_length=2048)
    user_agent: str = Field("", max_length=512)
    screen_width: int | None = Field(None, ge=0, le=100_000)
    screen_height: int | None = Field(None, ge=0, le=100_000)
    screenshot_key: str = Field("", max_length=255)


class FeedbackReportListOut(Schema):
    id: int
    kind: str
    app: str
    status: str
    body: str
    has_screenshot: bool
    received_at: datetime
    closed_at: datetime | None


class FeedbackStatusChangeOut(Schema):
    from_status: str
    to_status: str
    note: str
    actor: str
    changed_at: datetime


class FeedbackReportOut(FeedbackReportListOut):
    page_url: str
    resolution_note: str
    history: list[FeedbackStatusChangeOut]


class ScreenshotDownloadOut(Schema):
    download_url: str
    expires_at: datetime


def _list_row(report: FeedbackReport) -> FeedbackReportListOut:
    return FeedbackReportListOut(
        id=report.id,
        kind=report.kind,
        app=report.app,
        status=report.status,
        body=report.body,
        has_screenshot=bool(report.screenshot_key),
        received_at=report.received_at,
        closed_at=report.closed_at,
    )


def _history_row(change: FeedbackStatusChange) -> FeedbackStatusChangeOut:
    return FeedbackStatusChangeOut(
        from_status=change.from_status,
        to_status=change.to_status,
        note=change.note,
        actor=change.actor_label,
        changed_at=change.changed_at,
    )


def _detail(report: FeedbackReport) -> FeedbackReportOut:
    return FeedbackReportOut(
        **_list_row(report).dict(),
        page_url=report.page_url,
        resolution_note=report.resolution_note,
        history=[_history_row(change) for change in report.status_changes.all()],
    )


def _own_report(request: HttpRequest, report_id: int) -> FeedbackReport:
    return get_object_or_404(FeedbackReport, pk=report_id, reporter=request.auth_user)


@router.get("/permission", response=PermissionOut)
def get_own_permission(request: HttpRequest):
    """화면이 버튼을 그릴지 묻는 자리 — 권한이 없어도 403 이 아니라 `granted=false` 다."""

    return PermissionOut(granted=services.is_granted(request.auth_user))


@router.post("/screenshot-upload-url", response=ScreenshotUploadUrlOut)
def request_screenshot_upload_url(request: HttpRequest, payload: ScreenshotUploadUrlIn):
    _require_permission(request)
    presigned = screenshots.request_upload_url(request.auth_user.pk, payload.content_type)
    return ScreenshotUploadUrlOut(
        object_key=presigned.object_key,
        upload_url=presigned.url,
        method=presigned.method,
        fields=presigned.fields,
        expires_at=presigned.expires_at,
    )


@router.post("/reports", response={201: FeedbackReportOut})
def create_report(request: HttpRequest, payload: FeedbackReportIn):
    _require_permission(request)
    try:
        report = services.create_report(
            reporter=request.auth_user,
            data=services.NewReport(
                kind=payload.kind,
                body=payload.body,
                app=payload.app,
                page_url=payload.page_url,
                user_agent=payload.user_agent,
                screen_width=payload.screen_width,
                screen_height=payload.screen_height,
                screenshot_key=payload.screenshot_key,
            ),
        )
    except services.FeedbackValidationError as exc:
        raise HttpError(422, str(exc)) from exc
    except services.FeedbackRateLimitError as exc:
        raise HttpError(429, str(exc)) from exc
    return 201, _detail(report)


@router.get("/reports", response=list[FeedbackReportListOut])
def list_own_reports(request: HttpRequest):
    _require_permission(request)
    reports = FeedbackReport.objects.filter(reporter=request.auth_user).order_by(
        "-received_at", "-id"
    )[:200]
    return [_list_row(report) for report in reports]


@router.get("/reports/{report_id}", response=FeedbackReportOut)
def get_own_report(request: HttpRequest, report_id: int):
    _require_permission(request)
    return _detail(_own_report(request, report_id))


@router.get("/reports/{report_id}/screenshot", response=ScreenshotDownloadOut)
def get_own_screenshot(request: HttpRequest, report_id: int):
    """열 때마다 짧게(분 단위) 발급한다. 보관 기한이 지나 지운 그림도 404 다."""

    _require_permission(request)
    report = _own_report(request, report_id)
    if not report.screenshot_key:
        raise HttpError(404, "스크린샷이 없습니다.")
    presigned = screenshots.request_download_url(report.screenshot_key)
    return ScreenshotDownloadOut(download_url=presigned.url, expires_at=presigned.expires_at)
