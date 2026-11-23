"""채점 방식 실험의 「메인 + 서브에이전트」 에이전트 줄(#1352) — `agent:메인+서브`.

실제 벤더·실행기를 부르지 않는다: 실행기 자리(`agent_scoring.request_run`)에 프록시 흉내를 끼워, 실제 프록시처럼 요청마다
`authorize` 로 그 요청의 모델을 받고 `record_usage` 로 그 모델의 단가를 곱해 쌓는다. stdout 은 Claude Code 2.1.328 이
서브에이전트를 부를 때 내는 stream-json 의 꼴(메인 `Agent` 호출, 서브 안의 호출은 `parent_tool_use_id`, 결과의
`modelUsage`)을 따른다 — 가짜 Anthropic 서버에 그 판을 붙여 확인한 꼴이다.
"""

from __future__ import annotations

import io
import json
from datetime import UTC
from decimal import Decimal

import pytest
from django.core.management import call_command

from core import agent_scoring
from core.agent_run_tokens import (
    Grant,
    Refusal,
    RunTokenRefused,
    Usage,
    authorize,
    issue_run_token,
    record_usage,
    run_usage,
    usage_cost_usd,
)
from core.models import AgentRunToken
from scoring import experiment as ex
from scoring.models import ScoringExperimentRun
from tests.integration.test_scoring import category, landing_type  # noqa: F401 - fixture 등록
from tests.integration.test_scoring_experiment import grader_up, limit, scored  # noqa: F401 - fixture 등록

SONNET, HAIKU = "claude-sonnet-5-5", "claude-haiku-5-5"
PAIR = f"agent:{SONNET}+{HAIKU}"
PLAIN = f"agent:{SONNET}"


def _call(*args: str) -> str:
    out = io.StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


# ── 줄 꼴 ─────────────────────────────────────────────────────────────────────────────────────────────


def test_the_pair_row_names_main_then_subagent_and_a_plain_agent_row_has_none() -> None:
    pair, plain = ex.parse_rows(f"{PAIR},{PLAIN}")
    assert (pair.method, pair.model, pair.sub_model, pair.vendor) == ("agent", SONNET, HAIKU, "anthropic")
    assert pair.name == PAIR and ex.parse_rows(pair.name) == [pair]
    assert plain.sub_model is None and plain.name == PLAIN


@pytest.mark.parametrize(
    "text",
    [
        f"single_call:{HAIKU}+{HAIKU}",  # 에이전트가 아닌 방식
        f"self_loop:{HAIKU}+{HAIKU}",
        f"agent:gpt-4.1-mini+{HAIKU}",  # OpenAI 메인
        f"agent:{SONNET}+gpt-4.1-mini",  # OpenAI 서브
        f"agent:{SONNET}+",
        f"agent:{SONNET}+{HAIKU}+{HAIKU}",
        f"agent:{SONNET}+claude-nonexistent-9",  # 단가 모름
        f"agent:{SONNET}+{HAIKU}@high",  # 강도는 에이전트 줄에 붙지 않는다
    ],
)
def test_a_subagent_is_refused_outside_anthropic_agent_rows(text: str) -> None:
    with pytest.raises(ex.ExperimentError):
        ex.parse_rows(text)


def test_the_cost_estimate_adds_the_subagent_share_under_one_cell_budget() -> None:
    (pair,), (plain,) = ex.parse_rows(PAIR), ex.parse_rows(PLAIN)
    pair_low, pair_high = ex.cost_range(pair)
    plain_low, _ = ex.cost_range(plain)
    (sub_in, sub_out), _ = ex._SUBAGENT_TOKEN_ESTIMATE
    haiku = usage_cost_usd("anthropic", HAIKU, Usage(input_tokens=sub_in, output_tokens=sub_out), long_context=False)
    assert pair_low == (plain_low + haiku).quantize(Decimal("0.0001")) > plain_low
    # 두 모델이 실행 토큰 하나의 예산을 같이 쓴다 — 칸 상한은 그 예산이다.
    assert pair_high == ex.per_cell_max(pair) == ex.CELL_BUDGET_USD["agent"]


# ── 실행 토큰 장부 ──────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_only_experiment_anthropic_tokens_take_a_subagent_model() -> None:
    with pytest.raises(RunTokenRefused):
        issue_run_token(submission_id=1, purpose="scoring", vendor="anthropic", model=SONNET, sub_model=HAIKU)
    with pytest.raises(RunTokenRefused):
        issue_run_token(submission_id=1, purpose="experiment", vendor="openai", model="gpt-4.1-mini", sub_model=HAIKU)
    with pytest.raises(RunTokenRefused):
        issue_run_token(submission_id=1, purpose="experiment", vendor="anthropic", model=SONNET, sub_model="claude-x-0")


