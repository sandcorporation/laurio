"""#1311: 한 번 호출로 못 담는 제출물 — 클래스 설정(반려·에이전트로 채점·들어가는 파일만)대로 간다.

#989 의 「크기 초과」 보류를 대신한다. 크기는 비동기 채점 안에서만 잰다. 문법 검사 덧붙임(파서가 못 본 파일의 전문)도
같은 예산 안에서 잰다 — 어댑터가 보낼 요청 전체를 잰다. 에이전트 쪽은 `agent_grading.run_scoring`(실행기·프록시 길)만
가짜로 바꾼다 — 그 길 자체는 `test_classroom_agent_method` 가 본다.

OpenAI 에이전트(#1311 의 1)도 여기서 본다 — gpt-5-mini 이상만 열린다.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from classroom import agent_grading
from classroom.models import ClassroomScore, ClassroomScoringAttempt, Problem
from classroom.pending_scoring import REJECTED_ERROR_PREFIX
from core.agent_prompt import ID_KEY, ITEMS_KEY
from tests.classroom_scenarios import FakeVendorResponse, get_class, respond_with_verdicts
from classroom.tests.test_classroom_syntax_check_ai_fallback import (
    CLASSES_URL,
    REPO_URL,
    _auth_header,
    _login,
    _mine,
    _run_scan_with_files,
    _setup,
    _submit_repository,
)


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


#: 시험용 입력 한도(토큰) — 47KB 소스 하나(≈1.6만 토큰)는 들어가고, 덧붙임까지 두 벌(≈3만)은 넘는다.
_LIMIT_TOKENS = 24_000
#: 파이썬은 내장 파서가 판정해 덧붙임이 없다. PHP 는 파서가 없어 같은 파일의 전문이 한 벌 더 붙는다.
_PY_47KB = "print('print가 있다')\n" * 1_800
_PHP_47KB = "<?php\n" + "echo 'print가 있다';\n" * 1_900
_SMALL = {"app.py": "print('print가 있다')\n"}


@pytest.fixture
def small_limit(monkeypatch):
    monkeypatch.setattr("core.model_context.input_token_limit", lambda model: _LIMIT_TOKENS)


def _budget(monkeypatch, max_bytes: int) -> None:
    """한 번 호출 예산을 `max_bytes` 로 — 채점과 계산기(반려 사유의 한도)가 같은 값을 본다."""

    for target in ("classroom.scoring.source_budget_bytes", "classroom.scoring_calculator.source_budget_bytes"):
        monkeypatch.setattr(target, lambda model, *, instruction_bytes: max_bytes)


def _instructor(client) -> dict:
    return _login(client, uid="instructor-1")


def _patch_class(client, class_id: int, payload: dict):
    return client.patch(
        f"{CLASSES_URL}/{class_id}",
        data=payload,
        content_type="application/json",
        **_auth_header(_instructor(client)["access"]),
    )


def _instructor_rows(client, ctx) -> list[dict]:
    response = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}/submissions",
        **_auth_header(_instructor(client)["access"]),
    )
    assert response.status_code == 200, response.content
    body = response.json()
    return body["submissions"] if isinstance(body, dict) else body


def _rejections(submission_id: int):
    return ClassroomScoringAttempt.objects.filter(submission_id=submission_id, error__startswith=REJECTED_ERROR_PREFIX)


def _fake_agent(monkeypatch) -> list[str]:
    """에이전트 채점 자리 — 받은 모델을 남기고 모든 요구사항을 충족으로 받아들인다."""

    models: list[str] = []

    def run_scoring(submission, class_obj, *, model, requirements, snapshot):
        models.append(model)
        output = {ITEMS_KEY: [{ID_KEY: r.requirement_id, "met": True, "reason": "있다.", "evidence": ["app.py:1"]} for r in requirements]}
        return agent_grading.AgentAccepted(
            structured_output=output, model_version=f"agent:codex:{model}", record={"model": model}, used_tokens=0
        )

    monkeypatch.setattr(agent_grading, "run_scoring", run_scoring)
    return models


# --- 1. OpenAI 에이전트는 gpt-5-mini 이상만 ---------------------------------------------------------


def test_an_openai_class_opens_agent_from_gpt_5_mini_and_blocks_nano_and_4_1(client, db, monkeypatch):
    ctx = _setup(client, files=_SMALL)
    instructor = _instructor(client)
    body = get_class(client, instructor["access"], ctx["class_id"])
    assert body["grading_method_options"][1] == {"value": "agent", "selectable": True, "unavailable_reason": None}
    assert "gpt-5-mini" in body["agent_models"]
    assert not {"gpt-5-nano", "gpt-5.4-nano", "gpt-4.1-mini", "gpt-4o"} & set(body["agent_models"])

    # 기본 모델이 gpt-4.1-mini 인 채로는 에이전트를 고를 수 없다.
    response = _patch_class(client, ctx["class_id"], {"scoring_method": "agent"})
    assert response.status_code == 422, response.content
    respond_with_verdicts(monkeypatch, [])
    assert _patch_class(client, ctx["class_id"], {"default_model": "gpt-5-mini"}).status_code == 200
    response = _patch_class(client, ctx["class_id"], {"scoring_method": "agent"})
    assert response.status_code == 200, response.content

    for blocked in ("gpt-5-nano", "gpt-4.1-mini"):
        response = client.patch(
            f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
            data={"model": blocked},
            content_type="application/json",
            **_auth_header(instructor["access"]),
        )
        assert response.status_code == 422, (blocked, response.content)


def test_a_blocked_model_already_saved_on_an_agent_class_leaves_the_queue_as_model_rejected(client, db, monkeypatch):
    ctx = _setup(client, files=_SMALL)
    respond_with_verdicts(monkeypatch, [])
    assert _patch_class(client, ctx["class_id"], {"default_model": "gpt-5-mini"}).status_code == 200
    assert _patch_class(client, ctx["class_id"], {"scoring_method": "agent"}).status_code == 200
    # 이 티켓 전에 저장된 문제 모델(화면은 이제 이 값을 받지 않는다).
    Problem.objects.filter(pk=ctx["problem_id"]).update(model="gpt-5-nano")
    models = _fake_agent(monkeypatch)

    _run_scan_with_files(client, _SMALL)

    assert models == []
    assert _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])["submissions"][0][
        "pending_reason"
    ] == "model_rejected"


# --- 2. 클래스 설정 ---------------------------------------------------------------------------------


def test_a_new_class_rejects_by_default_and_agent_needs_an_agent_model(client, db):
    ctx = _setup(client, files=_SMALL)
    body = get_class(client, _instructor(client)["access"], ctx["class_id"])
    assert (body["oversize_policy"], body["oversize_agent_model"]) == ("reject", "")

    assert _patch_class(client, ctx["class_id"], {"oversize_policy": "agent"}).status_code == 422
    assert _patch_class(client, ctx["class_id"], {"oversize_policy": "agent", "oversize_agent_model": "gpt-5-nano"}).status_code == 422
    response = _patch_class(client, ctx["class_id"], {"oversize_policy": "agent", "oversize_agent_model": "gpt-5-mini"})
    assert response.status_code == 200, response.content
    assert (response.json()["oversize_policy"], response.json()["oversize_agent_model"]) == ("agent", "gpt-5-mini")
    assert _patch_class(client, ctx["class_id"], {"oversize_policy": "partial"}).json()["oversize_policy"] == "partial"


# --- 3. 반려 ----------------------------------------------------------------------------------------


def test_reject_calls_no_model_leaves_no_score_and_a_new_attempt_is_scored(client, db, monkeypatch):
    files = {"app.py": _PY_47KB}
    ctx = _setup(client, files=files)
    _budget(monkeypatch, 5_000)
    monkeypatch.setattr("core.llm_scoring.requests.post", lambda *a, **k: pytest.fail("반려할 시도로 벤더를 불렀다"))

    for _ in range(4):  # 다시 집지 않고, 실패 상한(3)에 세지 않는다.
        _run_scan_with_files(client, files)

    attempt = _rejections(ctx["submission_id"]).get()
    assert not attempt.permanent
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    row = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])["submissions"][0]
    assert (row["status"], row["pending_reason"], row["passed"]) == ("pending", "rejected", False)
    assert row["rejection"]["limit_chars"] < row["rejection"]["source_chars"]
    assert _instructor_rows(client, ctx)[0]["rejection"] == row["rejection"]

    # 학생이 줄여서 다시 낸다 — 새 시도가 채점된다.
    monkeypatch.undo()
    respond_with_verdicts(monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "ok"}])
    with override_settings(GITHUB_FAKE_REPO_FILES={REPO_URL: _SMALL}):
        again = _submit_repository(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"], REPO_URL)
    _run_scan_with_files(client, _SMALL)

    assert ClassroomScore.objects.filter(submission_id=again["id"]).exists()
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_the_syntax_check_addendum_is_measured_with_the_request(client, db, monkeypatch, small_limit):
    files = {"index.php": _PHP_47KB}
    ctx = _setup(client, files=files)
    sent: list = []
    respond_with_verdicts(monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "ok"}], capture=sent)

    _run_scan_with_files(client, files)

    assert sent == [], "덧붙임까지 넘치는 요청을 보냈다"
    assert _rejections(ctx["submission_id"]).exists()
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_the_same_size_without_the_addendum_fits(client, db, monkeypatch, small_limit):
    files = {"app.py": _PY_47KB}
    ctx = _setup(client, files=files)
    sent: list = []
    respond_with_verdicts(monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "ok"}], capture=sent)

    _run_scan_with_files(client, files)

    assert len(sent) == 1
    assert ClassroomScore.objects.get(submission_id=ctx["submission_id"]).unseen_files == 0


def test_a_vendor_context_rejection_rejects_and_is_not_picked_again(client, db, monkeypatch):
    ctx = _setup(client, files=_SMALL)
    calls: list = []
    too_long = {"error": {"message": "too long", "type": "invalid_request_error", "code": "context_length_exceeded"}}

    def post(*args, **kwargs):
        calls.append(kwargs["json"]["model"])
        return FakeVendorResponse(400, too_long)

    monkeypatch.setattr("core.llm_scoring.requests.post", post)

    _run_scan_with_files(client, _SMALL)
    _run_scan_with_files(client, _SMALL)

    assert calls == ["gpt-4.1-mini"]
    assert _rejections(ctx["submission_id"]).count() == 1
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


# --- 4. 에이전트로 채점 -----------------------------------------------------------------------------


def test_agent_scores_only_the_oversize_attempt_with_the_agent_model(client, db, monkeypatch):
    files = {"app.py": _PY_47KB}
    ctx = _setup(client, files=files)
    assert _patch_class(client, ctx["class_id"], {"oversize_policy": "agent", "oversize_agent_model": "gpt-5-mini"}).status_code == 200
    _budget(monkeypatch, 5_000)
    monkeypatch.setattr("core.llm_scoring.requests.post", lambda *a, **k: pytest.fail("한 번 호출 길로 나갔다"))
    models = _fake_agent(monkeypatch)

    _run_scan_with_files(client, files)

    assert models == ["gpt-5-mini"]
    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.model_version == "agent:codex:gpt-5-mini"
    assert not _rejections(ctx["submission_id"]).exists()


# --- 5. 들어가는 파일만 -----------------------------------------------------------------------------


def test_partial_scores_the_files_that_fit_and_keeps_the_unseen_count(client, db, monkeypatch):
    files = {"app.py": "print('print가 있다')\n", "zz_big.py": "x = 'BIG_FILE_MARKER'\n" * 3_000}
    ctx = _setup(client, files=files)
    assert _patch_class(client, ctx["class_id"], {"oversize_policy": "partial"}).status_code == 200
    _budget(monkeypatch, 2_000)
    sent: list = []
    respond_with_verdicts(monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "ok"}], capture=sent)

    _run_scan_with_files(client, files)

    assert len(sent) == 1
    assert str(sent[0]).count("BIG_FILE_MARKER") < 3_000, "다 들어가지 않는 파일을 통째로 실었다"
    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.unseen_files == 1
    row = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])["submissions"][0]
    assert row["score"]["unseen_files"] == 1
    assert _instructor_rows(client, ctx)[0]["score"]["unseen_files"] == 1
