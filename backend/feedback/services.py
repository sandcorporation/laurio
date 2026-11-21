"""제보 권한·제보 도메인 로직 (#1238).

API 레이어(`feedback.api`·`feedback.operator_api`)와 관리 명령에서만 부른다 — 시험의 시임은 HTTP 다.
권한은 `contests.hosting_permission_services` 와 같은 규율이다: 사유 없는 변경은 거부하고, 지금
값과 append-only 이력을 한 트랜잭션에서 남긴다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.db import transaction
from django.db.models import Q, QuerySet

from core.clock import Clock

from . import screenshots
from .models import (
    MAX_BODY_CHARS,
    FeedbackPermission,
    FeedbackPermissionChange,
    FeedbackReport,
)

# 계정당 24시간(굴러가는 창) 안에 만들 수 있는 제보 수.
DAILY_REPORT_LIMIT = 20
DAILY_WINDOW = timedelta(hours=24)


class FeedbackValidationError(Exception):
    """말이 안 되는 입력 — 호출자는 422 로 옮긴다."""


class FeedbackConflictError(Exception):
    """이미 그 상태다 — 호출자는 409 로 옮긴다."""


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
        return FeedbackReport.objects.create(
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
