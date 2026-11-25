"""문제 목록·격자 열을 바꾸는 쓰기마다 열어 둔 화면에 재조회 신호가 간다 (#1471 ⑦ 후속 2).

만들기·고치기·지우기·순서, 체크리스트 항목 넣기·고치기·지우기·순서, 다른 클래스로 복사, 템플릿·공모전에서
가져오기, 공모전 원본 동기화 — 그 클래스 강사 전원에게 `instructors-changed`(클래스 머리·격자·문제 목록), 참여자에게
보이는 문제(초안이 아닌 것)면 살아 있는 참여자에게 `participation-changed`(문제 목록·제출 화면)도 간다. 초안만
바뀌면 참여자는 받지 않는다. 바깥 클래스의 강사·참여자는 어느 신호도 받지 않는다. 본문의 `class_id` 를 본다(강사
신호의 `rev` 는 `test_classroom_refresh_signals.py` 가 본다).

경로가 화면 API 든 연결된 앱(MCP)이든 같은 도메인 함수를 지난다 — MCP 는 만들기 하나로 그 사실을 본다.
문제 열기·숨김·다시 열기는 `test_classroom_refresh_signals.py` 가 본다.
"""

from __future__ import annotations

import pytest

from core.events import FakeEventBus
from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    add_checklist_item,
    auth_header,
    create_class,
    create_open_problem,
    join_class,
    login,
    user_id,
)

from classroom.tests.test_classroom_connected_apps import _connect
from classroom.tests.test_classroom_mcp_problem_tools import _ok

pytestmark = pytest.mark.django_db

INSTRUCTORS_CHANGED = "instructors-changed"
PARTICIPATION_CHANGED = "participation-changed"
EVERYONE = {"owner", "co", "alice", "outsider-owner", "outsider"}


def _signals(uid: str, kind: str) -> list[dict]:
    return [e.payload for e in FakeEventBus._queues.get(user_id(uid), []) if e.kind == kind]


def _assert_only(kind: str, class_id: int, receivers: set[str]) -> None:
    for uid in EVERYONE:
        got = _signals(uid, kind)
        if uid in receivers:
            assert got and all(p["class_id"] == class_id for p in got), (kind, uid, got)
        else:
            assert got == [], (kind, uid, got)


def _expect(class_id: int, *, participants: bool) -> None:
    _assert_only(INSTRUCTORS_CHANGED, class_id, {"owner", "co"})
    _assert_only(PARTICIPATION_CHANGED, class_id, {"alice"} if participants else set())


def _send(client, method: str, access: str, path: str, data: dict | None = None):
    call = getattr(client, method)
    kwargs = {"content_type": "application/json", **auth_header(access)}
    if data is not None or method != "delete":
        kwargs["data"] = data or {}
    response = call(path if path.startswith("/") else f"{CLASSES_URL}/{path}", **kwargs)
    assert response.status_code < 300, response.content
    return response.json() if response.content else None


@pytest.fixture
def scene(client):
    """소유자·공동 강사·참여자 앨리스가 있는 클래스(열린 문제 하나·초안 하나)와 바깥 클래스."""

    owner = login(client, uid="owner")
    co = login(client, uid="co")
    alice = login(client, uid="alice")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    opened = create_open_problem(client, owner["access"], class_id, title="열린 문제", optional_labels=["선택"])
    draft = create_open_problem(client, owner["access"], class_id, title="초안 문제", open=False)
    join_class(client, alice["access"], class_id, instructor_access=owner["access"], display_name="앨리스")

    outsider_owner = login(client, uid="outsider-owner")
    outsider = login(client, uid="outsider")
    other_class = create_class(client, outsider_owner["access"], name="다른 클래스", with_key=False)
    create_open_problem(client, outsider_owner["access"], other_class)
    join_class(client, outsider["access"], other_class, instructor_access=outsider_owner["access"])
    FakeEventBus._queues.clear()
    return {"owner": owner["access"], "class_id": class_id, "open": opened, "draft": draft}


def _run(django_capture_on_commit_callbacks, action):
    FakeEventBus._queues.clear()
    with django_capture_on_commit_callbacks(execute=True):
        return action()


# --- 문제 ---------------------------------------------------------------------


def test_creating_a_draft_signals_the_instructors_only(client, scene, django_capture_on_commit_callbacks):
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "post", scene["owner"], f"{scene['class_id']}/problems",
        {"title": "새 초안", "submission_formats": ["repository"]},
    ))
    _expect(scene["class_id"], participants=False)


def test_creating_an_open_problem_signals_the_participants_too(client, scene, django_capture_on_commit_callbacks):
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "post", scene["owner"], f"{scene['class_id']}/problems",
        {
            "title": "바로 여는 문제",
            "submission_formats": ["repository"],
            "open": True,
            "checklist_items": [{"label": "통과 조건", "required": True}],
        },
    ))
    _expect(scene["class_id"], participants=True)


