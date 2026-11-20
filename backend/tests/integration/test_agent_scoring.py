"""#1000: 공모전 에이전트 채점 — 가짜 실행기(`agent-grader` 자리)로 받아들이는 조건과 보류를 본다.

시임은 HTTP(채점 스캔)다. 실행기 서비스 호출(`core.agent_scoring.request_run`)만 가짜로 바꾸고, 실행 토큰
발급·스트림 해석·근거 검사·보류 기록은 실제로 돈다. 시험 제출은 zip 소스 하나(`app.py` 한 줄)라 근거
`app.py:1` 만 실재한다.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta

import pytest
from django.core.management import call_command
from django.test import override_settings

from core.models import AgentRunToken
from core import agent_scoring
from scoring import services
from scoring.agent_runner import AgentGraderBusy
from scoring.models import AgentRun, Score, ScoringAttempt
from tests.integration.test_scoring import (  # noqa: F401 - fixture 들을 이 모듈에도 등록한다.
    _freeze,
    _internal_headers,
    _run_pending,
    category,
    landing_type,
)
from tests.integration.test_scoring_transient_vendor_failure import _closed_submission

AGENT_RUNS_URL = "/api/internal/scoring/agent-runs"


def _requirement_id(submission_id: int) -> int:
    return services.ContestSubmission.objects.get(pk=submission_id).contest.requirements.get().id


def _verdicts(rid: int, *, met: bool = True, evidence: list[str] | None = None, rid_override=None) -> dict:
    return {
        "verdicts": [
            {
                "requirement_id": rid if rid_override is None else rid_override,
                "met": met,
                "reason": "로그인 화면이 있다.",
                "evidence": ["app.py:1"] if evidence is None else evidence,
            }
        ]
    }


def _claude_stream(
    output: dict | None,
    *,
    tools: tuple[str, ...] = ("Read", "Grep", "Glob"),
    calls: tuple[str, ...] = ("Glob", "Read", "Grep"),
    api_key_source: str = "ANTHROPIC_API_KEY",
) -> str:
    events = [
        {"type": "system", "subtype": "init", "tools": list(tools), "apiKeySource": api_key_source},
        {
            "type": "assistant",
            "message": {"content": [{"type": "tool_use", "name": name, "input": {}} for name in calls]},
        },
        {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "num_turns": 4,
            "total_cost_usd": 0.12,
            "usage": {"input_tokens": 1000, "output_tokens": 200},
            "structured_output": output,
        },
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events)


def _codex_stream(output: dict, *, commands: int = 2) -> str:
    events: list[dict] = [{"type": "thread.started", "thread_id": "t"}]
    events += [
        {
            "type": "item.completed",
            "item": {"type": "command_execution", "command": "rg -n 로그인", "exit_code": 0, "aggregated_output": ""},
        }
        for _ in range(commands)
    ]
    events += [
        {"type": "item.completed", "item": {"type": "agent_message", "text": json.dumps(output, ensure_ascii=False)}},
        {"type": "turn.completed", "usage": {"input_tokens": 900, "cached_input_tokens": 100, "output_tokens": 150}},
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events)


class _FakeRunner:
    """`request_run` 자리. 부를 때마다 다음 stdout 을 낸다(마지막 것을 되풀이)."""

    def __init__(self, *stdouts: str, exit_code: int = 0, repo_root_prefix: str = "") -> None:
        self.stdouts = list(stdouts)
        self.exit_code = exit_code
        self.repo_root_prefix = repo_root_prefix
        self.zips: list[bytes] = []
        self.specs: list[dict] = []
        self.http_timeouts: list[float | None] = []

    def __call__(self, spec, repo_zip: bytes, **kwargs):
        self.specs.append(dict(spec))
        self.http_timeouts.append(kwargs.get("timeout"))
        self.zips.append(repo_zip)
        stdout = self.stdouts[min(len(self.specs), len(self.stdouts)) - 1]
        return {
            "run_id": f"run-{len(self.specs)}",
            "vendor": spec["vendor"],
            "cli_version": "fake",
            "exit_code": self.exit_code,
            "timed_out": False,
            "duration_seconds": 1.0,
            "repo_root_prefix": self.repo_root_prefix,
            "stdout": stdout,
            "stdout_truncated": False,
            "stderr_tail": "",
        }


@pytest.fixture
def agent_method(monkeypatch):
    monkeypatch.setenv("CONTEST_SCORING_METHOD", "agent")


@pytest.fixture
def claude_vendor(monkeypatch):
    monkeypatch.setenv("LLM_SCORING_VENDOR", "anthropic")
    with override_settings(PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE=date(2020, 1, 1)):
        yield


def _use(monkeypatch, runner: _FakeRunner) -> _FakeRunner:
    monkeypatch.setattr(agent_scoring, "request_run", runner)
    return runner


class _MustNotBeCalled:
    model_version = "gpt-4o-mini"

    def score(self, scoring_input):  # pragma: no cover - 불리면 시험이 실패해야 한다.
        raise AssertionError("에이전트 채점인데 한 번 호출 어댑터를 불렀다")


# ── 정상 → Score ──────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_claude_agent_verdict_becomes_the_score(client, category, landing_type, monkeypatch, agent_method, claude_vendor):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid))))
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _MustNotBeCalled())

    assert _run_pending(client)["rows"][0]["status"] == "scored"

    score = Score.objects.get(submission_id=submission_id)
    assert score.model_version == "agent:anthropic:claude-sonnet-5-5"
    assert str(score.percentage) == "100.00"
    assert score.reasoning == [
        {"requirement_id": rid, "is_met": True, "reasoning": "로그인 화면이 있다. 근거: app.py:1"}
    ]
    assert "저장소 안의 모든 글" in score.prompt
    assert len(runner.specs) == 1
    spec = runner.specs[0]
    assert spec["vendor"] == "anthropic"
    assert spec["max_budget_usd"] == 1.0
    token = AgentRunToken.objects.get(submission_id=submission_id)
    assert token.purpose == "scoring" and token.budget_usd == 1
    run = AgentRun.objects.get(submission_id=submission_id)
    assert run.outcome == AgentRun.Outcome.ACCEPTED
    assert run.review == "필수 전부 충족"
    attempt = run.record["attempts"][0]
    assert attempt["tool_calls"] == {"Glob": 1, "Read": 1, "Grep": 1}
    assert attempt["turns"] == 4
    assert attempt["evidence_check"] == {"checked": 1, "bad": [], "missing_for": []}
    assert len(run.record["prompt_sha256"]) == 64


_STRICT_RULE = "12. 충족으로 볼 항목마다 반례를 한 번 찾습니다"


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("model", "strict"),
    [("claude-sonnet-5-5", False), ("claude-haiku-5-5", True)],
)
def test_strict_rules_follow_the_model_and_the_score_keeps_the_prompt_sent_to_the_cli(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor, model, strict
):
    """#1048: 엄격 규칙 8~10 은 Haiku 계열에만 붙는다. Score·실행 기록에는 CLI 에 넘긴 지침이 그대로 남는다."""

    monkeypatch.setenv("LLM_ANTHROPIC_MODEL", model)
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid))))
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _MustNotBeCalled())

    assert _run_pending(client)["rows"][0]["status"] == "scored"

    (spec,) = runner.specs
    assert spec["model"] == model
    assert (_STRICT_RULE in spec["prompt"]) is strict
    assert Score.objects.get(submission_id=submission_id).prompt == spec["prompt"]
    record = AgentRun.objects.get(submission_id=submission_id).record
    assert record["prompt_sha256"] == hashlib.sha256(spec["prompt"].encode("utf-8")).hexdigest()


