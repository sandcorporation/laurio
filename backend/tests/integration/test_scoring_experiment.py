"""#1246: 채점 방식 비교 실험 — `compare_scoring_methods`·`experiment_report`, 실행 토큰 용도 `experiment` 의 하루 상한.

진짜 모델은 부르지 않는다: 한 번 호출은 가짜 어댑터(`LLM_ADAPTER_MODE=fake`), 우리 루프는 같은 프로세스의 실행기 +
가짜 `llm-proxy`(`tests.selfloop_fake`). 운영 표(`Score`·`ScoreCorrection`·`AgentRun`·순위)는 쓰지 않는다.
"""

from __future__ import annotations

import io
import json
from datetime import UTC
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from contests.models import ContestSubmission
from core import agent_scoring
from core.agent_run_tokens import Grant, Usage, authorize, issue_run_token, record_usage, spent_today_usd, usage_cost_usd
from core.models import AgentRunToken
from policies.runtime_settings import AGENT_EXPERIMENT_DAILY_LIMIT_USD
from scoring import agent_runner as ar
from scoring import experiment as ex
from scoring import services
from scoring.models import AgentRun, Score, ScoreCorrection, ScoringExperiment, ScoringExperimentRun
from tests import selfloop_fake
from tests.integration.test_scoring import category, landing_type  # noqa: F401 - fixture 등록
from tests.integration.test_scoring_transient_vendor_failure import _closed_submission
from tests.selfloop_fake import Call, FakeProxy, Say, serve

SINGLE = "single_call:gpt-4.1-mini"
LOOP = "self_loop:gpt-4.1-mini"


@pytest.fixture
def scored(client, category, landing_type):  # noqa: F811
    submission_id, _ = _closed_submission(client, category, landing_type)
    submission = ContestSubmission.objects.get(pk=submission_id)
    services.score_submission_once(submission, timezone.now())
    assert Score.objects.filter(submission_id=submission_id).exists()
    return submission


@pytest.fixture(autouse=True)
def grader_up(monkeypatch):
    """실행기 health 는 닿는다고 둔다 — 실행은 시험마다 같은 프로세스로 바꿔 끼운다(#1257)."""
    monkeypatch.setattr(ex, "probe_grader", lambda: None)


@pytest.fixture
def limit(monkeypatch):
    monkeypatch.delenv(AGENT_EXPERIMENT_DAILY_LIMIT_USD, raising=False)
    return lambda usd: monkeypatch.setenv(AGENT_EXPERIMENT_DAILY_LIMIT_USD, usd)


def _call(*args: str) -> str:
    out = io.StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


def _production_state() -> tuple:
    scores = list(Score.objects.order_by("pk").values_list("pk", "percentage", "model_version"))
    return scores, AgentRun.objects.count(), ScoreCorrection.objects.count(), AgentRunToken.objects.exclude(purpose="experiment").count()


@pytest.mark.django_db
def test_without_confirm_only_the_preview_and_no_model_call(scored, monkeypatch, limit):
    def boom(*a, **k):
        raise AssertionError("--confirm 없이 모델을 불렀다")

    monkeypatch.setattr(ex, "_RUNNERS", {"single_call": boom, "agent": boom, "self_loop": boom})
    monkeypatch.setattr(agent_scoring, "request_run", boom)
    before = _production_state()

    out = _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--repeat", "3")

    assert "제출 1건 × 회차 3 — 남은 호출 21칸" in out
    assert "agent:claude-sonnet-5-5 | 3 | 0 |" in out and "self_loop:gpt-4.1-mini | 3 | 0 |" in out
    assert "실험 하루 상한 0 USD" in out and "꺼짐" in out
    assert out.rstrip().endswith("--confirm 이 없어 모델을 부르지 않았다.")
    assert not ScoringExperiment.objects.exists() and not AgentRunToken.objects.exists()
    assert _production_state() == before


def _run_in_process(monkeypatch, tmp_path: Path, proxy: FakeProxy) -> None:
    def run(spec, repo_zip: bytes, *, timeout: float):
        zip_path = tmp_path / "repo.zip"
        zip_path.write_bytes(repo_zip)
        work = tmp_path / "work"
        work.mkdir(exist_ok=True)
        monkeypatch.setattr(selfloop_fake, "TOKEN", spec["run_token"])
        return ar.execute_run(ar.validate_spec(dict(spec)), zip_path, ar.RunnerConfig(work_root=work, proxy_base_url=proxy.url))

    monkeypatch.setattr(agent_scoring, "request_run", run)


