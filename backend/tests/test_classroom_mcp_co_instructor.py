"""공동 강사의 연결된 앱 — 공동 강사인 클래스에 닿고, 소유자 전용 도구만 거절된다
(#566, spec #558, ADR-0052·ADR-0055).

연결된 앱은 토큰 주인이 강사인 클래스 전부에 닿고, 화면에서 공동 강사가 하는 일을 똑같이
한다. 소유자 전용 도구(`OWNER_ONLY_MCP_TOOLS` — 클래스 삭제, 클래스 설정의 예산·소유자 강사
이름 칸)는 소유자일 때만이고, 공동 강사가 부르면 화면과 같은 문장(`OWNER_ONLY_MESSAGE`)으로
거절된다. 공동 강사 초대·내보내기·이전 도구는 없다.

강사 이름은 따로 연다(#576) — `rename_my_instructor_name` 은 부른 사람 **자기** 강사 이름만
바꾼다(화면의 `PATCH .../instructors/me` 와 같은 `co_instructors.rename_myself`). 소유자든 공동
강사든 같은 도구이고, 다른 강사를 가리킬 인자가 없다.

`/mcp` 에 JSON-RPC 를 보내고 결과는 화면 API 로 본다(`tests/test_classroom_mcp_*` 와 같은 결).
"""

from __future__ import annotations

import pytest
from django.core.cache import caches

from classroom.instructor_scope import OWNER_ONLY_MESSAGE
from classroom.models import ConnectedAppWrite
from tests.classroom_scenarios import (
    add_co_instructor,
    archive_class,
    create_class,
    get_class,
    join,
    join_code,
    join_preview,
    list_instructors,
    list_problems,
    list_taught_classes,
    login,
    rename_my_instructor_name,
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

    # 자기 강사 이름 바꾸기(#576)만 강사에 닿는다 — 남을 들이거나 내보내거나 넘기는 도구는 없다.
    assert {n for n in names if "instructor" in n or "invite" in n or "owner" in n or "transfer" in n} == {
        "rename_my_instructor_name"
    }


# --- 내 강사 이름 (#576) ----------------------------------------------------------------

_RENAME = "rename_my_instructor_name"


def _names(client, access: str, class_id: int) -> list[tuple[str, str]]:
    return [(row["role"], row["display_name"]) for row in list_instructors(client, access, class_id)]


def _records() -> list[tuple[str, int | None]]:
    return list(ConnectedAppWrite.objects.order_by("id").values_list("tool", "target_class_id"))


def test_the_rename_tool_is_a_reversible_write_with_no_place_to_name_another_instructor(client, db):
    _, _, _, _, token = _co_instructors_app(client)
    tools = {tool["name"]: tool for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}

    tool = tools[_RENAME]
    assert (tool["annotations"]["readOnlyHint"], tool["annotations"]["destructiveHint"]) == (False, False)
    assert tool["annotations"]["idempotentHint"] is True
    assert set(tool["inputSchema"]["properties"]) == {"class_id", "display_name"}
    assert tool["inputSchema"]["additionalProperties"] is False
    # 클래스 설정의 강사 이름 칸은 소유자의 이름이다 — 그 설명이 이 도구를 가리킨다.
    assert _RENAME in tools["update_class_settings"]["description"]


def test_a_co_instructors_app_renames_only_its_instructor_like_the_screen(client, db):
    owner, co, shared, _, token = _co_instructors_app(client)
    other = login(client, uid="mcp-other-co")
    add_co_instructor(client, owner["access"], shared, other["access"], display_name="조교")

    result = _ok(client, token, _RENAME, {"class_id": shared, "display_name": "박조교"})

    assert (result["role"], result["display_name"]) == ("co_instructor", "박조교")
    assert _names(client, owner["access"], shared) == [
        ("owner", "강사"),
        ("co_instructor", "박조교"),
        ("co_instructor", "조교"),
    ]
    assert join_preview(client, join_code(client, owner["access"], shared))["instructor_display_names"] == [
        "강사",
        "박조교",
        "조교",
    ]
    assert get_class(client, co["access"], shared)["my_instructor_display_name"] == "박조교"
    assert _records() == [(_RENAME, shared)]


def test_an_owners_app_renames_the_owners_instructor_name(client, db):
    owner, co, shared, _, _ = _co_instructors_app(client)
    token = _connect(client, owner["access"])["access_token"]

    result = _ok(client, token, _RENAME, {"class_id": shared, "display_name": "김강사"})

    assert (result["role"], result["display_name"]) == ("owner", "김강사")
    assert _names(client, co["access"], shared) == [("owner", "김강사"), ("co_instructor", "보조 강사")]
    assert get_class(client, co["access"], shared)["instructor_display_name"] == "김강사"


def test_a_class_the_app_does_not_teach_is_not_there_like_the_screen(client, db):
    _, co, _, _, token = _co_instructors_app(client)
    stranger = login(client, uid="mcp-stranger")
    theirs = create_class(client, stranger["access"], name="남의 반", with_key=False)
    joined = create_class(client, stranger["access"], name="수강하는 반", with_key=False)
    join(client, co["access"], join_code(client, stranger["access"], joined))

    for class_id in (theirs, joined):
        screen = rename_my_instructor_name(client, co["access"], class_id, "강사 행세")
        assert screen.status_code == 404
        assert _refused(client, token, _RENAME, {"class_id": class_id, "display_name": "강사 행세"}) == screen.json()["detail"]
        assert _names(client, stranger["access"], class_id) == [("owner", "강사")]
    assert not ConnectedAppWrite.objects.exists()


def test_renaming_works_in_an_archived_class_and_refuses_names_like_the_screen(client, db):
    owner, co, shared, _, token = _co_instructors_app(client)
    archive_class(client, owner["access"], shared)

    _ok(client, token, _RENAME, {"class_id": shared, "display_name": "지난 기수 조교"})
    assert _names(client, owner["access"], shared)[1] == ("co_instructor", "지난 기수 조교")

    for banned in ("운영자", "씨발"):
        screen = rename_my_instructor_name(client, co["access"], shared, banned)
        assert screen.status_code == 422
        assert _refused(client, token, _RENAME, {"class_id": shared, "display_name": banned}) == screen.json()["detail"]
    assert _refused(client, token, _RENAME, {"class_id": shared, "display_name": ""}).startswith("display_name")
    assert _names(client, owner["access"], shared)[1] == ("co_instructor", "지난 기수 조교")
    assert _records() == [(_RENAME, shared)]
