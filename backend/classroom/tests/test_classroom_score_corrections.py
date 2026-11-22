"""강의실 점수 정정(#1317) — 원래 점수는 두고 정정을 덧대 「현재 점수」로.

시임은 마운트된 HTTP API(거는 것·학생 결과·강사 제출 현황)와 grader 한 바퀴(`classroom.grader.run_round`)다.
벤더는 `core.llm_scoring.requests.post` 경계를 흉내 낸다(돈이 드는 호출 없음).
"""

from __future__ import annotations

import pytest
from django.test import Client

from classroom import agent_grading
from classroom import grader as classroom_grader
from classroom.models import (
    Class,
    ClassroomScore,
    ClassroomScoreCorrection,
    ClassroomScoringAttempt,
    ClassroomSubmission,
    Problem,
)
from classroom.score_corrections import run_correction_inline
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    mine,
    respond_with_permanent_failure,
    respond_with_rate_limit,
    respond_with_verdict,
    run_scan,
    submit_repository,
)


@pytest.fixture(autouse=True)
def _real_adapter(request):
    """벤더 HTTP 경계를 흉내 낸다 — grader 바퀴 시험만 흉내 어댑터(비동기 길)로 돈다."""

    marker = request.node.get_closest_marker("django_db")
    if marker is not None and marker.kwargs.get("transaction"):
        yield
        return
    with force_real_scoring_adapter():
        yield


def _capped_submission(client) -> dict:
    """실패 상한 점수(`platform-auto`)가 찍힌 시도 하나 — #1316 처럼 채점이 닿지 못한 꼴."""

    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submission_id = submit_repository(client, participant["access"], class_id, problem.id)["id"]
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem": problem,
        "submission_id": submission_id,
    }


def _cap(client, monkeypatch, ctx) -> None:
    respond_with_permanent_failure(monkeypatch)
    run_scan(client)
    assert ClassroomScore.objects.get(submission_id=ctx["submission_id"]).model_version == PLATFORM_FAILURE_MODEL_VERSION


def _request(client, ctx, submission_ids: list[int], *, access: str | None = None, reason: str = "실행기 망 누락"):
    return client.post(
        f"{CLASSES_URL}/{ctx['class_id']}/score-corrections",
        data={"submission_ids": submission_ids, "reason": reason},
        content_type="application/json",
        **auth_header(access or ctx["instructor"]["access"]),
    )


def _participant_view(client, ctx) -> dict:
    return mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)["submissions"][0]


def _instructor_view(client, ctx) -> dict:
    response = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem'].id}/submissions",
        **auth_header(ctx["instructor"]["access"]),
    )
    assert response.status_code == 200, response.content
    return next(row for row in response.json() if row["id"] == ctx["submission_id"])


def _attempt_trail(submission_id: int) -> tuple[list, tuple]:
    row = ClassroomSubmission.objects.get(pk=submission_id)
    attempts = list(
        ClassroomScoringAttempt.objects.filter(submission_id=submission_id).values_list("error", "permanent")
    )
    return attempts, (row.attempt_number, row.scoring_queued_at)


@pytest.mark.django_db(transaction=True)
def test_a_correction_on_a_capped_score_becomes_the_current_score_after_a_grader_round(monkeypatch, settings):
    """실패 상한 점수에 정정을 건다 → grader 한 바퀴(흉내 어댑터) → 정정 끝남 → 현재 점수가 정정 값이다."""

    client = Client()
    respond_with_permanent_failure(monkeypatch)
    with force_real_scoring_adapter():
        ctx = _capped_submission(client)
        run_scan(client)
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists(), list(
        ClassroomScoringAttempt.objects.values_list("error", flat=True)
    )
    settings.CLASSROOM_GRADER_INLINE = False
    original = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert _participant_view(client, ctx)["score"]["is_platform_failure"] is True

    response = _request(client, ctx, [ctx["submission_id"]])
    assert response.status_code == 201, response.content
    body = response.json()
    assert [c["status"] for c in body["corrections"]] == ["in_progress"] and body["skipped"] == []

    results = classroom_grader.run_round(global_limit=2, per_connection_limit=2, poll_seconds=0.01)

    assert [r["status"] for r in results if "correction_id" in r] == ["done"], results
    correction = ClassroomScoreCorrection.objects.get()
    assert correction.status == ClassroomScoreCorrection.Status.DONE
    assert correction.requested_by.email == "instructor-1@example.com"
    # 원래 점수는 그대로다.
    unchanged = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert (unchanged.pk, unchanged.model_version, unchanged.reasoning) == (
        original.pk,
        original.model_version,
        original.reasoning,
    )
    # 학생 결과·강사 제출 현황은 현재 점수(정정)를 보인다.
    participant = _participant_view(client, ctx)
    assert participant["score"]["corrected"] is True
    assert participant["score"]["is_platform_failure"] is False
    assert participant["score"]["model_version"] == correction.model_version
    instructor = _instructor_view(client, ctx)
    assert instructor["score"]["corrected"] is True