@pytest.mark.django_db
def test_confirm_runs_cells_writes_only_experiment_tables_and_reports(scored, monkeypatch, tmp_path, limit):
    rid = scored.contest.requirements.get().id
    verdict = Call("submit_verdict", {"met": True, "evidence": ["app.py:1"], "reason": "로그인 표식이 있다."})
    proxy = FakeProxy(
        vendor="openai", model="gpt-4.1-mini",
        script={"map": [[Say("…")]] * 2, rid: [[Call("read_file", {"path": "app.py"})], [verdict]] * 2},
    )
    _run_in_process(monkeypatch, tmp_path, proxy)
    limit("5")
    before = _production_state()

    with serve(proxy):
        out = _call(
            "compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", f"{SINGLE},{LOOP}",
            "--repeat", "2", "--name", "e1", "--by", "시험", "--confirm",
        )

    assert "칸 4개를 돌렸다" in out, out
    experiment = ScoringExperiment.objects.get(name="e1")
    assert experiment.rows == [SINGLE, LOOP] and experiment.created_by == "시험" and experiment.daily_limit_usd == Decimal("5")
    runs = {(r.row, r.round): r for r in experiment.runs.all()}
    assert set(runs) == {(SINGLE, 1), (SINGLE, 2), (LOOP, 1), (LOOP, 2)}
    loop = runs[(LOOP, 1)]
    assert loop.status == "scored", loop.problem
    assert loop.score == Decimal("100.00") and loop.model_version == "agent:selfloop:gpt-4.1-mini"
    assert (loop.evidence_offered, loop.evidence_real, loop.evidence_all_real) == (1, 1, True)
    assert loop.cost_usd > 0 and loop.input_tokens > 0 and loop.duration_seconds is not None
    assert runs[(SINGLE, 1)].status == "scored" and runs[(SINGLE, 1)].model_version == "fake-llm-v1"
    assert set(AgentRunToken.objects.values_list("purpose", flat=True)) == {"experiment"}
    # 운영 표는 그대로다.
    assert _production_state() == before

    md = _call("experiment_report", "e1")
    assert md.startswith("# 채점 방식 비교 — e1\n") and f"기준 줄 {SINGLE}" in md and "제출 1건 × 회차 2." in md
    assert f"| {LOOP} | 1 | 2 | 2 | 0 | 0 |" in md
    csv = _call("experiment_report", "e1", "--format", "csv").splitlines()
    assert csv[0].startswith("줄,") and len(csv) == 3


@pytest.mark.django_db
def test_stops_at_the_daily_limit_and_resumes_only_the_rest(scored, monkeypatch, limit):
    def single(submission, row, inputs):
        return ex.CellResult("scored", score=Decimal("50"), cost_usd=Decimal("0.05"))

    monkeypatch.setattr(ex, "_RUNNERS", {"single_call": single})
    # 칸당 최대를 0.05 로 고정한다(추정값이 아니라 시험이 정한 값).
    monkeypatch.setattr(ex, "cost_range", lambda row, observed=(): (Decimal("0.05"), Decimal("0.05")))
    args = ("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", SINGLE, "--repeat", "5", "--confirm")
    limit("0.12")

    first = _call(*args)

    assert "하루 상한에 닿아 멈췄다" in first and "남은 칸 3개" in first
    assert ScoringExperimentRun.objects.count() == 2

    limit("1")
    second = _call(*args)

    assert "(이어서)" in second and "남은 호출 3칸" in second and "칸 3개를 돌렸다" in second
    assert sorted(ScoringExperimentRun.objects.values_list("round", flat=True)) == [1, 2, 3, 4, 5]
    assert ScoringExperiment.objects.count() == 1
    assert "남은 호출 0칸" in _call(*args[:-1])


