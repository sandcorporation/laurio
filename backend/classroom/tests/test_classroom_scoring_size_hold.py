"""#989: 강의실 채점 — 채점 요청이 모델 컨텍스트를 넘으면 자르지도, 미충족으로 굳히지도 않고 「크기 초과」 보류로 둔다.

문법 검사 덧붙임(파서가 못 본 파일의 전문, `classroom.syntax_check.source_section_lines`)은 예전에 300KB 예산 밖에서
붙었다 — 이제 어댑터가 보낼 요청 전체를 재므로 같은 예산 안에 든다. 보류는 그 모델인 동안만이다: 강사가 모델을
바꾸면 다음 스캔이 다시 집는다.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from classroom.models import ClassroomScore, ClassroomScoringAttempt
from classroom.pending_scoring import SIZE_HOLD_ERROR_PREFIX
from tests.classroom_scenarios import FakeVendorResponse, respond_with_verdicts
from classroom.tests.test_classroom_syntax_check_ai_fallback import (
    CLASSES_URL,
    _auth_header,
    _login,
    _run_scan_with_files,
    _setup,
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


@pytest.fixture
def small_limit(monkeypatch):
    monkeypatch.setattr("core.model_context.input_token_limit", lambda model: _LIMIT_TOKENS)


def _held_attempts(submission_id: int):
    return ClassroomScoringAttempt.objects.filter(
        submission_id=submission_id, error__startswith=SIZE_HOLD_ERROR_PREFIX
    )


def test_the_syntax_check_addendum_is_measured_with_the_request(client, db, monkeypatch, small_limit):
    files = {"index.php": _PHP_47KB}
    ctx = _setup(client, files=files)
    sent: list = []
    respond_with_verdicts(monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "ok"}], capture=sent)

    _run_scan_with_files(client, files)

    assert sent == [], "덧붙임까지 넘치는 요청을 보냈다"
    attempt = _held_attempts(ctx["submission_id"]).get()
    assert "model=gpt-4.1-mini " in attempt.error
    assert not attempt.permanent
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_the_same_size_without_the_addendum_fits(client, db, monkeypatch, small_limit):
    files = {"app.py": _PY_47KB}
    ctx = _setup(client, files=files)
    sent: list = []
    respond_with_verdicts(monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "ok"}], capture=sent)

    _run_scan_with_files(client, files)

    assert len(sent) == 1
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_a_source_over_the_model_budget_is_held_without_truncating(client, db, monkeypatch):
    files = {"app.py": _PY_47KB}
    ctx = _setup(client, files=files)
    monkeypatch.setattr("classroom.scoring.source_budget_bytes", lambda model, *, instruction_bytes: 5)
    monkeypatch.setattr("core.llm_scoring.requests.post", lambda *a, **k: pytest.fail("잘린 소스로 벤더를 불렀다"))

    _run_scan_with_files(client, files)

    attempt = _held_attempts(ctx["submission_id"]).get()
    assert "truncated_files=1" in attempt.error
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_a_vendor_context_rejection_is_held_until_the_model_changes(client, db, monkeypatch):
    files = {"app.py": "print('print가 있다')\n"}
    ctx = _setup(client, files=files)
    calls: list = []
    rejected = {"error": {"message": "too long", "type": "invalid_request_error", "code": "context_length_exceeded"}}

    def post(*args, **kwargs):
        calls.append(kwargs["json"]["model"])
        return FakeVendorResponse(400, rejected)

    monkeypatch.setattr("core.llm_scoring.requests.post", post)

    _run_scan_with_files(client, files)
    _run_scan_with_files(client, files)

    assert calls == ["gpt-4.1-mini"], "보류된 시도를 같은 모델로 다시 불렀다"
    assert _held_attempts(ctx["submission_id"]).count() == 1
    assert not ClassroomScoringAttempt.objects.filter(submission_id=ctx["submission_id"], permanent=True).exists()
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()

    instructor = _login(client, uid="instructor-1")
    response = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"model": "gpt-4.1"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 200, response.content
    respond_with_verdicts(monkeypatch, [{"requirement_id": ctx["item_id"], "is_met": True, "reasoning": "ok"}])

    result = _run_scan_with_files(client, files)

    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists(), result


def test_screens_say_size_held_until_the_model_changes(client, db, monkeypatch):
    from classroom.tests.test_classroom_syntax_check_ai_fallback import _mine

    files = {"app.py": "print('print가 있다')\n"}
    ctx = _setup(client, files=files)
    rejected = {"error": {"message": "too long", "type": "invalid_request_error", "code": "context_length_exceeded"}}
    monkeypatch.setattr("core.llm_scoring.requests.post", lambda *a, **k: FakeVendorResponse(400, rejected))
    _run_scan_with_files(client, files)
    instructor = _login(client, uid="instructor-1")

    def instructor_rows():
        response = client.get(
            f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}/submissions",
            **_auth_header(instructor["access"]),
        )
        assert response.status_code == 200, response.content
        return response.json()

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["pending_reason"] == "size_held"
    rows = instructor_rows()
    rows = rows["submissions"] if isinstance(rows, dict) else rows
    assert rows[0]["pending_reason"] == "size_held"

    client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"model": "gpt-4.1"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["pending_reason"] is None