def test_a_met_correction_passes_the_attempt_and_charges_the_class_key(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    assert _participant_view(client, ctx)["passed"] is False
    _request(client, ctx, [ctx["submission_id"]])
    respond_with_verdict(monkeypatch, ctx["problem"].item_id, is_met=True, total_tokens=120)

    assert run_correction_inline(ClassroomScoreCorrection.objects.get().pk)["status"] == "done"

    participant = _participant_view(client, ctx)
    assert participant["passed"] is True and participant["score"]["corrected"] is True
    instructor = _instructor_view(client, ctx)
    assert all(v["is_met"] for v in instructor["score"]["reasoning"])
    assert Class.objects.get(pk=ctx["class_id"]).token_usage_total >= 120


def test_only_the_latest_scored_attempt_of_the_pair_can_be_corrected(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    newer = submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)["id"]

    body = _request(client, ctx, [ctx["submission_id"], newer]).json()

    assert body["corrections"] == []
    assert sorted((s["submission_id"], s["reason"]) for s in body["skipped"]) == sorted(
        [(ctx["submission_id"], "not_latest"), (newer, "not_scored")]
    )
    assert not ClassroomScoreCorrection.objects.exists()


def test_a_normal_score_is_refused_and_a_finished_correction_closes_the_button(client, db, monkeypatch):
    """범위는 「채점 실패」 점수뿐이다(#1317 대표 답) — 모델이 매긴 점수는 거절하고, 정정이 끝나 정상 점수가 되면
    다시 걸 수 없다. 강사 화면은 사유를 보내지 않는다."""

    ctx = _capped_submission(client)
    respond_with_verdict(monkeypatch, ctx["problem"].item_id, is_met=False)
    run_scan(client)

    body = _request(client, ctx, [ctx["submission_id"]]).json()
    assert body["skipped"] == [{"submission_id": ctx["submission_id"], "reason": "not_platform_failure"}]
    assert not ClassroomScoreCorrection.objects.exists()

    capped = _capped_submission_of(client, ctx, monkeypatch)
    response = client.post(
        f"{CLASSES_URL}/{ctx['class_id']}/score-corrections",
        data={"submission_ids": [capped]},
        content_type="application/json",
        **auth_header(ctx["instructor"]["access"]),
    )
    assert response.status_code == 201, response.content
    correction = ClassroomScoreCorrection.objects.get()
    assert correction.reason == "채점 실패 다시 채점"
    respond_with_verdict(monkeypatch, ctx["problem"].item_id, is_met=True)
    assert run_correction_inline(correction.pk)["status"] == "done"

    body = _request(client, ctx, [capped]).json()
    assert body["skipped"] == [{"submission_id": capped, "reason": "not_platform_failure"}]


def _capped_submission_of(client, ctx, monkeypatch) -> int:
    """같은 짝의 새 시도에 실패 상한 점수를 찍는다."""

    newer = submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)["id"]
    respond_with_permanent_failure(monkeypatch)
    run_scan(client)
    assert ClassroomScore.objects.get(submission_id=newer).model_version == PLATFORM_FAILURE_MODEL_VERSION
    return newer


