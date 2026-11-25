"""강의실 알림 목록은 채점 알림마다 그 문제의 **지금** 상태를 싣는다 (#1405).

화면은 같은 문제의 알림을 한 줄로 접고 머리글에 「지금 상태」와 시도 수를 적는다. 그 값을
불러온 알림에서 세면, 통과 알림이 다음 쪽에 있을 때 첫 쪽만 본 사람이 틀린 상태를 읽는다.
"""

from __future__ import annotations

from django.db import connection
from django.test.utils import CaptureQueriesContext

from notifications import api as notifications_api
from tests.classroom_scenarios import (
    add_checklist_item,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    internal_headers,
    join_class,
    login,
    my_problems,
    respond_with_verdict,
    run_scan,
    submit_repository,
    user_id,
)

_ME_URL = "/api/notifications/me?classroom_only=true"


def _setup(client) -> dict:
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    participant = login(client, uid="participant-1")
    problem = create_open_problem(client, instructor["access"], class_id, syntax_check_enabled=False)
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    return {"instructor": instructor, "participant": participant, "class_id": class_id, "problem": problem}


def _attempt(client, monkeypatch, ctx: dict, problem, *, is_met: bool) -> None:
    submit_repository(client, ctx["participant"]["access"], ctx["class_id"], problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=is_met)
    with force_real_scoring_adapter():
        run_scan(client)


def _page(client, access: str, url: str = _ME_URL) -> dict:
    response = client.get(url, **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def test_first_page_says_passed_even_when_the_passing_notification_is_on_the_next_page(
    client, db, monkeypatch
):
    ctx = _setup(client)
    _attempt(client, monkeypatch, ctx, ctx["problem"], is_met=True)
    _attempt(client, monkeypatch, ctx, ctx["problem"], is_met=False)
    monkeypatch.setattr(notifications_api, "NOTIFICATION_HISTORY_PAGE_SIZE", 1)

    first = _page(client, ctx["participant"]["access"])
    second = _page(client, ctx["participant"]["access"], f"{_ME_URL}&after={first['next']}")

    assert first["items"][0]["context"]["passed"] is False
    expected = {"passed": True, "attempt_count": 2}
    assert first["items"][0]["problem_status"] == expected
    assert second["items"][0]["problem_status"] == expected


def test_status_follows_the_current_checklist_like_my_problem_list(client, db, monkeypatch):
    ctx = _setup(client)
    _attempt(client, monkeypatch, ctx, ctx["problem"], is_met=True)
    add_checklist_item(
        client, ctx["instructor"]["access"], ctx["class_id"], ctx["problem"].id, "뒤에 더한 필수"
    )

    item = _page(client, ctx["participant"]["access"])["items"][0]

    listed = my_problems(client, ctx["participant"]["access"], ctx["class_id"])["problems"][0]
    assert listed["passed"] is False
    assert item["context"]["passed"] is True
    assert item["problem_status"] == {"passed": False, "attempt_count": listed["attempt_count"]}


def test_a_notification_pointing_at_a_problem_the_recipient_never_submitted_has_no_status(
    client, db, monkeypatch
):
    """남의 시도·문제 존재는 새로 드러나지 않는다 — 상태는 받는 사람 자신의 시도로만 센다."""

    ctx = _setup(client)
    _attempt(client, monkeypatch, ctx, ctx["problem"], is_met=True)
    outsider = login(client, uid="outsider-1")
    for problem_id in (ctx["problem"].id, 999_999, "문자열"):
        created = client.post(
            "/api/internal/notifications",
            data={
                "recipient_id": user_id("outsider-1"),
                "notification_type": "classroom_submission_scored",
                "context": {"class_id": ctx["class_id"], "problem_id": problem_id},
            },
            content_type="application/json",
            **internal_headers(),
        )
        assert created.status_code == 200, created.content

    items = _page(client, outsider["access"])["items"]

    assert [item["problem_status"] for item in items] == [None, None, None]


def test_query_count_does_not_grow_with_the_number_of_problems(client, db, monkeypatch):
    ctx = _setup(client)
    _attempt(client, monkeypatch, ctx, ctx["problem"], is_met=True)

    def count_queries() -> int:
        with CaptureQueriesContext(connection) as captured:
            _page(client, ctx["participant"]["access"])
        return len(captured)

    one_problem = count_queries()
    second = create_open_problem(
        client, ctx["instructor"]["access"], ctx["class_id"], title="2주차", syntax_check_enabled=False
    )
    _attempt(client, monkeypatch, ctx, second, is_met=True)

    assert count_queries() == one_problem