@pytest.mark.django_db
def test_two_by_one_first_then_the_same_experiment_grows_to_three_rounds(scored, monkeypatch, limit):
    monkeypatch.setattr(ex, "_RUNNERS", {"single_call": lambda *a: ex.CellResult("scored", score=Decimal("50"), cost_usd=Decimal("0.01"))})
    limit("1")
    base = ("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", SINGLE, "--name", "probe")

    _call(*base, "--limit-submissions", "2", "--repeat", "1", "--confirm")
    report = _call("experiment_report", "probe")
    assert "회차 1 — 잴 수 없음" in report and "제출 1 × 회차 3" in report and "| 0.0100 | 0.03 |" in report

    out = _call(*base, "--repeat", "3", "--confirm")
    assert "(이어서)" in out and "남은 호출 2칸" in out
    experiment = ScoringExperiment.objects.get(name="probe")
    assert (experiment.repeat, experiment.limit_submissions) == (3, None)
    assert sorted(experiment.runs.values_list("round", flat=True)) == [1, 2, 3]


@pytest.mark.django_db
def test_limit_zero_runs_nothing(scored, monkeypatch):
    monkeypatch.setattr(ex, "_RUNNERS", {"single_call": lambda *a: pytest.fail("상한 0 인데 돌았다")})
    out = _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", SINGLE, "--confirm")
    assert "하루 상한에 닿아 멈췄다" in out
    assert not ScoringExperimentRun.objects.exists()


@pytest.mark.django_db
def test_bad_rows_are_refused(scored):
    from django.core.management.base import CommandError

    with pytest.raises(CommandError, match="방식은"):
        _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", "magic:gpt-4.1-mini")
    with pytest.raises(CommandError, match="단가를 모르는"):
        _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", "agent:gpt-unknown")


@pytest.mark.django_db
def test_experiment_tokens_have_their_own_daily_limit(limit):
    exp = issue_run_token(submission_id=1, purpose="experiment", vendor="openai", model="gpt-4.1-mini")
    prod = issue_run_token(submission_id=1, purpose="scoring", vendor="openai", model="gpt-4.1-mini")

    refusal = authorize(exp.token, vendor="openai", model="gpt-4.1-mini")
    assert getattr(refusal, "code", None) == "experiment_daily_limit" and refusal.status == 429  # 기본 0 = 꺼짐

    limit("2")
    AgentRunToken.objects.filter(pk=exp.record_id).update(spent_usd=Decimal("0.5"))
    assert getattr(authorize(exp.token, vendor="openai", model="gpt-4.1-mini"), "record_id", None) == exp.record_id
    # 실험 몫은 운영 하루 합계에 세지 않고, 운영 몫은 실험 합계에 세지 않는다.
    AgentRunToken.objects.filter(pk=prod.record_id).update(spent_usd=Decimal("0.25"))
    assert spent_today_usd() == Decimal("0.25") and spent_today_usd(experiment=True) == Decimal("0.5")


def _grader_down():
    raise ar.AgentGraderError("URLError")


@pytest.mark.django_db
def test_unreachable_grader_makes_no_cells_even_with_confirm(scored, monkeypatch, limit):
    from django.core.management.base import CommandError

    monkeypatch.setattr(ex, "probe_grader", _grader_down)
    monkeypatch.setattr(ex, "_RUNNERS", {"self_loop": lambda *a: pytest.fail("실행기에 못 닿는데 칸을 돌았다")})
    limit("5")
    args = ("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", LOOP, "--repeat", "1")

    preview = _call(*args)
    assert "실행기 agent-grader:8003 에 닿지 못한다(URLError) — celery-worker 에서 돌린다" in preview
    with pytest.raises(CommandError, match="닿지 못한다.*한 칸도 만들지 않았다"):
        _call(*args, "--confirm")
    assert not ScoringExperiment.objects.exists() and not ScoringExperimentRun.objects.exists()
    # 한 번 호출 줄만이면 실행기를 묻지 않는다.
    assert "실행기" not in _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", SINGLE)


