"""연결된 앱의 되돌릴 수 없는 도구 — 미리보기와 확인 표, 두 단계 (#515, spec #511, ADR-0052).

`/mcp` 에 JSON-RPC 를 보내 도구를 부르고, 결과는 화면 API 로 본다. 확인 표 없이 부르면
아무것도 바뀌지 않고(기록도 없다), 표는 한 번만·그 앱·그 대상·5분 안에만 쓰인다. 화면이
막는 일은 미리보기에서도 실행에서도 화면과 같은 문장으로 막힌다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.cache import caches

from classroom.models import (
    ClassMember,
    ClassroomSubmission,
    ConnectedAppWrite,
    ProblemTemplate,
)
from core.clock import Clock
from core.models import ConnectedAppConfirmation
from tests.classroom_scenarios import (
    CLASSES_URL,
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    join_class,
    list_problems,
    login,
    submit_repository,
)
from tests.test_classroom_connected_apps import _connect, _rpc, _set_clock

DESTRUCTIVE_TOOLS = [
    "delete_problem",
    "delete_class",
    "expel_member",
    "publish_problem_template",
    "publish_class_template",
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
    return result["content"][0]["text"]


def _preview(client, token: str, name: str, arguments: dict) -> dict:
    result = _ok(client, token, name, arguments)
    assert result["status"] == "needs_confirmation", result
    return result


def _setup(client, uid: str = "mcp-danger"):
    instructor = login(client, uid=uid)
    class_id = create_class(client, instructor["access"], name="웹 스터디", with_key=False)
    token = _connect(client, instructor["access"])["access_token"]
    return instructor, class_id, token


def _problem_ids(client, access: str, class_id: int) -> list[int]:
    return [p["id"] for p in list_problems(client, access, class_id)]


def _members(client, access: str, class_id: int) -> list[dict]:
    response = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def test_the_four_irreversible_actions_are_listed_as_destructive(client, db):
    _, _, token = _setup(client)
    tools = {tool["name"]: tool for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    for name in DESTRUCTIVE_TOOLS:
        annotations = tools[name]["annotations"]
        assert annotations["destructiveHint"] is True, name
        assert annotations["readOnlyHint"] is False, name
        schema = tools[name]["inputSchema"]
        assert "confirmation" in schema["properties"], name
        assert "confirmation" not in schema["required"], name


# --- 문제 삭제 -------------------------------------------------------------------


def test_deleting_a_problem_previews_first_and_runs_only_with_the_ticket(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id, title="두 수의 합", optional_labels=["주석"])
    # 강사 자신이 한 번 내본다 — 지울 수 있고, 그 시도는 함께 사라진다(ADR-0050).
    join_class(client, instructor["access"], class_id, instructor_access=instructor["access"], display_name="강사")
    submit_repository(client, instructor["access"], class_id, problem.id)
    arguments = {"class_id": class_id, "problem_id": problem.id}

    first = _preview(client, token, "delete_problem", arguments)

    preview = first["preview"]
    assert preview["problem"] == {"id": problem.id, "title": "두 수의 합", "status": "open"}
    assert preview["checklist_item_count"] == 2
    assert preview["instructor_attempt_count"] == 1
    assert preview["participant_attempt_count"] == 0
    assert "두 수의 합" in preview["summary"] and "되돌릴 수 없다" in preview["summary"]
    assert first["confirmation"]
    # 미리보기는 쓰기가 아니다 — 아무것도 안 바뀌고 기록도 없다.
    assert _problem_ids(client, instructor["access"], class_id) == [problem.id]
    assert not ConnectedAppWrite.objects.exists()

    done = _ok(client, token, "delete_problem", {**arguments, "confirmation": first["confirmation"]})

    assert done == {"status": "done", "deleted_problem": {"id": problem.id, "title": "두 수의 합"}}
    assert _problem_ids(client, instructor["access"], class_id) == []
    assert not ClassroomSubmission.objects.exists()
    (record,) = ConnectedAppWrite.objects.all()
    assert (record.tool, record.target_class_id, record.target_problem_id) == ("delete_problem", class_id, problem.id)
    assert "두 수의 합" in record.summary


def test_a_problem_with_a_participant_attempt_gets_no_ticket_and_the_screen_sentence(client, db):
    instructor, class_id, token = _setup(client)
    participant = login(client, uid="mcp-danger-participant")
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)

    refused = _refused(client, token, "delete_problem", {"class_id": class_id, "problem_id": problem.id})

    screen = client.delete(f"{CLASSES_URL}/{class_id}/problems/{problem.id}", **auth_header(instructor["access"]))
    assert screen.status_code == 403
    assert refused == screen.json()["detail"] == "지울 수 없습니다 — 대신 숨겨주세요."
    assert not ConnectedAppConfirmation.objects.exists()


def test_if_a_participant_submits_between_preview_and_confirmation_the_deletion_is_refused(client, db):
    instructor, class_id, token = _setup(client)
    participant = login(client, uid="mcp-danger-participant")
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    arguments = {"class_id": class_id, "problem_id": problem.id}
    ticket = _preview(client, token, "delete_problem", arguments)["confirmation"]

    submit_repository(client, participant["access"], class_id, problem.id)
    refused = _refused(client, token, "delete_problem", {**arguments, "confirmation": ticket})

    assert refused == "지울 수 없습니다 — 대신 숨겨주세요."
    assert _problem_ids(client, instructor["access"], class_id) == [problem.id]
    assert not ConnectedAppWrite.objects.exists()


def test_deleting_a_problem_in_an_archived_class_is_refused_like_the_screen(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id)
    archive_class(client, instructor["access"], class_id)

    refused = _refused(client, token, "delete_problem", {"class_id": class_id, "problem_id": problem.id})

    screen = client.delete(f"{CLASSES_URL}/{class_id}/problems/{problem.id}", **auth_header(instructor["access"]))
    assert refused == screen.json()["detail"]
    assert not ConnectedAppConfirmation.objects.exists()


# --- 확인 표 -----------------------------------------------------------------------


def test_a_ticket_expires_after_five_minutes(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id)
    arguments = {"class_id": class_id, "problem_id": problem.id}
    start = Clock.now()
    _set_clock(start)
    ticket = _preview(client, token, "delete_problem", arguments)["confirmation"]

    _set_clock(start + timedelta(minutes=5, seconds=1))
    refused = _refused(client, token, "delete_problem", {**arguments, "confirmation": ticket})

    assert refused.startswith("확인 표가 만료됐습니다.")
    assert _problem_ids(client, instructor["access"], class_id) == [problem.id]
    assert not ConnectedAppWrite.objects.exists()

    # 시간 안이면 그대로 된다.
    _set_clock(start + timedelta(minutes=10))
    fresh = _preview(client, token, "delete_problem", arguments)["confirmation"]
    _set_clock(start + timedelta(minutes=14, seconds=59))
    assert _ok(client, token, "delete_problem", {**arguments, "confirmation": fresh})["status"] == "done"


def test_a_ticket_works_only_for_its_own_target_tool_and_app(client, db):
    instructor, class_id, token = _setup(client)
    first = create_open_problem(client, instructor["access"], class_id, title="첫째")
    second = create_open_problem(client, instructor["access"], class_id, title="둘째")
    ticket = _preview(client, token, "delete_problem", {"class_id": class_id, "problem_id": first.id})["confirmation"]

    other_target = _refused(
        client, token, "delete_problem", {"class_id": class_id, "problem_id": second.id, "confirmation": ticket}
    )
    other_tool = _refused(
        client,
        token,
        "publish_problem_template",
        {"class_id": class_id, "problem_id": first.id, "publisher_display_name": "김강사", "confirmation": ticket},
    )
    other_app = _connect(client, instructor["access"])["access_token"]
    from_other_app = _refused(
        client, other_app, "delete_problem", {"class_id": class_id, "problem_id": first.id, "confirmation": ticket}
    )

    assert other_target.startswith("이 확인 표는 다른 도구나 다른 대상·인자로 받은 것입니다.")
    assert other_tool.startswith("이 확인 표는 다른 도구나 다른 대상·인자로 받은 것입니다.")
    assert from_other_app.startswith("확인 표가 올바르지 않습니다.")
    assert _problem_ids(client, instructor["access"], class_id) == [first.id, second.id]
    assert not ProblemTemplate.objects.exists()
    assert not ConnectedAppWrite.objects.exists()

    # 제 대상에는 아직 쓰인다 — 잘못 낸 것이 표를 태우지 않는다.
    assert _ok(
        client, token, "delete_problem", {"class_id": class_id, "problem_id": first.id, "confirmation": ticket}
    )["status"] == "done"


def test_a_ticket_is_good_for_one_execution_only(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id, title="공개할 문제")
    arguments = {"class_id": class_id, "problem_id": problem.id, "publisher_display_name": "김강사"}
    ticket = _preview(client, token, "publish_problem_template", arguments)["confirmation"]
    published = _ok(client, token, "publish_problem_template", {**arguments, "confirmation": ticket})
    share_code = published["template"]["share_code"]
    # 화면에서 내린다 — 같은 문제를 다시 공개할 수 있는 상태가 된다.
    takedown = client.post(f"/api/classroom/problem-templates/{share_code}/takedown", **auth_header(instructor["access"]))
    assert takedown.status_code == 200, takedown.content

    reused = _refused(client, token, "publish_problem_template", {**arguments, "confirmation": ticket})

    assert reused.startswith("이미 쓴 확인 표입니다.")
    assert ProblemTemplate.objects.filter(taken_down_at__isnull=True).count() == 0
    assert ConnectedAppWrite.objects.count() == 1


def test_a_made_up_ticket_is_refused(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id)

    refused = _refused(
        client, token, "delete_problem", {"class_id": class_id, "problem_id": problem.id, "confirmation": "아무거나"}
    )

    assert refused.startswith("확인 표가 올바르지 않습니다.")
    assert _problem_ids(client, instructor["access"], class_id) == [problem.id]


# --- 클래스 삭제 ------------------------------------------------------------------


def test_deleting_a_class_previews_its_problems_and_members_then_deletes(client, db):
    instructor, class_id, token = _setup(client)
    participant = login(client, uid="mcp-danger-participant")
    create_open_problem(client, instructor["access"], class_id, title="열린 문제")
    create_open_problem(client, instructor["access"], class_id, title="초안", open=False)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"], display_name="김참여")
    arguments = {"class_id": class_id}

    first = _preview(client, token, "delete_class", arguments)

    preview = first["preview"]
    assert preview["class"] == {"id": class_id, "name": "웹 스터디", "archived": False}
    assert preview["problem_count"] == 2
    assert preview["problem_counts"] == {"draft": 1, "open": 1, "hidden": 0}
    assert [p["title"] for p in preview["problems"]] == ["열린 문제", "초안"]
    assert preview["participant_count"] == 1
    assert "@" not in str(first)  # 이메일은 나가지 않는다
    assert client.get(f"{CLASSES_URL}/{class_id}", **auth_header(instructor["access"])).status_code == 200

    done = _ok(client, token, "delete_class", {**arguments, "confirmation": first["confirmation"]})

    assert done == {"status": "done", "deleted_class": {"id": class_id, "name": "웹 스터디"}}
    assert client.get(f"{CLASSES_URL}/{class_id}", **auth_header(instructor["access"])).status_code == 404
    (record,) = ConnectedAppWrite.objects.all()
    assert (record.tool, record.target_class_id) == ("delete_class", class_id)


def test_a_class_with_a_submission_is_refused_with_the_screen_sentence(client, db):
    instructor, class_id, token = _setup(client)
    participant = login(client, uid="mcp-danger-participant")
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)

    refused = _refused(client, token, "delete_class", {"class_id": class_id})

    screen = client.delete(f"{CLASSES_URL}/{class_id}", **auth_header(instructor["access"]))
    assert screen.status_code == 403
    assert refused == screen.json()["detail"]
    assert not ConnectedAppConfirmation.objects.exists()


def test_someone_elses_class_is_not_found(client, db):
    _, _, token = _setup(client)
    other = login(client, uid="mcp-danger-other")
    others_class = create_class(client, other["access"], name="남의 클래스", with_key=False)

    refused = _refused(client, token, "delete_class", {"class_id": others_class})

    assert refused == "클래스를 찾을 수 없습니다."
    assert not ConnectedAppConfirmation.objects.exists()


# --- 참여자 내보내기 ----------------------------------------------------------------


def test_expelling_names_who_leaves_then_expels(client, db):
    instructor, class_id, token = _setup(client)
    participant = login(client, uid="mcp-danger-participant")
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"], display_name="김참여")
    submit_repository(client, participant["access"], class_id, problem.id)
    member_id = ClassMember.objects.get(display_name="김참여").id
    arguments = {"class_id": class_id, "member_id": member_id}

    first = _preview(client, token, "expel_member", arguments)

    assert first["preview"]["member"]["display_name"] == "김참여"
    assert first["preview"]["attempt_count"] == 1
    assert "@" not in str(first)
    assert _members(client, instructor["access"], class_id)[0]["expelled"] is False

    done = _ok(client, token, "expel_member", {**arguments, "confirmation": first["confirmation"]})

    assert done["member"]["expelled"] is True
    assert _members(client, instructor["access"], class_id)[0]["expelled"] is True
    (record,) = ConnectedAppWrite.objects.all()
    assert record.tool == "expel_member" and "김참여" in record.summary

    # 이미 내보낸 사람은 할 일이 없다 — 표도 기록도 없다.
    again = _ok(client, token, "expel_member", arguments)
    assert again["status"] == "nothing_to_do" and "confirmation" not in again
    assert ConnectedAppWrite.objects.count() == 1


def test_an_instructors_own_member_row_is_refused_like_the_screen(client, db):
    # #669 의 거절(`assert_member_expellable`)이 연결된 앱 경로에도 선다(#676) — 표도 기록도 남지 않는다.
    instructor, class_id, token = _setup(client)
    join_class(client, instructor["access"], class_id, instructor_access=instructor["access"], display_name="소유자")
    (own,) = _members(client, instructor["access"], class_id)

    refused = _refused(client, token, "expel_member", {"class_id": class_id, "member_id": own["id"]})

    assert refused == "강사는 내보낼 수 없습니다."
    assert _members(client, instructor["access"], class_id)[0]["expelled"] is False
    assert ConnectedAppWrite.objects.count() == 0


def test_an_unknown_member_is_not_found_like_the_screen(client, db):
    instructor, class_id, token = _setup(client)

    refused = _refused(client, token, "expel_member", {"class_id": class_id, "member_id": 999999})

    screen = client.post(f"{CLASSES_URL}/{class_id}/members/999999/expel", **auth_header(instructor["access"]))
    assert refused == screen.json()["detail"] == "참여자를 찾을 수 없습니다."


# --- 템플릿 공개 -----------------------------------------------------------------


def test_publishing_a_class_previews_every_problem_including_drafts(client, db):
    instructor, class_id, token = _setup(client)
    create_open_problem(client, instructor["access"], class_id, title="열린 문제")
    create_open_problem(client, instructor["access"], class_id, title="아직 초안", open=False)
    arguments = {"class_id": class_id, "publisher_display_name": "김강사"}

    first = _preview(client, token, "publish_class_template", arguments)

    preview = first["preview"]
    assert [p["title"] for p in preview["problems"]] == ["열린 문제", "아직 초안"]
    assert "초안 1개" in preview["summary"]
    assert preview["publisher_display_name"] == "김강사"

    done = _ok(client, token, "publish_class_template", {**arguments, "confirmation": first["confirmation"]})

    assert done["template"]["name"] == "웹 스터디"
    mine = client.get("/api/classroom/class-templates/mine", **auth_header(instructor["access"]))
    assert [t["share_code"] for t in mine.json()] == [done["template"]["share_code"]]
    assert ConnectedAppWrite.objects.get().tool == "publish_class_template"

    # 이미 공개돼 있으면 할 일이 없다.
    again = _ok(client, token, "publish_class_template", arguments)
    assert again["status"] == "nothing_to_do"
    assert again["template"]["share_code"] == done["template"]["share_code"]


def test_a_banned_publisher_name_is_refused_at_preview_like_the_screen(client, db):
    instructor, class_id, token = _setup(client)
    problem = create_open_problem(client, instructor["access"], class_id)

    refused = _refused(
        client,
        token,
        "publish_problem_template",
        {"class_id": class_id, "problem_id": problem.id, "publisher_display_name": "운영자"},
    )

    screen = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}/publish-template",
        data={"publisher_display_name": "운영자"},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert screen.status_code == 422
    assert refused == screen.json()["detail"]
    assert not ConnectedAppConfirmation.objects.exists()
