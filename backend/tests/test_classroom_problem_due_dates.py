"""문제마다 권장 기한과 마감 (#769, ADR-0063).

마감 뒤에도 참여자는 낸다(#941). 늦음은 권장 기한 뒤·마감 기한 뒤 두 단계이며
마감이 우선한다. 저장하지 않고 응답마다 계산하므로 날짜를 옮기면 판정이 바뀐다.
복사·템플릿은 두 날짜를 비운다. 전부 마운트된 HTTP API 로 확인한다."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from classroom.models import Class, ClassroomSubmission

from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    instructor_submissions,
    join_class,
    list_problems,
    login,
    mine,
    my_problems,
    open_problem,
    roster_grid,
    submit_repository,
    submit_source,
    user_id,
)
from tests.test_classroom_connected_apps import _connect
from tests.test_classroom_mcp_problem_tools import _ok, _refused

PROBLEM_TEMPLATES_URL = "/api/classroom/problem-templates"
CLASS_TEMPLATES_URL = "/api/classroom/class-templates"

PAST = datetime(2020, 1, 1, 9, 0, tzinfo=timezone.utc)
FUTURE = datetime(2099, 1, 1, 9, 0, tzinfo=timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _patch(client, access: str, class_id: int, problem_id: int, payload: dict):
    return client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data=payload,
        content_type="application/json",
        **auth_header(access),
    )


def _create(client, access: str, class_id: int, payload: dict):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "기한 있는 문제", "submission_formats": ["repository"], **payload},
        content_type="application/json",
        **auth_header(access),
    )


def _try_submit(client, access: str, class_id: int, problem_id: int):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": "https://github.com/octocat/hello-world", "submission_format": "repository"},
        content_type="application/json",
        **auth_header(access),
    )


def _setup_with_participant(client, *, recommended=None, due=None):
    instructor = login(client, uid="due-instructor")
    class_id = create_class(client, instructor["access"], name="기한 스터디", with_key=False)
    problem = create_open_problem(client, instructor["access"], class_id)
    payload = {}
    if recommended is not None:
        payload["recommended_due_at"] = _iso(recommended)
    if due is not None:
        payload["due_at"] = _iso(due)
    if payload:
        assert _patch(client, instructor["access"], class_id, problem.id, payload).status_code == 200
    participant = login(client, uid="due-participant")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    return instructor, participant, class_id, problem.id


# --- 두 날짜와 그 순서 ---------------------------------------------------------


def test_dates_are_nullable_and_round_trip_through_create_patch_list_and_participant_view(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client)

    assert list_problems(client, instructor["access"], class_id)[0]["recommended_due_at"] is None
    assert list_problems(client, instructor["access"], class_id)[0]["due_at"] is None

    created = _create(
        client, instructor["access"], class_id, {"recommended_due_at": _iso(PAST), "due_at": _iso(FUTURE)}
    )
    assert created.status_code == 201, created.content
    body = created.json()
    assert (body["recommended_due_at"], body["due_at"]) == (_iso(PAST), _iso(FUTURE))

    patched = _patch(client, instructor["access"], class_id, problem_id, {"due_at": _iso(FUTURE)})
    assert patched.status_code == 200, patched.content
    assert (patched.json()["recommended_due_at"], patched.json()["due_at"]) == (None, _iso(FUTURE))

    # 칸을 생략하면 그대로, null 을 보내면 비운다.
    kept = _patch(client, instructor["access"], class_id, problem_id, {"title": "제목만"})
    assert kept.json()["due_at"] == _iso(FUTURE)
    cleared = _patch(client, instructor["access"], class_id, problem_id, {"due_at": None})
    assert cleared.status_code == 200, cleared.content
    assert cleared.json()["due_at"] is None

    _patch(client, instructor["access"], class_id, problem_id, {"recommended_due_at": _iso(PAST)})
    seen = mine(client, participant["access"], class_id, problem_id)["problem"]
    assert (seen["recommended_due_at"], seen["due_at"]) == (_iso(PAST), None)


def test_recommended_after_due_is_422_on_create_and_patch(client, db):
    instructor, _, class_id, problem_id = _setup_with_participant(client, due=PAST)

    created = _create(
        client, instructor["access"], class_id, {"recommended_due_at": _iso(FUTURE), "due_at": _iso(PAST)}
    )
    assert created.status_code == 422, created.content
    assert created.json()["detail"] == "권장 기한은 마감보다 늦을 수 없습니다."

    # 이미 저장된 마감(2020)보다 늦은 권장 기한 하나만 보내도 같은 이유로 거절한다.
    patched = _patch(client, instructor["access"], class_id, problem_id, {"recommended_due_at": _iso(FUTURE)})
    assert patched.status_code == 422, patched.content
    assert patched.json()["detail"] == "권장 기한은 마감보다 늦을 수 없습니다."

    # 같은 시각은 된다.
    same = _patch(
        client, instructor["access"], class_id, problem_id, {"recommended_due_at": _iso(PAST), "due_at": _iso(PAST)}
    )
    assert same.status_code == 200, same.content


def test_dates_cannot_be_changed_on_an_archived_class(client, db):
    instructor, _, class_id, problem_id = _setup_with_participant(client)
    archive_class(client, instructor["access"], class_id)

    response = _patch(client, instructor["access"], class_id, problem_id, {"due_at": _iso(FUTURE)})

    assert response.status_code == 403, response.content


# --- 마감 뒤에도 제출한다 ------------------------------------------------------


def test_participant_submits_after_due_at_and_keeps_past_attempts(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, due=FUTURE)
    submit_repository(client, participant["access"], class_id, problem_id)
    _patch(client, instructor["access"], class_id, problem_id, {"due_at": _iso(PAST)})

    accepted = _try_submit(client, participant["access"], class_id, problem_id)

    assert accepted.status_code == 201, accepted.content
    assert accepted.json()["late"] == "deadline"
    body = mine(client, participant["access"], class_id, problem_id)
    assert body["submit_blocked_reason"] is None
    assert len(body["submissions"]) == 2
    assert [p["id"] for p in my_problems(client, participant["access"], class_id)["problems"]] == [problem_id]


def test_source_upload_and_submission_are_allowed_after_deadline(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, due=PAST)
    assert _patch(client, instructor["access"], class_id, problem_id, {
        "submission_formats": ["source"],
    }).status_code == 200
    uid = user_id("due-participant")
    upload = client.post("/api/storage/uploads", data={
        "target_ref": f"classroom-submission:{problem_id}:{uid}:source",
    }, content_type="application/json", **auth_header(participant["access"]))
    assert upload.status_code == 200, upload.content
    submitted = submit_source(client, participant["access"], class_id, problem_id,
                              participant_user_id=uid, files={"main.py": "print('학습')"})
    assert submitted["late"] == "deadline"


def test_moving_the_due_at_forward_changes_lateness_without_closing_submission(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, due=PAST)
    assert _try_submit(client, participant["access"], class_id, problem_id).json()["late"] == "deadline"

    _patch(client, instructor["access"], class_id, problem_id, {"due_at": _iso(FUTURE)})

    assert mine(client, participant["access"], class_id, problem_id)["submissions"][0]["late"] is None
    assert _try_submit(client, participant["access"], class_id, problem_id).json()["late"] is None
    assert mine(client, participant["access"], class_id, problem_id)["submit_blocked_reason"] is None


def test_owner_and_co_instructor_submit_after_due_at(client, db):
    instructor, _, class_id, problem_id = _setup_with_participant(client, due=PAST)
    co = login(client, uid="due-co-instructor")
    add_co_instructor(client, instructor["access"], class_id, co["access"])

    assert _try_submit(client, instructor["access"], class_id, problem_id).status_code == 201
    assert _try_submit(client, co["access"], class_id, problem_id).status_code == 201
    assert mine(client, instructor["access"], class_id, problem_id)["submit_blocked_reason"] is None


def test_hidden_still_blocks_after_deadline(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, due=PAST)
    _patch(client, instructor["access"], class_id, problem_id, {"due_at": _iso(FUTURE)})
    submit_repository(client, participant["access"], class_id, problem_id)
    _patch(client, instructor["access"], class_id, problem_id, {"due_at": _iso(PAST)})
    hidden = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/hide", **auth_header(instructor["access"])
    )
    assert hidden.status_code == 200, hidden.content

    assert mine(client, participant["access"], class_id, problem_id)["submit_blocked_reason"] == "hidden"
    assert _try_submit(client, participant["access"], class_id, problem_id).status_code == 403


def test_a_draft_whose_due_at_has_passed_can_still_be_opened(client, db):
    instructor = login(client, uid="due-instructor")
    class_id = create_class(client, instructor["access"], name="기한 스터디", with_key=False)
    problem = create_open_problem(client, instructor["access"], class_id, open=False)
    _patch(client, instructor["access"], class_id, problem.id, {"due_at": _iso(PAST)})

    open_problem(client, instructor["access"], class_id, problem.id)

    assert list_problems(client, instructor["access"], class_id)[0]["status"] == "open"


# --- 늦음 — 저장하지 않고 응답마다 계산한다 -------------------------------------------


def test_an_attempt_after_the_recommended_due_at_is_late_everywhere_and_follows_the_date(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, recommended=PAST)
    submitted = submit_repository(client, participant["access"], class_id, problem_id)
    assert submitted["late"] == "recommended"

    def _everywhere() -> tuple:
        own = mine(client, participant["access"], class_id, problem_id)["submissions"][0]["late"]
        listed = my_problems(client, participant["access"], class_id)["problems"][0]["late"]
        by_instructor = instructor_submissions(client, instructor["access"], class_id, problem_id)[0]["late"]
        rows = roster_grid(client, instructor["access"], class_id)["members"]
        cell = next(m for m in rows if m["display_name"] == "참여자")["cells"][0]["late"]
        return own, listed, by_instructor, cell

    assert _everywhere() == ("recommended",) * 4

    # 권장 기한을 뒤로 옮기면 같은 시도가 늦지 않은 것이 된다 — 저장된 값이 아니다.
    _patch(client, instructor["access"], class_id, problem_id, {"recommended_due_at": _iso(FUTURE)})
    assert _everywhere() == (None,) * 4

    # 권장 기한이 없으면 늦음도 없다.
    _patch(client, instructor["access"], class_id, problem_id, {"recommended_due_at": None})
    assert _everywhere() == (None,) * 4


def test_attempt_before_due_at_without_recommended_is_not_late(client, db):
    _, participant, class_id, problem_id = _setup_with_participant(client, due=FUTURE)

    assert submit_repository(client, participant["access"], class_id, problem_id)["late"] is None
    assert my_problems(client, participant["access"], class_id)["problems"][0]["late"] is None


def test_the_list_row_and_grid_cell_follow_the_last_attempt(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, recommended=PAST)
    submit_repository(client, participant["access"], class_id, problem_id)
    first = mine(client, participant["access"], class_id, problem_id)["submissions"][0]
    submit_repository(client, participant["access"], class_id, problem_id)
    first_at = _iso(ClassroomSubmission.objects.get(pk=first["id"]).created_at)
    # 첫 시각 자체는 늦지 않지만 두 번째는 늦다. 집계는 마지막 시도의 마감 단계를 따른다.
    _patch(client, instructor["access"], class_id, problem_id, {
        "recommended_due_at": first_at, "due_at": first_at,
    })
    attempts = mine(client, participant["access"], class_id, problem_id)["submissions"]
    assert [a["late"] for a in attempts] == ["deadline", None]
    assert my_problems(client, participant["access"], class_id)["problems"][0]["late"] == "deadline"
    rows = roster_grid(client, instructor["access"], class_id)["members"]
    assert next(m for m in rows if m["display_name"] == "참여자")["cells"][0]["late"] == "deadline"


@pytest.mark.parametrize("recommended,due,expected", [
    (None, None, None),
    (PAST, None, "recommended"),
    (PAST, FUTURE, "recommended"),
    (None, PAST, "deadline"),
    (PAST, PAST, "deadline"),
])
def test_lateness_contract_in_recent_attempts_and_mcp(client, db, recommended, due, expected):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, recommended=recommended, due=due)
    submitted = submit_repository(client, participant["access"], class_id, problem_id)
    assert submitted["late"] == expected
    recent = client.get(f"{CLASSES_URL}/{class_id}/recent-attempts", **auth_header(instructor["access"]))
    assert recent.status_code == 200, recent.content
    assert recent.json()[0]["late"] == expected

    token = _connect(client, instructor["access"])["access_token"]
    grid = _ok(client, token, "get_roster_grid", {"class_id": class_id})
    member = next(m for m in grid["members"] if m["display_name"] == "참여자")
    assert member["cells"][0]["late"] == expected
    report = _ok(client, token, "get_participant_report", {"class_id": class_id})
    member = next(m for m in report["participants"] if m["display_name"] == "참여자")
    assert member["problems"][0]["late"] == expected
    assert member["problems"][0]["latest"]["late"] == expected


def test_exact_deadlines_are_not_late_and_deadline_wins_after_boundary(client, db):
    instructor, participant, class_id, problem_id = _setup_with_participant(client)
    submitted = submit_repository(client, participant["access"], class_id, problem_id)
    # HTTP 응답은 밀리초로 직렬화되므로 정확한 경계는 저장된 시각을 읽어 쓴다.
    at = ClassroomSubmission.objects.get(pk=submitted["id"]).created_at
    def check(recommended, due, expected):
        assert _patch(client, instructor["access"], class_id, problem_id, {
            "recommended_due_at": _iso(recommended), "due_at": _iso(due),
        }).status_code == 200
        assert mine(client, participant["access"], class_id, problem_id)["submissions"][0]["late"] == expected
    check(at, at, None)
    check(at - timedelta(microseconds=1), at, "recommended")
    check(at - timedelta(microseconds=1), at - timedelta(microseconds=1), "deadline")


@pytest.mark.parametrize("reason", ["archived", "expelled"])
def test_membership_blocks_remain_after_deadline(client, db, reason):
    instructor, participant, class_id, problem_id = _setup_with_participant(client, due=PAST)
    if reason == "archived":
        archive_class(client, instructor["access"], class_id)
    else:
        members = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(instructor["access"])).json()
        member_id = next(m["id"] for m in members if m["display_name"] == "참여자")
        expelled = client.post(f"{CLASSES_URL}/{class_id}/members/{member_id}/expel", **auth_header(instructor["access"]))
        assert expelled.status_code == 200, expelled.content
    assert mine(client, participant["access"], class_id, problem_id)["submit_blocked_reason"] == reason
    assert _try_submit(client, participant["access"], class_id, problem_id).status_code == 403


def test_the_grid_problem_header_carries_both_dates(client, db):
    # 격자 화면이 문제 목록에서 기한을 꿰매 넣지 않도록(#774) 문제 머리가 두 날짜를 싣는다.
    instructor, participant, class_id, problem_id = _setup_with_participant(client, recommended=PAST, due=FUTURE)
    second = _create(client, instructor["access"], class_id, {}).json()["id"]

    headers = {p["id"]: p for p in roster_grid(client, instructor["access"], class_id)["problems"]}
    assert (headers[problem_id]["recommended_due_at"], headers[problem_id]["due_at"]) == (_iso(PAST), _iso(FUTURE))
    assert (headers[second]["recommended_due_at"], headers[second]["due_at"]) == (None, None)


# --- 복사·템플릿은 두 날짜를 비운다 ------------------------------------------------


def test_copy_and_templates_leave_both_dates_empty(client, db):
    access = login(client, uid="due-instructor")["access"]
    source = create_class(client, access, name="1기")
    target = create_class(client, access, name="2기")
    problem = create_open_problem(client, access, source)
    assert _patch(
        client, access, source, problem.id, {"recommended_due_at": _iso(PAST), "due_at": _iso(FUTURE)}
    ).status_code == 200

    copied = client.post(
        f"{CLASSES_URL}/{source}/problems/{problem.id}/copy",
        data={"target_class_id": target},
        content_type="application/json",
        **auth_header(access),
    )
    assert copied.status_code == 201, copied.content
    assert (copied.json()["recommended_due_at"], copied.json()["due_at"]) == (None, None)

    class_copy = client.post(f"{CLASSES_URL}/{source}/copy", content_type="application/json", **auth_header(access))
    assert class_copy.status_code == 201, class_copy.content
    copied_problem = Class.objects.get(pk=class_copy.json()["id"]).problems.get()
    assert (copied_problem.recommended_due_at, copied_problem.due_at) == (None, None)

    published = client.post(
        f"{CLASSES_URL}/{source}/problems/{problem.id}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **auth_header(access),
    )
    assert published.status_code == 201, published.content
    assert "due_at" not in published.json()
    imported = client.post(
        f"{PROBLEM_TEMPLATES_URL}/{published.json()['share_code']}/import",
        data={"target_class_id": target},
        content_type="application/json",
        **auth_header(access),
    )
    assert imported.status_code == 201, imported.content
    assert (imported.json()["recommended_due_at"], imported.json()["due_at"]) == (None, None)

    class_published = client.post(
        f"{CLASSES_URL}/{source}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **auth_header(access),
    )
    assert class_published.status_code == 201, class_published.content
    class_imported = client.post(
        f"{CLASS_TEMPLATES_URL}/{class_published.json()['share_code']}/import",
        data={"name": "가져온 클래스"},
        content_type="application/json",
        **auth_header(access),
    )
    assert class_imported.status_code == 201, class_imported.content
    imported_problem = Class.objects.get(pk=class_imported.json()["id"]).problems.get()
    assert (imported_problem.recommended_due_at, imported_problem.due_at) == (None, None)


# --- 연결된 앱(MCP) -------------------------------------------------------------


def test_mcp_create_and_update_take_the_same_dates(client, db):
    instructor = login(client, uid="due-mcp-writer")
    class_id = create_class(client, instructor["access"], name="웹 스터디", with_key=False)
    token = _connect(client, instructor["access"])["access_token"]

    created = _ok(
        client,
        token,
        "create_problem",
        {
            "class_id": class_id,
            "title": "기한 있는 문제",
            "submission_formats": ["repository"],
            "recommended_due_at": _iso(PAST),
            "due_at": _iso(FUTURE),
        },
    )["problem"]
    assert (created["recommended_due_at"], created["due_at"]) == (_iso(PAST), _iso(FUTURE))
    ref = {"class_id": class_id, "problem_id": created["id"]}

    kept = _ok(client, token, "update_problem", {**ref, "title": "제목만"})["problem"]
    assert (kept["recommended_due_at"], kept["due_at"]) == (_iso(PAST), _iso(FUTURE))

    cleared = _ok(client, token, "update_problem", {**ref, "recommended_due_at": None})["problem"]
    assert (cleared["recommended_due_at"], cleared["due_at"]) == (None, _iso(FUTURE))

    assert _refused(
        client, token, "update_problem", {**ref, "recommended_due_at": _iso(FUTURE), "due_at": _iso(PAST)}
    ) == "권장 기한은 마감보다 늦을 수 없습니다."
    assert list_problems(client, instructor["access"], class_id)[0]["due_at"] == _iso(FUTURE)