@pytest.mark.django_db
def test_infra_failures_rerun_and_model_failures_do_not(scored, monkeypatch, limit):
    def single(submission, row, inputs):
        raise ValueError("응답이 스키마와 다르다")  # 모델이 틀린 꼴을 냈다 — 방식의 실패

    def loop_down(submission, row, inputs):
        raise ar.AgentGraderError("URLError")

    monkeypatch.setattr(ex, "_RUNNERS", {"single_call": single, "self_loop": loop_down})
    limit("5")
    args = ("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", f"{SINGLE},{LOOP}", "--repeat", "2",
            "--name", "pilot", "--confirm")

    first = _call(*args)

    assert first.count("인프라 실패(결과로 남기지 않는다)") == 2 and "인프라 실패 2칸은 남기지 않았다" in first
    experiment = ScoringExperiment.objects.get(name="pilot")
    assert sorted(experiment.runs.values_list("row", "status")) == [(SINGLE, "failed"), (SINGLE, "failed")]
    # #1257 전 판은 인프라 실패도 `failed` 로 남겼다(운영 selfloop-pilot) — 같은 규칙으로 다시 돌아야 한다.
    ScoringExperimentRun.objects.create(
        experiment=experiment, submission=scored, row=LOOP, round=1, status="failed",
        problem="AgentGraderError: URLError", created_at=timezone.now(),
    )
    assert f"| {LOOP} | 0 | 0 | 0 | 0 | 0 |" in _call("experiment_report", "pilot")  # 결과가 아니라 보고표에 없다

    monkeypatch.setattr(ex, "_RUNNERS", {
        "single_call": lambda *a: pytest.fail("모델 실패 칸을 다시 돌았다"),
        "self_loop": lambda *a: ex.CellResult("scored", score=Decimal("90"), cost_usd=Decimal("0.02")),
    })
    second = _call(*args)

    assert "남은 호출 2칸" in second and "칸 2개를 돌렸다" in second, second
    runs = {(r.row, r.round): r.status for r in experiment.runs.all()}
    assert runs == {(SINGLE, 1): "failed", (SINGLE, 2): "failed", (LOOP, 1): "scored", (LOOP, 2): "scored"}
    assert f"| {LOOP} | 1 | 2 | 2 | 0 | 0 |" in _call("experiment_report", "pilot")


@pytest.mark.django_db
def test_three_infra_failures_in_a_row_stop_the_run(scored, monkeypatch, limit):
    from django.core.management.base import CommandError

    calls = []

    def busy(*a):
        calls.append(a)
        raise ar.AgentGraderBusy("busy")

    monkeypatch.setattr(ex, "_RUNNERS", {"self_loop": busy})
    limit("5")
    with pytest.raises(CommandError, match="연속 3칸이라 멈췄다. 남은 칸 5개"):
        _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", LOOP, "--repeat", "5", "--confirm")
    assert len(calls) == 3 and not ScoringExperimentRun.objects.exists()


# ── 돈의 상한(#1259) ──────────────────────────────────────────────────────────────────────────────────

HAIKU_LOOP = "self_loop:claude-haiku-5-5"
MINI_AGENT = "agent:gpt-4.1-mini"


def _proxy_like_executor(monkeypatch, plan: list[tuple[int, Usage]], stdout) -> list[dict]:
    """실행기 + 프록시 흉내 — 시도마다 (요청 수, 요청 하나의 usage). 실제 프록시처럼 요청 **전에** `authorize` 로 예산·하루
    상한을 보고, 거절되면 그 시도를 멈추고, 받은 요청은 `record_usage` 로 요청마다 단가를 곱해 쌓는다."""

    specs: list[dict] = []

    def run(spec, repo_zip: bytes, *, timeout: float):
        requests, usage = plan[len(specs)]
        specs.append(dict(spec))
        for _ in range(requests):
            grant = authorize(spec["run_token"], vendor=spec["vendor"], model=spec["model"])
            if not isinstance(grant, Grant):
                break
            record_usage(grant.record_id, usage)
        return {
            "run_id": f"r{len(specs)}", "cli_version": "fake", "exit_code": 0, "timed_out": False,
            "duration_seconds": 1.0, "stdout_truncated": False, "stderr_tail": "", "stdout": stdout(spec),
        }

    monkeypatch.setattr(agent_scoring, "request_run", run)
    return specs


def _loop_stdout(rid: int, requests: int, per: Usage):
    total = {
        "requests": requests, "input_tokens": per.input_tokens * requests, "output_tokens": per.output_tokens * requests,
        "cache_read_tokens": 0, "cache_write_tokens": 0,
    }
    verdict = {"requirement_id": rid, "met": True, "evidence": ["app.py:1"], "reason": "로그인 표식이 있다."}
    loop = {"usage": total, "map": {"usage": total}, "requirements": [{"requirement_id": rid, "status": "resolved", "usage": total}]}
    return lambda spec: json.dumps({"verdicts": [verdict], "loop": loop})


