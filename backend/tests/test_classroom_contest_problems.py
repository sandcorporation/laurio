"""강사가 허용된 무료 공모전을 「공모전 문제」로 들여온다 — 제목·설명·체크리스트는 공모전을
따라간다 (#548, 스펙 #546, ADR-0054, CONTEXT.md 「공모전 문제」).

두 앱을 실제로 함께 돌린다. 개최자는 공모전 HTTP 로 열고 고치고, 강사는 강의실 HTTP 로
들여오고 고친다. 둘 사이는 공유층(`core.contest_catalog`)만 지난다. 공모전 쪽 「바뀌었다」
신호는 커밋 뒤에 나가므로 `django_capture_on_commit_callbacks(execute=True)` 로 흘린다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from classroom.models import ChecklistItem
from contests.models import Contest
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    force_real_scoring_adapter,
    join_class,
    login,
    open_problem,
    respond_with_verdict,
    run_scan,
    submit_source,
    user_id,
)
from tests.test_classroom_mcp_problem_tools import _refused
from tests.test_classroom_connected_apps import _connect
from tests.test_contest_classroom_import import _free_contest, _host
from tests.test_free_contest_hosting import (  # noqa: F401 — 픽스처 재사용
    CONTESTS_URL,
    _auth_header,
    category,
    landing_type,
)

pytestmark = pytest.mark.django_db

LOCKED = "공모전 문제의 제목·설명·체크리스트는 공모전을 따라갑니다. 수업용 안내에 덧붙여 주세요."


def _import(client, access, class_id, contest_id, *, expect=201):
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/from-contest",
        data={"contest_id": contest_id},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == expect, response.content
    return response.json()


def _problem(client, access, class_id, problem_id):
    response = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem_id}", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def _patch_problem(client, access, class_id, problem_id, **fields):
    return client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data=fields,
        content_type="application/json",
        **auth_header(access),
    )


@pytest.fixture
def world(client, category, landing_type):
    host = _host(client, "cp-host")
    contest = _free_contest(client, host, category, landing_type, title="할 일 웹앱")
    instructor = login(client, uid="cp-instructor")
    class_id = create_class(client, instructor["access"])
    return {"host": host, "contest": contest, "instructor": instructor, "class_id": class_id}


# --- 들여오기 ------------------------------------------------------------------


def test_instructor_lists_only_contests_the_host_opened_to_classes(client, world, category, landing_type):
    _free_contest(client, world["host"], category, landing_type, title="허용 안 함", allow=False)

    response = client.get(
        f"{CLASSES_URL}/{world['class_id']}/importable-contests", **auth_header(world["instructor"]["access"])
    )

    assert response.status_code == 200
    assert [(c["contest_id"], c["title"], c["requirement_count"]) for c in response.json()["items"]] == [
        (world["contest"]["id"], "할 일 웹앱", 2)
    ]
    assert response.json()["next"] is None


def _importable(client, world, **params):
    response = client.get(
        f"{CLASSES_URL}/{world['class_id']}/importable-contests",
        params,
        **auth_header(world["instructor"]["access"]),
    )
    assert response.status_code == 200, response.content
    return response.json()


def test_a_long_list_comes_twenty_at_a_time_in_deadline_order(client, world, category, landing_type):
    """공모전이 많아도 시트가 한 번에 다 받지 않는다 — 마감 빠른 순 20개씩, `next` 로 이어 받는다."""

    now = timezone.now()
    for day in range(1, 25):
        _free_contest(
            client, world["host"], category, landing_type,
            title=f"공모전 {day:02d}", deadline_at=now + timedelta(days=day),
        )

    first = _importable(client, world)
    second = _importable(client, world, after=first["next"])

    assert len(first["items"]) == 20
    assert first["next"] is not None
    titles = [c["title"] for c in first["items"] + second["items"]]
    assert len(titles) == 25 and len(set(titles)) == 25
    deadlines = [c["deadline_at"] for c in first["items"] + second["items"]]
    assert deadlines == sorted(deadlines)
    assert second["next"] is None


def test_the_list_is_searchable_by_title(client, world, category, landing_type):
    _free_contest(client, world["host"], category, landing_type, title="날씨 앱 만들기")

    found = _importable(client, world, q="날씨")

    assert [c["title"] for c in found["items"]] == ["날씨 앱 만들기"]


def test_a_broken_cursor_is_refused(client, world):
    response = client.get(
        f"{CLASSES_URL}/{world['class_id']}/importable-contests",
        {"after": "not-a-cursor"},
        **auth_header(world["instructor"]["access"]),
    )

    assert response.status_code == 422


def test_imported_problem_follows_the_contest_title_description_and_requirements(client, world):
    problem = _import(client, world["instructor"]["access"], world["class_id"], world["contest"]["id"])

    assert problem["status"] == "draft"
    assert problem["title"] == "할 일 웹앱"
    assert problem["description"] == world["contest"]["description"]
    assert [(i["label"], i["required"]) for i in problem["checklist_items"]] == [
        ("할 일을 추가할 수 있다", True),
        ("할 일을 완료로 표시할 수 있다", False),
    ]
    assert problem["submission_formats"] == ["source", "repository"]
    assert problem["contest"]["contest_id"] == world["contest"]["id"]
    assert problem["contest"]["accepts_entries"] is True


def test_a_contest_the_host_did_not_open_cannot_be_imported(client, world, category, landing_type):
    closed_door = _free_contest(client, world["host"], category, landing_type, allow=False)

    response = _import(client, world["instructor"]["access"], world["class_id"], closed_door["id"], expect=422)

    assert "들여올 수 없는 공모전" in response["detail"]


# --- 잠금 ----------------------------------------------------------------------


def test_title_description_and_checklist_are_locked_but_class_settings_are_not(client, world):
    access = world["instructor"]["access"]
    problem = _import(client, access, world["class_id"], world["contest"]["id"])
    base = f"{CLASSES_URL}/{world['class_id']}/problems/{problem['id']}"
    item_id = problem["checklist_items"][0]["id"]

    assert _patch_problem(client, access, world["class_id"], problem["id"], title="딴 제목").json()["detail"] == LOCKED
    assert _patch_problem(client, access, world["class_id"], problem["id"], description="딴 설명").status_code == 422
    for response in (
        client.post(f"{base}/checklist-items", data={"label": "더", "required": True}, content_type="application/json", **auth_header(access)),
        client.patch(f"{base}/checklist-items/{item_id}", data={"label": "고침"}, content_type="application/json", **auth_header(access)),
        client.delete(f"{base}/checklist-items/{item_id}", **auth_header(access)),
        client.post(f"{base}/checklist-items/reorder", data={"item_ids": [i["id"] for i in reversed(problem["checklist_items"])]}, content_type="application/json", **auth_header(access)),
    ):
        assert response.status_code == 422, response.content
        assert response.json()["detail"] == LOCKED

    updated = _patch_problem(
        client,
        access,
        world["class_id"],
        problem["id"],
        instructor_note="3주차 과제입니다. README 에 실행 방법을 적어 주세요.",
        grading_strictness="lenient",
        submission_formats=["repository"],
    )
    assert updated.status_code == 200, updated.content
    body = updated.json()
    assert body["instructor_note"].startswith("3주차 과제")
    assert (body["grading_strictness"], body["submission_formats"]) == ("lenient", ["repository"])


def test_instructor_note_belongs_only_to_contest_problems(client, world):
    from tests.classroom_scenarios import create_open_problem

    plain = create_open_problem(client, world["instructor"]["access"], world["class_id"], open=False)

    response = _patch_problem(client, world["instructor"]["access"], world["class_id"], plain.id, instructor_note="안내")

    assert response.status_code == 422


def test_a_connected_app_gets_the_same_refusal(client, world):
    access = world["instructor"]["access"]
    problem = _import(client, access, world["class_id"], world["contest"]["id"])
    token = _connect(client, access)["access_token"]

    refusal = _refused(
        client, token, "update_problem", {"class_id": world["class_id"], "problem_id": problem["id"], "title": "앱이 바꾼 제목"}
    )

    assert refusal == LOCKED


# --- 따라가기 -------------------------------------------------------------------


def test_host_edits_flow_into_the_problem_keeping_item_identity(client, world, django_capture_on_commit_callbacks):
    access = world["instructor"]["access"]
    problem = _import(client, access, world["class_id"], world["contest"]["id"])
    first_item_id = problem["checklist_items"][0]["id"]
    contest_id = world["contest"]["id"]
    requirement_ids = [r["id"] for r in world["contest"]["requirements"]]
    host_header = _auth_header(world["host"]["access"])

    with django_capture_on_commit_callbacks(execute=True):
        client.patch(f"{CONTESTS_URL}/{contest_id}", data={"title": "할 일 웹앱 v2"}, content_type="application/json", **host_header)
    with django_capture_on_commit_callbacks(execute=True):
        client.patch(
            f"{CONTESTS_URL}/{contest_id}/requirements/{requirement_ids[0]}",
            data={"text": "할 일을 추가·수정할 수 있다"},
            content_type="application/json",
            **host_header,
        )
    with django_capture_on_commit_callbacks(execute=True):
        client.delete(f"{CONTESTS_URL}/{contest_id}/requirements/{requirement_ids[1]}", **host_header)
    with django_capture_on_commit_callbacks(execute=True):
        client.post(
            f"{CONTESTS_URL}/{contest_id}/requirements",
            data={"text": "할 일을 지울 수 있다", "grade": "required"},
            content_type="application/json",
            **host_header,
        )

    after = _problem(client, access, world["class_id"], problem["id"])
    assert after["title"] == "할 일 웹앱 v2"
    assert [(i["label"], i["required"]) for i in after["checklist_items"]] == [
        ("할 일을 추가·수정할 수 있다", True),
        ("할 일을 지울 수 있다", True),
    ]
    # 시도의 판정이 항목 id 를 가리키므로 고쳐진 항목은 같은 행이다.
    assert after["checklist_items"][0]["id"] == first_item_id


def test_after_the_deadline_the_problem_stays_but_stops_accepting_entries(client, world):
    access = world["instructor"]["access"]
    problem = _import(client, access, world["class_id"], world["contest"]["id"])
    Contest.objects.filter(pk=world["contest"]["id"]).update(deadline_at=timezone.now() - timedelta(minutes=1))

    after = _problem(client, access, world["class_id"], problem["id"])

    assert after["contest"]["accepts_entries"] is False
    assert after["title"] == "할 일 웹앱"


def test_turning_the_allowance_off_closes_entries_for_imported_problems(client, world, django_capture_on_commit_callbacks):
    access = world["instructor"]["access"]
    problem = _import(client, access, world["class_id"], world["contest"]["id"])

    with django_capture_on_commit_callbacks(execute=True):
        client.patch(
            f"{CONTESTS_URL}/{world['contest']['id']}",
            data={"allows_classroom_import": False},
            content_type="application/json",
            **_auth_header(world["host"]["access"]),
        )

    assert _problem(client, access, world["class_id"], problem["id"])["contest"]["accepts_entries"] is False


# --- 복사·템플릿 ---------------------------------------------------------------


def test_a_copied_class_keeps_following_the_contest(client, world, django_capture_on_commit_callbacks):
    access = world["instructor"]["access"]
    _import(client, access, world["class_id"], world["contest"]["id"])
    copied = client.post(f"{CLASSES_URL}/{world['class_id']}/copy", **auth_header(access))
    assert copied.status_code == 201, copied.content
    new_class_id = copied.json()["id"]

    with django_capture_on_commit_callbacks(execute=True):
        client.patch(
            f"{CONTESTS_URL}/{world['contest']['id']}",
            data={"title": "다음 학기에도"},
            content_type="application/json",
            **_auth_header(world["host"]["access"]),
        )

    problems = client.get(f"{CLASSES_URL}/{new_class_id}/problems", **auth_header(access)).json()
    assert [p["title"] for p in problems] == ["다음 학기에도"]
    assert problems[0]["contest"]["contest_id"] == world["contest"]["id"]
    assert ChecklistItem.objects.filter(problem_id=problems[0]["id"], contest_requirement_id__isnull=False).count() == 2


def test_contest_problems_are_not_published_as_templates(client, world):
    access = world["instructor"]["access"]
    problem = _import(client, access, world["class_id"], world["contest"]["id"])

    response = client.post(
        f"{CLASSES_URL}/{world['class_id']}/problems/{problem['id']}/publish-template",
        data={"publisher_display_name": "강사"},
        content_type="application/json",
        **auth_header(access),
    )

    assert response.status_code == 422
    assert "개최자의 글" in response.json()["detail"]


# --- 채점 ----------------------------------------------------------------------


def test_scoring_a_contest_problem_uses_the_contest_requirements(client, world, monkeypatch):
    access = world["instructor"]["access"]
    problem = _import(client, access, world["class_id"], world["contest"]["id"])
    open_problem(client, access, world["class_id"], problem["id"])
    participant = login(client, uid="cp-participant")
    join_class(client, participant["access"], world["class_id"], instructor_access=access)
    submit_source(
        client,
        participant["access"],
        world["class_id"],
        problem["id"],
        participant_user_id=user_id("cp-participant"),
        files={"app.js": "function add(todo) {}\n"},
    )
    captured: list = []
    with force_real_scoring_adapter():
        respond_with_verdict(monkeypatch, problem["checklist_items"][0]["id"], is_met=True, capture=captured)
        run_scan(client)

    prompt = captured[0]["messages"][1]["content"]
    assert "할 일을 추가할 수 있다" in prompt
    assert "할 일을 완료로 표시할 수 있다" in prompt
