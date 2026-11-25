"""강의실 접근 계약 고정 (#1390).

화면이 404 안내를 제 목록으로 고르는 전제(D1 안 C)를 못 박는다 — 강사 전용 GET 은 비강사
누구에게나 **같은** 404 를 주고(존재 숨김, #278), 참여자의 제출 화면은 「볼 수 있는가 →
낼 수 있는가(보관 → 내보냄 → 숨김)」 순서로 답한다(Spec §4.2).
"""

from __future__ import annotations

import json

import pytest

from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    archive_class,
    auth_header,
    create_class,
    create_open_problem,
    instructor_submissions,
    join_class,
    leave_class,
    login,
    submit_repository,
)

pytestmark = pytest.mark.django_db

CLASS_NOT_FOUND = json.dumps({"detail": "클래스를 찾을 수 없습니다."}).encode()

INSTRUCTOR_GETS = [
    "",
    "/scoring-models",
    "/scoring-cost",
    "/scoring-calculator",
    "/instructors",
    "/co-instructor-invites",
    "/members",
    "/roster-grid",
    "/recent-attempts",
    "/attempts",
    "/attempts/{sid}/verdicts",
    "/problems",
    "/importable-contests",
    "/problems/from-other-classes",
    "/problems/{pid}",
    "/problems/{pid}/submissions",
    "/problems/{pid}/quality",
    "/problems/{pid}/quality/estimate",
]


@pytest.fixture(autouse=True)
def _no_scoring_broker(monkeypatch):
    monkeypatch.setattr("classroom.api._enqueue_immediate_scoring", lambda submission_id: None)


def _get(client, access: str, path: str):
    return client.get(f"{CLASSES_URL}{path}", **auth_header(access))


def _post(client, access: str, path: str, data: dict | None = None):
    return client.post(
        f"{CLASSES_URL}{path}", data=data or {}, content_type="application/json", **auth_header(access)
    )


def _expel(client, owner: str, class_id: int, display_name: str) -> None:
    members = _get(client, owner, f"/{class_id}/members").json()
    member_id = next(m["id"] for m in members if m["display_name"] == display_name)
    response = _post(client, owner, f"/{class_id}/members/{member_id}/expel")
    assert response.status_code == 200, response.content


@pytest.mark.parametrize("archived", [False, True], ids=["진행", "보관"])
@pytest.mark.parametrize("route", INSTRUCTOR_GETS, ids=lambda r: r or "클래스")
def test_instructor_get_answers_instructors_only_and_hides_the_class_from_everyone_else(
    client, route, archived
):
    owner = login(client, "ac-owner")["access"]
    class_id = create_class(client, owner, with_key=False)
    problem = create_open_problem(client, owner, class_id)
    co, current, expelled, former, stranger = (
        login(client, f"ac-{name}")["access"]
        for name in ("co", "current", "expelled", "former", "stranger")
    )
    join_class(client, current, class_id, instructor_access=owner, display_name="현재")
    join_class(client, expelled, class_id, instructor_access=owner, display_name="내보냄")
    join_class(client, former, class_id, instructor_access=owner, display_name="전 공동 강사")
    submission = submit_repository(client, current, class_id, problem.id)
    add_co_instructor(client, owner, class_id, co)
    add_co_instructor(client, owner, class_id, former, display_name="떠날 강사")
    assert leave_class(client, former, class_id).status_code == 204
    _expel(client, owner, class_id, "내보냄")
    if archived:
        archive_class(client, owner, class_id)
    path = f"/{class_id}" + route.format(pid=problem.id, sid=submission["id"])

    for access in (owner, co):
        response = _get(client, access, path)
        assert response.status_code == 200, response.content

    # 참여자 셋과 무관한 사람의 본문이 바이트까지 같다 — 갈리면 존재가 새는 것이다.
    for access in (current, expelled, former, stranger):
        response = _get(client, access, path)
        assert (response.status_code, response.content) == (404, CLASS_NOT_FOUND)


def test_another_classs_problem_id_is_the_same_404_for_a_participant(client):
    owner = login(client, "ac-owner")["access"]
    class_id = create_class(client, owner, with_key=False)
    other_problem = create_open_problem(client, owner, create_class(client, owner, with_key=False))
    participant = login(client, "ac-current")["access"]
    join_class(client, participant, class_id, instructor_access=owner)

    for suffix in ("", "/submissions", "/quality", "/quality/estimate"):
        response = _get(client, participant, f"/{class_id}/problems/{other_problem.id}{suffix}")
        assert (response.status_code, response.content) == (404, CLASS_NOT_FOUND)


