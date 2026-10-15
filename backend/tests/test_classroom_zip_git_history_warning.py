"""zip 제출에는 Git 기록이 없다 — Git 을 묻는 필수 항목에 경고 (#587).

판정은 `classroom.git_history_hint` 한 자리이고, 강사의 문제 조회·참여자의 문제 화면·연결된
앱의 만들기·고치기 응답이 모두 그 결과를 싣는다. 경고는 저장을 막지 않는다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from classroom.git_history_hint import asks_for_git_history, zip_git_history_item_ids
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    join_class,
    list_problems,
    login,
    mine,
)
from tests.test_classroom_connected_apps import _connect, _rpc


@pytest.mark.parametrize(
    "label",
    [
        "Git 으로 커밋하고 커밋 메시지를 남겼다",
        "커밋을 기능 단위로 나눴다",
        "commit 메시지가 Conventional Commits 를 따른다",
        "feature 브랜치에서 작업했다",
        "Branches are merged",
        ".git 디렉터리가 있다",
        "GIT LOG 에 세 개 이상의 기록",
    ],
)
def test_labels_that_ask_for_git_history(label):
    assert asks_for_git_history(label)


@pytest.mark.parametrize(
    "label",
    ["GitHub 저장소 README 가 있다", "digit 을 센다", "테스트가 있다", "합을 출력한다", ""],
)
def test_labels_that_do_not(label):
    assert not asks_for_git_history(label)


def _item(id: int, label: str, required: bool = True):
    return SimpleNamespace(id=id, label=label, required=required)


def test_only_required_items_of_a_problem_that_takes_zip_are_flagged():
    items = [_item(1, "커밋 메시지를 남겼다"), _item(2, "테스트가 있다"), _item(3, "브랜치를 썼다", required=False)]

    assert zip_git_history_item_ids(["source"], items) == [1]
    assert zip_git_history_item_ids(["source", "repository"], items) == [1]
    assert zip_git_history_item_ids(["repository"], items) == []


def _problem(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def test_the_instructor_and_the_participant_read_the_same_warning(client, db):
    instructor = login(client, uid="git-instructor")["access"]
    class_id = create_class(client, instructor, with_key=False)
    flagged = create_open_problem(
        client,
        instructor,
        class_id,
        title="Git 과제",
        submission_formats=["source", "repository"],
        required_labels=["합을 출력한다", "Git 으로 커밋하고 커밋 메시지를 남겼다"],
    )
    repository_only = create_open_problem(
        client, instructor, class_id, title="저장소만", required_labels=["커밋 메시지를 남겼다"]
    )
    no_git_item = create_open_problem(
        client, instructor, class_id, title="zip", submission_formats=["source"], required_labels=["합을 출력한다"]
    )

    warnings = {p["id"]: p["zip_git_history_warning"] for p in list_problems(client, instructor, class_id)}
    assert warnings == {
        flagged.id: {"checklist_item_ids": [flagged.item_ids[1]]},
        repository_only.id: None,
        no_git_item.id: None,
    }

    participant = login(client, uid="git-participant")["access"]
    join_class(client, participant, class_id, instructor_access=instructor)
    assert mine(client, participant, class_id, flagged.id)["problem"]["zip_git_history_warning"] == {
        "checklist_item_ids": [flagged.item_ids[1]]
    }
    assert mine(client, participant, class_id, no_git_item.id)["problem"]["zip_git_history_warning"] is None

    # 고칠 길 하나 — 그 항목을 선택으로. 경고는 저장을 막지 않았고, 바꾸면 사라진다.
    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{flagged.id}/checklist-items/{flagged.item_ids[1]}",
        data={"required": False},
        content_type="application/json",
        **auth_header(instructor),
    )
    assert response.status_code == 200, response.content
    assert _problem(client, instructor, class_id, flagged.id)["zip_git_history_warning"] is None


def test_receiving_only_repositories_clears_the_warning(client, db):
    instructor = login(client, uid="git-instructor-2")["access"]
    class_id = create_class(client, instructor, with_key=False)
    problem = create_open_problem(
        client, instructor, class_id, submission_formats=["source"], required_labels=["브랜치를 나눠 작업했다"]
    )
    assert _problem(client, instructor, class_id, problem.id)["zip_git_history_warning"] is not None

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}",
        data={"submission_formats": ["repository"]},
        content_type="application/json",
        **auth_header(instructor),
    )
    assert response.status_code == 200, response.content
    assert response.json()["zip_git_history_warning"] is None


def _tool(client, token: str, name: str, arguments: dict) -> dict:
    response = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments})
    assert response.status_code == 200, response.content
    result = response.json()["result"]
    assert result["isError"] is False, result
    return result["structuredContent"]


def test_the_connected_app_hears_the_warning_in_one_line(client, db):
    instructor = login(client, uid="git-mcp")["access"]
    class_id = create_class(client, instructor, with_key=False)
    token = _connect(client, instructor)["access_token"]

    created = _tool(
        client,
        token,
        "create_problem",
        {
            "class_id": class_id,
            "title": "Git 과제",
            "submission_formats": ["source"],
            "checklist_items": [{"label": "합을 출력한다"}, {"label": "커밋 메시지를 남겼다"}],
        },
    )["problem"]
    flagged_id = created["checklist_items"][1]["id"]
    assert "Git 기록" in created["warning"] and str(flagged_id) in created["warning"]

    ref = {"class_id": class_id, "problem_id": created["id"]}
    fixed = _tool(client, token, "update_problem", {**ref, "submission_formats": ["repository"]})["problem"]
    assert "warning" not in fixed

    added = _tool(client, token, "add_checklist_item", {**ref, "label": "브랜치를 썼다"})
    assert "warning" not in added  # 저장소만 받으니 걸리지 않는다
    back = _tool(client, token, "update_problem", {**ref, "submission_formats": ["source", "repository"]})["problem"]
    assert str(added["item"]["id"]) in back["warning"]
    edited = _tool(client, token, "update_checklist_item", {**ref, "item_id": added["item"]["id"], "required": False})
    assert "warning" in edited and str(added["item"]["id"]) not in edited["warning"]
