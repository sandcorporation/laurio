"""공개 앱의 「연결된 앱」 — 동의 화면과 연결 보기·끊기 (#870, ADR-0069).

강의실의 `classroom.connected_app_api` 와 같은 모양이고, 다른 것은 둘이다: 자원이 공모전
(`contests.oauth.CONTESTS`)이고, **개최 권한이 없는 사람은 동의 단계에서 거절한다**(403) —
허락을 만들어 두고 호출에서야 막는 것보다 처음부터 분명히 말하는 편이 낫다. 목록·끊기는
권한이 회수된 사람도 쓸 수 있다(자기 연결을 끊을 수는 있어야 한다).
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from core import oauth

from .oauth import CONTESTS, NOT_ELIGIBLE, may_host

router = Router(tags=["contest-connected-apps"])


class ErrorOut(Schema):
    detail: str

_AUTHORIZE_FIELDS = (
    "client_id",
    "redirect_uri",
    "response_type",
    "code_challenge",
    "code_challenge_method",
    "state",
    "scope",
    "resource",
)


class ContestAuthorizationPreviewOut(Schema):
    client_name: str
    redirect_host: str


class ContestAuthorizationDecisionIn(Schema):
    client_id: str
    redirect_uri: str
    response_type: str = "code"
    code_challenge: str
    code_challenge_method: str
    state: str = ""
    scope: str = ""
    resource: str = ""
    approve: bool


class ContestAuthorizationRedirectOut(Schema):
    redirect_to: str


class ContestConnectedAppOut(Schema):
    id: int
    name: str
    connected_at: datetime
    last_used_at: datetime | None = None


def _validated(request: HttpRequest, params: dict) -> oauth.AuthorizationRequest:
    try:
        return oauth.validate_authorization_request(CONTESTS, params, CONTESTS.public_origin(request))
    except oauth.OAuthError as error:
        raise HttpError(400, error.description) from error


def _require_eligible(request: HttpRequest) -> None:
    if not may_host(request.auth_user):
        raise HttpError(403, NOT_ELIGIBLE)


@router.get(
    "/oauth/authorize",
    response={200: ContestAuthorizationPreviewOut, 400: ErrorOut, 403: ErrorOut},
    auth=jwt_auth,
)
def preview_contest_authorization(request: HttpRequest):
    params = {field: request.GET.get(field, "") for field in _AUTHORIZE_FIELDS}
    authorization = _validated(request, params)
    _require_eligible(request)
    return 200, ContestAuthorizationPreviewOut(
        client_name=authorization.client.client_name,
        redirect_host=urlsplit(authorization.redirect_uri).netloc,
    )


@router.post(
    "/oauth/authorize",
    response={200: ContestAuthorizationRedirectOut, 400: ErrorOut, 403: ErrorOut},
    auth=jwt_auth,
)
def decide_contest_authorization(request: HttpRequest, payload: ContestAuthorizationDecisionIn):
    authorization = _validated(request, payload.dict())
    origin = CONTESTS.public_origin(request)
    if not payload.approve:
        return 200, ContestAuthorizationRedirectOut(redirect_to=oauth.denial_redirect(authorization, origin))
    _require_eligible(request)
    return 200, ContestAuthorizationRedirectOut(
        redirect_to=oauth.issue_code(CONTESTS, authorization, request.auth_user, origin)
    )


@router.get("/connected-apps", response={200: list[ContestConnectedAppOut]}, auth=jwt_auth)
def list_contest_connected_apps(request: HttpRequest):
    """지금 살아 있는 공모전 범위의 연결만 — 끊긴 것은 목록에서 사라진다."""

    return 200, [
        ContestConnectedAppOut(
            id=grant.id,
            name=grant.name,
            connected_at=grant.created_at,
            last_used_at=grant.last_used_at,
        )
        for grant in oauth.active_connected_apps(CONTESTS, request.auth_user)
    ]


@router.delete("/connected-apps/{connected_app_id}", response={204: None, 404: ErrorOut}, auth=jwt_auth)
def disconnect_contest_connected_app(request: HttpRequest, connected_app_id: int):
    if not oauth.disconnect(CONTESTS, request.auth_user, connected_app_id):
        raise HttpError(404, "연결된 앱을 찾을 수 없습니다.")
    return 204, None
