"""#986: 앱 코드가 모델 컨텍스트에 다 들어가지 않는 공모전 제출은 벤더를 부르지 않고 보류한다.

공모전 3 16건 중 11건이 자르지 않으면 128K 를 넘었다(앱 코드만으로도 8건). 잘린 소스로 채점하면
「없는 기능」으로 미달이 나므로 사람이 볼 때까지 멈춘다 — 재시도도, 실패 상한의 0% 확정도 없다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.core.management import call_command

from scoring import services
from scoring.models import Score, ScoringAttempt
from tests.integration.test_scoring_transient_vendor_failure import _closed_submission
from tests.integration.test_scoring import (  # noqa: F401 - fixture 들을 이 모듈에도 등록한다.
    _freeze,
    _run_pending,
    category,
    landing_type,
)


class _MustNotBeCalled:
    model_version = "gpt-4o-mini"

    def __init__(self, *, timeout=None) -> None:
        pass

    def score(self, scoring_input):  # pragma: no cover - 불리면 시험이 실패해야 한다.
        raise AssertionError("보류된 제출에 벤더를 불렀다")


def _tiny_budget(monkeypatch) -> list[str]:
    models: list[str] = []

    def budget(model: str, *, instruction_bytes: int) -> int:
        models.append(model)
        return 5  # 시험 제출의 app.py(수십 바이트)가 다 들어가지 않는다.

    monkeypatch.setattr(services, "source_budget_bytes", budget)
    return models


@pytest.mark.django_db
def test_app_code_over_the_model_context_is_held_without_calling_the_vendor(
    client, category, landing_type, monkeypatch
):
    submission_id, deadline = _closed_submission(client, category, landing_type)
    models = _tiny_budget(monkeypatch)
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _MustNotBeCalled())

    rows = _run_pending(client)["rows"]

    assert rows[0]["status"] == "held"
    assert models == ["gpt-4o-mini"]
    attempt = ScoringAttempt.objects.get(submission_id=submission_id)
    assert attempt.error.startswith(services.SCORING_HOLD_ERROR_PREFIX)
    assert "truncated_code_files=1" in attempt.error
    assert not attempt.permanent


@pytest.mark.django_db
def test_a_held_submission_is_not_retried_and_not_finalized_as_zero(
    client, category, landing_type, monkeypatch
):
    submission_id, deadline = _closed_submission(client, category, landing_type)
    _tiny_budget(monkeypatch)
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _MustNotBeCalled())
    _run_pending(client)

    _freeze(deadline + services.SCORING_TRANSIENT_FAILURE_GRACE + timedelta(hours=1))
    assert _run_pending(client)["rows"] == []

    assert ScoringAttempt.objects.filter(submission_id=submission_id).count() == 1
    assert not Score.objects.filter(submission_id=submission_id).exists()


@pytest.mark.django_db
def test_released_hold_is_scored_with_what_fits(client, category, landing_type, monkeypatch):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    _tiny_budget(monkeypatch)
    _run_pending(client)

    call_command("release_scoring_hold", str(submission_id))

    assert _run_pending(client)["rows"][0]["status"] == "scored"
    assert Score.objects.filter(submission_id=submission_id).exists()
    attempt = ScoringAttempt.objects.get(submission_id=submission_id)
    assert attempt.error.startswith(services.SCORING_HOLD_RELEASED_ERROR_PREFIX)


@pytest.mark.django_db
def test_hold_records_do_not_count_toward_the_failure_cap(client, category, landing_type, monkeypatch):
    submission_id, deadline = _closed_submission(client, category, landing_type)
    _tiny_budget(monkeypatch)
    _run_pending(client)
    call_command("release_scoring_hold", str(submission_id))
    for _ in range(4):
        ScoringAttempt.objects.create(submission_id=submission_id, error="RuntimeError: 흉내")

    submission = services.ContestSubmission.objects.get(pk=submission_id)
    assert not services._scoring_cap_reached(submission, as_of=deadline + timedelta(hours=7))


@pytest.mark.django_db
def test_submissions_that_fit_are_scored_as_before(client, category, landing_type):
    submission_id, _deadline = _closed_submission(client, category, landing_type)

    assert _run_pending(client)["rows"][0]["status"] == "scored"
    assert not ScoringAttempt.objects.filter(submission_id=submission_id).exists()


@pytest.mark.django_db
def test_config_left_out_is_held_too(client, category, landing_type, monkeypatch):
    """보탬 4: 「코드 아님」을 뺀 뒤 남은 것은 전부 근거다 — 앱 코드가 다 들어가도 설정이 빠지면 보류한다."""

    from core.source_selection import SelectionOmission

    submission_id, _deadline = _closed_submission(client, category, landing_type)
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _MustNotBeCalled())
    monkeypatch.setattr(
        services,
        "select_source_files_with_omission",
        lambda sources, *, max_bytes: ([], SelectionOmission(omitted_files=1, omitted_bytes=4_000)),
    )

    rows = _run_pending(client)["rows"]

    assert rows[0]["status"] == "held"
    attempt = ScoringAttempt.objects.get(submission_id=submission_id)
    assert "omitted_files=1" in attempt.error
    assert "omitted_code_files=0" in attempt.error


class _RequestTooLarge:
    """보낼 요청이 모델 컨텍스트를 넘는다 — 어댑터가 재어 막았거나 벤더가 400 으로 거절했다(#989)."""

    model_version = "gpt-4o-mini"
    calls = 0

    def __init__(self, *, timeout=None) -> None:
        pass

    def score(self, scoring_input):
        from core.llm_scoring import LLMAdapterInputTooLargeError

        type(self).calls += 1
        raise LLMAdapterInputTooLargeError(
            "채점 요청이 모델 컨텍스트를 넘는다(model=gpt-4o-mini request_tokens≈120000 limit_tokens=111616)",
            model="gpt-4o-mini",
        )


@pytest.mark.django_db
def test_a_request_over_the_model_context_is_held_not_failed(client, category, landing_type, monkeypatch):
    """#989: 보낼 요청이 넘쳐도(벤더 400 컨텍스트 초과 포함) 영구 실패·0% 가 아니라 「크기 초과」 보류다."""

    submission_id, deadline = _closed_submission(client, category, landing_type)
    _RequestTooLarge.calls = 0
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _RequestTooLarge())

    rows = _run_pending(client)["rows"]

    assert rows[0]["status"] == "held"
    attempt = ScoringAttempt.objects.get(submission_id=submission_id)
    assert attempt.error.startswith(services.SCORING_HOLD_ERROR_PREFIX)
    assert "limit_tokens=111616" in attempt.error
    assert not attempt.permanent

    _freeze(deadline + services.SCORING_TRANSIENT_FAILURE_GRACE + timedelta(hours=1))
    assert _run_pending(client)["rows"] == []
    assert _RequestTooLarge.calls == 1
    assert not Score.objects.filter(submission_id=submission_id).exists()


@pytest.mark.django_db
def test_the_source_budget_leaves_room_for_what_the_adapter_sends_besides_the_prompt(
    client, category, landing_type, monkeypatch
):
    """#989: 지시문 몫은 어댑터가 보낼 요청을 그대로 잰 값이다(시스템 지시문·응답 스키마 포함)."""

    from scoring.adapters import FakeLLMScoringAdapter

    measured: list[int] = []

    class _Measuring(FakeLLMScoringAdapter):
        def request_bytes(self, scoring_input):
            measured.append(len(scoring_input.prompt.encode("utf-8")) + 7_000)
            return measured[-1]

    seen: list[int] = []

    def budget(model: str, *, instruction_bytes: int) -> int:
        seen.append(instruction_bytes)
        return 10_000_000

    _closed_submission(client, category, landing_type)
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _Measuring())
    monkeypatch.setattr(services, "source_budget_bytes", budget)

    assert _run_pending(client)["rows"][0]["status"] == "scored"
    assert seen == measured
