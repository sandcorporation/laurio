"""강사가 모델·추론 강도를 고를 때 채점 비용을 미리 본다 (#591, CONTEXT.md 「예상 채점 비용」).

두 겹을 본다. 셈 자체(`classroom.scoring_cost` — 토큰 환산·단가·추론 출력 추정·배율)는
순수 함수라 DB 없이 단위로 고정하고, 「무엇을 기준으로 셈했는가」(문제 → 클래스 →
소스 크기별로 내려가는 기준, 참여자 수 × 1인 시도 수)는 마운트된 HTTP API 로 본다.
"""

from __future__ import annotations

import pytest

from classroom import scoring_cost
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    patch_class,
    respond_with_permanent_failure,
    respond_with_verdict,
    run_scan,
    submit_source,
    user_id,
)

# --- 셈(순수 함수) ---------------------------------------------------------------


def test_characters_become_tokens_at_about_three_point_three_per_token():
    assert scoring_cost.tokens_for_chars(33_000) == 10_000
    assert scoring_cost.tokens_for_chars(0) == 0


def test_a_non_reasoning_model_costs_input_plus_a_fixed_output_at_its_price():
    cost = scoring_cost.attempt_cost("gpt-4.1-mini", None, prompt_chars=55_000)

    assert cost.input_tokens == round(55_000 / 3.3)
    assert cost.output_tokens == scoring_cost.NON_REASONING_OUTPUT_TOKENS
    expected_usd = cost.input_tokens * 0.40 / 1e6 + cost.output_tokens * 1.60 / 1e6
    assert cost.usd == pytest.approx(expected_usd)
    assert cost.krw == pytest.approx(expected_usd * scoring_cost.KRW_PER_USD)
    # 2026-10-06 클래스 5 실측과 같은 자릿수 — 시도 하나에 15원 안팎.
    assert 10 < cost.krw < 20


def test_a_reasoning_model_output_grows_with_the_effort():
    low = scoring_cost.attempt_cost("gpt-5.5", "low", prompt_chars=55_000)
    medium = scoring_cost.attempt_cost("gpt-5.5", "medium", prompt_chars=55_000)
    high = scoring_cost.attempt_cost("gpt-5.5", "high", prompt_chars=55_000)

    assert low.output_tokens < medium.output_tokens < high.output_tokens
    assert low.krw < medium.krw < high.krw
    # 실측: gpt-5.5 추론 보통으로 시도 1건이 약 430원.
    assert 380 < medium.krw < 480
    # 높음만 위로 열려 있다(「약 N원~」).
    assert (low.open_ended, medium.open_ended, high.open_ended) == (False, False, True)


def test_gpt_5_5_charges_more_once_the_input_passes_the_long_context_line():
    threshold_chars = int(272_000 * scoring_cost.CHARS_PER_TOKEN)
    below = scoring_cost.attempt_cost("gpt-5.5", "low", prompt_chars=threshold_chars - 3_300)
    above = scoring_cost.attempt_cost("gpt-5.5", "low", prompt_chars=threshold_chars + 3_300)

    def plain_usd(cost):
        return cost.input_tokens * 5.00 / 1e6 + cost.output_tokens * 30.00 / 1e6

    assert below.usd == pytest.approx(plain_usd(below))
    assert above.usd == pytest.approx(above.input_tokens * 10.00 / 1e6 + above.output_tokens * 45.00 / 1e6)


def test_a_model_missing_from_the_price_table_has_no_cost():
    assert scoring_cost.attempt_cost("gpt-4o", None, prompt_chars=10_000) is None
    assert scoring_cost.attempt_cost("gpt-5-mini", "low", prompt_chars=10_000) is None


def test_the_ratio_is_against_gpt_4_1_mini_at_the_same_length():
    assert scoring_cost.ratio_to_baseline("gpt-4.1-mini", None, prompt_chars=55_000) == pytest.approx(1.0)
    ratio = scoring_cost.ratio_to_baseline("gpt-5.5", "medium", prompt_chars=55_000)
    assert 25 < ratio < 33
    assert scoring_cost.ratio_to_baseline("gpt-4o", None, prompt_chars=55_000) is None


# --- 기준(HTTP) -----------------------------------------------------------------


def _estimate(client, access: str, class_id: int, problem_id: int | None = None, *, expect: int = 200):
    url = f"{CLASSES_URL}/{class_id}/scoring-cost"
    if problem_id is not None:
        url += f"?problem_id={problem_id}"
    response = client.get(url, **auth_header(access))
    assert response.status_code == expect, response.content
    return response.json()


def _row(estimate: dict, model_id: str, effort: str | None = None) -> dict:
    return next(r for r in estimate["rows"] if r["model_id"] == model_id and r["reasoning_effort"] == effort)


def _participant(client, instructor_access: str, class_id: int, uid: str) -> dict:
    participant = login(client, uid=uid)
    join_class(client, participant["access"], class_id, instructor_access=instructor_access)
    return participant


def _score_source(client, monkeypatch, participant: dict, uid: str, problem, source: str) -> int:
    """소스 하나를 내고 실물 어댑터 경로로 채점해, 벤더로 나간(=저장된) 프롬프트 길이를 돌려준다."""

    submit_source(
        client,
        participant["access"],
        problem.class_id,
        problem.id,
        participant_user_id=user_id(uid),
        files={"main.py": source},
    )
    sent: list = []
    with force_real_scoring_adapter():
        respond_with_verdict(monkeypatch, problem.item_id, is_met=False, capture=sent)
        run_scan(client)
    return len(sent[-1]["messages"][-1]["content"])


