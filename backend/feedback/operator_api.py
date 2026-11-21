"""운영자 API — `/api/operator/feedback-...` (#1238 권한, #1239 제보).

`OperatorAuth` 가 라우터 전체에 걸려 있다. 권한 켜기·끄기는 개최 권한과 같이 최고 운영자만 한다.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractBaseUser
from django.http import HttpRequest
from ninja import Router, Schema

from core.operator_auth import OperatorAuth, SuperuserOperatorAuth

from . import services
from .models import FeedbackPermission, FeedbackPermissionChange

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
