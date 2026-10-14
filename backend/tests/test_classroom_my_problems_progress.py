"""참여자 문제 목록의 진행 필드 — 상태·시도 수·마지막 시도 시각 (#639, 시안 v2 Mine).

상태 낱말은 명단 격자·최근 시도와 같다. 준비와 확인은 전부 마운트된 HTTP API 로 한다.
"""

from __future__ import annotations

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests.classroom_scenarios import (
    CLASSES_URL,
    add_co_instructor,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    join_code,
    join_preview,
    login,
    my_problems,
    rename_my_instructor_name,
    respond_with_verdict,
    run_scan,
    submit_repository,
)


@pytest.fixture(autouse=True)
def _real_scoring():
    with force_real_scoring_adapter():
        yield


def _setup(client):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    learner = login(client, "learner")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"], display_name="서지우")
    return owner, class_id, learner


def _by_title(body: dict) -> dict:
    return {p["title"]: p for p in body["problems"]}


def test_untouched_problem_is_not_submitted_with_zero_attempts(client, db):
    owner, class_id, learner = _setup(client)
    create_open_problem(client, owner["access"], class_id)

    item = my_problems(client, learner["access"], class_id)["problems"][0]

    assert item["status"] == "not_submitted"
    assert item["attempt_count"] == 0
    assert item["last_attempted_at"] is None
    assert item["passed"] is False


def test_unscored_attempts_are_scoring_with_count_and_last_time(client, db):
    owner, class_id, learner = _setup(client)
    problem = create_open_problem(client, owner["access"], class_id)
    submit_repository(client, learner["access"], class_id, problem.id)
    submit_repository(client, learner["access"], class_id, problem.id)

    item = my_problems(client, learner["access"], class_id)["problems"][0]

    assert item["status"] == "scoring"
    assert item["attempt_count"] == 2
    assert item["last_attempted_at"] is not None


def test_scored_attempts_are_passed_or_attempted_not_passed(client, db, monkeypatch):
    owner, class_id, learner = _setup(client)
    miss = create_open_problem(client, owner["access"], class_id, title="미통과 문제")
    hit = create_open_problem(client, owner["access"], class_id, title="통과 문제")
    submit_repository(client, learner["access"], class_id, miss.id)
    respond_with_verdict(monkeypatch, miss.item_id, is_met=False)
    run_scan(client)
    submit_repository(client, learner["access"], class_id, hit.id)
    respond_with_verdict(monkeypatch, hit.item_id, is_met=True)
    run_scan(client)

    items = _by_title(my_problems(client, learner["access"], class_id))

    assert items["미통과 문제"]["status"] == "attempted_not_passed"
    assert items["통과 문제"]["status"] == "passed"
    assert items["통과 문제"]["passed"] is True


def test_passed_stays_passed_after_a_later_unscored_attempt(client, db, monkeypatch):
    owner, class_id, learner = _setup(client)
    problem = create_open_problem(client, owner["access"], class_id)
    submit_repository(client, learner["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)
    submit_repository(client, learner["access"], class_id, problem.id)

    item = my_problems(client, learner["access"], class_id)["problems"][0]

    assert item["status"] == "passed"
    assert item["attempt_count"] == 2


def test_without_a_scoring_key_the_stuck_attempt_reads_as_needs_setup(client, db):
    """키가 없어 멈춘 시도(#670) — 격자와 같은 낱말 `needs_setup` 으로 내려 화면이
    「채점 중」이 아니라 「채점 대기」로 보이게 한다(CONTEXT.md 「채점 대기」)."""
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], with_key=False)
    learner = login(client, "learner")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"], display_name="서지우")
    problem = create_open_problem(client, owner["access"], class_id)
    submit_repository(client, learner["access"], class_id, problem.id)

    item = my_problems(client, learner["access"], class_id)["problems"][0]

    assert item["status"] == "needs_setup"
    assert item["attempt_count"] == 1
    assert item["passed"] is False


def test_hidden_problem_carries_the_same_fields(client, db):
    owner, class_id, learner = _setup(client)
    problem = create_open_problem(client, owner["access"], class_id)
    submit_repository(client, learner["access"], class_id, problem.id)
    hidden = client.post(f"{CLASSES_URL}/{class_id}/problems/{problem.id}/hide", **auth_header(owner["access"]))
    assert hidden.status_code == 200, hidden.content

    body = my_problems(client, learner["access"], class_id)

    assert body["problems"] == []
    assert body["hidden_problems"][0]["attempt_count"] == 1
    assert body["hidden_problems"][0]["status"] == "scoring"


def test_query_count_does_not_grow_with_problems_or_attempts(client, db):
    owner, class_id, learner = _setup(client)
    first = create_open_problem(client, owner["access"], class_id)
    submit_repository(client, learner["access"], class_id, first.id)

    def count() -> int:
        with CaptureQueriesContext(connection) as ctx:
            my_problems(client, learner["access"], class_id)
        return len(ctx)

    before = count()
    for n in range(3):
        extra = create_open_problem(client, owner["access"], class_id, title=f"추가 {n}")
        submit_repository(client, learner["access"], class_id, extra.id)
        submit_repository(client, learner["access"], class_id, extra.id)

    assert count() <= before


def test_the_eyebrow_names_every_instructor_like_the_join_preview(client, db):
    """눈썹의 강사 이름은 가입 미리보기와 같은 함수에서 나온다(#671, CONTEXT.md Class) — 소유자
    먼저, 그다음 공동 강사를 수락한 순서로."""

    owner, class_id, learner = _setup(client)
    co = login(client, "co")
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="김조교")
    renamed = rename_my_instructor_name(client, owner["access"], class_id, "박강사")
    assert renamed.status_code == 200, renamed.content

    body = my_problems(client, learner["access"], class_id)

    assert body["instructor_display_names"] == ["박강사", "김조교"]
    code = join_code(client, owner["access"], class_id)
    assert join_preview(client, code)["instructor_display_names"] == body["instructor_display_names"]
