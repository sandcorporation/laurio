"""그 키로 쓸 수 없는 채점 모델이면 채점하지 못함으로 남고 이유가 보인다
(#403, CONTEXT.md 「채점 모델」).

핵심 대상: 벤더가 모델을 그 키로 거부하면(`error.code ==
"model_not_found"`) 그 시도가 「채점하지 못함」으로 남는다 — 재시도하지
않고, 클래스의 채점 키 상태는 바뀌지 않는다(키 거부와 다른 사유다, #355와
대비되는 지점). 강사 화면에는 이유와 채점 모델 설정 링크가, 참여자 화면에는
기존 키 문제 안내와 같은 문구가 보인다. 강사가 모델을 바꾸면 새 시도부터
다시 채점된다.

**공용 시나리오 빌더(#433, #469) 위로 옮겼다** — `tests/classroom_scenarios.py` 참고.
"""

from __future__ import annotations

import pytest

from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt, Problem
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
    respond_with_key_rejection,
    respond_with_model_rejection,
    respond_with_verdict,
    run_scan,
    submit_repository,
    track_vendor_calls,
)


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with force_real_scoring_adapter():
        yield


def _setup_submission(client, *, model: str = "gpt-5-mini"):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, model=model)
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


@pytest.mark.parametrize("status_code", [400, 404])
def test_model_rejection_does_not_create_a_score(client, db, monkeypatch, status_code):
    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=status_code)

    result = run_scan(client)

    assert result["rows"][0]["status"] == "queued"
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_model_rejection_does_not_retry(client, db, monkeypatch):
    """no_key·key_rejected와 같은 규율 — 「아직 시도하지 않았다」로 남아야
    `_scoring_cap_reached`가 이 실패로 상한에 닿지 않는다."""

    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=404)

    for _ in range(6):
        run_scan(client)

    assert ClassroomScoringAttempt.objects.filter(submission_id=ctx["submission_id"]).count() == 0
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_model_rejection_leaves_the_class_key_status_untouched(client, db, monkeypatch):
    ctx = _setup_submission(client)
    class_before = Class.objects.get(id=ctx["class_id"]).openai_api_key_status

    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)

    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == class_before
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status != Class.ScoringKeyStatus.REJECTED


def test_model_rejection_marks_the_problem_and_excludes_it_from_the_scan(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)

    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    calls = track_vendor_calls(monkeypatch)
    result = run_scan(client)

    assert result["count"] == 0
    assert not calls


@pytest.mark.parametrize("status_code", [401, 403])
def test_key_rejection_is_unaffected_regression(client, db, monkeypatch, status_code):
    """키 거부(401·403)는 지금처럼 키 사유로 남는다 — 모델 거부 판정을
    더해도 회귀가 없다."""

    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch, status_code=status_code)

    result = run_scan(client)

    assert result["rows"][0]["status"] == "queued"
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == Class.ScoringKeyStatus.REJECTED
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is None


def test_instructor_screen_shows_the_model_rejected_reason(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)

    rows = instructor_submissions(client, ctx["instructor"]["access"], ctx["class_id"], ctx["problem_id"])
    assert rows[0]["status"] == "pending"
    assert rows[0]["pending_reason"] == "model_rejected"


def test_participant_screen_uses_the_existing_could_not_score_reason(client, db, monkeypatch):
    """참여자 화면은 모델 거부를 키 문제와 구별하지 않는다(#403 AC)."""

    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)

    mine_out = mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine_out["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] == "model_rejected"


def test_problem_detail_reports_scoring_model_rejected(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)

    detail = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        **auth_header(ctx["instructor"]["access"]),
    )
    assert detail.json()["scoring_model_rejected"] is True


def test_changing_the_problems_model_resumes_scoring_for_queued_submissions(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    patched = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"model": "gpt-4o-mini"},
        content_type="application/json",
        **auth_header(ctx["instructor"]["access"]),
    )
    assert patched.status_code == 200
    assert patched.json()["scoring_model_rejected"] is False
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is None

    respond_with_verdict(monkeypatch, ctx["item_id"])
    result = run_scan(client)

    assert result["count"] == 1
    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.reasoning[0]["is_met"] is True


def test_changing_the_class_default_model_resumes_problems_that_inherit_it(client, db, monkeypatch):
    """문제 자신의 모델이 비어 클래스 기본값을 따르던 경우, 클래스 기본값을
    바꾸면 그 문제도 다시 채점 후보에 든다."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5-mini"},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    # model=""(클래스 기본값을 따름)인 문제를 연다.
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submission_id = submit_repository(
        client, participant["access"], class_id, problem.id, "https://github.com/octocat/hello-world"
    )["id"]

    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)
    assert Problem.objects.get(id=problem.id).scoring_model_rejected_at is not None

    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o-mini"},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert Problem.objects.get(id=problem.id).scoring_model_rejected_at is None

    respond_with_verdict(monkeypatch, problem.item_id)
    result = run_scan(client)
    assert result["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=submission_id).exists()


def test_editing_the_title_without_the_model_field_keeps_the_rejection(client, db, monkeypatch):
    """제목만 고쳐 저장해도(#437) 화면이 모델 필드를 보내지 않으면 거부
    표시가 그대로 남는다 — 거부된 모델로 새 시도가 헛되이 다시 채점되지
    않는다."""

    ctx = _setup_submission(client)
    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    patched = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"title": "1주차 (고침)"},
        content_type="application/json",
        **auth_header(ctx["instructor"]["access"]),
    )
    assert patched.status_code == 200
    assert patched.json()["scoring_model_rejected"] is True
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    calls = track_vendor_calls(monkeypatch)
    result = run_scan(client)
    assert result["count"] == 0
    assert not calls


def test_resending_the_same_model_clears_the_rejection(client, db, monkeypatch):
    """같은 모델 값을 다시 보내면(#437 「이 모델로 다시 시도」) 값이 실제로
    달라지지 않았어도 거부 표시가 풀린다 — "설정을 확인했다"는 사실 자체가
    재시도 트리거다(기존 #403 규칙, 화면이 이 요청을 쓰는 경로가 새로
    생겼을 뿐이다)."""

    ctx = _setup_submission(client, model="gpt-5-mini")
    respond_with_model_rejection(monkeypatch, status_code=404)
    run_scan(client)
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    patched = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"model": "gpt-5-mini"},
        content_type="application/json",
        **auth_header(ctx["instructor"]["access"]),
    )
    assert patched.status_code == 200
    assert patched.json()["scoring_model_rejected"] is False
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is None

    respond_with_verdict(monkeypatch, ctx["item_id"])
    result = run_scan(client)
    assert result["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