@pytest.mark.django_db
def test_codex_agent_verdict_becomes_the_score(client, category, landing_type, monkeypatch, agent_method):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    _use(monkeypatch, _FakeRunner(_codex_stream(_verdicts(rid, met=False, evidence=[]))))

    assert _run_pending(client)["rows"][0]["status"] == "scored"

    score = Score.objects.get(submission_id=submission_id)
    assert score.model_version == "agent:openai:gpt-4o-mini"
    assert str(score.percentage) == "0.00"
    assert score.reasoning[0]["reasoning"] == "로그인 화면이 있다."
    run = AgentRun.objects.get(submission_id=submission_id)
    assert run.review == "필수 전부 미충족"
    assert run.record["attempts"][0]["tool_calls"] == {"command_execution": 2}


@pytest.mark.django_db
def test_a_bad_first_run_is_retried_once_and_the_good_second_run_is_kept(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(
        monkeypatch,
        _FakeRunner(_claude_stream(_verdicts(rid), calls=("Read",)), _claude_stream(_verdicts(rid))),
    )

    assert _run_pending(client)["rows"][0]["status"] == "scored"

    assert len(runner.specs) == 2
    assert runner.specs[0]["run_token"] != runner.specs[1]["run_token"]
    attempts = AgentRun.objects.get(submission_id=submission_id).record["attempts"]
    assert attempts[0]["problems"] == ["Grep·Glob 0"]
    assert attempts[1]["problems"] == []


@pytest.mark.django_db
def test_repository_snapshot_with_zipball_folder_is_checked_by_path_and_line_range(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    """저장소만 낸 제출 — 채점이 받은 clone 을 그대로 실행기에 주고(두 번 받지 않는다), 실행기가 벗긴 GitHub
    zipball 폴더(`repo_root_prefix`)를 붙여 근거를 찾는다. `경로:줄-줄` 은 끝 줄이 파일 안이어야 한다."""

    from tests.integration.test_repository_archiving import _repository_url, _submit_repository_only
    from tests.integration.test_scoring import _close_contest, _publish_contest, _verified_user
    from django.utils import timezone

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    url = _repository_url("octo")
    top = "octo-repo-abc123"
    files = {f"{top}/src/login.py": "def login():\n    return True\n", f"{top}/README.md": "로그인\n"}
    with override_settings(GITHUB_FAKE_REPO_FILES={url: files}):
        submission_id = _submit_repository_only(client, dev, contest["id"], repo_url=url)["id"]
        services.SubmissionAsset.objects.filter(submission_id=submission_id).update(is_public=True)
        _close_contest(client, contest, deadline=deadline)
        rid = contest["requirements"][0]["id"]
        runner = _use(
            monkeypatch,
            _FakeRunner(
                _claude_stream(_verdicts(rid, evidence=["src/login.py:1-3"])),
                _claude_stream(_verdicts(rid, evidence=["src/login.py:1-2", "./README.md:1"])),
                repo_root_prefix=top,
            ),
        )

        assert _run_pending(client)["rows"][0]["status"] == "scored"

    assert len(runner.specs) == 2
    attempts = AgentRun.objects.get(submission_id=submission_id).record["attempts"]
    assert attempts[0]["problems"] == ["근거 실재 안 함 1: ['%d:src/login.py:1-3(>2)']" % rid]
    assert attempts[1]["evidence_check"]["checked"] == 2
    score = Score.objects.get(submission_id=submission_id)
    assert score.reasoning[0]["reasoning"].endswith("근거: src/login.py:1-2, ./README.md:1")
    assert score.scored_assets[0]["commit_sha"]
    assert len({len(z) for z in runner.zips}) == 1


# ── 어긋나면 재실행 → 보류 ────────────────────────────────────────────────────────────────────────────────


def _held(client, submission_id: int, runner: _FakeRunner) -> AgentRun:
    rows = _run_pending(client)["rows"]
    assert rows[0]["status"] == "held"
    assert len(runner.specs) == 2  # 최초 + 1회 재실행
    assert not Score.objects.filter(submission_id=submission_id).exists()
    attempt = ScoringAttempt.objects.get(submission_id=submission_id)
    assert attempt.error.startswith(services.AGENT_SCORING_HOLD_ERROR_PREFIX)
    assert not attempt.permanent
    run = AgentRun.objects.get(submission_id=submission_id)
    assert run.outcome == AgentRun.Outcome.HELD
    assert len(run.record["attempts"]) == 2
    return run


@pytest.mark.django_db
def test_missing_tool_in_init_is_held(client, category, landing_type, monkeypatch, agent_method, claude_vendor):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid), tools=("Read",))))

    run = _held(client, submission_id, runner)

    assert any("도구 빠짐" in r for r in run.reasons)