def _participation_world(client, *, archived: bool) -> dict:
    """문제 넷 — 열림 · 낸 적 있는 숨김 · 낸 적 없는 숨김 · 초안. 참여자 둘(하나는 내보냄)."""

    owner = login(client, "ac-owner")["access"]
    class_id = create_class(client, owner, with_key=False)
    problems = {
        "열림": create_open_problem(client, owner, class_id, title="열림").id,
        "낸 숨김": create_open_problem(client, owner, class_id, title="낸 숨김").id,
        "안 낸 숨김": create_open_problem(client, owner, class_id, title="안 낸 숨김").id,
        "초안": create_open_problem(client, owner, class_id, title="초안", open=False).id,
    }
    people = {"강사": owner}
    for name, uid in (("현재", "ac-current"), ("내보냄", "ac-expelled")):
        people[name] = login(client, uid)["access"]
        join_class(client, people[name], class_id, instructor_access=owner, display_name=name)
        submit_repository(client, people[name], class_id, problems["낸 숨김"])
    for key in ("낸 숨김", "안 낸 숨김"):
        response = _post(client, owner, f"/{class_id}/problems/{problems[key]}/hide")
        assert response.status_code == 200, response.content
    _expel(client, owner, class_id, "내보냄")
    if archived:
        archive_class(client, owner, class_id)
    return {"class_id": class_id, "problems": problems, "people": people}


NOT_VISIBLE = None  # 404 — 보이지 않는 문제에는 사유가 붙을 자리가 없다(D4).

#: (보관, 부른 사람, 문제, GET 의 `submit_blocked_reason` 또는 NOT_VISIBLE, POST 상태)
ROWS = [
    (False, "현재", "열림", "", 201),
    (False, "현재", "낸 숨김", "hidden", 403),
    (False, "내보냄", "열림", "expelled", 403),
    (False, "내보냄", "낸 숨김", "expelled", 403),
    *[(True, who, key, "archived", 403) for who in ("현재", "내보냄") for key in ("열림", "낸 숨김")],
    *[
        (archived, who, key, NOT_VISIBLE, 404)
        for archived in (False, True)
        for who in ("현재", "내보냄")
        for key in ("초안", "안 낸 숨김")
    ],
    *[(False, "강사", key, "", 201) for key in ("초안", "열림", "낸 숨김")],
    *[(True, "강사", key, "archived", 403) for key in ("초안", "열림", "낸 숨김")],
]


@pytest.mark.parametrize(
    ("archived", "who", "key", "reason", "post_status"),
    ROWS,
    ids=[f"{'보관' if r[0] else '진행'}-{r[1]}-{r[2]}" for r in ROWS],
)
def test_my_problem_and_submit_answer_by_visibility_then_blocked_reason(
    client, archived, who, key, reason, post_status
):
    world = _participation_world(client, archived=archived)
    class_id, problem_id = world["class_id"], world["problems"][key]
    access = world["people"][who]

    shown = _get(client, access, f"/{class_id}/problems/{problem_id}/mine")
    if reason is NOT_VISIBLE:
        assert shown.status_code == 404, shown.content
    else:
        assert shown.status_code == 200, shown.content
        assert shown.json()["submit_blocked_reason"] == (reason or None)
        assert shown.json()["viewing_as_instructor"] is (who == "강사")

    owner = world["people"]["강사"]
    before = len(instructor_submissions(client, owner, class_id, problem_id))
    posted = _post(
        client,
        access,
        f"/{class_id}/problems/{problem_id}/submissions",
        {"value": "https://github.com/octocat/hello-world", "submission_format": "repository"},
    )
    assert posted.status_code == post_status, posted.content
    if post_status != 201:
        assert len(instructor_submissions(client, owner, class_id, problem_id)) == before


@pytest.mark.parametrize(
    ("key", "detail"),
    [
        ("초안", "문제를 찾을 수 없습니다."),
        ("안 낸 숨김", "문제를 찾을 수 없습니다."),
        ("열림", "공모전 문제가 아닙니다."),
        ("남의 클래스", "문제를 찾을 수 없습니다."),
    ],
)
def test_contest_entry_form_is_404_behind_the_same_visibility(client, key, detail):
    world = _participation_world(client, archived=False)
    if key == "남의 클래스":
        owner = world["people"]["강사"]
        other = create_class(client, owner, with_key=False)
        problem_id = create_open_problem(client, owner, other).id
    else:
        problem_id = world["problems"][key]

    response = _get(
        client, world["people"]["현재"], f"/{world['class_id']}/problems/{problem_id}/contest-entry"
    )

    assert (response.status_code, response.json()["detail"]) == (404, detail)


def test_too_long_class_name_is_a_422_with_the_shape_the_screen_translates(client):
    owner = login(client, "ac-owner")["access"]

    response = _post(client, owner, "", {"name": "가" * 201, "instructor_display_name": "강사"})

    assert response.status_code == 422, response.content
    error = response.json()["detail"][0]
    assert (error["type"], error["ctx"]["max_length"]) == ("string_too_long", 200)
