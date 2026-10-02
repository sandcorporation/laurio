"""연결된 앱 — 강사가 로그인한 채로 부르는 쪽 (ADR-0052, #512, CONTEXT.md 「연결된 앱」).

- 동의 화면(강의실 앱 `/oauth/authorize`)이 그리기 전에 요청을 확인받고(`GET
  /oauth/authorize`), 강사가 허락·거절하면 앱으로 돌아갈 주소를 받는다(`POST`).
  누가 허락하는지는 강의실 로그인(JWT 쿠키를 BFF 가 Bearer 로 바꿔 단다)이 정한다.
- 설정의 「연결된 앱」 목록과 끊기.

규격이 모양을 정하는 OAuth 엔드포인트(메타데이터·등록·토큰·회수)는
`classroom.oauth_views` 에 있다.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlsplit

from django.http import HttpRequest
from ninja import Router, Schema
from ninja.errors import HttpError

from accounts.middleware import jwt_auth

from . import oauth
from .schemas import ErrorOut

router = Router(tags=["classroom-connected-apps"])

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


class AuthorizationPreviewOut(Schema):
    #: 앱이 스스로 밝힌 이름 — 비어 있으면 화면이 「이름을 밝히지 않은 앱」으로 쓴다.
    client_name: str
    #: 허락하면 돌아갈 주소의 호스트 — 앱 이름은 앱이 지어 붙이는 것이라, 사람이
    #: 확인할 수 있는 사실은 이쪽이다.
    redirect_host: str


class AuthorizationDecisionIn(Schema):
    client_id: str
    redirect_uri: str
    response_type: str = "code"
    code_challenge: str
    code_challenge_method: str
    state: str = ""
    scope: str = ""
    resource: str = ""
    approve: bool


class AuthorizationRedirectOut(Schema):
    redirect_to: str


class ConnectedAppOut(Schema):
    id: int
    name: str
    connected_at: datetime
    #: 한 번도 부르지 않았으면 null.
    last_used_at: datetime | None = None


def _validated(request: HttpRequest, params: dict) -> oauth.AuthorizationRequest:
    try:
        return oauth.validate_authorization_request(params, oauth.public_origin(request))
    except oauth.OAuthError as error:
        raise HttpError(400, error.description) from error


@router.get(
    "/oauth/authorize",
    response={200: AuthorizationPreviewOut, 400: ErrorOut},
    auth=jwt_auth,
)
def preview_authorization(request: HttpRequest):
    params = {field: request.GET.get(field, "") for field in _AUTHORIZE_FIELDS}
    authorization = _validated(request, params)
    return 200, AuthorizationPreviewOut(
        client_name=authorization.client.client_name,
        redirect_host=urlsplit(authorization.redirect_uri).netloc,
    )


@router.post(
    "/oauth/authorize",
    response={200: AuthorizationRedirectOut, 400: ErrorOut},
    auth=jwt_auth,
)
def decide_authorization(request: HttpRequest, payload: AuthorizationDecisionIn):
    authorization = _validated(request, payload.dict())
    origin = oauth.public_origin(request)
    if not payload.approve:
        return 200, AuthorizationRedirectOut(redirect_to=oauth.denial_redirect(authorization, origin))
    return 200, AuthorizationRedirectOut(
        redirect_to=oauth.issue_code(authorization, request.auth_user, origin)
    )


@router.get("/connected-apps", response={200: list[ConnectedAppOut]}, auth=jwt_auth)
def list_connected_apps(request: HttpRequest):
    """지금 살아 있는 연결만 — 끊긴 것은 목록에서 사라진다."""

    return 200, [
        ConnectedAppOut(
            id=grant.id,
            name=grant.name,
            connected_at=grant.created_at,
            last_used_at=grant.last_used_at,
        )
        for grant in oauth.active_connected_apps(request.auth_user)
    ]


@router.delete("/connected-apps/{connected_app_id}", response={204: None, 404: ErrorOut}, auth=jwt_auth)
def disconnect_connected_app(request: HttpRequest, connected_app_id: int):
    if not oauth.disconnect(request.auth_user, connected_app_id):
        raise HttpError(404, "연결된 앱을 찾을 수 없습니다.")
    return 204, None
