"""강의실 집계 필드 — 클래스 행 수치·문제 행 최근 제출·최근 제출 목록·격자 행 가입일 (#632, 시안 v2).

세는 사람은 달성률과 같다(강사 전원·내보낸 참여자 제외, CONTEXT.md 「공동 강사」). 준비와 확인은
전부 마운트된 HTTP API 로 한다(`tests.classroom_scenarios`).
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
    get_class,
    join_class,
    join_code,
    join_preview,
    list_problems,
    list_taught_classes,
    login,
    respond_with_verdict,
    roster_grid,
    run_scan,
    submit_repository,
)


@pytest.fixture(autouse=True)
def _real_scoring():
    with force_real_scoring_adapter():
        yield


def _get(client, access: str, path: str):
    return client.get(f"{CLASSES_URL}{path}", **auth_header(access))


def _expel(client, owner: dict, class_id: int, display_name: str) -> None:
    members = _get(client, owner["access"], f"/{class_id}/members").json()
    member = next(m for m in members if m["display_name"] == display_name)
    response = client.post(
        f"{CLASSES_URL}/{class_id}/members/{member['id']}/expel",
        content_type="application/json",
        **auth_header(owner["access"]),
    )
    assert response.status_code == 200, response.content


def _row(client, access: str, class_id: int) -> dict:
    return next(c for c in list_taught_classes(client, access) if c["id"] == class_id)


def _class_with_two_learners(client, monkeypatch=None, *, syntax_check_enabled: bool = True):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id, syntax_check_enabled=syntax_check_enabled)
    a, b = login(client, "learner-a"), login(client, "learner-b")
    join_class(client, a["access"], class_id, instructor_access=owner["access"], display_name="가")
    join_class(client, b["access"], class_id, instructor_access=owner["access"], display_name="나")
    return owner, class_id, problem, a, b


def test_class_row_counts_skip_the_instructor_the_co_instructor_and_the_expelled(client, db):
    owner, class_id, _problem, _a, _b = _class_with_two_learners(client)
    helper = login(client, "helper")
    join_class(client, helper["access"], class_id, instructor_access=owner["access"], display_name="조교였던 학생")
    gone = login(client, "gone")
    join_class(client, gone["access"], class_id, instructor_access=owner["access"], display_name="떠난 학생")
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="강사 본인")
    add_co_instructor(client, owner["access"], class_id, helper["access"], display_name="조교")
    _expel(client, owner, class_id, "떠난 학생")

    row = _row(client, owner["access"], class_id)

    assert row["member_count"] == 2
    assert row["member_count"] == list_problems(client, owner["access"], class_id)[0]["member_count"]


def test_one_active_member_rule_for_a_single_class_and_for_many(client, db):
    """「강사 전원·내보낸 사람 제외」는 함수 하나다(#664) — 클래스 하나짜리(문제 목록의 분모)와
    여러 클래스용(클래스 행·가입 미리보기)이 같은 수를 낸다. 한 클래스의 강사가 다른 클래스에서는
    참여자로 세어지는지까지 본다."""

    owner, class_id, _problem, a, _b = _class_with_two_learners(client)
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="강사 본인")
    gone = login(client, "gone")
    join_class(client, gone["access"], class_id, instructor_access=owner["access"], display_name="떠난 학생")
    _expel(client, owner, class_id, "떠난 학생")
    other_id = create_class(client, a["access"], name="가의 클래스")
    create_open_problem(client, a["access"], other_id)
    join_class(client, owner["access"], other_id, instructor_access=a["access"], display_name="참여자가 된 강사")

    for access, cid, expected in ((owner["access"], class_id, 2), (a["access"], other_id, 1)):
        row = _row(client, access, cid)
        denominators = {p["member_count"] for p in list_problems(client, access, cid)}
        preview = join_preview(client, join_code(client, access, cid))
        assert (row["member_count"], denominators, preview["member_count"]) == (expected, {expected}, expected)



def test_connected_app_counts_use_the_same_active_member_rule(client, db):
    """연결된 앱의 참여자 수(`list_my_classes`·`delete_class` 미리보기)도 같은 규칙에서 나온다
    (#671) — 강사 본인·공동 강사의 가입과 내보낸 사람을 빼고, 내보낸 사람은 미리보기가 따로 센다."""

    from tests.test_classroom_connected_apps import _connect, _rpc

    owner, class_id, _problem, _a, _b = _class_with_two_learners(client)
    helper = login(client, "helper")
    join_class(client, helper["access"], class_id, instructor_access=owner["access"], display_name="조교였던 학생")
    add_co_instructor(client, owner["access"], class_id, helper["access"], display_name="조교")
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="강사 본인")
    gone = login(client, "gone")
    join_class(client, gone["access"], class_id, instructor_access=owner["access"], display_name="떠난 학생")
    _expel(client, owner, class_id, "떠난 학생")
    token = _connect(client, owner["access"])["access_token"]

    def tool(name: str, arguments: dict) -> dict:
        result = _rpc(client, token, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
        assert result["isError"] is False, result
        return result["structuredContent"]

    listed = next(c for c in tool("list_my_classes", {})["classes"] if c["id"] == class_id)
    preview = tool("delete_class", {"class_id": class_id})["preview"]

    assert listed["participant_count"] == _row(client, owner["access"], class_id)["member_count"] == 2
    assert (preview["participant_count"], preview["expelled_participant_count"]) == (2, 1)

def test_class_row_problem_count_includes_drafts_and_the_average_is_over_open_problems(client, db, monkeypatch):
    owner, class_id, problem, a, _b = _class_with_two_learners(client)
    create_open_problem(client, owner["access"], class_id, title="초안", open=False)
    second = create_open_problem(client, owner["access"], class_id, title="2주차")
    submit_repository(client, a["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)

    row = _row(client, owner["access"], class_id)

    rates = [p["pass_rate"] for p in list_problems(client, owner["access"], class_id) if p["status"] == "open"]
    assert rates == [0.5, 0.0]
    assert row["problem_count"] == 3
    assert row["average_pass_rate"] == pytest.approx(0.25)
    assert second.id


def test_join_preview_counts_match_the_class_rows(client, db):
    """가입 미리보기의 두 수치는 내 클래스 행과 같은 기준이다(#659) — 참여자 수는 가르치는
    행의 `member_count`(강사 전원·내보낸 사람 제외), 문제 수는 가입한 사람이 보게 될 열린
    문제 수라 참여 중 행의 `open_problem_count` 다. 미리보기는 질의 수가 사람·문제 수에 따라
    늘지 않는다."""

    owner, class_id, _problem, a, _b = _class_with_two_learners(client)
    create_open_problem(client, owner["access"], class_id, title="초안", open=False)
    gone = login(client, "gone")
    join_class(client, gone["access"], class_id, instructor_access=owner["access"], display_name="떠난 학생")
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="강사 본인")
    _expel(client, owner, class_id, "떠난 학생")
    code = join_code(client, owner["access"], class_id)

    with CaptureQueriesContext(connection) as before:
        preview = join_preview(client, code)
    joined = _get(client, a["access"], "/joined").json()[0]
    teaching = _row(client, owner["access"], class_id)

    assert (preview["member_count"], preview["open_problem_count"]) == (2, 1)
    assert preview["member_count"] == teaching["member_count"]
    assert preview["open_problem_count"] == joined["open_problem_count"]

    for name in ("다", "라"):
        extra = login(client, f"extra-{name}")
        join_class(client, extra["access"], class_id, instructor_access=owner["access"], display_name=name)
    create_open_problem(client, owner["access"], class_id, title="2주차")
    with CaptureQueriesContext(connection) as after:
        assert join_preview(client, code)["member_count"] == 4
    assert len(after) == len(before)


def test_class_row_average_pass_rate_is_null_without_open_problems_or_participants(client, db):
    owner = login(client, "owner")
    empty = create_class(client, owner["access"], name="빈 클래스")
    only_draft = create_class(client, owner["access"], name="초안만")
    create_open_problem(client, owner["access"], only_draft, open=False)
    no_learners = create_class(client, owner["access"], name="참여자 없음")
    create_open_problem(client, owner["access"], no_learners)

    for class_id in (empty, only_draft, no_learners):
        assert _row(client, owner["access"], class_id)["average_pass_rate"] is None
    assert _row(client, owner["access"], only_draft)["problem_count"] == 1


def test_class_row_last_submitted_at_ignores_the_instructors_own_attempts(client, db):
    owner, class_id, problem, a, _b = _class_with_two_learners(client)
    assert _row(client, owner["access"], class_id)["last_submitted_at"] is None
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="강사 본인")
    submit_repository(client, a["access"], class_id, problem.id)
    submit_repository(client, owner["access"], class_id, problem.id)

    row = _row(client, owner["access"], class_id)

    mine = _get(client, a["access"], f"/{class_id}/problems/{problem.id}/mine").json()
    assert row["last_submitted_at"] == mine["submissions"][0]["created_at"]


def test_class_detail_counts_every_scored_attempt(client, db, monkeypatch):
    owner, class_id, problem, a, b = _class_with_two_learners(client)
    assert get_class(client, owner["access"], class_id)["scored_attempt_count"] == 0
    submit_repository(client, a["access"], class_id, problem.id)
    submit_repository(client, a["access"], class_id, problem.id)
    submit_repository(client, b["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=False)
    run_scan(client)

    scored = get_class(client, owner["access"], class_id)["scored_attempt_count"]

    assert 1 <= scored <= 3


def test_problem_row_last_submitted_at_is_per_problem(client, db):
    owner, class_id, problem, a, _b = _class_with_two_learners(client)
    other = create_open_problem(client, owner["access"], class_id, title="2주차")
    submit_repository(client, a["access"], class_id, problem.id)

    rows = {p["id"]: p for p in list_problems(client, owner["access"], class_id)}

    assert rows[problem.id]["last_submitted_at"] is not None
    assert rows[other.id]["last_submitted_at"] is None


def test_joined_row_reports_my_passed_and_open_problem_counts(client, db, monkeypatch):
    owner, class_id, problem, a, _b = _class_with_two_learners(client)
    create_open_problem(client, owner["access"], class_id, title="2주차")
    create_open_problem(client, owner["access"], class_id, title="초안", open=False)
    submit_repository(client, a["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)

    mine = _get(client, a["access"], "/joined").json()
    theirs = _get(client, _b["access"], "/joined").json()

    assert (mine[0]["passed_count"], mine[0]["open_problem_count"]) == (1, 2)
    assert (theirs[0]["passed_count"], theirs[0]["open_problem_count"]) == (0, 2)


def test_grid_member_rows_carry_joined_at_and_last_submitted_at(client, db):
    owner, class_id, problem, a, _b = _class_with_two_learners(client)
    submit_repository(client, a["access"], class_id, problem.id)

    rows = {m["display_name"]: m for m in roster_grid(client, owner["access"], class_id)["members"]}

    assert rows["가"]["joined_at"] is not None
    assert rows["가"]["last_submitted_at"] is not None
    assert rows["나"]["joined_at"] is not None
    assert rows["나"]["last_submitted_at"] is None


@pytest.fixture
def eleven_unscored_attempts(client, db):
    """「열 개를 넘게 쌓였다」는 준비다 — 제출 11건(HTTP)은 시험 본문의 CPU 한도 밖에서
    올린다(#701: 본문에 두면 조용할 때도 0.7초였다). 문법 검사는 끈다 — 이 시험은
    상태를 보고, 켜 두면 채점마다 파서 프로세스가 하나씩 떠 스캔 둘에 CPU 0.2초가 든다."""

    owner, class_id, problem, a, b = _class_with_two_learners(client, syntax_check_enabled=False)
    for _ in range(11):
        submit_repository(client, a["access"], class_id, problem.id)
    return owner, class_id, problem, b


def test_recent_attempts_lists_ten_newest_with_the_four_statuses(client, monkeypatch, eleven_unscored_attempts):
    owner, class_id, problem, b = eleven_unscored_attempts

    unscored = _get(client, owner["access"], f"/{class_id}/recent-attempts").json()
    assert len(unscored) == 10
    assert {r["status"] for r in unscored} == {"scoring"}

    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)
    submit_repository(client, b["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=False)
    run_scan(client)

    rows = _get(client, owner["access"], f"/{class_id}/recent-attempts").json()
    assert rows[0]["member_display_name"] == "나"
    assert rows[0]["problem_title"] == "1주차"
    assert rows[0]["status"] == "attempted_not_passed"
    assert "passed" in {r["status"] for r in rows}
    assert [r["submitted_at"] for r in rows] == sorted((r["submitted_at"] for r in rows), reverse=True)


def test_recent_attempts_marks_needs_setup_when_there_is_no_scoring_key(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], with_key=False)
    problem = create_open_problem(client, owner["access"], class_id)
    a = login(client, "learner-a")
    join_class(client, a["access"], class_id, instructor_access=owner["access"], display_name="가")
    submit_repository(client, a["access"], class_id, problem.id)

    rows = _get(client, owner["access"], f"/{class_id}/recent-attempts").json()

    assert [r["status"] for r in rows] == ["needs_setup"]


def test_recent_attempts_skip_the_instructor_and_the_expelled_and_are_instructor_only(client, db):
    owner, class_id, problem, a, b = _class_with_two_learners(client)
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="강사 본인")
    submit_repository(client, owner["access"], class_id, problem.id)
    submit_repository(client, b["access"], class_id, problem.id)
    submit_repository(client, a["access"], class_id, problem.id)
    _expel(client, owner, class_id, "나")

    rows = _get(client, owner["access"], f"/{class_id}/recent-attempts").json()

    assert [r["member_display_name"] for r in rows] == ["가"]
    assert _get(client, a["access"], f"/{class_id}/recent-attempts").status_code == 404


def _build_listed_class(client, owner, name: str):
    class_id = create_class(client, owner["access"], name=name)
    create_open_problem(client, owner["access"], class_id)
    create_open_problem(client, owner["access"], class_id, title="2주차")
    learner = login(client, f"{name}-learner")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"], display_name="학생")
    return class_id, learner


@pytest.fixture
def first_listed_class(client, db):
    """질의 수를 처음 세는 상태(클래스 하나·제출 하나)는 준비다 — 시험 본문의 CPU
    한도 밖에서 만든다(#701)."""

    owner = login(client, "owner")
    first, learner = _build_listed_class(client, owner, "하나")
    submit_repository(client, learner["access"], first, list_problems(client, owner["access"], first)[0]["id"])
    return owner, first, learner


def test_listing_query_count_does_not_grow_with_classes_problems_or_members(client, first_listed_class):
    owner, first, learner = first_listed_class

    def build(name: str):
        return _build_listed_class(client, owner, name)

    def count(path: str, access: str) -> int:
        with CaptureQueriesContext(connection) as ctx:
            assert _get(client, access, path).status_code == 200
        return len(ctx)

    before_classes = count("", owner["access"])
    before_joined = count("/joined", learner["access"])
    before_problems = count(f"/{first}/problems", owner["access"])
    for name in ("둘", "셋", "넷"):
        build(name)
    extra = login(client, "extra")
    join_class(client, extra["access"], first, instructor_access=owner["access"], display_name="더")
    create_open_problem(client, owner["access"], first, title="3주차")

    # 클래스 행의 기존 직렬화(보관 여부·템플릿·소유권 이전)는 클래스마다 질의 넷(제출 유무·템플릿·시계·소유권 이전)이 따로 든다 — 이 티켓의
    # 집계 필드는 클래스를 몇 개 더해도 질의를 늘리지 않는다.
    assert count("", owner["access"]) <= before_classes + 4 * 3
    assert count("/joined", learner["access"]) <= before_joined
    # 문제 행(달성률·템플릿·제출 표식)은 클래스 단위로 한 번에 센다(#684) — 문제를 더해도 질의가 늘지 않는다.
    assert count(f"/{first}/problems", owner["access"]) <= before_problems


def test_reorder_query_count_does_not_grow_with_problems(client, db):
    """순서 바꾸기 응답(#679) — 문제 목록과 같이 제출 표식(마지막 제출·시도 수)을 한 번에 센다."""

    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    create_open_problem(client, owner["access"], class_id)
    learner = login(client, "learner")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"], display_name="학생")
    submit_repository(client, learner["access"], class_id, list_problems(client, owner["access"], class_id)[0]["id"])

    def count() -> int:
        ids = [p["id"] for p in list_problems(client, owner["access"], class_id)]
        with CaptureQueriesContext(connection) as ctx:
            response = client.post(
                f"{CLASSES_URL}/{class_id}/problems/reorder",
                data={"problem_ids": list(reversed(ids))},
                content_type="application/json",
                **auth_header(owner["access"]),
            )
            assert response.status_code == 200
        return len(ctx)

    before = count()
    create_open_problem(client, owner["access"], class_id, title="2주차")
    create_open_problem(client, owner["access"], class_id, title="3주차")

    # 문제 행은 목록과 같이 클래스 단위로 한 번에 센다(#684) — 문제를 더해도 질의가 늘지 않는다.
    assert count() <= before


def test_problem_participant_attempt_count_is_the_submissions_screens_attempts(client, db):
    """문제 편집 머리의 「제출 현황 N」(#674) — 강사 본인·내보낸 사람의 시도는 세지 않는다.
    문제 상세와 문제 목록이 같은 수를 내고, 제출 현황의 「시도」(참여자 행)와 같다."""

    owner, class_id, problem, a, b = _class_with_two_learners(client)
    other = create_open_problem(client, owner["access"], class_id, title="2주차")
    join_class(client, owner["access"], class_id, instructor_access=owner["access"], display_name="강사 본인")
    submit_repository(client, a["access"], class_id, problem.id)
    submit_repository(client, a["access"], class_id, problem.id)
    submit_repository(client, b["access"], class_id, problem.id)
    submit_repository(client, owner["access"], class_id, problem.id)
    _expel(client, owner, class_id, "나")

    detail = _get(client, owner["access"], f"/{class_id}/problems/{problem.id}").json()
    rows = {p["id"]: p for p in list_problems(client, owner["access"], class_id)}

    assert detail["participant_attempt_count"] == 2
    assert rows[problem.id]["participant_attempt_count"] == 2
    assert rows[other.id]["participant_attempt_count"] == 0


@pytest.fixture
def scored_class(client, db, monkeypatch):
    """채점까지 끝난 클래스 하나 — 질의를 처음 세는 상태라 준비다(#701, #819)."""

    owner, class_id, problem, a, b = _class_with_two_learners(client)
    submit_repository(client, a["access"], class_id, problem.id)
    submit_repository(client, b["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)
    return owner, class_id


def _class_detail_queries(client, access: str, class_id: int) -> list[str]:
    with CaptureQueriesContext(connection) as ctx:
        assert _get(client, access, f"/{class_id}").status_code == 200
    return [q["sql"] for q in ctx.captured_queries]


def test_class_detail_skips_scoring_prompts_and_query_count_stays_flat(
    client, scored_class, monkeypatch, django_assert_max_num_queries
):
    """클래스 상세(#819) — 달성률은 판정(`reasoning`·문법 검사)만 읽는다. 채점 프롬프트는 시도마다
    수십 KB(제출 소스가 그 안에 있다)라 prod 에서 시도 158개에 4MB 를 끌어와 응답이 100~250ms 였다.
    질의 수는 문제·참여자·시도를 더해도 늘지 않는다."""

    owner, class_id = scored_class
    before = _class_detail_queries(client, owner["access"], class_id)
    assert not [sql for sql in before if '"classroom_classroomscore"."prompt"' in sql]

    second = create_open_problem(client, owner["access"], class_id, title="2주차")
    for name in ("다", "라"):
        extra = login(client, f"extra-{name}")
        join_class(client, extra["access"], class_id, instructor_access=owner["access"], display_name=name)
        submit_repository(client, extra["access"], class_id, second.id)
    respond_with_verdict(monkeypatch, second.item_id, is_met=False)
    run_scan(client)

    # 인증 둘·클래스 하나·집계 여섯·직렬화(제출 유무·템플릿·시계 둘·소유권 이전) — 지금 14개다.
    assert len(before) <= 14
    with django_assert_max_num_queries(len(before)):
        detail = get_class(client, owner["access"], class_id)
    assert detail["scored_attempt_count"] == 4
