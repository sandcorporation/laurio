"""강의실 「완벽」 판정(#962, spec #960 B, ADR-0081) — 한 시도에서 필수·심화(`optional`) 항목이 전부 충족이다.

통과와 같은 규칙을 따른다: 지금 체크리스트로 다시 센다(저장하지 않는다), 확인 불가는 충족이 아니고, 숨긴 항목도
들어가고, 가산은 빠진다. 심화 항목이 없는 문제에는 완벽이 없다(`None` — 거짓·0명과 다르다).
준비와 확인은 마운트된 HTTP API 로 하고(`tests.classroom_scenarios`) 벤더 응답만 녹화본으로 흉내 낸다.
"""

from __future__ import annotations

import pytest
from django.core.cache import caches
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    instructor_submissions,
    join_class,
    login,
    mine,
    my_problems,
    respond_with_verdicts,
    roster_grid,
    run_scan,
    submit_repository,
)


@pytest.fixture(autouse=True)
def _real_scoring():
    caches["rate_limits"].clear()
    with force_real_scoring_adapter():
        yield
    caches["rate_limits"].clear()


def _add_item(client, access: str, class_id: int, problem_id: int, label: str, grade: str, *, hidden: bool = False) -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": label, "grade": grade, "hidden": hidden},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


def _attempt(client, monkeypatch, access: str, class_id: int, problem_id: int, verdicts: dict[int, str]) -> None:
    """시도 하나를 내고 항목마다 주어진 판정(met·unmet·unverifiable)으로 채점한다."""

    respond_with_verdicts(
        monkeypatch,
        [{"requirement_id": item_id, "verdict": verdict, "reasoning": "근거"} for item_id, verdict in verdicts.items()],
    )
    submit_repository(client, access, class_id, problem_id)
    run_scan(client)


@pytest.fixture
def world(client, db):
    """필수 하나·심화 둘(하나는 숨김)·가산 하나. 참여자 한 명."""

    owner = login(client, uid="perfect-owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(
        client, owner["access"], class_id, required_labels=["테스트가 있다"], optional_labels=["주석이 있다"],
        syntax_check_enabled=False,
    )
    required, advanced = problem.item_ids
    hidden_advanced = _add_item(client, owner["access"], class_id, problem.id, "README 가 있다", "optional", hidden=True)
    bonus = _add_item(client, owner["access"], class_id, problem.id, "타입이 있다", "bonus")
    student = login(client, uid="perfect-student")
    join_class(client, student["access"], class_id, instructor_access=owner["access"], display_name="가람")
    return {
        "owner": owner["access"],
        "student": student["access"],
        "class_id": class_id,
        "problem_id": problem.id,
        "required": required,
        "advanced": advanced,
        "hidden_advanced": hidden_advanced,
        "bonus": bonus,
    }


def _all(world: dict, **overrides: str) -> dict[int, str]:
    verdicts = {world[k]: "met" for k in ("required", "advanced", "hidden_advanced", "bonus")}
    for key, verdict in overrides.items():
        verdicts[world[key]] = verdict
    return verdicts


def _student_view(client, world: dict) -> tuple[dict, dict]:
    detail = mine(client, world["student"], world["class_id"], world["problem_id"])
    [listed] = my_problems(client, world["student"], world["class_id"])["problems"]
    return detail, listed


def _queries(fn) -> int:
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


def test_all_required_and_advanced_met_is_perfect_on_every_surface(client, world, monkeypatch):
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world))

    detail, listed = _student_view(client, world)
    assert detail["problem"]["passed"] is True and detail["problem"]["perfect"] is True
    assert [s["perfect"] for s in detail["submissions"]] == [True]
    assert listed["perfect"] is True

    grid = roster_grid(client, world["owner"], world["class_id"])
    assert grid["problems"][0]["passed_count"] == 1 and grid["problems"][0]["perfect_count"] == 1
    [row] = [m for m in grid["members"] if m["display_name"] == "가람"]
    assert row["cells"][0]["status"] == "passed" and row["cells"][0]["perfect"] is True
    [attempt] = instructor_submissions(client, world["owner"], world["class_id"], world["problem_id"])
    assert attempt["perfect"] is True


def test_an_unverifiable_advanced_item_passes_but_is_not_perfect(client, world, monkeypatch):
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world, advanced="unverifiable"))

    detail, listed = _student_view(client, world)
    assert detail["problem"]["passed"] is True and detail["problem"]["perfect"] is False
    assert detail["submissions"][0]["perfect"] is False and listed["perfect"] is False


