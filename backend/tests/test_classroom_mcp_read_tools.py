"""연결된 앱의 읽기 도구 (#513, 부모 #511, ADR-0052·ADR-0040).

강사 화면의 API 와 MCP 도구를 **같은 HTTP 로** 나란히 부르고 값을 대조한다 — 두 표면이 같은
함수를 부른다는 것을 결과로 고정한다. 화면과 다른 것은 클래스 상세의 채점 연결 값 조각(키 가린 표시·호환 서버 주소)이다
(연결된 앱에는 「있는가」만 간다).
"""

from __future__ import annotations

import json

import pytest
from django.apps import apps
from django.core.cache import caches

from tests.classroom_scenarios import (
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    get_class,
    join_class,
    list_problems,
    login,
    patch_class,
    roster_grid,
    submit_repository,
)
from tests.test_classroom_connected_apps import _connect, _rpc

CLASSES_URL = "/api/classroom/classes"
READ_TOOLS = ["get_class", "list_problems", "get_problem", "list_participants", "get_roster_grid"]
#: 문제 목록이 화면의 문제 한 줄에서 그대로 옮겨 싣는 칸(#579) — 여기에 항목 수가 더해진다.
LIST_PROBLEM_KEYS = [
    "id",
    "title",
    "status",
    "order",
    "submission_formats",
    "scoring_model_rejected",
    "passed_count",
    "member_count",
    "pass_rate",
    "deletable",
    "available_transitions",
]


def tools_by_name(client, token: str) -> dict:
    return {tool["name"]: tool for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}
KEY = "sk-test-secret-key-9f3a"


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


def _call(client, token: str, name: str, **arguments):
    response = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.content
    return response.json()["result"]


def _structured(client, token: str, name: str, **arguments) -> dict:
    result = _call(client, token, name, **arguments)
    assert result["isError"] is False, result
    assert json.loads(result["content"][0]["text"]) == result["structuredContent"]
    return result["structuredContent"]


def _screen(client, access: str, path: str):
    response = client.get(f"{CLASSES_URL}/{path}", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def _a_class_with_everything(client):
    """키·예산·초안 문제·열린 문제·참여자 둘(하나는 시도)·내보낸 참여자까지 있는 클래스."""

    instructor = login(client, uid="mcp-read-teacher", email="teacher@school.example")
    class_id = create_class(client, instructor["access"], name="자료구조", key=KEY)
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"token_budget": 50000},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    opened = create_open_problem(
        client, instructor["access"], class_id, title="스택", optional_labels=["주석이 있다"]
    )
    draft = create_open_problem(client, instructor["access"], class_id, title="큐", open=False)
    first = login(client, uid="mcp-read-p1", email="first@student.example")
    second = login(client, uid="mcp-read-p2", email="second@student.example")
    join_class(client, first["access"], class_id, instructor_access=instructor["access"], display_name="김하나")
    join_class(client, second["access"], class_id, instructor_access=instructor["access"], display_name="이둘")
    submit_repository(client, first["access"], class_id, opened.id)
    members = _screen(client, instructor["access"], f"{class_id}/members")
    expelled_id = next(m["id"] for m in members if m["display_name"] == "이둘")
    expelled = client.post(
        f"{CLASSES_URL}/{class_id}/members/{expelled_id}/expel", **auth_header(instructor["access"])
    )
    assert expelled.status_code == 200, expelled.content
    return instructor, class_id, opened, draft


def test_read_tools_are_listed_as_read_only_with_korean_titles(client, db):
    instructor = login(client, uid="mcp-read-list")
    token = _connect(client, instructor["access"])["access_token"]

    tools = {tool["name"]: tool for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}

    assert set(READ_TOOLS) <= set(tools)
    titles = {name: tools[name]["title"] for name in READ_TOOLS}
    assert titles == {
        "get_class": "클래스 상세",
        "list_problems": "문제 목록",
        "get_problem": "문제 상세",
        "list_participants": "참여자 명단",
        "get_roster_grid": "명단 격자",
    }
    for name in READ_TOOLS:
        assert tools[name]["annotations"]["readOnlyHint"] is True
        assert tools[name]["annotations"]["destructiveHint"] is False
        assert "class_id" in tools[name]["inputSchema"]["required"]
    assert "학생" not in json.dumps([tools[name] for name in READ_TOOLS], ensure_ascii=False)


