"""채점 중 키가 거절당해도 참여자가 0%를 받지 않는다 (#355, ADR-0045).

핵심 대상: 채점이 벤더에게 401·403을 받으면 `ClassroomScore`를 만들지 않고,
그 클래스의 채점 키 상태를 "거부됨"으로 바꾸며, 채점 스캔의 후보에서 그
클래스를 뺀다. 강사가 새 키를 저장하면(#354의 검증을 통과하거나 미검증으로
저장되면) 상태가 덮이고 밀려 있던 제출물이 다시 채점된다. 401·403 밖의
영구 실패는 이 티켓이 건드리지 않는다 — 그 고정은 `test_classroom_scoring.py`
의 `test_non_auth_permanent_failure_still_finalizes_immediately`가 맡는다.

공모전 채점(`scoring` 앱)은 이 파일의 대상이 아니다 — ADR-0037의 경계 안에서
의도된 비대칭이다.

**공용 시나리오 빌더(#433, #469) 위로 옮겼다** — `tests/classroom_scenarios.py` 참고.
"""

from __future__ import annotations

import pytest

from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt
from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    mine,
    respond_to_models_endpoint,
    respond_with_key_rejection,
    respond_with_verdict,
    run_scan,
    set_key,
    submit_repository,
    track_vendor_calls,
)


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with force_real_scoring_adapter():
        yield


def _setup_submission(client):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submitted = submit_repository(
        client, participant["access"], class_id, problem.id, "https://github.com/octocat/hello-world"
    )
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem.id,
        "item_id": problem.item_id,
        "submission_id": submitted["id"],
    }


@pytest.mark.parametrize("status_code", [401, 403])
def test_rejected_key_does_not_create_a_score(client, db, monkeypatch, status_code):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch, status_code=status_code)

    result = run_scan(client)

    assert result["rows"][0]["status"] == "queued"
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_rejected_key_marks_the_class_status(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)

    run_scan(client)

    class_obj = Class.objects.get(id=ctx["class_id"])
    assert class_obj.openai_api_key_status == Class.ScoringKeyStatus.REJECTED


def test_rejected_key_leaves_no_scoring_attempt_history(client, db, monkeypatch):
    """no_key와 같은 규율 — "아직 시도하지 않았다"로 남아야 `_scoring_cap_reached`가
    이 실패로 상한에 닿지 않는다."""

    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)

    for _ in range(6):
        run_scan(client)

    assert ClassroomScoringAttempt.objects.filter(submission_id=ctx["submission_id"]).count() == 0
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_rejected_class_is_excluded_from_the_scan_candidates(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)
    run_scan(client)

    calls = track_vendor_calls(monkeypatch)
    result = run_scan(client)

    assert result["count"] == 0
    assert not calls


def test_participant_screen_does_not_distinguish_rejected_from_missing_key(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)
    run_scan(client)

    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine_out["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] == "no_api_key"


def test_saving_a_new_valid_key_resumes_scoring_for_the_queued_submission(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)
    run_scan(client)
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == Class.ScoringKeyStatus.REJECTED

    respond_to_models_endpoint(monkeypatch)
    set_key(client, ctx["instructor"]["access"], ctx["class_id"], "sk-new-good-key")
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == Class.ScoringKeyStatus.VERIFIED

    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)
    result = run_scan(client)

    assert result["count"] == 1
    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.reasoning[0]["is_met"] is True


def test_instructor_class_detail_distinguishes_rejected_from_missing(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)
    run_scan(client)

    body = get_class(client, ctx["instructor"]["access"], ctx["class_id"])
    assert body["has_openai_key"] is True
    assert body["openai_key_status"] == "rejected"
