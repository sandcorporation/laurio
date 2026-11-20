"""#986(ADR-0031 개정): 벤더 시간 초과·판정 누락은 공모전 채점 실패 상한의 횟수에 세지 않는다.

공모전 3에서 실제 저장소를 채점하는 벤더 호출이 20초 한도에 걸려(ReadTimeout 7건) 판정 누락
1건과 함께 실패만 쌓였고, 이대로면 마감 후 6시간에 16건 전원이 되돌릴 수 없는 0%가 될 뻔했다.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from core import scans
from core import tasks as core_tasks
from core.llm_scoring import LLMAdapterError, LLMAdapterTimeoutError
from scoring import services
from scoring.models import Score, ScoringAttempt
from tests.integration.test_scoring import (  # noqa: F401 - fixture 들을 이 모듈에도 등록한다.
    _close_contest,
    _freeze,
    _publish_contest,
    _run_pending,
    _submit_with_marker,
    _verified_user,
    category,
    landing_type,
)


class _RaisingAdapter:
    model_version = "raising-v1"

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def score(self, scoring_input):
        raise self._exc


def _closed_submission(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission_id = _submit_with_marker(client, contest, contest["requirements"][0]["id"], dev)
    _close_contest(client, contest, deadline=deadline)
    return submission_id, deadline


def _fail_with(monkeypatch, exc: Exception) -> list[float | None]:
    timeouts: list[float | None] = []

    def fake_get_adapter(*, timeout: float | None = None):
        timeouts.append(timeout)
        return _RaisingAdapter(exc)

    monkeypatch.setattr(services, "get_adapter", fake_get_adapter)
    return timeouts


@pytest.mark.django_db
def test_five_vendor_timeouts_after_six_hour_grace_do_not_finalize_as_zero(
    client, category, landing_type, monkeypatch
):
    submission_id, deadline = _closed_submission(client, category, landing_type)
    _fail_with(monkeypatch, LLMAdapterTimeoutError("openai 요청 실패: ReadTimeout"))

    for _ in range(5):
        assert _run_pending(client)["rows"][0]["status"] == "failed"

    _freeze(deadline + timedelta(hours=6, minutes=1))
    assert _run_pending(client)["rows"][0]["status"] == "failed"

    assert ScoringAttempt.objects.filter(submission_id=submission_id).count() == 6
    assert not Score.objects.filter(submission_id=submission_id).exists()


@pytest.mark.django_db
def test_vendor_timeouts_still_terminate_after_the_transient_grace(
    client, category, landing_type, monkeypatch
):
    """「반드시 끝난다」(ADR-0031)는 그대로다 — 일시 실패뿐이어도 하루 유예 뒤에는 0%로 확정된다."""

    submission_id, deadline = _closed_submission(client, category, landing_type)
    _fail_with(monkeypatch, LLMAdapterTimeoutError("openai 요청 실패: ReadTimeout"))
    for _ in range(5):
        _run_pending(client)

    _freeze(deadline + services.SCORING_TRANSIENT_FAILURE_GRACE + timedelta(minutes=1))
    assert _run_pending(client)["rows"][0]["status"] == "scored"

    score = Score.objects.get(submission_id=submission_id)
    assert score.percentage == Decimal("0.00")
    assert score.model_version == "platform-auto (채점 실패 상한)"


@pytest.mark.django_db
def test_missing_verdict_failures_recorded_before_986_are_not_counted(
    client, category, landing_type, monkeypatch
):
    """공모전 3의 809 처럼 #986 전 이름(`LLMAdapterError`)으로 남은 판정 누락도 세지 않는다 —
    영구 실패가 아니라 재시도 대상이다(permanent=False)."""

    submission_id, deadline = _closed_submission(client, category, landing_type)
    _fail_with(
        monkeypatch,
        LLMAdapterError(
            "openai 응답이 일부 requirement에 대한 판정을 빠뜨렸다"
            f"(missing_requirement_ids=[1, 2], submission={submission_id})"
        ),
    )
    for _ in range(5):
        _run_pending(client)
    assert not ScoringAttempt.objects.filter(submission_id=submission_id, permanent=True).exists()

    _freeze(deadline + timedelta(hours=6, minutes=1))
    _run_pending(client)
    assert not Score.objects.filter(submission_id=submission_id).exists()


@pytest.mark.django_db
def test_other_failures_still_reach_the_cap_after_six_hours(
    client, category, landing_type, monkeypatch
):
    """일시 벤더 실패를 뺀 나머지가 5회면 예전 규칙(6시간) 그대로다."""

    submission_id, deadline = _closed_submission(client, category, landing_type)
    _fail_with(monkeypatch, LLMAdapterTimeoutError("openai 요청 실패: ReadTimeout"))
    _run_pending(client)
    _fail_with(monkeypatch, LLMAdapterError("openai 응답 본문을 읽지 못했다"))
    for _ in range(5):
        _run_pending(client)

    _freeze(deadline + timedelta(hours=6, minutes=1))
    assert _run_pending(client)["rows"][0]["status"] == "scored"
    assert Score.objects.get(submission_id=submission_id).percentage == Decimal("0.00")


@pytest.mark.django_db
def test_contest_scoring_calls_the_vendor_with_the_contest_timeout(
    client, category, landing_type, monkeypatch
):
    _closed_submission(client, category, landing_type)
    timeouts = _fail_with(monkeypatch, LLMAdapterTimeoutError("흉내"))

    _run_pending(client)

    assert timeouts == [services.CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS]
    assert services.CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS == 180


def test_scoring_scan_runs_in_the_worker_with_room_for_the_vendor_timeout():
    """보탬 4: 행 시작 예산 + 벤더 한도가 실행 상한 안에 들고, 그 상한이 잠금·beat 의 time_limit 이다."""

    spec = scans.SCAN_REGISTRY["submission-scoring"]
    assert spec.worker_time_limit_seconds is not None
    assert (
        spec.time_budget_seconds + services.CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS
        < spec.worker_time_limit_seconds
    )
    entry = scans.beat_schedule()["scan:submission-scoring"]
    assert entry["task"] == "core.run_scan"
    assert entry["options"] == {"expires": spec.interval_seconds, "time_limit": spec.worker_time_limit_seconds}


@pytest.mark.parametrize("name", ["submission-scoring", "submission-quality-review"])
def test_agent_scans_run_in_the_worker_with_room_for_an_agent_job_and_its_retry(name):
    """#1686: 에이전트 한 건(시도 2회 × (CLI 상한 + HTTP 여유))이 행 시작 예산 뒤에도 워커 한도 안에 든다.
    완성도 리뷰도 워커 안에서 돈다 — 실행기는 celery-worker 가 붙은 `agent-call` 망에서만 닿는다."""

    from core import agent_scoring
    from scoring import agent_runner

    spec = scans.SCAN_REGISTRY[name]
    assert agent_scoring.ATTEMPT_TIMEOUT_SECONDS < agent_runner.RUN_TIMEOUT_SECONDS
    assert agent_scoring.AGENT_JOB_MAX_SECONDS == agent_scoring.MAX_ATTEMPTS * (agent_scoring.ATTEMPT_TIMEOUT_SECONDS + 60)
    assert spec.worker_time_limit_seconds is not None
    assert spec.time_budget_seconds + agent_scoring.AGENT_JOB_MAX_SECONDS < spec.worker_time_limit_seconds
    assert agent_scoring.AGENT_JOB_MAX_SECONDS < 15 * 60  # 실행 토큰 TTL(`core.agent_run_tokens.RUN_TOKEN_TTL`) 안
    assert scans.beat_schedule()[f"scan:{name}"]["options"]["time_limit"] == spec.worker_time_limit_seconds


def test_run_scan_task_runs_worker_scans_in_process_and_others_over_http(monkeypatch):
    calls: list[tuple[str, float]] = []
    monkeypatch.setattr(
        core_tasks, "call_internal", lambda path, *, timeout: calls.append((path, timeout)) or {}
    )
    ran: list[str] = []
    monkeypatch.setattr(scans, "run_scan", lambda name: ran.append(name) or {"scan": name})
    spec = scans.SCAN_REGISTRY["submission-scoring"]
    monkeypatch.setitem(scans.SCAN_REGISTRY, "submission-scoring", replace(spec, enabled=lambda: True))

    core_tasks.run_scan.run("submission-scoring")
    core_tasks.run_scan.run("contest-close")

    assert ran == ["submission-scoring"]
    assert calls == [("/api/internal/scans/contest-close", scans.DEFAULT_REQUEST_TIMEOUT_SECONDS)]