def test_a_class_without_attempts_prices_attempts_by_source_size(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])

    estimate = _estimate(client, instructor["access"], class_id)

    assert estimate["basis"] == "source_sizes"
    assert estimate["avg_prompt_chars"] is None
    assert estimate["source_size_bands"] == [10_000, 50_000, 200_000]
    assert estimate["attempts_per_participant"] == 2.5
    assert estimate["attempts_per_participant_measured"] is False
    mini = _row(estimate, "gpt-4.1-mini")
    assert mini["per_attempt"] is None
    assert [band["krw"] for band in mini["by_source_size"]] == [
        pytest.approx(scoring_cost.attempt_cost("gpt-4.1-mini", None, prompt_chars=chars).krw)
        for chars in (10_000, 50_000, 200_000)
    ]


def test_only_models_the_key_can_use_appear_and_reasoning_models_get_a_row_per_effort(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])

    estimate = _estimate(client, instructor["access"], class_id)

    keys = {(r["model_id"], r["reasoning_effort"]) for r in estimate["rows"]}
    assert ("gpt-4.1-mini", None) in keys
    assert {("gpt-5.5", "low"), ("gpt-5.5", "medium"), ("gpt-5.5", "high")} <= keys
    # 단가표에 없는 모델은 표에 줄을 만들지 않는다 — 지금 설정이 아니면.
    assert all(r["priced"] for r in estimate["rows"])
    assert "gpt-4o" not in {r["model_id"] for r in estimate["rows"]}


def test_the_current_setting_gets_a_row_even_without_a_price(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    patch_class(client, instructor["access"], class_id, {"default_model": "gpt-4o"})

    estimate = _estimate(client, instructor["access"], class_id)

    row = _row(estimate, "gpt-4o")
    assert row["priced"] is False
    assert row["per_attempt"] is None
    assert row["by_source_size"] == []
    assert row["ratio_to_baseline"] is None


def test_a_problem_with_attempts_is_priced_from_its_own_average_prompt(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    alice = _participant(client, instructor["access"], class_id, "participant-1")
    bob = _participant(client, instructor["access"], class_id, "participant-2")
    _participant(client, instructor["access"], class_id, "participant-3")

    lengths = [
        _score_source(client, monkeypatch, alice, "participant-1", problem, "a = 1\n" * 2_000),
        _score_source(client, monkeypatch, alice, "participant-1", problem, "b = 2\n" * 4_000),
        _score_source(client, monkeypatch, bob, "participant-2", problem, "c = 3\n" * 1_000),
    ]

    estimate = _estimate(client, instructor["access"], class_id, problem.id)

    assert estimate["basis"] == "problem"
    assert estimate["sample_count"] == 3
    assert estimate["avg_prompt_chars"] == round(sum(lengths) / 3)
    assert estimate["participant_count"] == 3
    # 시도 3건을 (문제, 참여자) 두 쌍이 냈다.
    assert estimate["attempts_per_participant"] == pytest.approx(1.5)
    assert estimate["attempts_per_participant_measured"] is True
    mini = _row(estimate, "gpt-4.1-mini")
    per_attempt = scoring_cost.attempt_cost("gpt-4.1-mini", None, prompt_chars=estimate["avg_prompt_chars"])
    assert mini["per_attempt"]["krw"] == pytest.approx(per_attempt.krw)
    assert mini["per_attempt"]["tokens"] == per_attempt.total_tokens
    assert mini["per_problem_krw"] == pytest.approx(per_attempt.krw * 3 * 1.5)
    assert mini["ratio_to_baseline"] == pytest.approx(1.0)


def test_a_problem_without_attempts_falls_back_to_the_class_average(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    scored = create_open_problem(client, instructor["access"], class_id, title="1주차", submission_formats=["source"])
    fresh = create_open_problem(client, instructor["access"], class_id, title="2주차", submission_formats=["source"])
    alice = _participant(client, instructor["access"], class_id, "participant-1")
    length = _score_source(client, monkeypatch, alice, "participant-1", scored, "x = 1\n" * 3_000)

    estimate = _estimate(client, instructor["access"], class_id, fresh.id)

    assert estimate["basis"] == "class"
    assert estimate["avg_prompt_chars"] == length
    # 클래스 설정 화면(문제 없이)도 같은 클래스 평균을 쓴다.
    assert _estimate(client, instructor["access"], class_id)["basis"] == "class"


def test_platform_auto_failures_do_not_count_as_prompts(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["source"])
    alice = _participant(client, instructor["access"], class_id, "participant-1")
    submit_source(
        client, alice["access"], class_id, problem.id, participant_user_id=user_id("participant-1"), files={"a.py": "1"}
    )
    with force_real_scoring_adapter():
        respond_with_permanent_failure(monkeypatch)
        run_scan(client)

    estimate = _estimate(client, instructor["access"], class_id, problem.id)

    assert estimate["basis"] == "source_sizes"


def test_someone_elses_class_and_problem_are_not_found(client, db):
    owner = login(client, uid="instructor-1")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id)
    stranger = login(client, uid="stranger")

    _estimate(client, stranger["access"], class_id, expect=404)
    other_class = create_class(client, stranger["access"])
    _estimate(client, stranger["access"], other_class, problem.id, expect=404)
