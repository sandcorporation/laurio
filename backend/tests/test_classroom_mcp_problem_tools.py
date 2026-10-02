"""연결된 앱이 문제를 만들고 고친다 — 화면과 같은 규칙, 쓰기마다 기록 (#514, spec #511, ADR-0052).

`/mcp` 에 JSON-RPC 를 보내 도구를 부르고, 같은 일을 화면 API 로도 해 본다 — 두 표면이
같은 서비스 함수를 부르므로 거절 문장이 글자 하나까지 같아야 한다. 쓰기 기록
(`ConnectedAppWrite`)은 아직 그것을 보여 주는 화면이 없어 행을 직접 센다.
"""

from __future__ import annotations

import pytest
from django.core.cache import caches

from classroom.models import ConnectedApp, ConnectedAppWrite
from tests.classroom_scenarios import (
    CLASSES_URL,
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    list_problems,
    login,
)
from tests.test_classroom_connected_apps import _connect, _rpc

WRITE_TOOLS = [
    "create_problem",
    "update_problem",
    "add_checklist_item",
    "update_checklist_item",
    "delete_checklist_item",
    "reorder_checklist_items",
    "open_problem",
    "hide_problem",
    "reopen_problem",
    "reorder_problems",
    "copy_problem",
]


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
    assert "structuredContent" not in result
    return result["content"][0]["text"]


def _setup(client, uid: str = "mcp-writer"):
    instructor = login(client, uid=uid)
    class_id = create_class(client, instructor["access"], name="웹 스터디", with_key=False)
    token = _connect(client, instructor["access"])["access_token"]
    return instructor, class_id, token


def _screen_detail(response) -> str:
    assert 400 <= response.status_code < 500, response.content
    return response.json()["detail"]


# --- 만들기 ---------------------------------------------------------------------