def test_each_read_tool_returns_what_the_screen_returns(client, db):
    instructor, class_id, opened, draft = _a_class_with_everything(client)
    access = instructor["access"]
    token = _connect(client, access)["access_token"]

    screen_class = get_class(client, access, class_id)
    assert screen_class["has_openai_key"] is True
    assert screen_class["openai_key_masked"]  # 화면에는 끝 네 자리가 보인다
    tool_class = _structured(client, token, "get_class", class_id=class_id)
    # 화면에 없는 칸은 예상 채점 비용 하나다(#591) — 화면은 따로 `scoring-cost` 로 읽는다.
    class_estimate = tool_class.pop("scoring_cost_estimate")
    # 채점 연결의 값 조각(키 끝 네 자리, 호환 서버 주소·인증 가림, #605)은 화면에만 있다.
    withheld = {"openai_key_masked", "scoring_server_url", "scoring_auth_masked"}
    assert tool_class == {k: v for k, v in screen_class.items() if k not in withheld}
    assert class_estimate["model"] == screen_class["default_model"]
    assert tool_class["token_budget"] == 50000

    # 목록은 문제마다 요약만 싣는다(#579) — 설명·체크리스트 원문은 get_problem 에서 읽는다.
    problems = _structured(client, token, "list_problems", class_id=class_id)["problems"]
    screen_problems = list_problems(client, access, class_id)
    assert problems == [
        {
            **{key: screen[key] for key in LIST_PROBLEM_KEYS},
            "checklist_item_count": len(screen["checklist_items"]),
        }
        for screen in screen_problems
    ]
    assert [p["status"] for p in problems] == ["open", "draft"]
    assert problems[0]["checklist_item_count"] == 2
    assert "get_problem" in tools_by_name(client, token)["list_problems"]["description"]

    for problem in (opened, draft):
        tool_problem = _structured(client, token, "get_problem", class_id=class_id, problem_id=problem.id)
        problem_estimate = tool_problem.pop("scoring_cost_estimate")
        assert tool_problem == _screen(client, access, f"{class_id}/problems/{problem.id}")
        assert problem_estimate["model"] == tool_problem["effective_model"]
    stack = _structured(client, token, "get_problem", class_id=class_id, problem_id=opened.id)
    assert [(i["label"], i["required"]) for i in stack["checklist_items"]] == [
        ("테스트가 있다", True),
        ("주석이 있다", False),
    ]
    assert stack["submission_formats"] == ["repository"]
    assert stack["deletable"] is False  # 참여자의 시도가 있다

    participants = _structured(client, token, "list_participants", class_id=class_id)["participants"]
    assert participants == _screen(client, access, f"{class_id}/members")
    assert {p["display_name"]: p["expelled"] for p in participants} == {"김하나": False, "이둘": True}

    grid = _structured(client, token, "get_roster_grid", class_id=class_id)
    assert grid == roster_grid(client, access, class_id)
    cells = {m["display_name"]: {c["problem_id"]: c["status"] for c in m["cells"]} for m in grid["members"]}
    assert cells["김하나"][opened.id] in {"scoring", "passed", "attempted_not_passed"}
    assert cells["김하나"][draft.id] == "not_submitted"


def test_responses_carry_no_email_and_no_piece_of_the_key(client, db):
    instructor, class_id, opened, _draft = _a_class_with_everything(client)
    token = _connect(client, instructor["access"])["access_token"]

    bodies = [
        _rpc(client, token, "tools/call", {"name": name, "arguments": arguments}).content.decode("utf-8")
        for name, arguments in [
            ("get_class", {"class_id": class_id}),
            ("list_problems", {"class_id": class_id}),
            ("get_problem", {"class_id": class_id, "problem_id": opened.id}),
            ("list_participants", {"class_id": class_id}),
            ("get_roster_grid", {"class_id": class_id}),
        ]
    ]

    for body in bodies:
        assert "@" not in body
        assert "example" not in body
        assert "sk-" not in body
        assert "openai_key_masked" not in body


