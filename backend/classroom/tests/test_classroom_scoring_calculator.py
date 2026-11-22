"""채점 비용 예상표(#1270·#1304) — 프로바이더 × 방식 × 모델의 제출 한 건 예상은 단가표 × 가정이라 빈 클래스에서도 모든 칸에 금액이 있고,
실측은 그 옆에 덧붙는다.

셈(소스 크기·요구사항 수 → 한 번 호출 금액·감당 글자 수)은 단가표(`scoring_cost.PRICES`)·`source_budget_bytes` 한 곳에서 오는지를
단위로 잡고, 표·가정·실측은 마운트된 HTTP API 로 본다. 벤더는 부르지 않는다 — 한 번 호출은 흉내 응답, 에이전트는 실행기 자리의
가짜(`classroom.tests.test_classroom_agent_method._Runner`)다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from classroom import scoring, scoring_calculator, scoring_cost
from core import model_context
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
    zip_bytes,
    user_id,
)
from tests.integration.test_llm_proxy import FakeVendor

# --- 셈(순수 함수) ---------------------------------------------------------------


def _single(model: str = "gpt-4.1-mini", *, source: int = 30_000, instruction: int = 3_000, requirements: int = 10):
    return scoring_calculator.single_call(
        model,
        None,
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
        "claude-sonnet-5-5", "medium", source_chars=10_000, instruction_chars=0, requirement_count=4
    )

    assert claude.output_tokens == (
        4 * scoring_calculator.OUTPUT_TOKENS_PER_REQUIREMENT
        + scoring_cost.REASONING_OUTPUT_TOKENS["medium"]
        - scoring_cost.NON_REASONING_OUTPUT_TOKENS
    )


def test_a_source_past_the_model_context_does_not_fit_and_is_held_without_a_charge():
    assert _single(source=30_000).fits is True
    assert _single(source=30_000).route == "single"
    held = _single(source=20_000_000)
    assert (held.fits, held.route, held.usd) == (False, "hold", 0.0)


def test_the_capacity_comes_from_the_same_budget_function_the_scoring_uses():
    for model in scoring_cost.PRICES:
        budget = model_context.source_budget_bytes(model, instruction_bytes=3_000)
        capacity = scoring_calculator.single_call(
            model, None, source_chars=1, instruction_chars=3_000, requirement_count=1
        ).capacity_chars
        assert capacity == int(budget // scoring_calculator.BYTES_PER_CHAR)


def test_the_fit_is_judged_in_bytes_not_in_characters():
    capacity = _single(source=1).capacity_chars

    assert _single(source=capacity).fits is True
    # 글자 수로는 예산 안처럼 보여도 바이트(× BYTES_PER_CHAR)로 바꾸면 넘는 경계 — 실제 채점은 바이트로 자른다.
    assert _single(source=capacity + 2).fits is False


def _hangul_source(size_bytes: int) -> str:
    """바이트가 글자보다 많은 파이썬 소스 — 한글 주석 줄에 영문 주석으로 바이트 수를 맞춘다."""

    unit = "# 가나다\n"  # 12바이트 · 7글자
    body = unit * (size_bytes // len(unit.encode()))
    return body + "#" * (size_bytes - len(body.encode()))


@pytest.mark.parametrize("delta, held", [(-1, False), (0, False), (1, True)])
def test_a_hangul_source_is_held_by_the_scoring_exactly_when_the_calculator_says_it_does_not_fit(delta, held):
    """한글 소스를 채점에 그대로 넣어 본다(모델은 부르지 않는다) — 채점의 「크기 초과」 보류(#989, `omission.any`)와
    계산기의 한 번 호출 판정이 예산 바로 아래·위에서 같다. 계산기는 글자를 받으므로 바이트를 같은 예산에 직접 대 본다."""

    model, instruction = "gpt-4o-mini", 3_000
    budget = model_context.source_budget_bytes(model, instruction_bytes=instruction)
    text = _hangul_source(budget + delta)
    assert len(text.encode()) == budget + delta and len(text) < len(text.encode())  # 바이트 > 글자

    _, omission = scoring._scoring_source_files(
        zip_bytes({"main.py": text}), SimpleNamespace(id=1, label="s"), model=model, instruction_bytes=instruction
    )
    fits = scoring_calculator.fits_source_bytes(model, source_bytes=len(text.encode()), instruction_chars=instruction)

    assert omission.any is held
    assert fits is (not held)


@pytest.mark.parametrize("delta", [-1_000, 1_000])
def test_the_calculator_input_in_characters_is_the_bytes_over_bytes_per_char(delta):
    """계산기 입력은 글자라 `바이트 ÷ BYTES_PER_CHAR` 로 넣으면 같은 판정이다 — 예산 1천 바이트 아래는 들어가고 위는 보류."""

    model, instruction = "gpt-4o-mini", 3_000
    budget = model_context.source_budget_bytes(model, instruction_bytes=instruction)
    chars = int((budget + delta) / scoring_calculator.BYTES_PER_CHAR)

    single = _single(model, source=chars, instruction=instruction)

    assert single.fits is (delta < 0)
    assert single.route == ("single" if delta < 0 else "hold")


def test_every_priced_model_has_a_known_context_window():
    unknown = [m for m in scoring_cost.PRICES if not model_context.is_known_model(m)]
    assert unknown == []


def _staged_single(source: int, **kwargs):
    return scoring_calculator.single_call(
        "gpt-4.1-mini",
        None,
        source_chars=source,
        instruction_chars=3_000,
        requirement_count=10,
        staged=True,
        two_step_threshold_chars=120_000,
        two_step_budget_chars=60_000,
        **kwargs,
    )


def test_staged_goes_two_step_past_the_threshold_and_loads_only_the_budget():
    one_call = _single(source=307_000, requirements=10)
    staged = _staged_single(307_000)

    assert staged.route == "two_step"
    assert staged.usd < one_call.usd  # 30.7만 자 전부를 싣는 것보다 작다.
    assert _staged_single(30_000).route == "single"


def test_staged_leaves_the_machine_judged_share_out_of_the_output():
    off = _single(source=30_000, requirements=10)
    on = _staged_single(30_000)

    assert on.output_tokens < off.output_tokens


def test_staged_with_the_two_step_off_holds_what_does_not_fit():
    held = scoring_calculator.single_call(
        "gpt-4.1-mini",
        None,
        source_chars=20_000_000,
        instruction_chars=3_000,
        requirement_count=10,
        staged=True,
        two_step_threshold_chars=0,
        two_step_budget_chars=60_000,
    )
    assert held.route == "hold"


def test_the_agent_estimate_prices_the_provider_token_shape_at_the_model_price_and_grows_with_the_source():
    small = scoring_calculator.agent_estimate("anthropic", "claude-sonnet-5-5", source_chars=10_000, instruction_chars=1_500)
    large = scoring_calculator.agent_estimate("anthropic", "claude-sonnet-5-5", source_chars=300_000, instruction_chars=1_500)
    haiku = scoring_calculator.agent_estimate("anthropic", "claude-haiku-5-5", source_chars=10_000, instruction_chars=1_500)

    assert large[0] > small[0] > haiku[0] > 0
    assert small[1] == scoring_calculator.ASSUMED_AGENT_SECONDS["anthropic"]


def test_the_agent_caps_are_the_runners_numbers():
    from scoring import agent_runner

    assert scoring_calculator.AGENT_MAX_ZIP_BYTES == agent_runner.MAX_REPO_ZIP_BYTES
    assert scoring_calculator.AGENT_MAX_EXTRACTED_BYTES == agent_runner.MAX_EXTRACTED_BYTES
    assert scoring_calculator.AGENT_MAX_ZIP_ENTRIES == agent_runner.MAX_ZIP_ENTRIES


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


def _row(calc: dict, model: str) -> dict:
    return next(r for r in calc["rows"] if r["model_id"] == model)


def test_an_empty_class_prices_every_model_by_both_methods_and_no_cell_is_missing(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    calc = _calc(client, owner["access"], class_id)

    assert calc["problems"] == []
    assert [r["model_id"] for r in calc["rows"]] == list(scoring_cost.PRICES)
    for row in calc["rows"]:
        assert row["single"]["usd"] > 0 and row["single"]["capacity_chars"] > 0, row["model_id"]
        assert row["single"]["seconds"] == scoring_calculator.ASSUMED_SINGLE_SECONDS
        if row["vendor"] == "anthropic":
            assert row["agent"]["available"] is True
            assert row["agent"]["usd"] > 0 and row["agent"]["seconds"] > 0, row["model_id"]
        else:
            # 못 받는 조합은 빈칸이 아니라 「지원 안 함」 표지다.
            assert row["agent"] == {
                "available": False,
                "usd": None,
                "krw": None,
                "seconds": None,
                "measured_krw": {"sample_count": 0, "median": None, "p90": None},
                "measured_seconds": {"sample_count": 0, "median": None, "p90": None},
            }
    assert calc["agent_vendors"] == ["anthropic"]
    assert calc["assumptions"] == {
        "source_chars": 32_000,
        "source_files": 20,
        "source_chars_per_file": 1_600,
        "requirements": 6,
        "instruction_chars": scoring_calculator.assumed_instruction_chars(6),
        "suspect_rate": 0.025,
        "requirements_from": "assumed",
        "source_from": "assumed",
    }
    assert calc["escalation"]["model_id"] is None


def test_both_providers_are_offered_and_the_missing_key_is_marked(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    calc = _calc(client, owner["access"], class_id)

    providers = {p["vendor"]: p for p in calc["providers"]}
    assert (providers["openai"]["has_key"], providers["anthropic"]["has_key"]) == (True, False)
    assert [m["id"] for m in providers["anthropic"]["models"]] == [m for m in scoring_cost.PRICES if m.startswith("claude-")]
    assert all(m["context_tokens"] > 0 for p in calc["providers"] for m in p["models"])
    # 지금 이 클래스의 조합에서 시작한다 — OpenAI 키·한 번 호출·기본 모델.
    assert calc["selection"]["vendor"] == "openai"
    assert calc["selection"]["method"] == "single"
    # 키가 없는 Claude 도 고를 수 있고 에이전트는 Claude 일 때만 열린다.
    claude = _calc(client, owner["access"], class_id, vendor="anthropic", method="agent", model="claude-haiku-5-5")
    assert (claude["selection"]["model_id"], claude["selection"]["method"]) == ("claude-haiku-5-5", "agent")
    openai_agent = _calc(client, owner["access"], class_id, vendor="openai", method="agent")
    assert openai_agent["selection"]["method"] == "single"


def test_the_capacity_in_the_table_is_what_the_scoring_budget_gives(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    calc = _calc(client, owner["access"], class_id)

    instruction = calc["assumptions"]["instruction_chars"]
    for row in calc["rows"]:
        budget = model_context.source_budget_bytes(row["model_id"], instruction_bytes=instruction)
        assert row["single"]["capacity_chars"] == int(budget // scoring_calculator.BYTES_PER_CHAR), row["model_id"]
        assert row["single"]["capacity_chars_hangul"] == int(budget // 1.48), row["model_id"]
        per_file = scoring_calculator.SOURCE_CHARS_PER_FILE
        assert per_file == 1_600
        assert row["single"]["capacity_files"] == round(row["single"]["capacity_chars"] / per_file), row["model_id"]
        assert row["single"]["capacity_files_hangul"] == round(row["single"]["capacity_chars_hangul"] / per_file), row["model_id"]
    assumptions = calc["assumptions"]
    assert assumptions["source_chars_per_file"] == 1_600
    assert assumptions["source_files"] == round(assumptions["source_chars"] / 1_600)


def test_changing_the_assumptions_changes_the_values_and_a_source_past_the_capacity_is_held(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])
    base = _calc(client, owner["access"], class_id)

    more_items = _calc(client, owner["access"], class_id, requirements=20)
    bigger = _calc(client, owner["access"], class_id, source_chars=100_000)
    huge = _calc(client, owner["access"], class_id, source_chars=5_000_000)

    row = lambda calc: _row(calc, "gpt-4.1-mini")  # noqa: E731
    assert (more_items["assumptions"]["requirements"], more_items["assumptions"]["requirements_from"]) == (20, "custom")
    assert row(more_items)["single"]["usd"] > row(base)["single"]["usd"]
    assert (bigger["selection"]["source"], bigger["assumptions"]["source_from"]) == ("custom", "custom")
    assert row(bigger)["single"]["usd"] > row(base)["single"]["usd"]
    assert _row(bigger, "claude-haiku-5-5")["agent"]["usd"] > _row(base, "claude-haiku-5-5")["agent"]["usd"]
    # 100만 토큰 모델도 500만 자는 담지 못한다 — 보류, 채점하지 않는다.
    assert (row(huge)["single"]["route"], row(huge)["single"]["fits"], row(huge)["single"]["usd"]) == ("hold", False, 0)


def test_a_source_bigger_than_the_capacity_gets_the_hold_on_a_small_context_model_only(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    calc = _calc(client, owner["access"], class_id, source_chars=600_000)

    assert _row(calc, "gpt-4o-mini")["single"]["route"] == "hold"
    assert _row(calc, "gpt-5")["single"]["route"] == "single"


def test_the_response_has_no_semester_figures_only_the_per_submission_rows(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    calc = _calc(client, owner["access"], class_id, students=10, assignments=4, regrade_rate=0.5)

    assert "semester" not in calc
    assert not {"students", "assignments", "regrade_rate"} & set(calc["assumptions"])
    assert not {"students", "assignments", "regrade_rate"} & set(calc["defaults"])


def test_staged_makes_a_307k_single_call_cheaper_than_off(client, db, monkeypatch):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])
    off = _calc(client, owner["access"], class_id, source_chars=307_000)
    monkeypatch.setenv("CLASSROOM_SCORING_PIPELINE", "staged")

    on = _calc(client, owner["access"], class_id, source_chars=307_000)

    assert (off["staged"]["enabled"], on["staged"]["enabled"]) == (False, True)
    assert on["staged"]["threshold_chars"] == 120_000 and on["staged"]["budget_chars"] == 60_000
    assert _row(on, "gpt-4.1-mini")["single"]["route"] == "two_step"
    assert _row(on, "gpt-4.1-mini")["single"]["usd"] < _row(off, "gpt-4.1-mini")["single"]["usd"]


def test_the_agent_caps_are_in_the_response(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])

    limits = _calc(client, owner["access"], class_id)["agent_limits"]

    assert limits == {
        "max_zip_bytes": 100 * 1024 * 1024,
        "max_extracted_bytes": 256 * 1024 * 1024,
        "max_zip_entries": 50_000,
        "attempt_seconds": agent_scoring.ATTEMPT_TIMEOUT_SECONDS,
        "attempts": agent_scoring.MAX_ATTEMPTS,
        "budget_usd": 1.0,
    }


def test_a_problem_gives_its_requirement_count_and_instruction_and_assumed_sizes_until_attempts_exist(client, db):
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
        ("median", 32_000, False),
        ("p90", 307_000, False),
    ]
    assert calc["assumptions"]["requirements"] == 4
    assert (calc["assumptions"]["requirements_from"], calc["assumptions"]["source_from"]) == ("problem", "assumed")
    assert calc["assumptions"]["instruction_chars"] == offered["instruction_chars"]
    p90 = _calc(client, owner["access"], class_id, source="p90")
    assert _row(p90, "gpt-4.1")["single"]["usd"] > _row(calc, "gpt-4.1")["single"]["usd"]


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
    assert calc["assumptions"]["source_from"] == "problem"


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


def test_two_agent_runs_leave_the_estimate_and_have_no_measured_line_yet(client, db, monkeypatch):
    owner, class_id = _agent_runs(client, monkeypatch, 2)

    calc = _calc(client, owner["access"], class_id)

    assert calc["selection"]["method"] == "agent"
    agent = _row(calc, "claude-haiku-5-5")["agent"]
    assert agent["usd"] > 0
    assert agent["measured_krw"] == {"sample_count": 2, "median": None, "p90": None}
    assert agent["measured_seconds"]["median"] is None


def test_three_agent_runs_put_the_measured_median_beside_the_unchanged_estimate(client, db, monkeypatch):
    owner, class_id = _agent_runs(client, monkeypatch, 3)

    calc = _calc(client, owner["access"], class_id)
    agent = _row(calc, "claude-haiku-5-5")["agent"]

    measured = agent["measured_krw"]
    assert measured["sample_count"] == 3
    assert measured["median"] > 0 and measured["p90"] >= measured["median"]
    # 예상은 실측이 쌓여도 그대로 가정 토큰 꼴 × 단가다.
    expected, _ = scoring_calculator.agent_estimate(
        "anthropic",
        "claude-haiku-5-5",
        source_chars=calc["assumptions"]["source_chars"],
        instruction_chars=calc["assumptions"]["instruction_chars"],
    )
    assert agent["usd"] == pytest.approx(expected)
    assert agent["measured_seconds"] == {"sample_count": 3, "median": 1.0, "p90": 1.0}
    # 다른 모델의 실측은 섞지 않는다.
    assert _row(calc, "claude-sonnet-5-5")["agent"]["measured_krw"]["median"] is None


def _class_with_escalation(client, model: str) -> tuple[str, int]:
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"])
    create_open_problem(client, owner["access"], class_id, required_labels=["가", "나", "다"])
    if model:
        response = client.patch(
            f"{CLASSES_URL}/{class_id}",
            data={"escalation_model": model},
            content_type="application/json",
            **auth_header(owner["access"]),
        )
        assert response.status_code == 200, response.content
    return owner["access"], class_id


def test_the_escalation_line_prices_one_suspect_and_multiplies_by_the_assumed_rate_and_items(client, db, monkeypatch):
    """의심 재판정 줄(#1291) — 고른 모델의 단가로 의심 한 건(같은 소스 + 항목 하나) × 비율(가정) × 항목 수."""

    access, class_id = _class_with_escalation(client, "gpt-4.1")

    calc = _calc(client, access, class_id)

    escalation = calc["escalation"]
    (problem,) = calc["problems"]
    expected = scoring_cost.attempt_cost(
        "gpt-4.1",
        None,
        prompt_chars=calc["selection"]["source_chars"] + problem["escalation_instruction_chars"],
        output_tokens=scoring_calculator.OUTPUT_TOKENS_PER_REQUIREMENT,
    )
    assert escalation["model_id"] == "gpt-4.1"
    assert escalation["per_suspect"]["usd"] == pytest.approx(expected.usd)
    assert escalation["per_suspect"]["output_tokens"] == scoring_calculator.OUTPUT_TOKENS_PER_REQUIREMENT
    assert escalation["suspect_rate"] == scoring_calculator.ASSUMED_SUSPECT_RATE
    assert escalation["per_submission_krw"] == pytest.approx(
        expected.usd * scoring_cost.KRW_PER_USD * 0.025 * problem["requirement_count"]
    )
    more = _calc(client, access, class_id, suspect_rate=0.1)
    assert more["escalation"]["per_submission_krw"] == pytest.approx(escalation["per_submission_krw"] * 4)
    monkeypatch.setitem(scoring_cost.PRICES, "gpt-4.1", scoring_cost.ModelPrice(input_usd_per_million=20.0, output_usd_per_million=80.0))
    assert _calc(client, access, class_id)["escalation"]["per_suspect"]["usd"] == pytest.approx(expected.usd * 10)


def test_no_escalation_line_while_it_is_off_or_for_the_other_provider(client, db):
    access, class_id = _class_with_escalation(client, "")
    off = _calc(client, access, class_id)["escalation"]
    assert (off["model_id"], off["per_suspect"], off["per_submission_krw"]) == (None, None, 0)

    access, class_id = _class_with_escalation(client, "gpt-4.1")
    assert _calc(client, access, class_id, vendor="anthropic")["escalation"]["model_id"] is None