@pytest.mark.django_db
def test_codex_without_any_command_is_held(client, category, landing_type, monkeypatch, agent_method):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_codex_stream(_verdicts(rid), commands=0)))

    assert _held(client, submission_id, runner).reasons == ["명령 실행 0"]


@pytest.mark.django_db
def test_met_without_evidence_is_held(client, category, landing_type, monkeypatch, agent_method, claude_vendor):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid, evidence=[]))))

    assert _held(client, submission_id, runner).reasons == [f"근거 없음: [{rid}]"]


@pytest.mark.django_db
def test_evidence_that_does_not_exist_in_the_snapshot_is_held(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(
        monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid, evidence=["app.py:2", "nope.py:1", "../x:1"])))
    )

    run = _held(client, submission_id, runner)

    assert len(run.reasons) == 1 and run.reasons[0].startswith("근거 실재 안 함 3")


@pytest.mark.django_db
def test_a_whole_file_reference_to_an_existing_file_is_accepted(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    """#1699 — 줄 없이 파일만 댄 근거(운영: migration.sql·toss.ts)는 그 파일이 있으면 받아들인다. 없는 파일은 여전히 어긋남."""

    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid, evidence=["app.py"]))))

    assert _run_pending(client)["rows"][0]["status"] == "scored"
    run = AgentRun.objects.get(submission_id=submission_id)
    assert run.record["attempts"][0]["evidence_check"] == {"checked": 1, "bad": [], "missing_for": []}
    assert len(runner.specs) == 1


