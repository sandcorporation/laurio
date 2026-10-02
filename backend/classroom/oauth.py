"""연결된 앱의 OAuth 2.1 인가 서버 (ADR-0052, #512, CONTEXT.md 「연결된 앱」).

강사가 claude.ai 같은 외부 AI 도구에 강의실 `/mcp` 주소 하나를 넣고 강의실 로그인으로
허락하면, 그 도구는 이 모듈이 발급한 토큰으로 MCP 엔드포인트(`classroom.mcp`)를 부른다.
MCP 규격의 Authorization 절이 요구하는 조각을 그대로 따른다:

- 보호 자원 메타데이터(RFC 9728)와 인가 서버 메타데이터(RFC 8414) — `metadata_*`.
- 동적 클라이언트 등록(RFC 7591) — `register_client`.
- 인가 코드 + PKCE(S256 만) — 동의 화면이 `issue_code`, 토큰 엔드포인트가
  `exchange_code`. `resource`(RFC 8707)는 이 서버의 `/mcp` 주소 하나만 받는다.
- 접근 토큰 1시간 + 쓸 때마다 바뀌는 갱신 토큰 — `refresh`. 회수(RFC 7009) — `revoke_token`.

**토큰·코드는 해시로만 저장한다.** 평문은 발급하는 순간 응답에 한 번 실릴 뿐이다.

**허락(`ConnectedApp`) 하나가 문이다.** 끊기·90일 미사용 만료·탈퇴·휴면 모두 그 행의
`revoked_at` 을 채우고, 토큰 확인(`authenticate_access_token`)이 매번 그 행을 본다 —
토큰을 하나씩 찾아 지우지 않아도 그 순간부터 거절된다.

**공개 주소는 강의실 도메인이다.** backend 는 배포에서 호스트 포트가 없어(#485)
강의실 앱이 `/mcp`·`/.well-known/oauth-*`·`/oauth/*` 를 이 앱으로 넘긴다. 메타데이터에
나가는 issuer·resource 는 `public_origin` 이 고른다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import timedelta
from urllib.parse import unquote_plus, urlencode, urlsplit

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.models.functions import Coalesce

from core.clock import Clock
from core.scans import ScanSpec

from .models import ConnectedApp, OAuthAuthorizationCode, OAuthClient, OAuthToken

ACCESS_TOKEN_LIFETIME = timedelta(hours=1)
AUTHORIZATION_CODE_LIFETIME = timedelta(minutes=5)
#: 이만큼 한 번도 쓰이지 않은 허락은 스캔이 끊는다(ADR-0052).
UNUSED_GRANT_LIFETIME = timedelta(days=90)
#: 아무도 허락하지 않은 등록은 이만큼 지나면 걷는다 — 등록은 인증이 없다.
UNUSED_CLIENT_LIFETIME = timedelta(days=1)
#: 바뀐 갱신 토큰 행을 남겨 두는 기간 — 지나면 다음 갱신 때 함께 지운다.
ROTATED_REFRESH_RETENTION = timedelta(days=1)
#: `last_used_at` 을 매 요청마다 쓰지 않는다 — 화면이 보여주는 것은 「날」이다.
LAST_USED_WRITE_INTERVAL = timedelta(minutes=1)

#: 범위는 하나 — 그 강사의 모든 Class(ADR-0052).
SCOPE = "classroom"
MCP_PATH = "/mcp"
PUBLIC_ORIGIN_HEADER = "HTTP_X_CODEMIT_PUBLIC_ORIGIN"

_ACCESS_PREFIX = "cmt_at_"
_REFRESH_PREFIX = "cmt_rt_"
_CODE_PREFIX = "cmt_ac_"

_AUTH_METHODS = {"none", "client_secret_post", "client_secret_basic"}
_GRANT_TYPES = {"authorization_code", "refresh_token"}
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1", "[::1]"}
_ORIGIN_PATTERN = re.compile(r"^https?://[A-Za-z0-9.\-]+(:\d{1,5})?$")
_PKCE_VERIFIER_PATTERN = re.compile(r"^[A-Za-z0-9\-._~]{43,128}$")
_PKCE_CHALLENGE_PATTERN = re.compile(r"^[A-Za-z0-9\-_]{43}$")
_MAX_REDIRECT_URIS = 10
_MAX_REDIRECT_URI_LENGTH = 2000
_MAX_CLIENT_NAME_LENGTH = 200


class OAuthError(Exception):
    """RFC 6749 §5.2 의 오류 응답 하나. `error` 는 규격의 기계용 코드, `description` 은
    사람에게 보일 수 있는 설명이다."""

    def __init__(self, error: str, description: str, status: int = 400):
        super().__init__(description)
        self.error = error
        self.description = description
        self.status = status

    def as_body(self) -> dict:
        return {"error": self.error, "error_description": self.description}


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _new_secret(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


# --- 공개 주소 ---------------------------------------------------------------


def public_origin(request) -> str:
    """메타데이터·토큰 대상이 쓰는 강의실의 공개 오리진.

    설정(`CODEMIT_CLASSROOM_ORIGIN`)이 있으면 그것이다 — 배포는 늘 이쪽이다. 없으면(dev)
    강의실 BFF 가 실어 보낸 자기 오리진을 모양만 확인해 쓰고, 그것도 없으면 요청이 도착한
    주소다(이 엔드포인트를 직접 친 시험). 헤더는 강의실 BFF 만 붙인다 — backend 는
    배포에서 바깥에 열려 있지 않다."""

    configured = getattr(settings, "CLASSROOM_WEB_ORIGIN", "")
    if configured:
        return configured
    forwarded = request.META.get(PUBLIC_ORIGIN_HEADER, "").strip().rstrip("/")
    if forwarded and _ORIGIN_PATTERN.match(forwarded):
        return forwarded
    return f"{request.scheme}://{request.get_host()}"


def resource_url(origin: str) -> str:
    return f"{origin}{MCP_PATH}"


def protected_resource_metadata_url(origin: str) -> str:
    # RFC 9728 §3.1 — 경로가 있는 자원은 well-known 뒤에 그 경로를 붙인다.
    return f"{origin}/.well-known/oauth-protected-resource{MCP_PATH}"


def protected_resource_metadata(origin: str) -> dict:
    return {
        "resource": resource_url(origin),
        "authorization_servers": [origin],
        "scopes_supported": [SCOPE],
        "bearer_methods_supported": ["header"],
        "resource_name": "Codemit 강의실",
    }


def authorization_server_metadata(origin: str) -> dict:
    return {
        "issuer": origin,
        "authorization_endpoint": f"{origin}/oauth/authorize",
        "token_endpoint": f"{origin}/oauth/token",
        "registration_endpoint": f"{origin}/oauth/register",
        "revocation_endpoint": f"{origin}/oauth/revoke",
        "scopes_supported": [SCOPE],
        "response_types_supported": ["code"],
        "response_modes_supported": ["query"],
        "grant_types_supported": sorted(_GRANT_TYPES),
        "token_endpoint_auth_methods_supported": sorted(_AUTH_METHODS),
        "revocation_endpoint_auth_methods_supported": sorted(_AUTH_METHODS),
        "code_challenge_methods_supported": ["S256"],
        "authorization_response_iss_parameter_supported": True,
    }


def _canonical(url: str) -> str:
    """scheme·host 의 대소문자와 끝의 `/` 만 맞춘다(MCP 규격 「Canonical Server URI」)."""

    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"


def _resolve_resource(requested: str | None, origin: str) -> str:
    """`resource` 가 없으면 이 서버의 `/mcp` 로 묶고, 있으면 그 주소여야 한다 — 다른
    서버에 쓸 토큰을 여기서 받아 갈 수 없다(RFC 8707, MCP 「Token Audience」)."""

    expected = resource_url(origin)
    if not requested:
        return expected
    if _canonical(requested) in {_canonical(expected), _canonical(origin)}:
        return expected
    raise OAuthError("invalid_target", "이 서버의 주소가 아닌 resource 입니다.")


# --- 동적 클라이언트 등록 ------------------------------------------------------


def _valid_redirect_uri(uri: str) -> bool:
    if not isinstance(uri, str) or len(uri) > _MAX_REDIRECT_URI_LENGTH:
        return False
    parts = urlsplit(uri)
    if parts.fragment or not parts.netloc:
        return False
    if parts.scheme == "https":
        return True
    # OAuth 2.1 §8.4.2 — 평문 http 는 같은 기계로 돌아오는 주소만 허락한다.
    return parts.scheme == "http" and (parts.hostname or "") in _LOOPBACK_HOSTS


def register_client(metadata: dict) -> dict:
    """RFC 7591 등록. 돌려주는 dict 가 그대로 응답 본문이다(평문 비밀은 여기 한 번뿐)."""

    if not isinstance(metadata, dict):
        raise OAuthError("invalid_client_metadata", "등록 요청은 JSON 객체여야 합니다.")

    redirect_uris = metadata.get("redirect_uris")
    if (
        not isinstance(redirect_uris, list)
        or not redirect_uris
        or len(redirect_uris) > _MAX_REDIRECT_URIS
        or not all(_valid_redirect_uri(uri) for uri in redirect_uris)
    ):
        raise OAuthError(
            "invalid_redirect_uri",
            "redirect_uris 는 https 주소(또는 이 기계로 돌아오는 http 주소) 목록이어야 합니다.",
        )

    auth_method = metadata.get("token_endpoint_auth_method") or "client_secret_basic"
    if auth_method not in _AUTH_METHODS:
        raise OAuthError("invalid_client_metadata", "지원하지 않는 토큰 엔드포인트 인증 방식입니다.")

    grant_types = metadata.get("grant_types") or ["authorization_code"]
    if not isinstance(grant_types, list) or not set(grant_types) <= _GRANT_TYPES or "authorization_code" not in grant_types:
        raise OAuthError("invalid_client_metadata", "지원하지 않는 grant_types 입니다.")

    response_types = metadata.get("response_types") or ["code"]
    if response_types != ["code"]:
        raise OAuthError("invalid_client_metadata", "response_types 는 code 하나만 지원합니다.")

    client_name = metadata.get("client_name") or ""
    if not isinstance(client_name, str):
        raise OAuthError("invalid_client_metadata", "client_name 은 문자열이어야 합니다.")
    client_name = client_name.strip()[:_MAX_CLIENT_NAME_LENGTH]

    now = Clock.now()
    client_id = secrets.token_urlsafe(24)
    secret = _new_secret("cmt_cs_") if auth_method != "none" else ""
    OAuthClient.objects.create(
        client_id=client_id,
        client_secret_hash=_hash(secret) if secret else "",
        token_endpoint_auth_method=auth_method,
        client_name=client_name,
        redirect_uris=list(redirect_uris),
        created_at=now,
    )
    body = {
        "client_id": client_id,
        "client_id_issued_at": int(now.timestamp()),
        "client_name": client_name,
        "redirect_uris": list(redirect_uris),
        "grant_types": list(grant_types),
        "response_types": ["code"],
        "token_endpoint_auth_method": auth_method,
        "scope": SCOPE,
    }
    if secret:
        body["client_secret"] = secret
        body["client_secret_expires_at"] = 0
    return body


# --- 동의 화면 ---------------------------------------------------------------


@dataclass(frozen=True)
class AuthorizationRequest:
    client: OAuthClient
    redirect_uri: str
    code_challenge: str
    state: str
    resource: str


def validate_authorization_request(params: dict, origin: str) -> AuthorizationRequest:
    """동의 화면이 그리기 전에, 그리고 허락을 받을 때 한 번 더 부른다."""

    client = OAuthClient.objects.filter(client_id=params.get("client_id") or "").first()
    if client is None:
        raise OAuthError("invalid_client", "등록되지 않은 앱입니다. 앱에서 연결을 처음부터 다시 시작하세요.")
    redirect_uri = params.get("redirect_uri") or ""
    if redirect_uri not in client.redirect_uris:
        raise OAuthError("invalid_request", "앱이 등록한 주소와 돌아갈 주소가 다릅니다.")
    if (params.get("response_type") or "code") != "code":
        raise OAuthError("unsupported_response_type", "지원하지 않는 요청입니다.")
    if params.get("code_challenge_method") != "S256" or not _PKCE_CHALLENGE_PATTERN.match(
        params.get("code_challenge") or ""
    ):
        raise OAuthError("invalid_request", "PKCE(S256) 값이 없거나 올바르지 않습니다.")
    resource = _resolve_resource(params.get("resource"), origin)
    return AuthorizationRequest(
        client=client,
        redirect_uri=redirect_uri,
        code_challenge=params["code_challenge"],
        state=params.get("state") or "",
        resource=resource,
    )


def _redirect_with(redirect_uri: str, values: dict) -> str:
    joiner = "&" if urlsplit(redirect_uri).query else "?"
    return f"{redirect_uri}{joiner}{urlencode({k: v for k, v in values.items() if v})}"


@transaction.atomic
def issue_code(request: AuthorizationRequest, instructor, origin: str) -> str:
    """강사가 「허락」을 눌렀다 — 허락(같은 앱이면 이어 쓴다)과 코드를 만들고, 앱으로
    돌아갈 주소를 돌려준다. `iss` 를 함께 싣는다(RFC 9207)."""

    now = Clock.now()
    grant = (
        ConnectedApp.objects.select_for_update()
        .filter(instructor=instructor, client=request.client, revoked_at__isnull=True)
        .first()
    )
    if grant is None:
        grant = ConnectedApp.objects.create(
            instructor=instructor,
            client=request.client,
            name=request.client.client_name,
            created_at=now,
        )
    code = _new_secret(_CODE_PREFIX)
    OAuthAuthorizationCode.objects.create(
        code_hash=_hash(code),
        connected_app=grant,
        redirect_uri=request.redirect_uri,
        code_challenge=request.code_challenge,
        resource=request.resource,
        expires_at=now + AUTHORIZATION_CODE_LIFETIME,
    )
    return _redirect_with(request.redirect_uri, {"code": code, "state": request.state, "iss": origin})


def denial_redirect(request: AuthorizationRequest, origin: str) -> str:
    return _redirect_with(
        request.redirect_uri,
        {"error": "access_denied", "state": request.state, "iss": origin},
    )


# --- 토큰 엔드포인트 -------------------------------------------------------------


def authenticate_client(client_id: str | None, client_secret: str | None) -> OAuthClient:
    client = OAuthClient.objects.filter(client_id=client_id or "").first()
    if client is None:
        raise OAuthError("invalid_client", "등록되지 않은 앱입니다.", status=401)
    if client.client_secret_hash:
        if not client_secret or not hmac.compare_digest(client.client_secret_hash, _hash(client_secret)):
            raise OAuthError("invalid_client", "앱 인증에 실패했습니다.", status=401)
    return client


def client_credentials_from(request, form) -> tuple[str | None, str | None]:
    """`client_secret_basic`(Authorization 헤더)과 `client_secret_post`·공개 클라이언트
    (본문의 client_id) 를 같은 모양으로 꺼낸다."""

    header = request.META.get("HTTP_AUTHORIZATION", "")
    if header.startswith("Basic "):
        try:
            decoded = base64.b64decode(header[len("Basic ") :]).decode("utf-8")
            client_id, _, secret = decoded.partition(":")
            return unquote_plus(client_id), unquote_plus(secret)
        except (ValueError, UnicodeDecodeError) as exc:
            raise OAuthError("invalid_client", "앱 인증 헤더가 올바르지 않습니다.", status=401) from exc
    return form.get("client_id"), form.get("client_secret")


def _token_response(grant: ConnectedApp, resource: str) -> dict:
    now = Clock.now()
    access = _new_secret(_ACCESS_PREFIX)
    refresh = _new_secret(_REFRESH_PREFIX)
    OAuthToken.objects.bulk_create(
        [
            OAuthToken(
                token_hash=_hash(access),
                kind=OAuthToken.Kind.ACCESS,
                connected_app=grant,
                resource=resource,
                created_at=now,
                expires_at=now + ACCESS_TOKEN_LIFETIME,
            ),
            OAuthToken(
                token_hash=_hash(refresh),
                kind=OAuthToken.Kind.REFRESH,
                connected_app=grant,
                resource=resource,
                created_at=now,
            ),
        ]
    )
    return {
        "access_token": access,
        "token_type": "Bearer",
        "expires_in": int(ACCESS_TOKEN_LIFETIME.total_seconds()),
        "refresh_token": refresh,
        "scope": SCOPE,
    }


def _verify_pkce(verifier: str | None, challenge: str) -> bool:
    if not verifier or not _PKCE_VERIFIER_PATTERN.match(verifier):
        return False
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    computed = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return hmac.compare_digest(computed, challenge)


@transaction.atomic
def exchange_code(client: OAuthClient, form, origin: str) -> dict:
    now = Clock.now()
    code = (
        OAuthAuthorizationCode.objects.select_for_update()
        .select_related("connected_app")
        .filter(code_hash=_hash(form.get("code") or ""), connected_app__client=client)
        .first()
    )
    if code is None or code.used_at is not None or code.expires_at <= now:
        raise OAuthError("invalid_grant", "인가 코드가 없거나 이미 쓰였거나 만료됐습니다.")
    code.used_at = now
    code.save(update_fields=["used_at"])
    if form.get("redirect_uri") != code.redirect_uri:
        raise OAuthError("invalid_grant", "인가 요청과 돌아갈 주소가 다릅니다.")
    if not _verify_pkce(form.get("code_verifier"), code.code_challenge):
        raise OAuthError("invalid_grant", "PKCE 확인에 실패했습니다.")
    resource = _resolve_resource(form.get("resource"), origin)
    if resource != code.resource:
        raise OAuthError("invalid_target", "인가 요청과 resource 가 다릅니다.")
    grant = code.connected_app
    if not _grant_is_live(grant):
        raise OAuthError("invalid_grant", "이 연결은 끊겼습니다.")
    return _token_response(grant, resource)


def _grant_is_live(grant: ConnectedApp) -> bool:
    return grant.revoked_at is None and grant.instructor.is_active


@transaction.atomic
def refresh(client: OAuthClient, form, origin: str) -> dict:
    """갱신 토큰은 한 번 쓰면 바뀐다(OAuth 2.1 §4.3.1 의 회전). 이미 바뀐 토큰을 다시
    내면 거절만 한다 — 같은 요청을 다시 보낸 앱의 연결을 통째로 끊지 않는다."""

    now = Clock.now()
    token = (
        OAuthToken.objects.select_for_update()
        .select_related("connected_app__instructor")
        .filter(
            token_hash=_hash(form.get("refresh_token") or ""),
            kind=OAuthToken.Kind.REFRESH,
            connected_app__client=client,
        )
        .first()
    )
    if token is None or token.revoked_at is not None or not _grant_is_live(token.connected_app):
        raise OAuthError("invalid_grant", "갱신 토큰이 없거나 이미 쓰였거나 연결이 끊겼습니다.")
    if form.get("resource"):
        if _resolve_resource(form.get("resource"), origin) != token.resource:
            raise OAuthError("invalid_target", "처음 허락한 resource 와 다릅니다.")
    token.revoked_at = now
    token.save(update_fields=["revoked_at"])
    grant = token.connected_app
    # 이 허락에 쌓인 지난 토큰을 걷는다 — 회전이 한 시간마다 두 줄씩 남기기 때문이다.
    grant.tokens.filter(
        Q(kind=OAuthToken.Kind.ACCESS, expires_at__lte=now)
        | Q(kind=OAuthToken.Kind.REFRESH, revoked_at__lte=now - ROTATED_REFRESH_RETENTION)
    ).delete()
    return _token_response(grant, token.resource)


def revoke_token(client: OAuthClient, form) -> None:
    """RFC 7009 — 모르는 토큰이어도 성공으로 답한다(존재를 알려주지 않는다)."""

    OAuthToken.objects.filter(
        token_hash=_hash(form.get("token") or ""),
        connected_app__client=client,
        revoked_at__isnull=True,
    ).update(revoked_at=Clock.now())


# --- 자원 서버(MCP) 쪽 ---------------------------------------------------------


def authenticate_access_token(raw: str, origin: str) -> ConnectedApp | None:
    """살아 있는 허락에서 나온, 이 서버 몫의 만료되지 않은 접근 토큰이면 그 허락을."""

    if not raw.startswith(_ACCESS_PREFIX):
        return None
    now = Clock.now()
    token = (
        OAuthToken.objects.select_related("connected_app__instructor")
        .filter(
            token_hash=_hash(raw),
            kind=OAuthToken.Kind.ACCESS,
            revoked_at__isnull=True,
            expires_at__gt=now,
        )
        .first()
    )
    if token is None or token.resource != resource_url(origin):
        return None
    grant = token.connected_app
    if not _grant_is_live(grant):
        return None
    if grant.last_used_at is None or grant.last_used_at <= now - LAST_USED_WRITE_INTERVAL:
        ConnectedApp.objects.filter(pk=grant.pk).update(last_used_at=now)
        grant.last_used_at = now
    return grant


# --- 끊기 ---------------------------------------------------------------------


def revoke_grants(queryset, reason: str, *, as_of=None) -> int:
    now = as_of or Clock.now()
    ids = list(queryset.filter(revoked_at__isnull=True).values_list("id", flat=True))
    if not ids:
        return 0
    ConnectedApp.objects.filter(id__in=ids).update(revoked_at=now, revoke_reason=reason)
    OAuthToken.objects.filter(connected_app_id__in=ids, revoked_at__isnull=True).update(revoked_at=now)
    return len(ids)


def disconnect(instructor, connected_app_id: int) -> bool:
    return bool(
        revoke_grants(
            ConnectedApp.objects.filter(id=connected_app_id, instructor=instructor),
            ConnectedApp.RevokeReason.DISCONNECTED,
        )
    )


def revoke_all_for_user(user, reason: str) -> int:
    return revoke_grants(ConnectedApp.objects.filter(instructor=user), reason)


def active_connected_apps(instructor):
    return ConnectedApp.objects.filter(instructor=instructor, revoked_at__isnull=True)


# --- 스캔 ---------------------------------------------------------------------


def _unused_grants(as_of, ctx):
    return ConnectedApp.objects.filter(revoked_at__isnull=True).alias(
        last_activity=Coalesce("last_used_at", "created_at")
    ).filter(last_activity__lte=as_of - UNUSED_GRANT_LIFETIME)


def _expire_grant(grant, as_of, ctx):
    if revoke_grants(ConnectedApp.objects.filter(pk=grant.pk), ConnectedApp.RevokeReason.EXPIRED, as_of=as_of):
        return {"connected_app_id": grant.pk}
    return None


CONNECTED_APP_EXPIRY_SCAN = ScanSpec(
    name="classroom-connected-app-expiry",
    candidates=_unused_grants,
    handle_row=_expire_grant,
    interval_seconds=3600.0,
)


def _abandoned_clients(as_of, ctx):
    return OAuthClient.objects.filter(
        created_at__lte=as_of - UNUSED_CLIENT_LIFETIME, grants__isnull=True
    )


def _delete_client(client, as_of, ctx):
    deleted, _ = OAuthClient.objects.filter(pk=client.pk, grants__isnull=True).delete()
    return {"client_id": client.pk} if deleted else None


UNUSED_CLIENT_SCAN = ScanSpec(
    name="classroom-oauth-client-cleanup",
    candidates=_abandoned_clients,
    handle_row=_delete_client,
    interval_seconds=3600.0,
)
