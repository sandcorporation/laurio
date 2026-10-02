"""강사가 제출 현황·명단 격자·연결된 앱에서 참여자가 공모전에도 냈는지, 어느 시도였는지 본다
(#550, 스펙 #546, ADR-0054, CONTEXT.md 「공모전에도 내기」).

준비는 #549 시험의 무대(`world`)를 그대로 쓴다 — 개최자가 연 무료 공모전, 그것을 들여와 연
클래스, 가입한 참여자 하나. 결과는 전부 강사 HTTP·연결된 앱 MCP 로 읽는다.
"""

from __future__ import annotations

import pytest
from django.core.cache import caches

from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    join_class,
    login,
    roster_grid,
)
from tests.test_classroom_contest_entries import (  # noqa: F401 — 무대와 픽스처 재사용
    _entry,
    _no_scoring_broker,
    _requirement_ids,
    _submit,
    world,
)
from tests.test_classroom_connected_apps import _connect
from tests.test_classroom_mcp_report_tools import _expel, _structured
from tests.test_free_contest_hosting import (  # noqa: F401 — 픽스처 재사용
    CONTESTS_URL,
    _auth_header,
    category,
    landing_type,
)

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


def _instructor_rows(client, world) -> list[dict]:
    response = client.get(
        f"{CLASSES_URL}/{world['class_id']}/problems/{world['problem']['id']}/submissions",
        **auth_header(world["instructor"]["access"]),
    )
    assert response.status_code == 200, response.content
    return sorted(response.json(), key=lambda r: r["attempt_number"])


def _cell(client, world) -> dict:
    grid = roster_grid(client, world["instructor"]["access"], world["class_id"])
    member = next(m for m in grid["members"] if not m["is_instructor"])
    return next(c for c in member["cells"] if c["problem_id"] == world["problem"]["id"])


def test_the_submission_list_marks_entered_attempts_and_the_current_one(
    client, world, django_capture_on_commit_callbacks
):
    requirement_ids = _requirement_ids(client, world)
    capture = django_capture_on_commit_callbacks
    _submit(client, world, entry=_entry(requirement_ids), capture=capture)
    _submit(client, world, capture=capture)
    _submit(client, world, entry=_entry(requirement_ids, replace=True), capture=capture)

    first, second, third = _instructor_rows(client, world)

    assert (first["contest_entry"]["status"], first["is_current_contest_entry"]) == ("entered", False)
    assert (second["contest_entry"], second["is_current_contest_entry"]) == (None, False)
    assert (third["contest_entry"]["status"], third["is_current_contest_entry"]) == ("entered", True)
    # 보이는 것은 「냈는지와 어느 시도인지」뿐이다 — 근거·공모전 점수·수상은 없다.
    assert set(third["contest_entry"]) == {"status", "reason"}
    body = str(_instructor_rows(client, world))
    assert "구현했다" not in body and "00:12" not in body
    assert _cell(client, world)["contest_entry"] == "current"


def test_a_direct_edit_on_the_contest_takes_the_current_mark_away(
    client, world, django_capture_on_commit_callbacks
):
    _submit(client, world, entry=_entry(_requirement_ids(client, world)), capture=django_capture_on_commit_callbacks)
    edited = client.put(
        f"{CONTESTS_URL}/{world['contest']['id']}/submissions/me",
        data={
            "assets": [{"kind": "repository", "value": "https://github.com/me/direct"}],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(world["participant"]["access"]),
    )
    assert edited.status_code == 200, edited.content

    (row,) = _instructor_rows(client, world)

    assert row["contest_entry"]["status"] == "entered"
    assert row["is_current_contest_entry"] is False
    assert _cell(client, world)["contest_entry"] == "entered"


def test_a_newer_entry_from_another_class_wins(client, world, django_capture_on_commit_callbacks):
    capture = django_capture_on_commit_callbacks
    requirement_ids = _requirement_ids(client, world)
    _submit(client, world, entry=_entry(requirement_ids), capture=capture)

    other_instructor = login(client, uid="ce-other-instructor")
    other_class = create_class(client, other_instructor["access"])
    imported = client.post(
        f"{CLASSES_URL}/{other_class}/problems/from-contest",
        data={"contest_id": world["contest"]["id"]},
        content_type="application/json",
        **auth_header(other_instructor["access"]),
    ).json()
    client.post(
        f"{CLASSES_URL}/{other_class}/problems/{imported['id']}/open",
        content_type="application/json",
        **auth_header(other_instructor["access"]),
    )
    join_class(client, world["participant"]["access"], other_class, instructor_access=other_instructor["access"])
    other_world = {**world, "class_id": other_class, "problem": imported, "instructor": other_instructor}
    _submit(client, other_world, entry=_entry(requirement_ids, replace=True), capture=capture)

    assert _cell(client, world)["contest_entry"] == "entered"
    assert _cell(client, other_world)["contest_entry"] == "current"


def test_the_marks_stay_after_the_participant_is_expelled_and_the_problem_hidden(
    client, world, django_capture_on_commit_callbacks
):
    _submit(client, world, entry=_entry(_requirement_ids(client, world)), capture=django_capture_on_commit_callbacks)
    access = world["instructor"]["access"]
    _expel(client, access, world["class_id"], "참여자")
    hidden = client.post(
        f"{CLASSES_URL}/{world['class_id']}/problems/{world['problem']['id']}/hide",
        content_type="application/json",
        **auth_header(access),
    )
    assert hidden.status_code == 200, hidden.content

    (row,) = _instructor_rows(client, world)
    assert row["is_current_contest_entry"] is True
    assert _cell(client, world)["contest_entry"] == "current"


def test_a_connected_app_sees_the_same_marks(client, world, django_capture_on_commit_callbacks):
    _submit(client, world, entry=_entry(_requirement_ids(client, world)), capture=django_capture_on_commit_callbacks)
    token = _connect(client, world["instructor"]["access"])["access_token"]
    (row,) = _instructor_rows(client, world)

    report = _structured(client, token, "get_participant_report", class_id=world["class_id"])
    grid = _structured(client, token, "get_roster_grid", class_id=world["class_id"])

    participant = next(p for p in report["participants"] if not p["is_instructor"])
    (cell,) = participant["problems"]
    assert cell["contest_entry"] == "current"
    assert cell["contest_entry_submission_id"] == row["id"]
    grid_member = next(m for m in grid["members"] if not m["is_instructor"])
    assert grid_member["cells"][0]["contest_entry"] == "current"