@pytest.mark.django_db
def test_a_whole_file_reference_to_a_missing_file_is_still_held(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid, evidence=["nope.py"]))))

    assert _held(client, submission_id, runner).reasons == [f"근거 실재 안 함 1: ['{rid}:nope.py(없음)']"]


@pytest.mark.django_db
def test_missing_requirement_id_is_held(client, category, landing_type, monkeypatch, agent_method, claude_vendor):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid, rid_override=rid + 1000))))

    run = _held(client, submission_id, runner)

    assert run.reasons == [f"id 어긋남: 빠짐 [{rid}] 남음 [{rid + 1000}] 받은 1"]


@pytest.mark.django_db
def test_nonzero_exit_and_schema_mismatch_are_held(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    bad = _verdicts(rid)
    bad["verdicts"][0]["met"] = "yes"
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(bad), exit_code=1))

    reasons = _held(client, submission_id, runner).reasons

    assert reasons[0] == "종료코드 1"
    assert reasons[1].startswith("스키마 어긋남 1")


@pytest.mark.django_db
def test_an_api_error_result_keeps_its_text_and_the_stdout_tail(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    """#1666 — 벤더 요청이 실패하면 Claude Code 는 stderr 없이 stdout 에 「success 인데 is_error」 결과를 낸다."""
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    stream = "\n".join(
        json.dumps(e)
        for e in (
            {"type": "system", "subtype": "init", "tools": ["Read", "Grep", "Glob"], "apiKeySource": "ANTHROPIC_API_KEY"},
            {"type": "result", "subtype": "success", "is_error": True, "num_turns": 1, "api_error_status": 400,
             "result": "API Error: 400 invalid_request_error"},
        )
    )
    runner = _use(monkeypatch, _FakeRunner(stream, exit_code=1))

    run = _held(client, submission_id, runner)

    assert "오류 결과 success api_error_status=400 API Error: 400 invalid_request_error" in run.record["attempts"][0]["problems"]
    assert "API Error: 400" in run.record["attempts"][0]["stdout_tail"]


@pytest.mark.django_db
def test_each_attempt_carries_its_cli_and_http_time_limits(client, category, landing_type, monkeypatch, agent_method, claude_vendor):
    """#1686 — 실행기 기본 600초가 아니라 시도 상한(300초)을 넘기고, 실행기 HTTP 는 그보다 60초 더 기다린다."""

    _closed_submission(client, category, landing_type)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(None), exit_code=1))

    _run_pending(client)

    assert [s["timeout_seconds"] for s in runner.specs] == [agent_scoring.ATTEMPT_TIMEOUT_SECONDS] * 2
    assert runner.http_timeouts == [agent_scoring.ATTEMPT_TIMEOUT_SECONDS + 60] * 2


@pytest.mark.django_db
def test_an_attempt_that_spent_the_run_budget_is_not_retried(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    """#1681 — 예산을 다 쓰고 끊긴 시도를 다시 돌리면 같은 길을 헤매며 예산을 한 번 더 쓴다."""
    import dataclasses

    submission_id, _deadline = _closed_submission(client, category, landing_type)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(None), exit_code=1))
    real = agent_scoring.run_usage
    monkeypatch.setattr(
        agent_scoring,
        "run_usage",
        lambda record_id: dataclasses.replace(real(record_id), spent_usd=agent_scoring.RUN_BUDGET_USD),
    )

    rows = _run_pending(client)["rows"]

    assert rows[0]["status"] == "held"
    assert len(runner.specs) == 1
    run = AgentRun.objects.get(submission_id=submission_id)
    assert len(run.record["attempts"]) == 1
    assert "실행 예산 소진 — 재실행하지 않는다" in AgentRun.objects.get(submission_id=submission_id).reasons


