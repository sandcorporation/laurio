"""통과 여부가 다섯 화면에서 언제나 같다 — Problem이 스스로 답한다 (#436,
spec #432).

핵심 대상: 「이 판정이 이 문제에서 통과인가」를 `Problem.is_score_passed`
하나가 답하고, 달성률(`GET .../problems`)·참여자별 현황 격자(`.../roster-
grid`)·참여자의 문제 목록(`.../problems/mine`)·제출 목록(`.../{problem_id}/
mine`)·채점 완료 알림(`CLASSROOM_SUBMISSION_SCORED`)이 모두 같은 값을
쓴다. 문법 검사를 켠 문제와 끈 문제 양쪽에서 다섯이 어긋나지 않는지 본다.
"""

from __future__ import annotations

from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext

from notifications.models import Notification, NotificationType

from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    list_problems,
    login,
    mine,
    my_problems,
    respond_with_verdict,
    roster_grid,
    run_scan,
    submit_repository,
)

_REPO_URL = "https://github.com/octocat/pass-consistency-repo"
_CHECKLIST_LABEL = "print가 있다"
#: 문법 오류가 없는 소스 — 문법 검사를 켠 문제에서도 그 항목이 통과한다.
_VALID_SOURCE = "def f():\n    x = 1\n    print(x)\n    return x\n"
#: 들여쓰기가 깨진 소스 — 문법 검사를 켜면 그 항목이 미달, 꺼두면 무관하다.
_SYNTAX_BROKEN_SOURCE = "def f():\n    x = 1\n        return x\n    print(x)\n"


def _cell_status(grid: dict, member_id: int, problem_id: int) -> str:
    member = next(m for m in grid["members"] if m["id"] == member_id)
    return next(c for c in member["cells"] if c["problem_id"] == problem_id)["status"]


def _run_scenario(client, monkeypatch, *, syntax_check_enabled: bool, source: str) -> dict:
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(
        client,
        instructor["access"],
        class_id,
        submission_formats=["repository"],
        required_labels=[_CHECKLIST_LABEL],
        syntax_check_enabled=syntax_check_enabled,
    )
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])

    with override_settings(GITHUB_FAKE_REPO_FILES={_REPO_URL: {"app.py": source}}):
        submitted = submit_repository(client, participant["access"], class_id, problem.id, _REPO_URL)
        respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
        with force_real_scoring_adapter():
            run_scan(client)

    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem.id,
        "submission_id": submitted["id"],
    }


def _assert_passed_everywhere(client, ctx: dict) -> None:
    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine_out["submissions"][0]["passed"] is True

    my_problems_out = my_problems(client, ctx["participant"]["access"], ctx["class_id"])
    my_problem = next(p for p in my_problems_out["problems"] if p["id"] == ctx["problem_id"])
    assert my_problem["passed"] is True

    problems_out = list_problems(client, ctx["instructor"]["access"], ctx["class_id"])
    problem_out = next(p for p in problems_out if p["id"] == ctx["problem_id"])
    assert problem_out["passed_count"] == 1

    grid = roster_grid(client, ctx["instructor"]["access"], ctx["class_id"])
    participant_row = next(m for m in grid["members"] if not m["is_instructor"])
    assert _cell_status(grid, participant_row["id"], ctx["problem_id"]) == "passed"

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
        context__submission_id=ctx["submission_id"],
    )
    assert notification.context["passed"] is True


def test_syntax_check_enabled_agrees_across_all_five_screens_when_passed(client, db, monkeypatch):
    ctx = _run_scenario(
        client, monkeypatch, syntax_check_enabled=True, source=_VALID_SOURCE
    )
    _assert_passed_everywhere(client, ctx)


def test_syntax_check_disabled_agrees_across_all_five_screens_despite_broken_source(
    client, db, monkeypatch
):
    """문법 검사를 꺼 두면 실제로는 들여쓰기가 깨진 소스여도 그 항목이
    판정에 관여하지 않아 다섯 화면 모두 통과로 본다."""

    ctx = _run_scenario(
        client, monkeypatch, syntax_check_enabled=False, source=_SYNTAX_BROKEN_SOURCE
    )
    _assert_passed_everywhere(client, ctx)


def test_syntax_check_enabled_agrees_across_all_five_screens_when_syntax_fails(
    client, db, monkeypatch
):
    """문법 검사를 켠 문제에서 문법이 깨지면, 체크리스트 항목이 충족돼도
    다섯 화면 모두 미통과로 본다."""

    ctx = _run_scenario(
        client, monkeypatch, syntax_check_enabled=True, source=_SYNTAX_BROKEN_SOURCE
    )

    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine_out["submissions"][0]["score"]["syntax_check"]["is_met"] is False
    assert mine_out["submissions"][0]["passed"] is False

    my_problems_out = my_problems(client, ctx["participant"]["access"], ctx["class_id"])
    my_problem = next(p for p in my_problems_out["problems"] if p["id"] == ctx["problem_id"])
    assert my_problem["passed"] is False

    problems_out = list_problems(client, ctx["instructor"]["access"], ctx["class_id"])
    problem_out = next(p for p in problems_out if p["id"] == ctx["problem_id"])
    assert problem_out["passed_count"] == 0

    grid = roster_grid(client, ctx["instructor"]["access"], ctx["class_id"])
    participant_row = next(m for m in grid["members"] if not m["is_instructor"])
    assert _cell_status(grid, participant_row["id"], ctx["problem_id"]) == "attempted_not_passed"

    notification = Notification.objects.get(
        notification_type=NotificationType.CLASSROOM_SUBMISSION_SCORED,
        context__submission_id=ctx["submission_id"],
    )
    assert notification.context["passed"] is False


def _checklist_item_selects(queries) -> int:
    return sum(
        1
        for q in queries
        if "classroom_checklistitem" in q["sql"] and q["sql"].lstrip().upper().startswith("SELECT")
    )


def test_roster_grid_reads_checklist_items_once_regardless_of_problem_count(client, db):
    """`Problem.is_score_passed`가 문제마다 체크리스트를 다시 읽지 않는다
    (#436 AC "목록·격자에서 문제 수만큼 질의가 늘지 않는다") — 다섯 문제가
    있어도 `get_roster_grid`의 `prefetch_related("checklist_items")` 하나가
    낸 SELECT 한 번으로 전부 해결된다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    for i in range(5):
        create_open_problem(client, instructor["access"], class_id, title=f"{i}주차")

    with CaptureQueriesContext(connection) as ctx:
        roster_grid(client, instructor["access"], class_id)

    assert _checklist_item_selects(ctx.captured_queries) == 1, [
        q["sql"] for q in ctx.captured_queries if "classroom_checklistitem" in q["sql"]
    ]


def test_problem_list_reads_checklist_items_once_regardless_of_problem_count(client, db):
    """`list_problems`(문제 중심 탭)도 같은 프리페치 하나로 해결된다 —
    `_problem_pass_stats`가 문제마다 `problem.checklist_items.all()`을 새로
    구하지 않는다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    for i in range(5):
        create_open_problem(client, instructor["access"], class_id, title=f"{i}주차")

    with CaptureQueriesContext(connection) as ctx:
        list_problems(client, instructor["access"], class_id)

    assert _checklist_item_selects(ctx.captured_queries) == 1, [
        q["sql"] for q in ctx.captured_queries if "classroom_checklistitem" in q["sql"]
    ]
