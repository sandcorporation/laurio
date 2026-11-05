"""공모전 MCP — OAuth 허락부터 무료 공모전 도구까지 (#870, ADR-0070, CONTEXT.md 「연결된 앱」·「보관」).

강의실 MCP 시험(`test_classroom_connected_apps.py`)과 같은 길을 공모전 자원으로 걷는다:
메타데이터 → 동적 등록 → (개최 권한이 있는 사용자 로그인으로) 동의 → 코드 + PKCE → 토큰 →
`/api/contests/mcp`. 배포에서는 공개 앱(frontend)이 `/mcp` 를 이 경로로 넘긴다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import secrets
from datetime import timedelta
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import caches
from django.utils import timezone

from contests.mcp import TOOLS as CONTEST_TOOLS
from contests.models import Contest, ContestConnectedAppWrite
from core.contest_catalog import contest_catalog
from tests.mcp_output_schema import assert_matches_output_schema
from tests.test_free_contest_hosting import (  # noqa: F401 — 픽스처 재사용
    CONTESTS_URL,
    _auth_header,
    _free_brief,
    _grant,
    _hosted_user,
    _operator_client,
    category,
    landing_type,
)

pytestmark = pytest.mark.django_db

ORIGIN = "http://testserver"
RESOURCE = f"{ORIGIN}/mcp"
REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"

PRM_URL = "/api/contests/oauth/metadata/protected-resource"
ASM_URL = "/api/contests/oauth/metadata/authorization-server"
REGISTER_URL = "/api/contests/oauth/register"
AUTHORIZE_URL = "/api/contests/oauth/authorize"
TOKEN_URL = "/api/contests/oauth/token"
MCP_URL = "/api/contests/mcp"
APPS_URL = "/api/contests/connected-apps"
PERMISSIONS_URL = "/api/operator/hosting-permissions"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


# --- 도우미 ---------------------------------------------------------------------


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return verifier, base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _register(client) -> dict:
    body = {
        "client_name": "Claude",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
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
        "scope": "contests",
        "resource": RESOURCE,
    }


def _connect(client, access: str) -> dict:
    registered = _register(client)
    verifier, challenge = _pkce()
    decided = client.post(
        AUTHORIZE_URL,
        data={**_authorize_params(registered["client_id"], challenge), "approve": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert decided.status_code == 200, decided.content
    location = urlsplit(decided.json()["redirect_to"])
    query = {key: values[0] for key, values in parse_qs(location.query).items()}
    response = client.post(
        TOKEN_URL,
        data=urlencode(
            {
                "grant_type": "authorization_code",
                "code": query["code"],
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
                "client_id": registered["client_id"],
                "resource": RESOURCE,
            }
        ),
        content_type="application/x-www-form-urlencoded",
    )
    assert response.status_code == 200, response.content
    return {**response.json(), "client_id": registered["client_id"]}


def _rpc(client, token: str | None, method: str, params: dict | None = None, *, url: str = MCP_URL):
    message: dict = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        message["params"] = params
    extra = {"HTTP_ACCEPT": "application/json, text/event-stream"}
    if token:
        extra["HTTP_AUTHORIZATION"] = f"Bearer {token}"
    response = client.post(url, data=json.dumps(message), content_type="application/json", **extra)
    if method == "tools/call" and response.status_code == 200 and url == MCP_URL:
        result = response.json().get("result") or {}
        if result.get("isError") is False and "structuredContent" in result:
            assert_matches_output_schema(params["name"], result["structuredContent"], CONTEST_TOOLS)
    return response


def _call(client, token: str, name: str, **arguments) -> dict:
    response = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.content
    return response.json()["result"]


def _ok(client, token: str, name: str, **arguments) -> dict:
    result = _call(client, token, name, **arguments)
    assert result["isError"] is False, result
    return result["structuredContent"]


def _refused(client, token: str, name: str, **arguments) -> str:
    result = _call(client, token, name, **arguments)
    assert result["isError"] is True, result
    return result["content"][0]["text"]


def _confirmed(client, token: str, name: str, **arguments) -> dict:
    """두 단계 도구 — 미리보기를 받고, 같은 인자에 확인 표를 더해 다시 부른다."""

    preview = _ok(client, token, name, **arguments)
    assert preview["status"] == "needs_confirmation", preview
    return _ok(client, token, name, **arguments, confirmation=preview["confirmation"])


def _host(client, uid: str) -> dict:
    user = _hosted_user(client, uid)
    _grant(_operator_client(f"root-{uid}"), user["user_id"])
    return user


def _operator(client, uid: str) -> dict:
    """운영자(`is_staff`)도 개최 권한 검사를 똑같이 받는다 — 권한을 켜 둔 운영자."""

    user = _host(client, uid)
    get_user_model().objects.filter(pk=user["user_id"]).update(is_staff=True)
    return user


def _web_free_contest(client, user, category, landing_type, *, title="웹 무료 공모전", publish=True) -> dict:
    payload = _free_brief(category, landing_type, title=title)
    created = client.post(f"{CONTESTS_URL}/free", data=payload, content_type="application/json", **_auth_header(user["access"]))
    assert created.status_code == 200, created.content
    contest = created.json()
    if publish:
        published = client.post(f"{CONTESTS_URL}/{contest['id']}/publish", content_type="application/json", **_auth_header(user["access"]))
        assert published.status_code == 200, published.content
    return contest


def _brief(category, landing_type, **overrides) -> dict:
    return {
        "title": "MCP 로 만든 공모전",
        "category_id": category.id,
        "deliverable_type_ids": [landing_type.id],
        "description": "도구로 만든 무료 공모전",
        "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
        "requirements": [{"text": "할 일을 추가할 수 있다", "grade": "required"}],
        **overrides,
    }


# --- 디스커버리 ------------------------------------------------------------------


def test_discovery_points_the_connector_at_the_contests_resource(client):
    unauthorized = _rpc(client, None, "initialize", {"protocolVersion": "2025-06-18"})
    assert unauthorized.status_code == 401
    assert PRM_URL.rsplit("/", 1)[-1] in unauthorized["WWW-Authenticate"] or "resource_metadata" in unauthorized["WWW-Authenticate"]

    prm = client.get(PRM_URL).json()
    assert prm["resource"] == RESOURCE
    assert prm["scopes_supported"] == ["contests"]
    asm = client.get(ASM_URL).json()
    assert asm["scopes_supported"] == ["contests"]
    assert asm["code_challenge_methods_supported"] == ["S256"]


# --- 입장: 개최 권한 --------------------------------------------------------------


def test_user_without_hosting_permission_cannot_consent(client):
    plain = _hosted_user(client, "mcp-plain")
    registered = _register(client)
    _, challenge = _pkce()

    preview = client.get(AUTHORIZE_URL, _authorize_params(registered["client_id"], challenge), **_auth_header(plain["access"]))
    assert preview.status_code == 403

    decided = client.post(
        AUTHORIZE_URL,
        data={**_authorize_params(registered["client_id"], challenge), "approve": True},
        content_type="application/json",
        **_auth_header(plain["access"]),
    )
    assert decided.status_code == 403


def test_revoking_hosting_permission_refuses_every_call(client):
    host = _host(client, "mcp-revoked")
    token = _connect(client, host["access"])["access_token"]
    assert _rpc(client, token, "tools/list").status_code == 200

    _grant(_operator_client("root-revoker"), host["user_id"], granted=False, reason="회수")

    for method, params in [("tools/list", None), ("tools/call", {"name": "list_free_contests", "arguments": {}})]:
        response = _rpc(client, token, method, params)
        assert response.status_code == 403
        assert "개최 권한" in response.json()["error"]["message"]


def test_a_classroom_token_does_not_open_the_contests_resource(client):
    """범위 교차 — 강의실 허락(scope classroom)으로 받은 토큰은 공모전 MCP 에서 401."""

    from tests.test_classroom_connected_apps import _connect as classroom_connect

    host = _host(client, "mcp-cross-scope")
    classroom_token = classroom_connect(client, host["access"])["access_token"]
    assert _rpc(client, classroom_token, "tools/list").status_code == 401

    contests_token = _connect(client, host["access"])["access_token"]
    assert _rpc(client, contests_token, "tools/list", url="/api/classroom/mcp").status_code == 401


# --- 범위: 내 것, 운영자는 전부, 무료만 -------------------------------------------------


def test_host_sees_only_own_free_contests_and_others_are_404(client, category, landing_type):
    me = _host(client, "mcp-me")
    other = _host(client, "mcp-other")
    mine = _web_free_contest(client, me, category, landing_type, title="내 것")
    theirs = _web_free_contest(client, other, category, landing_type, title="남의 것")
    token = _connect(client, me["access"])["access_token"]

    listed = _ok(client, token, "list_free_contests")["contests"]
    assert [c["id"] for c in listed] == [mine["id"]]
    assert listed[0]["mine"] is True

    for name, extra in [
        ("get_free_contest", {}),
        ("list_submissions", {}),
        ("update_free_contest", {"title": "가로채기"}),
        ("add_requirement", {"text": "몰래", "grade": "optional"}),
        ("close_free_contest_now", {}),
        ("archive_free_contest", {}),
    ]:
        assert "찾을 수 없습니다" in _refused(client, token, name, contest_id=theirs["id"], **extra)
    assert Contest.objects.get(pk=theirs["id"]).title == "남의 것"


def test_operator_handles_every_free_contest_but_creates_in_own_name(client, category, landing_type):
    host = _host(client, "mcp-host-of-op")
    hosted = _web_free_contest(client, host, category, landing_type, title="개최자의 것")
    operator = _operator(client, "mcp-dahye")
    token = _connect(client, operator["access"])["access_token"]

    listed = _ok(client, token, "list_free_contests")["contests"]
    assert {c["id"]: c["mine"] for c in listed} == {hosted["id"]: False}
    updated = _ok(client, token, "update_free_contest", contest_id=hosted["id"], description="운영자가 고침")
    assert updated["contest"]["description"] == "운영자가 고침"

    created = _ok(client, token, "create_free_contest", **_brief(category, landing_type))["contest"]
    assert created["mine"] is True
    assert Contest.objects.get(pk=created["id"]).sponsor.user_id == operator["user_id"]


def test_paid_contests_and_prizes_are_refused(client, category, landing_type):
    host = _host(client, "mcp-paid")
    verified = client.post(
        "/api/verification/verify",
        data={"verification_token": "사람|1990-01-01|mcp-paid-ci|mcp-paid-di"},
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert verified.status_code == 200, verified.content
    paid = client.post(
        CONTESTS_URL,
        data={
            "title": "유료 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [{"text": "할 일을 추가·완료할 수 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert paid.status_code == 200, paid.content
    paid_id = paid.json()["id"]
    token = _connect(client, host["access"])["access_token"]

    assert _ok(client, token, "list_free_contests")["contests"] == []
    assert "찾을 수 없습니다" in _refused(client, token, "get_free_contest", contest_id=paid_id)
    assert "찾을 수 없습니다" in _refused(client, token, "update_free_contest", contest_id=paid_id, title="바꾸기")
    assert "찾을 수 없습니다" in _refused(client, token, "publish_free_contest", contest_id=paid_id)

    assert "무료 공모전만" in _refused(client, token, "create_free_contest", **_brief(category, landing_type), prize=500_000)
    draft = _ok(client, token, "create_free_contest", **_brief(category, landing_type))["contest"]
    assert "무료 공모전만" in _refused(client, token, "update_free_contest", contest_id=draft["id"], is_free=False)
    assert "무료 공모전만" in _refused(client, token, "update_free_contest", contest_id=draft["id"], prize=1)
    assert Contest.objects.get(pk=draft["id"]).is_free is True


# --- 흐름: 만들기 → 고치기 → 공개 → 마감 → 보관 → 해제 ------------------------------------


def test_create_update_publish_close_archive_and_unarchive(client, category, landing_type):
    host = _host(client, "mcp-flow")
    token = _connect(client, host["access"])["access_token"]

    options = _ok(client, token, "list_contest_options")
    assert category.id in [c["id"] for c in options["categories"]]

    contest = _ok(client, token, "create_free_contest", **_brief(category, landing_type))["contest"]
    assert contest["status"] == "draft"
    contest_id = contest["id"]

    contest = _ok(client, token, "update_free_contest", contest_id=contest_id, title="고친 제목")["contest"]
    assert contest["title"] == "고친 제목"
    added = _ok(client, token, "add_requirement", contest_id=contest_id, text="완료 표시", grade="optional")["contest"]
    second = added["requirements"][-1]
    assert second["text"] == "완료 표시"
    changed = _ok(client, token, "update_requirement", contest_id=contest_id, requirement_id=second["id"], text="완료로 표시할 수 있다")
    assert changed["contest"]["requirements"][-1]["text"] == "완료로 표시할 수 있다"
    removed = _ok(client, token, "delete_requirement", contest_id=contest_id, requirement_id=second["id"])
    assert len(removed["contest"]["requirements"]) == 1

    assert _ok(client, token, "publish_free_contest", contest_id=contest_id)["contest"]["status"] == "published"
    assert client.get(f"{CONTESTS_URL}/{contest_id}").status_code == 200

    preview = _ok(client, token, "close_free_contest_now", contest_id=contest_id)
    assert preview["status"] == "needs_confirmation"
    assert Contest.objects.get(pk=contest_id).status == Contest.Status.PUBLISHED  # 미리보기는 바꾸지 않는다.
    closed = _ok(client, token, "close_free_contest_now", contest_id=contest_id, confirmation=preview["confirmation"])
    assert closed["contest"]["status"] == "closed"
    assert closed["contest"]["judging_ends_at"]
    assert "마감" in _refused(client, token, "update_free_contest", contest_id=contest_id, title="마감 뒤")

    archived = _confirmed(client, token, "archive_free_contest", contest_id=contest_id)
    assert archived["contest"]["archived"] is True
    assert _ok(client, token, "list_free_contests")["contests"] == []
    assert [c["id"] for c in _ok(client, token, "list_free_contests", archived="only")["contests"]] == [contest_id]

    unarchived = _confirmed(client, token, "unarchive_free_contest", contest_id=contest_id)
    assert unarchived["contest"]["archived"] is False

    tools = list(ContestConnectedAppWrite.objects.filter(target_contest_id=contest_id).order_by("id").values_list("tool", flat=True))
    assert tools == [
        "create_free_contest",
        "update_free_contest",
        "add_requirement",
        "update_requirement",
        "delete_requirement",
        "publish_free_contest",
        "close_free_contest_now",
        "archive_free_contest",
        "unarchive_free_contest",
    ]


def test_published_contest_with_submissions_cannot_be_archived_until_closed(client, category, landing_type):
    from tests.test_free_contest_award import _submit

    host = _host(client, "mcp-busy")
    contest = _web_free_contest(client, host, category, landing_type)
    dev = _hosted_user(client, "mcp-busy-dev")
    _submit(client, dev, contest["id"])
    token = _connect(client, host["access"])["access_token"]

    assert "마감한 뒤" in _refused(client, token, "archive_free_contest", contest_id=contest["id"])
    submissions = _ok(client, token, "list_submissions", contest_id=contest["id"])["submissions"]
    assert len(submissions) == 1
    assert set(submissions[0]) == {"id", "developer_display_name", "submitted_at", "awarded"}
    assert "@" not in submissions[0]["developer_display_name"]
    one = _ok(client, token, "get_submission", contest_id=contest["id"], submission_id=submissions[0]["id"])
    assert one["submission"]["id"] == submissions[0]["id"]


# --- 보관하면 공개 목록·상세·들여오기에서 빠진다 -------------------------------------------


def test_archived_contest_leaves_public_list_detail_and_classroom_import(client, category, landing_type):
    host = _host(client, "mcp-hide")
    payload = _free_brief(category, landing_type, title="숨길 공모전")
    payload["allows_classroom_import"] = True
    created = client.post(f"{CONTESTS_URL}/free", data=payload, content_type="application/json", **_auth_header(host["access"]))
    assert created.status_code == 200, created.content
    contest_id = created.json()["id"]
    assert client.post(f"{CONTESTS_URL}/{contest_id}/publish", content_type="application/json", **_auth_header(host["access"])).status_code == 200

    def public_ids() -> list[int]:
        body = client.get(CONTESTS_URL).json()
        rows = body["items"] if isinstance(body, dict) else body
        return [row["id"] for row in rows]

    assert contest_id in public_ids()
    assert contest_id in [c.contest_id for c in contest_catalog().list_importable()]

    token = _connect(client, host["access"])["access_token"]
    _confirmed(client, token, "archive_free_contest", contest_id=contest_id)

    assert contest_id not in public_ids()
    assert client.get(f"{CONTESTS_URL}/{contest_id}").status_code == 404
    assert contest_id not in [c.contest_id for c in contest_catalog().list_importable()]

    _confirmed(client, token, "unarchive_free_contest", contest_id=contest_id)
    assert contest_id in public_ids()
    assert client.get(f"{CONTESTS_URL}/{contest_id}").status_code == 200


# --- 연결 보기·끊기 ------------------------------------------------------------------


def test_host_lists_and_disconnects_contest_connections(client):
    host = _host(client, "mcp-apps")
    token = _connect(client, host["access"])["access_token"]

    listed = client.get(APPS_URL, **_auth_header(host["access"]))
    assert listed.status_code == 200, listed.content
    apps = listed.json()
    assert [app["name"] for app in apps] == ["Claude"]

    gone = client.delete(f"{APPS_URL}/{apps[0]['id']}", **_auth_header(host["access"]))
    assert gone.status_code == 204
    assert _rpc(client, token, "tools/list").status_code == 401
    assert client.get(APPS_URL, **_auth_header(host["access"])).json() == []