def test_the_write_tools_are_listed_as_reversible_writes(client, db):
    _, _, token = _setup(client)
    tools = {tool["name"]: tool for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert set(WRITE_TOOLS) <= set(tools)
    assert "delete_problem" not in WRITE_TOOLS  # 삭제는 두 단계 확인 도구다(#515, test_classroom_mcp_destructive_tools)
    for name in WRITE_TOOLS:
        annotations = tools[name]["annotations"]
        assert annotations["readOnlyHint"] is False, name
        assert annotations["destructiveHint"] is False, name
        assert tools[name]["inputSchema"]["additionalProperties"] is False, name


def test_a_problem_made_by_the_app_is_what_the_screen_shows_and_leaves_one_record(client, db):
    instructor, class_id, token = _setup(client)

    created = _ok(
        client,
        token,
        "create_problem",
        {
            "class_id": class_id,
            "title": "두 수의 합",
            "description": "## 문제\n두 정수를 더한다.",
            "submission_formats": ["repository", "source"],
            "checklist_items": [
                {"label": "합을 출력한다", "required": True},
                {"label": "테스트가 있다", "required": False},
            ],
            "grading_strictness": "custom",
            "grading_guideline_text": "출력 형식은 느슨하게 본다.",
            "syntax_check_enabled": False,
            "open": True,
        },
    )["problem"]

    assert created["status"] == "open"
    assert created["submission_formats"] == ["source", "repository"]  # 화면과 같은 정규화
    assert [(i["label"], i["required"]) for i in created["checklist_items"]] == [
        ("합을 출력한다", True),
        ("테스트가 있다", False),
    ]
    assert created["available_transitions"] == [{"name": "hide", "to_state": "hidden", "blocked_reason": None}]

    (screen,) = list_problems(client, instructor["access"], class_id)
    assert screen["id"] == created["id"]
    for key in (
        "title",
        "description",
        "status",
        "submission_formats",
        "grading_strictness",
        "grading_guideline_text",
        "syntax_check_enabled",
    ):
        assert screen[key] == created[key], key
    assert [i["label"] for i in screen["checklist_items"]] == ["합을 출력한다", "테스트가 있다"]

    (record,) = ConnectedAppWrite.objects.all()
    grant = ConnectedApp.objects.get()
    assert record.instructor_id == grant.instructor_id
    assert record.connected_app_id == grant.id
    assert record.tool == "create_problem"
    assert record.target_class_id == class_id
    assert record.target_problem_id == created["id"]
    assert "두 수의 합" in record.summary
    assert record.created_at is not None


def test_reading_leaves_no_record(client, db):
    _, _, token = _setup(client)
    assert _call(client, token, "list_my_classes", {})["isError"] is False
    assert not ConnectedAppWrite.objects.exists()


# --- 화면과 같은 거절 --------------------------------------------------------------


def test_an_archived_class_refuses_with_the_screens_sentence_and_records_nothing(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id)
    other_class = create_class(client, instructor["access"], name="다음 학기", with_key=False)
    archive_class(client, instructor["access"], class_id)

    screen = _screen_detail(
        client.post(
            f"{CLASSES_URL}/{class_id}/problems",
            data={"title": "새 문제", "submission_formats": ["source"]},
            content_type="application/json",
            **auth_header(instructor["access"]),
        )
    )
    ref = {"class_id": class_id, "problem_id": problem.id}
    refusals = [
        _refused(client, token, "create_problem", {"class_id": class_id, "title": "새 문제", "submission_formats": ["source"]}),
        _refused(client, token, "update_problem", {**ref, "title": "고친 제목"}),
        _refused(client, token, "add_checklist_item", {**ref, "label": "더한 항목"}),
        _refused(client, token, "hide_problem", ref),
        _refused(client, token, "reorder_problems", {"class_id": class_id, "problem_ids": [problem.id]}),
    ]
    assert refusals == [screen] * len(refusals)

    # 보관된 클래스에서 꺼내 가는 복사는 화면처럼 열려 있다 — 넣는 쪽이 보관이면 막힌다.
    copied = _ok(client, token, "copy_problem", {**ref, "target_class_id": other_class})["problem"]
    assert copied["status"] == "draft"
    assert _refused(
        client, token, "copy_problem", {"class_id": other_class, "problem_id": copied["id"], "target_class_id": class_id}
    ) == screen

    assert list(ConnectedAppWrite.objects.values_list("tool", flat=True)) == ["copy_problem"]


def test_banned_words_and_missing_required_items_refuse_like_the_screen(client, db):
    instructor, class_id, token = _setup(client)

    profane = {"title": "씨발 과제", "submission_formats": ["source"]}
    screen_profane = _screen_detail(
        client.post(
            f"{CLASSES_URL}/{class_id}/problems",
            data=profane,
            content_type="application/json",
            **auth_header(instructor["access"]),
        )
    )
    assert _refused(client, token, "create_problem", {"class_id": class_id, **profane}) == screen_profane
    assert "씨발" not in screen_profane

    unopenable = {"title": "필수 없음", "submission_formats": ["source"], "checklist_items": [{"label": "선택", "required": False}], "open": True}
    screen_unopenable = _screen_detail(
        client.post(
            f"{CLASSES_URL}/{class_id}/problems",
            data=unopenable,
            content_type="application/json",
            **auth_header(instructor["access"]),
        )
    )
    assert _refused(client, token, "create_problem", {"class_id": class_id, **unopenable}) == screen_unopenable

    no_format = {"title": "형식 없음", "submission_formats": []}
    assert _refused(client, token, "create_problem", {"class_id": class_id, **no_format}) == _screen_detail(
        client.post(
            f"{CLASSES_URL}/{class_id}/problems",
            data=no_format,
            content_type="application/json",
            **auth_header(instructor["access"]),
        )
    )

    assert list_problems(client, instructor["access"], class_id) == []  # 실패하면 문제도 생기지 않는다
    assert not ConnectedAppWrite.objects.exists()


def test_the_last_required_item_of_an_open_problem_stays_like_on_the_screen(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id, required_labels=["테스트가 있다"])
    item_url = f"{CLASSES_URL}/{class_id}/problems/{problem.id}/checklist-items/{problem.item_id}"
    ref = {"class_id": class_id, "problem_id": problem.id, "item_id": problem.item_id}

    screen = _screen_detail(
        client.patch(item_url, data={"required": False}, content_type="application/json", **auth_header(instructor["access"]))
    )
    assert _refused(client, token, "update_checklist_item", {**ref, "required": False}) == screen
    assert _refused(client, token, "delete_checklist_item", ref) == _screen_detail(
        client.delete(item_url, **auth_header(instructor["access"]))
    )
    assert not ConnectedAppWrite.objects.exists()


def test_transitions_follow_the_same_table_and_each_success_is_recorded(client, db):
    instructor, class_id, token = _setup(client)
    draft = _ok(
        client,
        token,
        "create_problem",
        {"class_id": class_id, "title": "초안", "submission_formats": ["source"]},
    )["problem"]
    ref = {"class_id": class_id, "problem_id": draft["id"]}

    # 없는 전이는 화면과 같은 문장으로 거절된다.
    screen_hide = _screen_detail(
        client.post(f"{CLASSES_URL}/{class_id}/problems/{draft['id']}/hide", **auth_header(instructor["access"]))
    )
    assert _refused(client, token, "hide_problem", ref) == screen_hide
    screen_open = _screen_detail(
        client.post(f"{CLASSES_URL}/{class_id}/problems/{draft['id']}/open", **auth_header(instructor["access"]))
    )
    assert _refused(client, token, "open_problem", ref) == screen_open  # 필수 항목이 없다

    _ok(client, token, "add_checklist_item", {**ref, "label": "합을 출력한다"})
    assert _ok(client, token, "open_problem", ref)["problem"]["status"] == "open"
    assert _ok(client, token, "hide_problem", ref)["problem"]["status"] == "hidden"
    assert _ok(client, token, "reopen_problem", ref)["problem"]["status"] == "open"

    assert list(ConnectedAppWrite.objects.order_by("id").values_list("tool", "target_problem_id")) == [
        ("create_problem", draft["id"]),
        ("add_checklist_item", draft["id"]),
        ("open_problem", draft["id"]),
        ("hide_problem", draft["id"]),
        ("reopen_problem", draft["id"]),
    ]


# --- 고치기·순서·복사 ---------------------------------------------------------------


def test_editing_reordering_and_copying(client, db):
    instructor, class_id, token = _setup(client)
    first = create_open_problem(client, instructor["access"], class_id, title="첫째", required_labels=["가", "나"])
    second = create_open_problem(client, instructor["access"], class_id, title="둘째", open=False)
    target = create_class(client, instructor["access"], name="다음 학기", with_key=False)
    ref = {"class_id": class_id, "problem_id": first.id}

    updated = _ok(client, token, "update_problem", {**ref, "title": "첫째 고침", "grading_strictness": "strict"})["problem"]
    assert (updated["title"], updated["grading_strictness"], updated["status"]) == ("첫째 고침", "strict", "open")

    item = _ok(client, token, "update_checklist_item", {**ref, "item_id": first.item_ids[1], "label": "나 고침"})["item"]
    assert item == {"id": first.item_ids[1], "label": "나 고침", "required": True, "order": 1}

    reordered = _ok(client, token, "reorder_checklist_items", {**ref, "item_ids": list(reversed(first.item_ids))})
    assert [i["label"] for i in reordered["problem"]["checklist_items"]] == ["나 고침", "가"]

    deleted = _ok(client, token, "delete_checklist_item", {**ref, "item_id": first.item_ids[0]})
    assert deleted["deleted_item_id"] == first.item_ids[0]
    assert [i["label"] for i in deleted["problem"]["checklist_items"]] == ["나 고침"]

    problems = _ok(client, token, "reorder_problems", {"class_id": class_id, "problem_ids": [second.id, first.id]})["problems"]
    assert [p["id"] for p in problems] == [second.id, first.id]
    assert [p["id"] for p in list_problems(client, instructor["access"], class_id)] == [second.id, first.id]
    assert _refused(client, token, "reorder_problems", {"class_id": class_id, "problem_ids": [first.id]}) == (
        "이 클래스의 문제 목록과 일치하지 않습니다."
    )

    copied = _ok(client, token, "copy_problem", {**ref, "target_class_id": target})["problem"]
    assert (copied["class_id"], copied["title"], copied["status"]) == (target, "첫째 고침", "draft")
    assert [i["label"] for i in copied["checklist_items"]] == ["나 고침"]

    tools = list(ConnectedAppWrite.objects.order_by("id").values_list("tool", "target_class_id"))
    assert tools == [
        ("update_problem", class_id),
        ("update_checklist_item", class_id),
        ("reorder_checklist_items", class_id),
        ("delete_checklist_item", class_id),
        ("reorder_problems", class_id),
        ("copy_problem", target),
    ]
    assert "title" in ConnectedAppWrite.objects.get(tool="update_problem").summary


def test_someone_elses_class_is_not_there(client, db):
    _, my_class, token = _setup(client)
    other = login(client, uid="mcp-someone-else")
    other_class = create_class(client, other["access"], name="남의 클래스", with_key=False)
    other_problem = create_open_problem(client, other["access"], other_class)

    assert _refused(
        client, token, "create_problem", {"class_id": other_class, "title": "끼어들기", "submission_formats": ["source"]}
    ) == "클래스를 찾을 수 없습니다."
    assert _refused(client, token, "hide_problem", {"class_id": other_class, "problem_id": other_problem.id}) == (
        "클래스를 찾을 수 없습니다."
    )
    # 남의 문제 번호를 내 클래스 번호와 짝지어도 없다.
    assert _refused(client, token, "hide_problem", {"class_id": my_class, "problem_id": other_problem.id}) == (
        "문제를 찾을 수 없습니다."
    )
    assert not ConnectedAppWrite.objects.exists()


def test_misshapen_arguments_are_refused_without_writing(client, db):
    _, class_id, token = _setup(client)

    assert "titel" in _refused(
        client, token, "create_problem", {"class_id": class_id, "titel": "오타", "submission_formats": ["source"]}
    )
    assert "title" in _refused(client, token, "create_problem", {"class_id": class_id, "submission_formats": ["source"]})
    assert "class_id" in _refused(
        client, token, "create_problem", {"class_id": "하나", "title": "문자 번호", "submission_formats": ["source"]}
    )
    assert "title" in _refused(
        client, token, "create_problem", {"class_id": class_id, "title": "", "submission_formats": ["source"]}
    )
    assert not ConnectedAppWrite.objects.exists()