def test_creating_through_a_connected_app_signals_the_same(client, scene, django_capture_on_commit_callbacks):
    token = _connect(client, scene["owner"])["access_token"]
    _run(django_capture_on_commit_callbacks, lambda: _ok(
        client, token, "create_problem",
        {"class_id": scene["class_id"], "title": "앱이 만든 초안", "submission_formats": ["repository"]},
    ))
    _expect(scene["class_id"], participants=False)


@pytest.mark.parametrize(("which", "participants"), [("open", True), ("draft", False)])
def test_editing_a_problem_signals(client, scene, django_capture_on_commit_callbacks, which, participants):
    problem = scene[which]
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "patch", scene["owner"], f"{scene['class_id']}/problems/{problem.id}", {"title": "고친 제목"},
    ))
    _expect(scene["class_id"], participants=participants)


def test_reordering_problems_signals_the_participants_too(client, scene, django_capture_on_commit_callbacks):
    order = [scene["draft"].id, scene["open"].id]
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "post", scene["owner"], f"{scene['class_id']}/problems/reorder", {"problem_ids": order},
    ))
    _expect(scene["class_id"], participants=True)


@pytest.mark.parametrize(("which", "participants"), [("open", True), ("draft", False)])
def test_deleting_a_problem_signals(client, scene, django_capture_on_commit_callbacks, which, participants):
    problem = scene[which]
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "delete", scene["owner"], f"{scene['class_id']}/problems/{problem.id}",
    ))
    _expect(scene["class_id"], participants=participants)


def test_copying_a_problem_signals_the_target_class_instructors_only(client, scene, django_capture_on_commit_callbacks):
    """복사본은 대상 클래스의 초안이다 — 원본 클래스는 바뀌지 않는다."""

    target = create_class(client, scene["owner"], name="복사 대상", with_key=False)
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "post", scene["owner"], f"{scene['class_id']}/problems/{scene['open'].id}/copy",
        {"target_class_id": target},
    ))
    assert [p["class_id"] for p in _signals("owner", INSTRUCTORS_CHANGED)] == [target]
    for uid in EVERYONE - {"owner"}:
        assert _signals(uid, INSTRUCTORS_CHANGED) == [], uid
        assert _signals(uid, PARTICIPATION_CHANGED) == [], uid


def test_copying_a_class_sends_no_per_problem_signals(client, scene, django_capture_on_commit_callbacks):
    """방금 만든 클래스라 열린 화면이 없다 — 문제마다 신호를 보내지 않는다."""

    _run(django_capture_on_commit_callbacks, lambda: _send(client, "post", scene["owner"], f"{scene['class_id']}/copy"))
    for uid in EVERYONE:
        assert _signals(uid, INSTRUCTORS_CHANGED) == [], uid


def test_importing_a_problem_template_signals_the_target_class_instructors_only(
    client, scene, django_capture_on_commit_callbacks
):
    published = _send(
        client, "post", scene["owner"], f"{scene['class_id']}/problems/{scene['open'].id}/publish-template",
        {"publisher_display_name": "강사"},
    )
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "post", scene["owner"], f"/api/classroom/problem-templates/{published['share_code']}/import",
        {"target_class_id": scene["class_id"]},
    ))
    _expect(scene["class_id"], participants=False)


# --- 체크리스트 -------------------------------------------------------------------


@pytest.mark.parametrize(("which", "participants"), [("open", True), ("draft", False)])
def test_adding_a_checklist_item_signals(client, scene, django_capture_on_commit_callbacks, which, participants):
    problem = scene[which]
    _run(django_capture_on_commit_callbacks, lambda: add_checklist_item(
        client, scene["owner"], scene["class_id"], problem.id, "새 항목", required=False
    ))
    _expect(scene["class_id"], participants=participants)


def test_editing_a_checklist_item_signals_the_participants_of_an_open_problem(
    client, scene, django_capture_on_commit_callbacks
):
    problem = scene["open"]
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "patch", scene["owner"],
        f"{scene['class_id']}/problems/{problem.id}/checklist-items/{problem.item_ids[1]}", {"label": "고친 항목"},
    ))
    _expect(scene["class_id"], participants=True)


def test_deleting_a_checklist_item_signals_the_participants_of_an_open_problem(
    client, scene, django_capture_on_commit_callbacks
):
    problem = scene["open"]
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "delete", scene["owner"],
        f"{scene['class_id']}/problems/{problem.id}/checklist-items/{problem.item_ids[1]}",
    ))
    _expect(scene["class_id"], participants=True)


def test_reordering_checklist_items_signals_the_participants_of_an_open_problem(
    client, scene, django_capture_on_commit_callbacks
):
    problem = scene["open"]
    _run(django_capture_on_commit_callbacks, lambda: _send(
        client, "post", scene["owner"],
        f"{scene['class_id']}/problems/{problem.id}/checklist-items/reorder",
        {"item_ids": list(reversed(problem.item_ids))},
    ))
    _expect(scene["class_id"], participants=True)