@pytest.mark.django_db
def test_the_proxy_takes_the_subagent_model_and_prices_each_request_by_its_own_model(limit) -> None:  # noqa: F811
    limit("5")
    pair = issue_run_token(submission_id=1, purpose="experiment", vendor="anthropic", model=SONNET, sub_model=HAIKU)
    plain = issue_run_token(submission_id=1, purpose="experiment", vendor="anthropic", model=SONNET)

    assert isinstance(g := authorize(pair.token, vendor="anthropic", model=HAIKU), Grant) and g.model == HAIKU
    assert isinstance(authorize(pair.token, vendor="anthropic", model=SONNET), Grant)
    assert isinstance(r := authorize(pair.token, vendor="anthropic", model="claude-opus-5-5"), Refusal) and r.code == "wrong_model"
    # 서브 모델이 없는 토큰(운영 채점과 같은 꼴)은 지금처럼 그 모델만.
    assert isinstance(r := authorize(plain.token, vendor="anthropic", model=HAIKU), Refusal) and r.code == "wrong_model"

    main_use = Usage(input_tokens=3_000, output_tokens=500, cache_read_tokens=20_000, cache_write_tokens=1_000)
    small, big = Usage(input_tokens=40_000, output_tokens=800), Usage(input_tokens=120_000, output_tokens=900)
    spent = [
        record_usage(pair.record_id, main_use, SONNET),
        record_usage(pair.record_id, small, HAIKU),
        record_usage(pair.record_id, big, HAIKU),
    ]
    assert spent[1] == usage_cost_usd("anthropic", HAIKU, small) < usage_cost_usd("anthropic", SONNET, small)
    assert spent[2] == usage_cost_usd("anthropic", HAIKU, big)  # 10만 초과 — 5배 단가

    usage = run_usage(pair.record_id)
    assert usage.spent_usd == sum(spent) and usage.request_count == 3
    assert usage.model_usage is not None
    assert usage.model_usage[SONNET] == {
        "requests": 1, "input_tokens": 3_000, "output_tokens": 500, "cache_read_tokens": 20_000,
        "cache_write_tokens": 1_000, "spent_usd": str(spent[0]), "long_context_requests": 0,
    }
    sub = usage.model_usage[HAIKU]
    assert (sub["requests"], sub["input_tokens"], sub["long_context_requests"]) == (2, 160_000, 1)
    assert Decimal(sub["spent_usd"]) == spent[1] + spent[2]

    record_usage(plain.record_id, main_use, SONNET)
    assert run_usage(plain.record_id).model_usage is None
    assert AgentRunToken.objects.get(pk=plain.record_id).model_usage is None


# ── 실험 칸 하나 ──────────────────────────────────────────────────────────────────────────────────────


MAIN_REQ = Usage(input_tokens=2_000, output_tokens=400, cache_read_tokens=10_000)
SUB_REQS = (Usage(input_tokens=30_000, output_tokens=600), Usage(input_tokens=110_000, output_tokens=700))


def _stream(rid: int, *, subagent: bool) -> str:
    verdict = {"requirement_id": rid, "met": True, "evidence": ["app.py:1"], "reason": "로그인 표식이 있다."}
    tools = ["Task", "Glob", "Grep", "Read", "StructuredOutput"] if subagent else ["Glob", "Grep", "Read", "StructuredOutput"]
    events: list[dict[str, object]] = [{"type": "system", "subtype": "init", "tools": tools, "apiKeySource": "ANTHROPIC_API_KEY"}]
    main_calls = [("Agent", None), ("Grep", None)] if subagent else [("Glob", None), ("Read", None), ("Grep", None)]
    sub_calls = [("Glob", "tu_1"), ("Read", "tu_1"), ("Read", "tu_1")] if subagent else []
    for name, parent in [*main_calls, *sub_calls]:
        events.append({
            "type": "assistant", "parent_tool_use_id": parent,
            "message": {"content": [{"type": "tool_use", "id": f"tu_{len(events)}", "name": name, "input": {}}]},
        })
    model_usage = {SONNET: {"inputTokens": 2_000, "outputTokens": 400, "cacheReadInputTokens": 10_000, "costUSD": 0.01}}
    if subagent:
        model_usage[HAIKU] = {"inputTokens": 140_000, "outputTokens": 1_300, "cacheReadInputTokens": 0, "costUSD": 0.2}
    events.append({
        "type": "result", "subtype": "success", "is_error": False, "num_turns": 3, "total_cost_usd": 0.21,
        "usage": {"input_tokens": 2_000, "output_tokens": 400}, "modelUsage": model_usage,
        "structured_output": {"verdicts": [verdict]},
    })
    return "\n".join(json.dumps(e, ensure_ascii=False) for e in events)