def test_someone_elses_class_and_problem_are_not_found_like_on_the_screen(client, db):
    owner, class_id, opened, _draft = _a_class_with_everything(client)
    stranger = login(client, uid="mcp-read-stranger")
    mine = create_class(client, stranger["access"], name="내 클래스", with_key=False)
    token = _connect(client, stranger["access"])["access_token"]

    for name in ["get_class", "list_problems", "list_participants", "get_roster_grid"]:
        result = _call(client, token, name, class_id=class_id)
        assert result["isError"] is True
        assert result["content"][0]["text"] == "클래스를 찾을 수 없습니다."
        assert "structuredContent" not in result

    elsewhere = _call(client, token, "get_problem", class_id=class_id, problem_id=opened.id)
    assert elsewhere["content"][0]["text"] == "클래스를 찾을 수 없습니다."
    # 내 클래스 번호에 남의 문제 번호를 붙여도 「없다」다.
    crossed = _call(client, token, "get_problem", class_id=mine, problem_id=opened.id)
    assert crossed["isError"] is True
    assert crossed["content"][0]["text"] == "문제를 찾을 수 없습니다."

    # 그 클래스의 참여자가 연결한 앱도 강사 화면을 읽지 못한다.
    participant = login(client, uid="mcp-read-p1")
    participant_token = _connect(client, participant["access"])["access_token"]
    assert _call(client, participant_token, "list_participants", class_id=class_id)["isError"] is True
    assert client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(owner["access"])).status_code == 200


def test_bad_arguments_come_back_as_a_tool_error(client, db):
    instructor = login(client, uid="mcp-read-args")
    class_id = create_class(client, instructor["access"], with_key=False)
    token = _connect(client, instructor["access"])["access_token"]

    missing = _call(client, token, "get_class")
    assert missing["isError"] is True
    assert "class_id" in missing["content"][0]["text"]
    as_text = _call(client, token, "get_problem", class_id=class_id, problem_id="1")
    assert as_text["isError"] is True
    assert "problem_id" in as_text["content"][0]["text"]


def test_an_archived_class_is_still_readable(client, db):
    instructor = login(client, uid="mcp-read-archived")
    class_id = create_class(client, instructor["access"], name="지난 학기", with_key=False)
    create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)
    token = _connect(client, instructor["access"])["access_token"]

    assert _structured(client, token, "get_class", class_id=class_id)["archived"] is True
    assert len(_structured(client, token, "list_problems", class_id=class_id)["problems"]) == 1


def _row_counts() -> dict[str, int]:
    return {model._meta.label: model.objects.count() for model in apps.get_models()}


def test_reading_leaves_no_record(client, db):
    """ADR-0040 — 연결된 앱이 무엇을 몇 번 읽었는지는 어디에도 남지 않는다."""

    instructor, class_id, opened, _draft = _a_class_with_everything(client)
    token = _connect(client, instructor["access"])["access_token"]
    _call(client, token, "get_class", class_id=class_id)  # 「마지막으로 쓴 날」은 첫 호출에 이미 적혔다

    before = _row_counts()
    for _ in range(2):
        _structured(client, token, "get_class", class_id=class_id)
        _structured(client, token, "list_problems", class_id=class_id)
        _structured(client, token, "get_problem", class_id=class_id, problem_id=opened.id)
        _structured(client, token, "list_participants", class_id=class_id)
        _structured(client, token, "get_roster_grid", class_id=class_id)
    _call(client, token, "get_class", class_id=class_id + 999)  # 거절된 읽기도 마찬가지

    assert _row_counts() == before


def test_get_class_and_get_problem_carry_a_short_cost_estimate_for_the_current_setting(client, db):
    """#591 — 지금 설정 한 줄만 싣는다(#579 의 크기 원칙). 시도가 없으면 소스 크기별이다."""

    instructor = login(client, uid="instructor-1")
    access = instructor["access"]
    class_id = create_class(client, access)
    patch_class(client, access, class_id, {"default_model": "gpt-5.5", "default_reasoning_effort": "medium"})
    problem = create_open_problem(client, access, class_id, model="gpt-4.1-mini")
    token = _connect(client, access)["access_token"]

    class_estimate = _structured(client, token, "get_class", class_id=class_id)["scoring_cost_estimate"]
    assert class_estimate["basis"] == "source_sizes"
    assert (class_estimate["model"], class_estimate["reasoning_effort"]) == ("gpt-5.5", "medium")
    assert set(class_estimate["per_attempt_krw_by_source_chars"]) == {"10000", "50000", "200000"}
    assert class_estimate["ratio_to_gpt_4_1_mini"] > 20

    problem_estimate = _structured(client, token, "get_problem", class_id=class_id, problem_id=problem.id)[
        "scoring_cost_estimate"
    ]
    assert (problem_estimate["model"], problem_estimate["reasoning_effort"]) == ("gpt-4.1-mini", None)
    assert problem_estimate["ratio_to_gpt_4_1_mini"] == 1.0

    patch_class(client, access, class_id, {"default_model": "gpt-4o"})
    unpriced = _structured(client, token, "get_class", class_id=class_id)["scoring_cost_estimate"]
    assert unpriced == {"basis": "source_sizes", "model": "gpt-4o", "reasoning_effort": None, "priced": False}
