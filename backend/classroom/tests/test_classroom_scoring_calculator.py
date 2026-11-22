"""채점 비용 계산기 — 프로바이더 × 방식 × 모델 × 체크리스트 × 소스 크기를 골라 제출 한 건 예상을 본다(#1270).

셈(소스 크기·요구사항 수 → 한 번 호출 금액)은 단가표(`scoring_cost.PRICES`) 하나에서 오는지를 단위로 잡고, 고를 수
있는 값·기본 조합·실측(소스 크기 중앙·p90, 에이전트 실행 범위)은 마운트된 HTTP API 로 본다. 벤더는 부르지 않는다 —
한 번 호출은 흉내 응답, 에이전트는 실행기 자리의 가짜(`classroom.tests.test_classroom_agent_method._Runner`)다.
"""

from __future__ import annotations

import pytest

from classroom import scoring_calculator, scoring_cost
from classroom.tests.test_classroom_agent_method import _claude_stream, _Runner
from classroom.tests.test_classroom_anthropic_key import _anthropic_vendor
from core import agent_scoring
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    respond_with_verdict,
    run_scan,
    set_anthropic_key,
    submit_repository,
    submit_source,
    user_id,
)
from tests.integration.test_llm_proxy import FakeVendor

# --- 셈(순수 함수) ---------------------------------------------------------------


def _single(model: str = "gpt-4.1-mini", *, source: int = 30_000, instruction: int = 3_000, requirements: int = 10):
    return scoring_calculator.single_call(
        model,
        None,
        vendor=scoring_calculator.vendor_of_model(model),
        source_chars=source,
        instruction_chars=instruction,
        requirement_count=requirements,
    )


def test_a_single_call_prices_source_plus_instructions_in_and_requirements_out_at_the_table_price():
    cost = _single(source=30_000, instruction=3_000, requirements=10)

    assert cost.input_tokens == scoring_cost.tokens_for_chars(33_000)
    assert cost.output_tokens == 10 * scoring_calculator.OUTPUT_TOKENS_PER_REQUIREMENT
    price = scoring_cost.PRICES["gpt-4.1-mini"]
    expected = (cost.input_tokens * price.input_usd_per_million + cost.output_tokens * price.output_usd_per_million) / 1e6
    assert cost.usd == pytest.approx(expected)


def test_more_source_or_more_requirements_cost_more():
    base = _single()

    assert _single(source=60_000).usd > base.usd
    assert _single(requirements=20).usd > base.usd
    assert _single(requirements=20).input_tokens == base.input_tokens


def test_the_single_call_price_follows_the_price_table(monkeypatch):
    before = _single().usd
    monkeypatch.setitem(
        scoring_cost.PRICES, "gpt-4.1-mini", scoring_cost.ModelPrice(input_usd_per_million=4.0, output_usd_per_million=16.0)
    )

    assert _single().usd == pytest.approx(before * 10)


def test_a_reasoning_model_adds_the_effort_share_on_top_of_the_requirements():
    claude = scoring_calculator.single_call(
        "claude-sonnet-5-5", "medium", vendor="anthropic", source_chars=10_000, instruction_chars=0, requirement_count=4
    )

    assert claude.output_tokens == (
        4 * scoring_calculator.OUTPUT_TOKENS_PER_REQUIREMENT
        + scoring_cost.REASONING_OUTPUT_TOKENS["medium"]
        - scoring_cost.NON_REASONING_OUTPUT_TOKENS
    )


def test_a_source_past_the_model_context_does_not_fit():
    assert _single(source=30_000).fits is True
    assert _single(source=20_000_000).fits is False


def test_claude_single_call_marks_the_requirement_limit_and_openai_does_not():
    limit = scoring_calculator.CLAUDE_SINGLE_REQUIREMENT_LIMIT
    assert limit is not None
    assert _single("claude-haiku-5-5", requirements=limit).requirement_limit == limit
    assert _single("claude-haiku-5-5", requirements=limit - 1).requirement_limit is None
    assert _single("gpt-4.1-mini", requirements=limit).requirement_limit is None


def test_a_spread_needs_the_minimum_sample_count():
    assert scoring_calculator.percentile_spread([1.0, 2.0]).median is None
    spread = scoring_calculator.percentile_spread([float(v) for v in range(1, 11)])
    assert (spread.sample_count, spread.median, spread.p90) == (10, 5.5, 9.0)


# --- HTTP -------------------------------------------------------------------------