def _spend_today(usd: str) -> None:
    prior = issue_run_token(submission_id=1, purpose="experiment", vendor="openai", model="gpt-4.1-mini")
    AgentRunToken.objects.filter(pk=prior.record_id).update(spent_usd=Decimal(usd))


@pytest.mark.django_db
def test_loop_cell_costs_what_the_proxy_counted_not_five_times_and_bill_lists_it(scored, monkeypatch, limit):
    # 운영 617 의 꼴: Haiku 우리 루프 합계 176만 토큰, 요청 하나는 10만 미만(8.8만) — 할증이 붙지 않는다.
    per = Usage(input_tokens=88_000, output_tokens=1_500)
    rid = scored.contest.requirements.get().id
    _proxy_like_executor(monkeypatch, [(20, per)], _loop_stdout(rid, 20, per))
    limit("5")

    out = _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", HAIKU_LOOP, "--repeat", "1",
                "--name", "bill", "--confirm")

    run = ScoringExperimentRun.objects.get()
    assert run.status == "scored", (run.problem, out)
    # 요청마다 0.0088 + 0.00075 = 0.00955, 스무 번 = 0.191. 합계에 문턱을 걸면 5배(0.955)가 된다.
    assert run.cost_usd == Decimal("0.191000") and run.input_tokens == 1_760_000
    loop = run.record["attempts"][-1]["loop"]
    assert loop["cost_basis"] == "sum_without_long_context" and Decimal(loop["cost_usd"]) == Decimal("0.191")

    bill = _call("experiment_report", "bill", "--bill")
    assert bill.startswith("# 청구 대조 — bill\n")
    day = run.created_at.astimezone(UTC).strftime("%Y-%m-%d")
    assert f"| anthropic | claude-haiku-5-5 | {day} |" in bill
    assert "| 20 | 1760000 | 0 | 0 | 30000 | 0.191000 |" in bill and "| 합계 | | | | 20 | | | | | 0.191000 |" in bill


@pytest.mark.django_db
def test_agent_cell_attempts_share_one_cell_budget(scored, monkeypatch, limit):
    # 요청 하나 = 입력 10만($0.04) + 출력 6250($0.01) = $0.05. 첫 시도는 $0.60 을 쓰고 틀린 꼴로 끝난다.
    per = Usage(input_tokens=100_000, output_tokens=6_250)
    specs = _proxy_like_executor(monkeypatch, [(12, per), (100, per)], lambda spec: "")
    limit("5")

    _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", MINI_AGENT, "--repeat", "1", "--confirm")

    run = ScoringExperimentRun.objects.get()
    assert run.status == "held" and len(specs) == 2
    budgets = list(AgentRunToken.objects.filter(purpose="experiment").order_by("pk").values_list("budget_usd", "spent_usd"))
    assert budgets == [(Decimal("1"), Decimal("0.6")), (Decimal("0.4"), Decimal("0.4"))]
    assert specs[1]["max_budget_usd"] == pytest.approx(0.4)
    assert run.cost_usd == Decimal("1.000000") <= ex.CELL_BUDGET_USD["agent"]


@pytest.mark.django_db
def test_a_cell_does_not_start_when_the_day_has_less_than_its_hard_cap(scored, monkeypatch, limit):
    # 운영 11-21 의 순서: 남은 0.2524 > 추정 0.1792 라 시작했고 0.58 을 쓰다 끊겼다. 이제는 칸 예산($1)과 견준다.
    specs = _proxy_like_executor(monkeypatch, [], lambda spec: pytest.fail("남은 돈이 칸 예산보다 적은데 시작했다"))
    limit("5")
    _spend_today("4.7476")

    out = _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", LOOP, "--repeat", "1", "--confirm")

    assert "하루 상한에 닿아 멈췄다 — 남은 돈 0.2524 < 칸당 최대 1.0000" in out
    assert not specs and not ScoringExperimentRun.objects.exists()
    assert "self_loop:gpt-4.1-mini | 1 | 0 |" in out and "| 1.0000" in out  # 미리 보기의 칸당 최대도 칸 예산


