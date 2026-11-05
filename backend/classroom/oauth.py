"""강의실의 연결된 앱 자원 (ADR-0052, #512, CONTEXT.md 「연결된 앱」).

OAuth 2.1 인가 서버의 몸은 공유층 `core.oauth` 에 있다(#870 — 공모전 MCP 가 같은 엔진을
쓴다). 여기에는 강의실 자원 하나(`CLASSROOM`: 범위 `classroom`, 공개 오리진
`CLASSROOM_WEB_ORIGIN`)와, 그 자원에 묶인 이름들이 있다 — 강의실 코드와 시험은 예전처럼
`classroom.oauth.issue_code(...)` 를 부른다.
"""

from __future__ import annotations

from core import oauth as _engine
from core.models import ConnectedApp, OAuthClient
from core.oauth import (  # noqa: F401 — 강의실 코드·시험이 이 이름으로 부른다.
    ACCESS_TOKEN_LIFETIME,
    AUTHORIZATION_CODE_LIFETIME,
    CONNECTED_APP_EXPIRY_SCAN,
    MCP_PATH,
    UNUSED_CLIENT_SCAN,
    UNUSED_GRANT_LIFETIME,
    AuthorizationRequest,
    OAuthError,
    OAuthResource,
    authenticate_client,
    client_credentials_from,
    denial_redirect,
    protected_resource_metadata_url,
    resource_url,
    revoke_all_for_user,
    revoke_grants,
    revoke_token,
)

#: 범위는 하나 — 그 강사의 모든 Class(ADR-0052).
CLASSROOM = OAuthResource(
    scope=ConnectedApp.Scope.CLASSROOM,
    resource_name="Codemit 강의실",
    realm="codemit-classroom",
    origin_setting="CLASSROOM_WEB_ORIGIN",
)
SCOPE = CLASSROOM.scope


def public_origin(request) -> str:
    return CLASSROOM.public_origin(request)


def protected_resource_metadata(origin: str) -> dict:
    return CLASSROOM.protected_resource_metadata(origin)


def authorization_server_metadata(origin: str) -> dict:
    return CLASSROOM.authorization_server_metadata(origin)


def register_client(metadata: dict) -> dict:
    return _engine.register_client(CLASSROOM, metadata)


def validate_authorization_request(params: dict, origin: str) -> AuthorizationRequest:
    return _engine.validate_authorization_request(CLASSROOM, params, origin)


def issue_code(request: AuthorizationRequest, instructor, origin: str) -> str:
    return _engine.issue_code(CLASSROOM, request, instructor, origin)


def exchange_code(client: OAuthClient, form, origin: str) -> dict:
    return _engine.exchange_code(CLASSROOM, client, form, origin)


def refresh(client: OAuthClient, form, origin: str) -> dict:
    return _engine.refresh(CLASSROOM, client, form, origin)


def authenticate_access_token(raw: str, origin: str) -> ConnectedApp | None:
    return _engine.authenticate_access_token(CLASSROOM, raw, origin)


def disconnect(instructor, connected_app_id: int) -> bool:
    return _engine.disconnect(CLASSROOM, instructor, connected_app_id)


def active_connected_apps(instructor):
    return _engine.active_connected_apps(CLASSROOM, instructor)