def test_a_score_with_a_correction_in_progress_is_refused(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    assert _request(client, ctx, [ctx["submission_id"]]).status_code == 201

    body = _request(client, ctx, [ctx["submission_id"]]).json()

    assert body["skipped"] == [{"submission_id": ctx["submission_id"], "reason": "in_progress"}]
    assert ClassroomScoreCorrection.objects.count() == 1


def test_only_the_class_owner_can_request_and_a_reason_is_required(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    other = login(client, uid="instructor-2")

    assert _request(client, ctx, [ctx["submission_id"]], access=ctx["participant"]["access"]).status_code == 404
    assert _request(client, ctx, [ctx["submission_id"]], access=other["access"]).status_code == 404
    assert _request(client, ctx, [ctx["submission_id"]], reason="  ").status_code == 422
    assert _request(client, ctx, [ctx["submission_id"] + 999]).status_code == 422
    assert not ClassroomScoreCorrection.objects.exists()


def test_a_failed_correction_leaves_the_original_attempt_trail_untouched(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    before = _attempt_trail(ctx["submission_id"])
    _request(client, ctx, [ctx["submission_id"]])

    respond_with_permanent_failure(monkeypatch)
    result = run_correction_inline(ClassroomScoreCorrection.objects.get().pk)

    assert result["status"] == "failed"
    correction = ClassroomScoreCorrection.objects.get()
    assert correction.status == ClassroomScoreCorrection.Status.FAILED and correction.error
    assert _attempt_trail(ctx["submission_id"]) == before
    assert _participant_view(client, ctx)["score"]["corrected"] is False


def test_an_agent_hold_fails_the_correction_without_touching_the_attempt(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    before = _attempt_trail(ctx["submission_id"])
    _request(client, ctx, [ctx["submission_id"]])
    Class.objects.filter(pk=ctx["class_id"]).update(scoring_method=Class.GradingMethod.AGENT)
    Problem.objects.filter(pk=ctx["problem"].id).update(model="gpt-5-mini")
    calls: list[int] = []

    def held(submission, class_obj, **kwargs):
        calls.append(submission.id)
        return agent_grading.AgentHeld(reasons=["근거가 소스에 없다"], record={})

    monkeypatch.setattr(agent_grading, "run_scoring", held)

    result = run_correction_inline(ClassroomScoreCorrection.objects.get().pk)

    # 에이전트 클래스의 정정은 실행기 길(`agent_grading.run_scoring`)을 탄다.
    assert calls == [ctx["submission_id"]]
    assert result["status"] == "failed" and "보류" in result["error"]
    assert _attempt_trail(ctx["submission_id"]) == before


def test_a_vendor_side_refusal_keeps_the_correction_in_progress_for_a_later_round(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    _request(client, ctx, [ctx["submission_id"]])
    respond_with_rate_limit(monkeypatch)

    result = run_correction_inline(ClassroomScoreCorrection.objects.get().pk)

    assert result["status"] == "deferred"
    correction = ClassroomScoreCorrection.objects.get()
    assert correction.status == ClassroomScoreCorrection.Status.IN_PROGRESS
    assert correction.lease_owner == "" and correction.lease_until is not None
    # 미룬 동안은 다시 집지 않는다.
    assert run_correction_inline(correction.pk) is None


def test_a_class_without_a_key_fails_the_correction_with_the_reason(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    _request(client, ctx, [ctx["submission_id"]])
    response = client.delete(
        f"{CLASSES_URL}/{ctx['class_id']}/openai-key", **auth_header(ctx["instructor"]["access"])
    )
    assert response.status_code == 200, response.content

    result = run_correction_inline(ClassroomScoreCorrection.objects.get().pk)

    assert result["status"] == "failed" and "키" in result["error"]


def test_the_class_owner_lists_the_corrections_of_the_class(client, db, monkeypatch):
    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    _request(client, ctx, [ctx["submission_id"]])

    response = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/score-corrections", **auth_header(ctx["instructor"]["access"])
    )

    assert response.status_code == 200, response.content
    [row] = response.json()["corrections"]
    assert (row["submission_id"], row["status"], row["reason"]) == (ctx["submission_id"], "in_progress", "실행기 망 누락")


def test_the_class_attempts_page_marks_only_the_latest_capped_attempt_as_correctable(client, db, monkeypatch):
    """「제출」 화면(#1317) — 「최근 제출」과 같은 줄을 최신순으로 쪽을 넘기며, 「다시 채점」은 범위 안 줄에만."""

    from classroom.api import CLASS_ATTEMPTS_PAGE_SIZE

    ctx = _capped_submission(client)
    _cap(client, monkeypatch, ctx)
    older = ctx["submission_id"]
    newer = _capped_submission_of(client, ctx, monkeypatch)

    def page(n: int, access: str | None = None):
        return client.get(
            f"{CLASSES_URL}/{ctx['class_id']}/attempts?page={n}", **auth_header(access or ctx["instructor"]["access"])
        )

    body = page(1).json()
    assert [(r["id"], r["correctable"]) for r in body["rows"]] == [(newer, True), (older, False)]
    assert (body["page"], body["has_next"]) == (1, False)
    assert {"member_display_name", "problem_title", "status", "late"} <= set(body["rows"][0])
    # 실패 상한 점수 줄은 버튼이 없는 앞선 시도까지 「채점 실패」다 — 「최근 제출」도 같은 낱말.
    assert [r["status"] for r in body["rows"]] == ["scoring_failed", "scoring_failed"]
    recent = client.get(f"{CLASSES_URL}/{ctx['class_id']}/recent-attempts", **auth_header(ctx["instructor"]["access"]))
    assert [r["status"] for r in recent.json()] == ["scoring_failed", "scoring_failed"]
    assert page(1, ctx["participant"]["access"]).status_code == 404
    # 걸어 두면 진행 중인 동안 버튼이 내려간다.
    _request(client, ctx, [newer])
    assert [r["correctable"] for r in page(1).json()["rows"]] == [False, False]

    for _ in range(CLASS_ATTEMPTS_PAGE_SIZE):
        submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem"].id)
    first, second = page(1).json(), page(2).json()
    assert first["has_next"] is True and len(first["rows"]) == CLASS_ATTEMPTS_PAGE_SIZE
    # 새 시도가 생겨 `newer` 는 더 이상 최근 시도가 아니다.
    assert [(r["id"], r["correctable"]) for r in second["rows"]] == [(newer, False), (older, False)]
    assert second["has_next"] is False