@pytest.mark.django_db
def test_a_started_cell_is_cut_within_the_days_money_plus_one_request(scored, monkeypatch, limit):
    # 칸 도중(나): 토큰 예산 = min(칸 예산, 남은 하루 돈). 시작 확인을 지나친 칸(동시에 다른 지출 등)도 하루 상한 앞에서 끊긴다.
    per = Usage(input_tokens=100_000, output_tokens=18_750)  # 요청 하나 $0.07
    one_request = usage_cost_usd("openai", "gpt-4.1-mini", per)
    rid = scored.contest.requirements.get().id
    _proxy_like_executor(monkeypatch, [(9, per)], _loop_stdout(rid, 9, per))  # 다 돌면 $0.63
    limit("5")
    _spend_today("4.7476")
    experiment = ScoringExperiment.objects.create(
        name="cut", contest=scored.contest, created_by="시험", rows=[LOOP], repeat=1, daily_limit_usd=Decimal("5")
    )

    ex.run_cell(experiment, scored, ex.parse_rows(LOOP)[0], 1, ex.load_inputs(scored))

    token = AgentRunToken.objects.filter(purpose="experiment").latest("pk")
    assert token.budget_usd == Decimal("0.2524")
    assert ex.spent_today_experiment_usd() <= Decimal("5") + one_request  # 넘쳐도 요청 하나 몫
    assert token.spent_usd == Decimal("0.28")  # 0.21 < 0.2524 라 넷째 요청까지 받고 끊긴다


def test_openai_cached_input_is_priced_at_the_cache_rate():
    # gpt-4.1-mini: 입력 $0.40, 캐시 입력 $0.10, 출력 $1.60 / 100만.
    assert usage_cost_usd("openai", "gpt-4.1-mini", Usage(input_tokens=1_000_000, cache_read_tokens=800_000)) == Decimal("0.16")
    # 운영 4.1-mini 실행 토큰 6개: 입력 879만 중 캐시 708만 — 입력 몫이 $3.52 가 아니라 $1.392.
    assert usage_cost_usd("openai", "gpt-4.1-mini", Usage(input_tokens=8_790_000, cache_read_tokens=7_080_000)) == Decimal("1.392")
    # 긴 프롬프트 할증(gpt-5.4, 27.2만 초과)은 캐시 입력에도 붙는다: 20만 × $5 + 10만 × $0.50.
    assert usage_cost_usd("openai", "gpt-5.4", Usage(input_tokens=300_000, cache_read_tokens=100_000)) == Decimal("1.05")
    # 표에 캐시 단가가 없는 모델은 입력 단가 그대로.
    assert usage_cost_usd("openai", "gpt-4.1-nano", Usage(input_tokens=1_000_000, cache_read_tokens=1_000_000)) == Decimal("0.1")
    # Anthropic 은 그대로(캐시 읽기 0.1배).
    assert usage_cost_usd("anthropic", "claude-haiku-5-5", Usage(input_tokens=0, cache_read_tokens=50_000)) == Decimal("0.0005")


def test_haiku_long_prompt_surcharge_is_per_request_and_off_for_sums():
    one = Usage(input_tokens=88_000, output_tokens=1_500)
    total = Usage(input_tokens=1_760_000, output_tokens=30_000)
    assert usage_cost_usd("anthropic", "claude-haiku-5-5", one) * 20 == Decimal("0.191")
    assert usage_cost_usd("anthropic", "claude-haiku-5-5", total) == Decimal("0.955")  # 합계에 걸면 5배
    assert usage_cost_usd("anthropic", "claude-haiku-5-5", total, long_context=False) == Decimal("0.191")


def test_spread_picks_evenly_across_the_score_order():
    ranked = list(range(10, 20))
    assert ex.spread(ranked, 4) == [10, 13, 16, 19]
    assert ex.spread(ranked, 1) == [14]
    assert ex.spread(ranked, 10) == ranked and ex.spread(ranked, 30) == ranked


@pytest.mark.django_db
def test_pick_is_kept_with_the_experiment(scored, monkeypatch, limit):
    monkeypatch.setattr(ex, "_RUNNERS", {"single_call": lambda *a: ex.CellResult("scored", score=Decimal("50"), cost_usd=Decimal("0.01"))})
    limit("5")
    args = ("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", SINGLE, "--repeat", "1",
            "--limit-submissions", "1", "--name", "p")

    _call(*args, "--pick", "spread", "--confirm")

    assert ScoringExperiment.objects.get(name="p").pick == "spread"
    with pytest.raises(CommandError, match="--pick spread 로 만들어졌다"):
        _call(*args, "--pick", "id")
    assert "남은 호출 0칸" in _call(*args)  # --pick 을 빼면 실험에 남은 고르는 법으로
