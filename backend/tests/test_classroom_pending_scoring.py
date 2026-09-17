"""채점 대기 판정을 한 모듈로 (#434, spec #432).

핵심 대상: 시도 하나가 지금 채점될 수 있는지, 아니라면 사유가 무엇인지를
`classroom.pending_scoring` 한 모듈이 답한다 — 스캔 후보 질의·채점 직전
확인·참여자 화면의 `pending_reason`·강사 참여자별 격자의 칸 상태가 모두 그
답을 쓴다. 사유가 여럿이면 키(없음·거부) → 모델 거부 → 예산 소진 순서로
하나만 말한다. 강사 격자는 키 문제와 모델 거부를 합쳐 「설정 필요」
(`needs_setup`)로 보인다 — 지금까지는 모델이 거부된 시도가 「채점 중」으로
잘못 보였다(이 파일의 첫 테스트가 그 버그를 빨갛게 드러낸다).

`classroom_scenarios`(#433) 위에 선다.
"""

from __future__ import annotations

from classroom.models import Class, Problem

from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    mine,
    respond_with_model_rejection,
    roster_grid,
    run_scan,
    submit_repository,
)


def _grid_cell(grid: dict, member_id: int, problem_id: int) -> dict:
    member = next(m for m in grid["members"] if m["id"] == member_id)
    return next(c for c in member["cells"] if c["problem_id"] == problem_id)


def _setup_model_rejected_submission(client, monkeypatch) -> dict:
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, model="gpt-5-mini")
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submitted = submit_repository(client, participant["access"], class_id, problem.id)

    respond_with_model_rejection(monkeypatch)
    with force_real_scoring_adapter():
        run_scan(client)

    assert Problem.objects.get(id=problem.id).scoring_model_rejected_at is not None

    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem.id,
        "submission_id": submitted["id"],
    }


def test_grid_cell_for_a_model_rejected_attempt_shows_needs_setup_not_scoring(client, db, monkeypatch):
    """지금까지 격자는 모델 거부를 몰라 「채점 중」으로 보였다 — 강사가
    기다려도 절대 풀리지 않는데도 그렇게 보인 것이 #432의 출발점 버그다."""

    ctx = _setup_model_rejected_submission(client, monkeypatch)

    grid = roster_grid(client, ctx["instructor"]["access"], ctx["class_id"])

    participant_row = next(m for m in grid["members"] if not m["is_instructor"])
    cell = _grid_cell(grid, participant_row["id"], ctx["problem_id"])
    assert cell["status"] == "needs_setup"


def test_grid_cell_for_a_missing_key_attempt_also_shows_needs_setup(client, db):
    """키 문제와 모델 거부를 격자는 하나의 값으로 합친다(#434) — 예전
    "no_api_key" 값이 "needs_setup"으로 넓어졌다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=False)
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)

    grid = roster_grid(client, instructor["access"], class_id)

    participant_row = next(m for m in grid["members"] if not m["is_instructor"])
    cell = _grid_cell(grid, participant_row["id"], problem.id)
    assert cell["status"] == "needs_setup"


def test_grid_cell_for_a_budget_exhausted_attempt_still_shows_scoring(client, db):
    """예산 소진은 강사가 손대지 않아도 예산을 채우면 풀리므로 "설정 필요"가
    아니라 여전히 "채점 중"이다(#434 AC)."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    Class.objects.filter(id=class_id).update(token_budget=100, token_usage_total=100)

    grid = roster_grid(client, instructor["access"], class_id)

    participant_row = next(m for m in grid["members"] if not m["is_instructor"])
    cell = _grid_cell(grid, participant_row["id"], problem.id)
    assert cell["status"] == "scoring"


def test_pending_reason_priority_is_key_then_model_then_budget(client, db):
    """셋 다 동시에 걸려 있어도 참여자 화면은 키 사유 하나만 말한다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=False)
    problem = create_open_problem(client, instructor["access"], class_id, model="gpt-5-mini")
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)

    Problem.objects.filter(id=problem.id).update(scoring_model_rejected_at="2026-01-01T00:00:00Z")
    Class.objects.filter(id=class_id).update(token_budget=100, token_usage_total=100)

    mine_out = mine(client, participant["access"], class_id, problem.id)
    assert mine_out["submissions"][0]["pending_reason"] == "no_api_key"


def test_pending_reason_is_model_rejected_when_key_is_fine_but_budget_is_also_gone(client, db):
    """키가 멀쩡하면 모델 거부가 예산 소진보다 먼저 말해진다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, model="gpt-5-mini")
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)

    Problem.objects.filter(id=problem.id).update(scoring_model_rejected_at="2026-01-01T00:00:00Z")
    Class.objects.filter(id=class_id).update(token_budget=100, token_usage_total=100)

    mine_out = mine(client, participant["access"], class_id, problem.id)
    assert mine_out["submissions"][0]["pending_reason"] == "model_rejected"


def test_scan_skips_a_submission_whose_screen_reason_is_model_rejected(client, db, monkeypatch):
    """스캔 후보와 화면 사유가 어긋나지 않는다 — 화면이 "채점할 수 없다"고
    말하는 시도는 스캔도 건드리지 않는다."""

    ctx = _setup_model_rejected_submission(client, monkeypatch)

    result = run_scan(client)

    assert result["count"] == 0

    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine_out["submissions"][0]["pending_reason"] == "model_rejected"