@pytest.fixture
def executor(monkeypatch, scored):  # noqa: F811
    """실행기 + 프록시 흉내 — 메인 요청 하나, 서브 줄이면 서브 요청 둘(하나는 10만 초과)을 그 모델로 보낸다."""

    rid = scored.contest.requirements.get().id
    specs: list[dict] = []

    def run(spec, repo_zip: bytes, *, timeout: float):
        specs.append(dict(spec))
        sub = spec.get("subagent_model")
        for model, usage in [(spec["model"], MAIN_REQ), *((sub, u) for u in SUB_REQS if sub)]:
            grant = authorize(spec["run_token"], vendor=spec["vendor"], model=model)
            assert isinstance(grant, Grant), grant
            record_usage(grant.record_id, usage, grant.model)
        return {
            "run_id": f"r{len(specs)}", "cli_version": "2.1.328", "exit_code": 0, "timed_out": False,
            "duration_seconds": 1.0, "repo_root_prefix": "", "stdout_truncated": False, "stderr_tail": "",
            "stdout": _stream(rid, subagent=sub is not None),
        }

    monkeypatch.setattr(agent_scoring, "request_run", run)
    return specs


@pytest.mark.django_db
def test_a_pair_cell_books_both_models_and_the_plain_agent_row_stays_as_it_was(scored, executor, limit):  # noqa: F811
    limit("5")
    out = _call("compare_scoring_methods", "--contest", str(scored.contest_id), "--rows", f"{PAIR},{PLAIN}",
                "--repeat", "1", "--name", "pair", "--cost-only", "--confirm")

    runs = {r.row: r for r in ScoringExperimentRun.objects.all()}
    assert {r.status for r in runs.values()} == {"scored"}, out
    by_model = {s.get("subagent_model"): s for s in executor}
    assert set(by_model) == {HAIKU, None}  # 기본 에이전트 줄의 요청에는 서브에이전트가 없다

    pair = runs[PAIR]
    main_cost = usage_cost_usd("anthropic", SONNET, MAIN_REQ)
    sub_costs = [usage_cost_usd("anthropic", HAIKU, u) for u in SUB_REQS]
    assert pair.cost_usd == main_cost + sum(sub_costs)  # 칸 비용 = 프록시 장부 = 두 모델 합
    share = pair.record["attempts"][-1]["subagent"]
    assert share["main_model"] == SONNET and share["sub_model"] == HAIKU
    assert Decimal(share["main"]["spent_usd"]) == main_cost and share["main"]["cache_read_tokens"] == 10_000
    assert (share["sub"]["requests"], share["sub"]["long_context_requests"]) == (2, 1)
    assert Decimal(share["sub"]["spent_usd"]) == sum(sub_costs)
    # 메인이 직접 부른 읽기 도구(서브 안의 Read 둘·Glob 하나는 빼고)와 서브 호출 수.
    assert share["main_read_calls"] == {"Read": 0, "Grep": 1, "Glob": 0} and share["subagent_calls"] == 1
    assert set(share["cli_model_usage"]) == {SONNET, HAIKU}
    assert "subagent" not in runs[PLAIN].record["attempts"][-1]
    assert AgentRunToken.objects.filter(sub_model=HAIKU).count() == 1

    report = _call("experiment_report", "pair")
    assert "## 메인 + 서브에이전트 줄의 모델별 몫" in report
    sub_usd = sum(sub_costs)
    section = report.split("## 메인 + 서브에이전트 줄의 모델별 몫", 1)[1].splitlines()
    line = next(ln for ln in section if ln.startswith(f"| {PAIR} |"))
    assert line == (
        f"| {PAIR} | 1 | 2000 | 10000 | 0 | 400 | {main_cost:.4f} | 140000 | 0 | 0 | 1300 | {sub_usd:.4f} | 2 | 1 | 1 | 1 | 3 |"
    )
    assert not any(ln.startswith(f"| {PLAIN} |") for ln in section)

    bill = _call("experiment_report", "pair", "--bill")
    day = pair.created_at.astimezone(UTC).strftime("%Y-%m-%d")
    assert f"| anthropic | {HAIKU} | {day} |" in bill  # 서브 몫은 제 모델 줄로 청구된다