def test_a_hidden_advanced_item_counts_even_though_the_student_cannot_see_it(client, world, monkeypatch):
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world, hidden_advanced="unmet"))

    detail, _ = _student_view(client, world)
    assert detail["problem"]["hidden_checklist_item_count"] == 1
    assert detail["problem"]["passed"] is True and detail["problem"]["perfect"] is False
    grid = roster_grid(client, world["owner"], world["class_id"])
    assert grid["problems"][0]["passed_count"] == 1 and grid["problems"][0]["perfect_count"] == 0


def test_an_unmet_bonus_item_does_not_stop_perfect(client, world, monkeypatch):
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world, bonus="unmet"))

    detail, _ = _student_view(client, world)
    assert detail["problem"]["perfect"] is True


def test_an_unmet_required_item_is_neither_passed_nor_perfect(client, world, monkeypatch):
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world, required="unmet"))

    detail, _ = _student_view(client, world)
    assert detail["problem"]["passed"] is False and detail["problem"]["perfect"] is False


def test_one_perfect_attempt_makes_the_problem_perfect_and_each_attempt_shows_its_own(client, world, monkeypatch):
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world))
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world, advanced="unmet"))

    detail, listed = _student_view(client, world)
    assert sorted((s["attempt_number"], s["perfect"]) for s in detail["submissions"]) == [(1, True), (2, False)]
    assert detail["problem"]["perfect"] is True and listed["perfect"] is True
    grid = roster_grid(client, world["owner"], world["class_id"])
    assert grid["problems"][0]["perfect_count"] == 1


def test_editing_the_checklist_recounts_perfect(client, world, monkeypatch):
    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world))
    assert _student_view(client, world)[0]["problem"]["perfect"] is True

    # 강사가 뒤에 심화 항목을 더하면 그 항목은 지난 판정에 없으니 충족이 아니다 — 완벽이 풀린다.
    _add_item(client, world["owner"], world["class_id"], world["problem_id"], "배포 문서가 있다", "optional")
    detail, _ = _student_view(client, world)
    assert detail["problem"]["passed"] is True and detail["problem"]["perfect"] is False
    assert roster_grid(client, world["owner"], world["class_id"])["problems"][0]["perfect_count"] == 0


def test_a_problem_without_advanced_items_has_no_perfect_at_all(client, db, monkeypatch):
    owner = login(client, uid="plain-owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id, required_labels=["테스트가 있다"], syntax_check_enabled=False)
    student = login(client, uid="plain-student")
    join_class(client, student["access"], class_id, instructor_access=owner["access"], display_name="나래")
    _attempt(client, monkeypatch, student["access"], class_id, problem.id, {problem.item_ids[0]: "met"})

    detail = mine(client, student["access"], class_id, problem.id)
    assert detail["problem"]["passed"] is True and detail["problem"]["perfect"] is None
    assert detail["submissions"][0]["perfect"] is None
    assert my_problems(client, student["access"], class_id)["problems"][0]["perfect"] is None
    grid = roster_grid(client, owner["access"], class_id)
    assert grid["problems"][0]["perfect_count"] is None
    [row] = [m for m in grid["members"] if m["display_name"] == "나래"]
    assert row["cells"][0]["perfect"] is None


def test_query_count_does_not_grow_with_attempts(client, world, monkeypatch, django_assert_max_num_queries):
    """시도가 늘어도 완벽을 세느라 질의가 늘지 않는다 — 같은 시도 묶음을 한 번 훑어 통과와 함께 센다.
    (격자의 참여자 줄마다 드는 질의는 이 티켓 이전부터다 — 여기서는 참여자 수를 고정한다.)"""

    _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world))
    grid_queries = _queries(lambda: roster_grid(client, world["owner"], world["class_id"]))
    list_queries = _queries(lambda: my_problems(client, world["student"], world["class_id"]))
    detail_queries = _queries(lambda: mine(client, world["student"], world["class_id"], world["problem_id"]))

    for _ in range(3):
        _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world, advanced="unmet"))
        _attempt(client, monkeypatch, world["student"], world["class_id"], world["problem_id"], _all(world))

    with django_assert_max_num_queries(grid_queries):
        grid = roster_grid(client, world["owner"], world["class_id"])
    assert grid["problems"][0]["perfect_count"] == 1
    with django_assert_max_num_queries(list_queries):
        assert my_problems(client, world["student"], world["class_id"])["problems"][0]["perfect"] is True
    with django_assert_max_num_queries(detail_queries):
        assert len(mine(client, world["student"], world["class_id"], world["problem_id"])["submissions"]) == 7
