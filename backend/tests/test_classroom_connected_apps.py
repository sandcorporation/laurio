"""연결된 앱 — OAuth 허락부터 MCP 도구 호출까지 (#512, ADR-0052, CONTEXT.md 「연결된 앱」).

claude.ai 커넥터가 밟는 순서를 HTTP 로 그대로 걷는다: 보호 자원 메타데이터 → 인가 서버
메타데이터 → 동적 등록 → (강사 로그인으로) 동의 → 인가 코드 + PKCE → 토큰 → `/mcp`.
backend 를 직접 치므로 공개 주소는 `http://testserver` 다 — 배포에서는 강의실 앱이 같은
경로를 강의실 도메인으로 넘긴다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.core.cache import caches
from django.test import override_settings
from django.utils import timezone

from core.models import ClockOverride
from tests.mcp_output_schema import assert_matches_output_schema
from tests.classroom_scenarios import (
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    internal_headers,
    join_class,
    login,
)

ORIGIN = "http://testserver"
RESOURCE = f"{ORIGIN}/mcp"
REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"

PRM_URL = "/api/classroom/oauth/metadata/protected-resource"
ASM_URL = "/api/classroom/oauth/metadata/authorization-server"
REGISTER_URL = "/api/classroom/oauth/register"
AUTHORIZE_URL = "/api/classroom/oauth/authorize"
TOKEN_URL = "/api/classroom/oauth/token"
REVOKE_URL = "/api/classroom/oauth/revoke"
MCP_URL = "/api/classroom/mcp"
APPS_URL = "/api/classroom/connected-apps"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


def _set_clock(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _register(client, **overrides) -> dict:
    body = {
        "client_name": "Claude",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        **overrides,
    }
    response = client.post(REGISTER_URL, data=json.dumps(body), content_type="application/json")
    assert response.status_code == 201, response.content
    return response.json()


def _authorize_params(client_id: str, challenge: str) -> dict:
    return {
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz",
        "scope": "classroom",
        "resource": RESOURCE,
    }


def _approve(client, access: str, client_id: str, challenge: str, *, approve: bool = True) -> dict:
    response = client.post(
        AUTHORIZE_URL,
        data={**_authorize_params(client_id, challenge), "approve": approve},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content
    location = urlsplit(response.json()["redirect_to"])
    assert f"{location.scheme}://{location.netloc}{location.path}" == REDIRECT_URI
    return {key: values[0] for key, values in parse_qs(location.query).items()}


def _token(client, form: dict, **extra):
    return client.post(
        TOKEN_URL,
        data=urlencode(form),
        content_type="application/x-www-form-urlencoded",
        **extra,
    )


def _connect(client, access: str) -> dict:
    """등록 → 허락 → 코드 교환까지. 토큰 응답에 client_id 를 얹어 돌려준다."""

    registered = _register(client)
    verifier, challenge = _pkce()
    query = _approve(client, access, registered["client_id"], challenge)
    response = _token(
        client,
        {
            "grant_type": "authorization_code",
            "code": query["code"],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": registered["client_id"],
            "resource": RESOURCE,
        },
    )
    assert response.status_code == 200, response.content
    return {**response.json(), "client_id": registered["client_id"]}


def _rpc(client, token: str | None, method: str, params: dict | None = None, *, request_id=1, headers=None):
    message: dict = {"jsonrpc": "2.0", "method": method}
    if request_id is not None:
        message["id"] = request_id
    if params is not None:
        message["params"] = params
    extra = {"HTTP_ACCEPT": "application/json, text/event-stream", **(headers or {})}
    if token:
        extra["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    response = client.post(MCP_URL, data=json.dumps(message), content_type="application/json", **extra)
    # 성공한 도구 호출은 저절로 자기 outputSchema 와 맞춰 본다(#579) — MCP 시험 전부가 이 길로 부른다.
    if method == "tools/call" and response.status_code == 200 and isinstance(params, dict):
        result = response.json().get("result") or {}
        if result.get("isError") is False and "structuredContent" in result:
            assert_matches_output_schema(params["name"], result["structuredContent"])
    return response


def _call_list_my_classes(client, token: str):
    return _rpc(client, token, "tools/call", {"name": "list_my_classes", "arguments": {}})


# --- 끝에서 끝까지 ---------------------------------------------------------------


def test_connector_discovers_registers_gets_consent_and_lists_my_classes(client, db):
    instructor = login(client, uid="mcp-teacher")
    other = login(client, uid="mcp-other-teacher")
    participant = login(client, uid="mcp-participant")
    kept = create_class(client, instructor["access"], name="웹 스터디", with_key=False)
    archived = create_class(client, instructor["access"], name="지난 학기", with_key=False)
    create_class(client, other["access"], name="남의 클래스", with_key=False)
    create_open_problem(client, instructor["access"], kept)
    join_class(client, participant["access"], kept, instructor_access=instructor["access"], display_name="참여자 하나")
    archive_class(client, instructor["access"], archived)

    # 토큰 없이 부르면 어디서 허락받을지 알려준다(RFC 9728 §5.1).
    unauthorized = _rpc(client, None, "initialize", {"protocolVersion": "2025-06-18"})
    assert unauthorized.status_code == 401
    challenge_header = unauthorized["WWW-Authenticate"]
    assert challenge_header.startswith("Bearer ")
    assert f'resource_metadata="{ORIGIN}/.well-known/oauth-protected-resource/mcp"' in challenge_header

    prm = client.get(PRM_URL).json()
    assert prm["resource"] == RESOURCE
    assert prm["authorization_servers"] == [ORIGIN]
    asm = client.get(ASM_URL).json()
    assert asm["issuer"] == ORIGIN
    assert asm["code_challenge_methods_supported"] == ["S256"]
    assert asm["registration_endpoint"] == f"{ORIGIN}/oauth/register"
    assert asm["authorization_endpoint"] == f"{ORIGIN}/oauth/authorize"

    registered = _register(client)
    verifier, challenge = _pkce()

    preview = client.get(
        AUTHORIZE_URL,
        _authorize_params(registered["client_id"], challenge),
        **auth_header(instructor["access"]),
    )
    assert preview.status_code == 200, preview.content
    assert preview.json() == {"client_name": "Claude", "redirect_host": "claude.ai"}

    query = _approve(client, instructor["access"], registered["client_id"], challenge)
    assert query["state"] == "xyz"
    assert query["iss"] == ORIGIN

    tokens = _token(
        client,
        {
            "grant_type": "authorization_code",
            "code": query["code"],
            "redirect_uri": REDIRECT_URI,
            "code_verifier": verifier,
            "client_id": registered["client_id"],
            "resource": RESOURCE,
        },
    )
    assert tokens.status_code == 200, tokens.content
    body = tokens.json()
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["refresh_token"]
    access = body["access_token"]

    init = _rpc(client, access, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {}})
    assert init.status_code == 200
    assert init.json()["result"]["protocolVersion"] == "2025-06-18"
    assert "Mcp-Session-Id" not in init
    assert _rpc(client, access, "notifications/initialized", request_id=None).status_code == 202

    tools = _rpc(client, access, "tools/list").json()["result"]["tools"]
    listed = {tool["name"]: tool for tool in tools}
    assert listed["list_my_classes"]["annotations"]["readOnlyHint"] is True

    called = _call_list_my_classes(client, access)
    assert called.status_code == 200
    result = called.json()["result"]
    assert result["isError"] is False
    rows = result["structuredContent"]["classes"]
    # 남의 클래스는 보이지 않고, 화면의 「내 클래스」처럼 최근에 만든 것이 먼저다.
    assert [row["name"] for row in rows] == ["지난 학기", "웹 스터디"]
    classes = {row["name"]: row for row in rows}
    assert classes["웹 스터디"]["participant_count"] == 1
    assert classes["웹 스터디"]["problem_counts"] == {"open": 1, "draft": 0, "hidden": 0}
    assert classes["웹 스터디"]["archived"] is False
    assert classes["지난 학기"]["archived"] is True
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    assert "@" not in called.content.decode("utf-8")  # 이메일이 실리지 않는다

    listing = client.get(APPS_URL, **auth_header(instructor["access"])).json()
    assert [row["name"] for row in listing] == ["Claude"]
    assert listing[0]["last_used_at"] is not None
    assert client.get(APPS_URL, **auth_header(other["access"])).json() == []


def test_modern_clients_send_meta_and_mirrored_headers(client, db):
    instructor = login(client, uid="mcp-modern")
    create_class(client, instructor["access"], name="모던", with_key=False)
    access = _connect(client, instructor["access"])["access_token"]
    meta = {"_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28"}}
    headers = {"HTTP_MCP_PROTOCOL_VERSION": "2026-07-28", "HTTP_MCP_METHOD": "tools/call", "HTTP_MCP_NAME": "list_my_classes"}

    ok = _rpc(client, access, "tools/call", {"name": "list_my_classes", "arguments": {}, **meta}, headers=headers)
    assert ok.status_code == 200
    assert ok.json()["result"]["resultType"] == "complete"

    mismatch = _rpc(
        client,
        access,
        "tools/call",
        {"name": "list_my_classes", "arguments": {}, **meta},
        headers={**headers, "HTTP_MCP_NAME": "other_tool"},
    )
    assert mismatch.status_code == 400
    assert mismatch.json()["error"]["code"] == -32020

    unsupported = _rpc(
        client,
        access,
        "server/discover",
        {"_meta": {"io.modelcontextprotocol/protocolVersion": "1900-01-01"}},
        headers={"HTTP_MCP_PROTOCOL_VERSION": "1900-01-01", "HTTP_MCP_METHOD": "server/discover"},
    )
    assert unsupported.status_code == 400
    assert unsupported.json()["error"]["code"] == -32022
    assert "2026-07-28" in unsupported.json()["error"]["data"]["supported"]


def test_get_on_the_mcp_endpoint_is_not_allowed(client, db):
    assert client.get(MCP_URL).status_code == 405


# --- 토큰 ---------------------------------------------------------------------


def test_unknown_or_expired_access_token_is_rejected(client, db):
    instructor = login(client, uid="mcp-expiry")
    access = _connect(client, instructor["access"])["access_token"]

    bogus = _call_list_my_classes(client, "cmt_at_not-a-real-token")
    assert bogus.status_code == 401
    assert 'error="invalid_token"' in bogus["WWW-Authenticate"]

    _set_clock(timezone.now() + timedelta(hours=1, seconds=1))
    assert _call_list_my_classes(client, access).status_code == 401


def test_refresh_token_rotates_and_the_old_one_stops_working(client, db):
    instructor = login(client, uid="mcp-refresh")
    connected = _connect(client, instructor["access"])

    rotated = _token(
        client,
        {"grant_type": "refresh_token", "refresh_token": connected["refresh_token"], "client_id": connected["client_id"]},
    )
    assert rotated.status_code == 200, rotated.content
    assert rotated.json()["refresh_token"] != connected["refresh_token"]
    assert _call_list_my_classes(client, rotated.json()["access_token"]).status_code == 200

    reused = _token(
        client,
        {"grant_type": "refresh_token", "refresh_token": connected["refresh_token"], "client_id": connected["client_id"]},
    )
    assert reused.status_code == 400
    assert reused.json()["error"] == "invalid_grant"


def test_code_needs_the_right_verifier_and_works_only_once(client, db):
    instructor = login(client, uid="mcp-pkce")
    registered = _register(client)
    verifier, challenge = _pkce()
    code = _approve(client, instructor["access"], registered["client_id"], challenge)["code"]
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "client_id": registered["client_id"],
    }

    wrong = _token(client, {**form, "code_verifier": secrets.token_urlsafe(48)})
    assert wrong.status_code == 400
    assert wrong.json()["error"] == "invalid_grant"

    assert _token(client, {**form, "code_verifier": verifier}).status_code == 200
    again = _token(client, {**form, "code_verifier": verifier})
    assert again.status_code == 400
    assert again.json()["error"] == "invalid_grant"


def test_token_for_another_resource_is_refused(client, db):
    instructor = login(client, uid="mcp-resource")
    registered = _register(client)
    _verifier, challenge = _pkce()
    response = client.post(
        AUTHORIZE_URL,
        data={**_authorize_params(registered["client_id"], challenge), "resource": "https://evil.example/mcp", "approve": True},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert response.status_code == 400


def test_confidential_client_must_present_its_secret(client, db):
    instructor = login(client, uid="mcp-secret")
    registered = _register(client, token_endpoint_auth_method="client_secret_basic")
    assert registered["client_secret"]
    verifier, challenge = _pkce()
    code = _approve(client, instructor["access"], registered["client_id"], challenge)["code"]
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI, "code_verifier": verifier}

    no_secret = _token(client, {**form, "client_id": registered["client_id"]})
    assert no_secret.status_code == 401

    basic = base64.b64encode(f"{registered['client_id']}:{registered['client_secret']}".encode()).decode()
    assert _token(client, form, HTTP_AUTHORIZATION=f"Basic {basic}").status_code == 200


def test_registration_refuses_plain_http_redirects_to_other_hosts(client, db):
    response = client.post(
        REGISTER_URL,
        data=json.dumps({"redirect_uris": ["http://evil.example/callback"]}),
        content_type="application/json",
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_consent_needs_a_login(client, db):
    registered = _register(client)
    _verifier, challenge = _pkce()
    assert client.get(AUTHORIZE_URL, _authorize_params(registered["client_id"], challenge)).status_code == 401


def test_denying_sends_the_app_back_with_access_denied(client, db):
    instructor = login(client, uid="mcp-deny")
    registered = _register(client)
    _verifier, challenge = _pkce()
    query = _approve(client, instructor["access"], registered["client_id"], challenge, approve=False)
    assert query["error"] == "access_denied"
    assert "code" not in query
    assert client.get(APPS_URL, **auth_header(instructor["access"])).json() == []


# --- 끊기·만료·회수 ---------------------------------------------------------------


def test_disconnecting_rejects_the_apps_tokens_at_once(client, db):
    instructor = login(client, uid="mcp-disconnect")
    stranger = login(client, uid="mcp-stranger")
    connected = _connect(client, instructor["access"])
    app_id = client.get(APPS_URL, **auth_header(instructor["access"])).json()[0]["id"]

    assert client.delete(f"{APPS_URL}/{app_id}", **auth_header(stranger["access"])).status_code == 404
    assert client.delete(f"{APPS_URL}/{app_id}", **auth_header(instructor["access"])).status_code == 204

    assert _call_list_my_classes(client, connected["access_token"]).status_code == 401
    refreshed = _token(
        client,
        {"grant_type": "refresh_token", "refresh_token": connected["refresh_token"], "client_id": connected["client_id"]},
    )
    assert refreshed.status_code == 400
    assert client.get(APPS_URL, **auth_header(instructor["access"])).json() == []


def test_revocation_endpoint_retires_a_token(client, db):
    instructor = login(client, uid="mcp-revoke")
    connected = _connect(client, instructor["access"])
    response = client.post(
        REVOKE_URL,
        data=urlencode({"token": connected["access_token"], "client_id": connected["client_id"]}),
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200
    assert _call_list_my_classes(client, connected["access_token"]).status_code == 401


def test_a_connection_unused_for_ninety_days_expires(client, db):
    instructor = login(client, uid="mcp-unused")
    connected = _connect(client, instructor["access"])
    scan_url = "/api/internal/scans/classroom-connected-app-expiry"

    _set_clock(timezone.now() + timedelta(days=89))
    assert client.post(scan_url, **internal_headers()).json()["count"] == 0

    _set_clock(timezone.now() + timedelta(days=91))
    assert client.post(scan_url, **internal_headers()).json()["count"] == 1
    assert client.get(APPS_URL, **auth_header(instructor["access"])).json() == []
    refreshed = _token(
        client,
        {"grant_type": "refresh_token", "refresh_token": connected["refresh_token"], "client_id": connected["client_id"]},
    )
    assert refreshed.status_code == 400


def test_withdrawing_cuts_the_connection(client, db):
    instructor = login(client, uid="mcp-withdraw")
    connected = _connect(client, instructor["access"])

    withdrawn = client.post("/api/accounts/withdrawal", content_type="application/json", **auth_header(instructor["access"]))
    assert withdrawn.status_code == 200, withdrawn.content

    refreshed = _token(
        client,
        {"grant_type": "refresh_token", "refresh_token": connected["refresh_token"], "client_id": connected["client_id"]},
    )
    assert refreshed.status_code == 400
    assert _call_list_my_classes(client, connected["access_token"]).status_code == 401


# --- 호출 상한 -----------------------------------------------------------------


@override_settings(CLASSROOM_MCP_CALLS_PER_MINUTE=3)
def test_calls_over_the_per_minute_limit_wait_for_the_next_minute(client, db):
    instructor = login(client, uid="mcp-rate")
    access = _connect(client, instructor["access"])["access_token"]
    start = timezone.now().replace(second=5, microsecond=0) + timedelta(minutes=1)
    _set_clock(start)

    for _ in range(3):
        assert _call_list_my_classes(client, access).status_code == 200
    limited = _call_list_my_classes(client, access)
    assert limited.status_code == 429
    error = limited.json()["error"]
    assert error["code"] == -32000
    assert "초 뒤에 다시" in error["message"]
    assert limited["Retry-After"] == "55"

    _set_clock(start + timedelta(minutes=1))
    assert _call_list_my_classes(client, access).status_code == 200
