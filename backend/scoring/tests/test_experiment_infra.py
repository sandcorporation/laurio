"""#1257: 채점 방식 실험 — 인프라 실패 판정, 실행기 health 확인, 한 번 호출 비용 추정이 공모전 3 실측을 덮는다."""

from __future__ import annotations

from decimal import Decimal

import pytest

from core.agent_run_tokens import Usage, usage_cost_usd
from core.agent_scoring import AgentRunHeld
from scoring import agent_runner as ar
from scoring import experiment as ex

#: 운영 실험 `selfloop-pilot` 의 한 번 호출 칸 넷(공모전 3 제출 613·617) — (모델, 입력, 출력, 운영 표의 비용).
REAL_SINGLE_CALLS = [
    ("claude-haiku-5-5", 165_656, 1_694, Decimal("0.087063")),
    ("claude-haiku-5-5", 254_525, 1_591, Decimal("0.131240")),
    ("gpt-4.1-mini", 100_242, 2_539, Decimal("0.044159")),
    ("gpt-4.1-mini", 145_230, 2_301, Decimal("0.061774")),
]


@pytest.mark.parametrize(("model", "tokens_in", "tokens_out", "real"), REAL_SINGLE_CALLS)
def test_single_call_estimate_covers_the_contest3_cells(model, tokens_in, tokens_out, real):
    row = ex.parse_rows(f"single_call:{model}")[0]
    # 추정과 실제가 같은 계산(`usage_cost_usd`)이다 — 운영 표의 비용이 그대로 나온다.
    assert usage_cost_usd(row.vendor, model, Usage(input_tokens=tokens_in, output_tokens=tokens_out)) == real
    _low, high = ex.cost_range(row)
    assert high >= real


def test_haiku_estimate_uses_the_real_cost_function():
    row = ex.parse_rows("single_call:claude-haiku-5-5")[0]
    (_lo, (hi_in, hi_out)) = ex._TOKEN_ESTIMATE["single_call"]
    expected = usage_cost_usd("anthropic", row.model, Usage(input_tokens=hi_in, output_tokens=hi_out))
    assert ex.cost_range(row)[1] == expected.quantize(Decimal("0.0001"))


@pytest.mark.parametrize(
    ("status", "problem", "infra"),
    [
        ("failed", "AgentGraderError: URLError", True),  # 운영 selfloop-pilot 의 칸 10개
        ("failed", "AgentGraderBusy: busy", True),
        ("failed", "RunTokenRefused: 오늘 상한", True),
        ("failed", "AgentVendorRefused: api_error_status=429", True),
        ("failed", "ValueError: 응답이 스키마와 다르다", False),
        ("held", "AgentGraderError: URLError", False),
        ("scored", "", False),
    ],
)
def test_infra_failure_rule(status, problem, infra):
    assert ex.is_infra_failure(status, problem) is infra


def _held(stopped: str, detail: str) -> AgentRunHeld:
    return AgentRunHeld(["루프가 멈췄다"], {"attempts": [{"loop": {"stopped": stopped, "stop_detail": detail}}]})


@pytest.mark.parametrize(
    ("stopped", "detail", "status"),
    [
        ("budget", '{"error": {"type": "experiment_daily_limit"}}', ex.INFRA),
        ("proxy_refused", 'HTTP 401 {"error": {"type": "expired"}}', ex.INFRA),
        ("budget", '{"error": {"type": "run_budget"}}', "held"),  # 실행 예산 안에 못 끝낸 것은 방식의 몫
        ("deadline", "실행 전체 600초를 넘었다", "held"),
    ],
)
def test_self_loop_stopped_by_the_proxy_is_infra(monkeypatch, stopped, detail, status):
    def held(*_a, **_k):
        raise _held(stopped, detail)

    monkeypatch.setattr(ex, "run_selfloop_scoring", held)
    row = ex.parse_rows("self_loop:gpt-4.1-mini")[0]
    result = ex._run_self_loop(None, row, ex._Inputs([], [], [], object()))  # type: ignore[arg-type]  # 루프를 바꿔 끼웠다
    assert result.status == status


def test_infra_prefixes_name_the_infra_errors():
    assert ex.INFRA_PROBLEM_PREFIXES == tuple(f"{e.__name__}:" for e in ex.infra_errors())


def test_check_health_raises_when_unreachable():
    with pytest.raises(ar.AgentGraderError):
        ar.check_health(service_url="http://127.0.0.1:9", timeout=1)