@pytest.mark.django_db
def test_a_held_submission_is_not_retried_nor_finalized_as_zero(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid, evidence=[]))))
    _run_pending(client)

    _freeze(deadline + services.SCORING_TRANSIENT_FAILURE_GRACE + timedelta(hours=1))
    assert _run_pending(client)["rows"] == []

    assert len(runner.specs) == 2
    assert not Score.objects.filter(submission_id=submission_id).exists()
    for _ in range(4):
        ScoringAttempt.objects.create(submission_id=submission_id, error="RuntimeError: 흉내")
    submission = services.ContestSubmission.objects.get(pk=submission_id)
    assert not services._scoring_cap_reached(submission, as_of=deadline + timedelta(hours=7))


@pytest.mark.django_db
def test_released_agent_hold_runs_the_agent_again(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(submission_id)
    runner = _use(
        monkeypatch,
        _FakeRunner(
            _claude_stream(_verdicts(rid, evidence=[])),
            _claude_stream(_verdicts(rid, evidence=[])),
            _claude_stream(_verdicts(rid)),
        ),
    )
    _run_pending(client)

    call_command("release_scoring_hold", str(submission_id))

    assert _run_pending(client)["rows"][0]["status"] == "scored"
    assert len(runner.specs) == 3
    attempt = ScoringAttempt.objects.get(submission_id=submission_id)
    assert attempt.error.startswith(services.AGENT_SCORING_HOLD_RELEASED_ERROR_PREFIX)


@pytest.mark.django_db
def test_operator_sees_held_and_review_runs(client, category, landing_type, monkeypatch, agent_method, claude_vendor):
    held_id, _deadline = _closed_submission(client, category, landing_type)
    rid = _requirement_id(held_id)
    _use(monkeypatch, _FakeRunner(_claude_stream(_verdicts(rid, evidence=[]))))
    _run_pending(client)

    response = client.get(AGENT_RUNS_URL, **_internal_headers())

    assert response.status_code == 200
    runs = response.json()["runs"]
    assert [(r["submission_id"], r["outcome"], r["attempts"]) for r in runs] == [(held_id, "held", 2)]
    assert runs[0]["reasons"] == [f"근거 없음: [{rid}]"]
    assert client.get(AGENT_RUNS_URL).status_code == 401


@pytest.mark.django_db
def test_grader_busy_is_a_transient_failure_not_a_hold(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, _deadline = _closed_submission(client, category, landing_type)

    def busy(spec, repo_zip, **_kwargs):
        raise AgentGraderBusy("busy")

    monkeypatch.setattr(agent_scoring, "request_run", busy)

    assert _run_pending(client)["rows"][0]["status"] == "failed"
    attempt = ScoringAttempt.objects.get(submission_id=submission_id)
    assert attempt.error.startswith("AgentGraderBusy:")
    assert ScoringAttempt.objects.filter(services._TRANSIENT_VENDOR_FAILURE).count() == 1
    assert not AgentRun.objects.exists()


# ── 기본값이면 기존 경로 ──────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.parametrize("method", [None, "single_call", "Agentic"])
def test_default_method_keeps_the_single_call_path(client, category, landing_type, monkeypatch, method):
    """값이 없거나 `single_call`·알 수 없는 값이면 그 전과 같다 — 실행 토큰도 발급하지 않는다."""

    if method is not None:
        monkeypatch.setenv("CONTEST_SCORING_METHOD", method)
    submission_id, _deadline = _closed_submission(client, category, landing_type)

    def must_not_run(spec, repo_zip, **_kwargs):  # pragma: no cover - 불리면 시험이 실패해야 한다.
        raise AssertionError("기본값인데 에이전트를 불렀다")

    monkeypatch.setattr(agent_scoring, "request_run", must_not_run)

    assert _run_pending(client)["rows"][0]["status"] == "scored"
    assert not Score.objects.get(submission_id=submission_id).model_version.startswith("agent:")
    assert not AgentRun.objects.exists()
    assert not AgentRunToken.objects.exists()


# ── 벤더 계정 거절은 미룸(#1052) ─────────────────────────────────────────────────────────────────────────

#: 11-19 운영에서 받은 거절 원문 그대로.
USAGE_LIMIT_MESSAGE = (
    "API Error: 400 You have reached your specified workspace API usage limits. "
    "You will regain access on 2026-12-01 at 00:00 UTC."
)


def _vendor_error_stream(status: int, message: str) -> str:
    """CLI 가 벤더 거절을 결과로 감싼 꼴 — 도구는 하나도 부르지 못했다."""

    events = [
        {"type": "system", "subtype": "init", "tools": ["Read", "Grep", "Glob"], "apiKeySource": "ANTHROPIC_API_KEY"},
        {
            "type": "result",
            "subtype": "success",
            "is_error": True,
            "api_error_status": status,
            "num_turns": 1,
            "total_cost_usd": 0,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "result": message,
        },
    ]
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events)


def _two_closed_submissions(client, category, landing_type) -> list[int]:
    from django.utils import timezone

    from tests.integration.test_scoring import _close_contest, _publish_contest, _submit_with_marker, _verified_user

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    ids = [
        _submit_with_marker(client, contest, contest["requirements"][0]["id"], _verified_user(client, f"dev-{n}", f"dev-ci-{n}"))
        for n in (1, 2)
    ]
    _close_contest(client, contest, deadline=deadline)
    return ids


@pytest.mark.django_db
def test_usage_limit_refusal_defers_without_hold_or_failure_and_is_picked_again(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    runner = _use(monkeypatch, _FakeRunner(_vendor_error_stream(400, USAGE_LIMIT_MESSAGE), exit_code=1))

    [row] = _run_pending(client)["rows"]

    assert row["status"] == "deferred"
    assert "usage limits" in row["error"]
    assert len(runner.specs) == 1  # 같은 거절이라 두 번째 시도를 하지 않는다
    assert not ScoringAttempt.objects.exists()  # 보류도 실패 횟수도 늘지 않는다
    assert not Score.objects.exists()
    assert not AgentRun.objects.exists()

    # 다음 스캔에 다시 집힌다 — 한도가 풀리면 그대로 채점된다.
    runner.stdouts, runner.exit_code = [_claude_stream(_verdicts(_requirement_id(submission_id)))], 0
    assert _run_pending(client)["rows"][0]["status"] == "scored"
    assert len(runner.specs) == 2


@pytest.mark.django_db
def test_after_the_first_account_refusal_the_rest_of_the_scan_does_not_call_the_vendor(
    client, category, landing_type, monkeypatch, agent_method, claude_vendor
):
    ids = _two_closed_submissions(client, category, landing_type)
    runner = _use(
        monkeypatch,
        _FakeRunner(_vendor_error_stream(429, "API Error: 429 rate_limit_error: Number of request tokens has exceeded your per-minute rate limit"), exit_code=1),
    )

    rows = _run_pending(client)["rows"]

    assert sorted(r["submission_id"] for r in rows) == sorted(ids)
    assert {r["status"] for r in rows} == {"deferred"}
    assert len(runner.specs) == 1
    assert not ScoringAttempt.objects.exists()


@pytest.mark.django_db
def test_other_vendor_400_is_still_retried_and_held(client, category, landing_type, monkeypatch, agent_method, claude_vendor):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    message = "API Error: 400 invalid_request_error: output_format.schema: unsupported keyword"
    runner = _use(monkeypatch, _FakeRunner(_vendor_error_stream(400, message), exit_code=1))

    run = _held(client, submission_id, runner)

    assert any("unsupported keyword" in r for r in run.reasons)


@pytest.mark.parametrize(
    "detail",
    [
        f"success api_error_status=400 {USAGE_LIMIT_MESSAGE}",
        "success api_error_status=429 API Error: 429 rate_limit_error",
        "success api_error_status=400 Your credit balance is too low to access the Anthropic API.",
        "You exceeded your current quota (insufficient_quota)",
    ],
)
def test_account_refusal_texts_are_recognised(detail):
    assert agent_scoring.account_refusal(detail)


@pytest.mark.parametrize(
    "detail",
    ["", "result 이벤트 없음", "success api_error_status=400 invalid_request_error: schema", "error_max_turns"],
)
def test_other_errors_are_not_account_refusals(detail):
    assert agent_scoring.account_refusal(detail) is None