def _calc(client, access: str, class_id: int, **params) -> dict:
    query = "&".join(f"{k}={v}" for k, v in params.items() if v is not None)
    response = client.get(f"{CLASSES_URL}/{class_id}/scoring-calculator?{query}", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def test_both_providers_are_offered_and_the_missing_key_is_marked(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    calc = _calc(client, owner["access"], class_id)

    providers = {p["vendor"]: p for p in calc["providers"]}
    assert (providers["openai"]["has_key"], providers["anthropic"]["has_key"]) == (True, False)
    assert [m["id"] for m in providers["anthropic"]["models"]] == [
        m for m in scoring_cost.PRICES if m.startswith("claude-")
    ]
    assert providers["openai"]["models"][0]["input_usd_per_million"] == next(iter(scoring_cost.PRICES.values())).input_usd_per_million
    assert calc["agent_vendors"] == ["anthropic"]
    # 지금 이 클래스의 조합에서 시작한다 — OpenAI 키·한 번 호출·기본 모델.
    assert calc["selection"]["vendor"] == "openai"
    assert calc["selection"]["method"] == "single"
    assert calc["agent"]["available"] is False

    # 키가 없는 Claude 도 고를 수 있고 값이 나온다. 에이전트는 Claude 일 때만 열린다.
    claude = _calc(client, owner["access"], class_id, vendor="anthropic", method="agent", model="claude-haiku-5-5")
    assert claude["selection"]["model_id"] == "claude-haiku-5-5"
    assert claude["selection"]["method"] == "agent"
    assert claude["single"]["usd"] > 0
    openai_agent = _calc(client, owner["access"], class_id, vendor="openai", method="agent")
    assert openai_agent["selection"]["method"] == "single"


def test_without_attempts_the_problem_offers_size_bands_and_its_requirement_count(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(
        client, owner["access"], class_id, required_labels=["가", "나", "다"], optional_labels=["라"]
    )

    calc = _calc(client, owner["access"], class_id)

    (offered,) = calc["problems"]
    assert offered["id"] == problem.id
    assert offered["requirement_count"] == 4
    assert offered["instruction_chars"] > 0
    assert [(s["key"], s["chars"], s["measured"]) for s in offered["sources"]] == [
        ("small", 10_000, False),
        ("medium", 50_000, False),
        ("large", 200_000, False),
    ]
    assert (calc["selection"]["source"], calc["selection"]["source_chars"]) == ("medium", 50_000)
    large = _calc(client, owner["access"], class_id, source="large")
    assert large["single"]["usd"] > calc["single"]["usd"]
    other = _calc(client, owner["access"], class_id, model="gpt-4.1")
    assert other["single"]["usd"] > calc["single"]["usd"]


def test_measured_single_call_prompts_give_the_median_and_p90_source_sizes(client, db, monkeypatch):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(
        client, owner["access"], class_id, submission_formats=["source"], syntax_check_enabled=False
    )
    lengths = [2_000, 4_000, 6_000]
    for index, length in enumerate(lengths):
        uid = f"p{index}"
        participant = login(client, uid=uid)
        join_class(client, participant["access"], class_id, instructor_access=owner["access"])
        submit_source(
            client, participant["access"], class_id, problem.id, participant_user_id=user_id(uid), files={"main.py": "x" * length}
        )
        with force_real_scoring_adapter():
            respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
            run_scan(client)

    calc = _calc(client, owner["access"], class_id)

    (offered,) = calc["problems"]
    assert offered["sample_count"] == 3
    sources = {s["key"]: s for s in offered["sources"]}
    assert set(sources) == {"median", "p90"}
    assert all(s["measured"] for s in sources.values())
    # 프롬프트에서 지시문 몫을 뺀 소스 — 파일 머리글·제출 형식 줄만큼 어긋나는 어림이다.
    assert sources["median"]["chars"] == pytest.approx(4_000, rel=0.05)
    assert sources["p90"]["chars"] == pytest.approx(6_000, rel=0.05)
    assert calc["selection"]["source"] == "median"


def _agent_runs(client, monkeypatch, count: int) -> tuple[dict, int]:
    _anthropic_vendor(monkeypatch)
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    assert set_anthropic_key(client, owner["access"], class_id).status_code == 200
    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"scoring_method": "agent", "default_model": "claude-haiku-5-5"},
        content_type="application/json",
        **auth_header(owner["access"]),
    )
    assert response.status_code == 200, response.content
    problem = create_open_problem(client, owner["access"], class_id, syntax_check_enabled=False)
    verdicts = {"verdicts": [{"requirement_id": problem.item_id, "met": True, "reason": "있다.", "evidence": ["app.py:1"]}]}
    monkeypatch.setattr(agent_scoring, "request_run", _Runner(lambda: _claude_stream(verdicts), vendor=FakeVendor()))
    for index in range(count):
        participant = login(client, uid=f"a{index}")
        join_class(client, participant["access"], class_id, instructor_access=owner["access"])
        submit_repository(client, participant["access"], class_id, problem.id)
    run_scan(client)
    return owner, class_id


def test_two_agent_runs_are_not_a_measurement(client, db, monkeypatch):
    owner, class_id = _agent_runs(client, monkeypatch, 2)

    calc = _calc(client, owner["access"], class_id)

    assert calc["selection"]["method"] == "agent"
    assert calc["agent"]["available"] is True
    assert calc["agent"]["usd"] == {"sample_count": 2, "median": None, "p90": None}
    assert calc["agent"]["seconds"]["median"] is None


def test_three_agent_runs_give_the_median_and_p90_of_that_model(client, db, monkeypatch):
    owner, class_id = _agent_runs(client, monkeypatch, 3)

    calc = _calc(client, owner["access"], class_id, vendor="anthropic", model="claude-haiku-5-5")

    usd = calc["agent"]["usd"]
    assert usd["sample_count"] == 3
    assert usd["median"] > 0 and usd["p90"] >= usd["median"]
    assert calc["agent"]["krw"]["median"] == pytest.approx(usd["median"] * scoring_cost.KRW_PER_USD)
    assert calc["agent"]["seconds"] == {"sample_count": 3, "median": 1.0, "p90": 1.0}
    # 다른 모델의 실측은 섞지 않는다.
    sonnet = _calc(client, owner["access"], class_id, vendor="anthropic", model="claude-sonnet-5-5")
    assert sonnet["agent"]["usd"]["median"] is None
