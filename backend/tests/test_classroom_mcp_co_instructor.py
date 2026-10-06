"""공동 강사의 연결된 앱 — 공동 강사인 클래스에 닿고, 소유자 전용 도구만 거절된다
(#566, spec #558, ADR-0052·ADR-0055).

연결된 앱은 토큰 주인이 강사인 클래스 전부에 닿고, 화면에서 공동 강사가 하는 일을 똑같이
한다. 소유자 전용 도구(`OWNER_ONLY_MCP_TOOLS` — 클래스 삭제, 클래스 설정의 예산·소유자 강사
이름 칸)는 소유자일 때만이고, 공동 강사가 부르면 화면과 같은 문장(`OWNER_ONLY_MESSAGE`)으로
거절된다. 공동 강사 초대·내보내기·이전 도구는 없다.

`/mcp` 에 JSON-RPC 를 보내고 결과는 화면 API 로 본다(`tests/test_classroom_mcp_*` 와 같은 결).
"""

from __future__ import annotations

import pytest
from django.core.cache import caches

from classroom.instructor_scope import OWNER_ONLY_MESSAGE
from tests.classroom_scenarios import (
    add_co_instructor,
    create_class,
    get_class,
    list_problems,
    list_taught_classes,
    login,
)
from tests.test_classroom_connected_apps import _connect, _rpc


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


def _call(client, token: str, name: str, arguments: dict) -> dict:
    response = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.content
    return response.json()["result"]


def _ok(client, token: str, name: str, arguments: dict) -> dict:
    result = _call(client, token, name, arguments)
    assert result["isError"] is False, result
    return result["structuredContent"]


def _refused(client, token: str, name: str, arguments: dict) -> str:
    result = _call(client, token, name, arguments)
    assert result["isError"] is True, result
    return result["content"][0]["text"]


def _co_instructors_app(client):
    """소유자의 클래스 하나에 공동 강사로 들어간 사람이 앱을 연결한다. 그 사람이 소유한 클래스도 하나 있다."""

    owner = login(client, uid="mcp-owner")
    co = login(client, uid="mcp-co")
    shared = create_class(client, owner["access"], name="함께 가르치는 반", with_key=False)
    add_co_instructor(client, owner["access"], shared, co["access"], display_name="보조 강사")
    own = create_class(client, co["access"], name="내 반", with_key=False)
    token = _connect(client, co["access"])["access_token"]
    return owner, co, shared, own, token


def test_the_app_lists_the_co_taught_class_with_its_role_like_the_screen(client, db):
    _, co, shared, own, token = _co_instructors_app(client)

    listed = _ok(client, token, "list_my_classes", {})["classes"]

    assert {(c["id"], c["role"]) for c in listed} == {(shared, "co_instructor"), (own, "owner")}
    assert {(c["id"], c["role"]) for c in listed} == {(c["id"], c["role"]) for c in list_taught_classes(client, co["access"])}
    assert _ok(client, token, "get_class", {"class_id": shared})["role"] == "co_instructor"


def test_the_app_makes_and_edits_problems_in_the_co_taught_class(client, db):
    owner, _, shared, _, token = _co_instructors_app(client)

    created = _ok(
        client,
        token,
        "create_problem",
        {"class_id": shared, "title": "두 수의 합", "submission_formats": ["source"]},
    )["problem"]
    _ok(client, token, "update_problem", {"class_id": shared, "problem_id": created["id"], "title": "세 수의 합"})

    assert [p["title"] for p in list_problems(client, owner["access"], shared)] == ["세 수의 합"]


def test_deleting_the_co_taught_class_is_refused_with_the_screens_sentence(client, db):
    owner, _, shared, _, token = _co_instructors_app(client)

    assert _refused(client, token, "delete_class", {"class_id": shared}) == OWNER_ONLY_MESSAGE

    assert get_class(client, owner["access"], shared)["name"] == "함께 가르치는 반"


def test_class_settings_open_to_the_co_instructor_except_the_budget_and_the_owners_name(client, db):
    owner, _, shared, _, token = _co_instructors_app(client)

    assert _refused(client, token, "update_class_settings", {"class_id": shared, "token_budget": 1000}) == OWNER_ONLY_MESSAGE
    # 강사 이름 칸은 소유자의 이름이다 — 공동 강사의 앱이 보내면 남의 이름을 바꾸게 되므로 거절된다(#565).
    assert (
        _refused(client, token, "update_class_settings", {"class_id": shared, "instructor_display_name": "보조 강사"})
        == OWNER_ONLY_MESSAGE
    )
    _ok(client, token, "update_class_settings", {"class_id": shared, "name": "함께 가르치는 반 2기"})

    screen = get_class(client, owner["access"], shared)
    assert (screen["name"], screen["token_budget"], screen["instructor_display_name"]) == ("함께 가르치는 반 2기", None, "강사")


def test_the_app_has_no_tools_for_co_instructors_or_ownership(client, db):
    """공동 강사 초대·내보내기·소유권 이전은 화면에서만 한다(ADR-0055)."""

    _, _, _, _, token = _co_instructors_app(client)
    names = {tool["name"] for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}

    assert not {n for n in names if "instructor" in n or "invite" in n or "owner" in n or "transfer" in n}
