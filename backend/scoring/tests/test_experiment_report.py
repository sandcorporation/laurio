"""#1246·#1261: 비교 실험 보고표 계산 — 고정 자료로 평균 차·최대 차·스피어만·흔들림·근거 실재율·건당 비용·p50/p90·문턱 열·
전체 예상, 요구사항 단위 판정 일치율·판정 흔들림."""

from __future__ import annotations

from decimal import Decimal

import pytest

from scoring.experiment_report import (
    BASELINE_ROW,
    COST_ONLY_NOTE,
    NO_TRUTH_NOTE,
    RunRow,
    ci95_half_width,
    limits_note,
    percentile,
    report_rows,
    spearman,
    to_csv,
    to_markdown,
)

CHEAP = "self_loop:gpt-4.1-mini"


def _run(sub: int, row: str, rnd: int, score: float | None, *, status: str = "scored", offered: int = 10,
         real: int = 10, cost: str = "0.10", secs: float | None = 30.0,
         verdicts: tuple[tuple[int, bool], ...] = ()) -> RunRow:
    return RunRow(sub, row, rnd, status, score, offered, real, Decimal(cost), secs, verdicts)


def _fixture() -> list[RunRow]:
    runs: list[RunRow] = []
    # 기준: 제출 1·2·3 의 회차 점수(평균 60·70·80), 회차 표준편차 각 10.
    for sub, scores in {1: (50, 60, 70), 2: (60, 70, 80), 3: (70, 80, 90)}.items():
        runs += [_run(sub, BASELINE_ROW, i, s, cost="0.20", secs=40.0 + i) for i, s in enumerate(scores)]
    # 싼 줄: 평균 62·66·80 → 차 2·4·0, 회차 표준편차 각 1. 하나는 보류, 근거 10 중 9.
    for sub, scores in {1: (61, 62, 63), 2: (65, 66, 67), 3: (79, 80, 81)}.items():
        runs += [_run(sub, CHEAP, i, s, real=9, secs=10.0 * (i + 1)) for i, s in enumerate(scores)]
    runs.append(_run(3, CHEAP, 3, None, status="held", offered=0, real=0, secs=5.0))
    return runs


def test_numbers_against_the_baseline():
    base, cheap = report_rows(_fixture())

    assert base.row == BASELINE_ROW and cheap.row == CHEAP
    assert cheap.mean_diff == pytest.approx(2.0) and cheap.max_diff == pytest.approx(4.0)
    assert cheap.spearman == pytest.approx(1.0)
    assert cheap.stability == pytest.approx(1.0) and base.stability == pytest.approx(10.0)
    assert cheap.evidence_rate == pytest.approx(0.9)
    assert (cheap.runs, cheap.scored, cheap.held, cheap.failed, cheap.submissions) == (10, 9, 1, 0, 3)
    # 비용은 보류 회차까지 나눈다(돈은 썼다): 0.10 × 10 / 10.
    assert cheap.cost_per_run == Decimal("0.1000") and base.cost_per_run == Decimal("0.2000")
    assert cheap.p50_seconds == pytest.approx(20.0) and cheap.p90_seconds == pytest.approx(30.0)
    # 근거 90% < 95%, 실패·보류 1/10 > 1/16, 비용 0.10 > 0.20/3.
    assert cheap.passes == {
        "diff": True, "max_diff": True, "spearman": True, "stability": True,
        "evidence": False, "trouble": False, "cost": False, "p90": True, "agreement": None, "flip": None,
    }
    # 기준 줄은 자기와 견주지 않는다 — 절대 문턱만.
    assert base.mean_diff == 0 and base.passes == {
        "diff": None, "max_diff": None, "spearman": None, "stability": None,
        "evidence": True, "trouble": True, "cost": None, "p90": True, "agreement": None, "flip": None,
    }


def test_relative_thresholds_at_their_edges():
    runs = []
    for sub, (b, c) in {1: (50, 63), 2: (60, 58), 3: (70, 68), 4: (80, 78)}.items():
        runs += [_run(sub, BASELINE_ROW, i, b + i, cost="0.30", secs=300.0) for i in range(3)]
        runs += [_run(sub, CHEAP, i, c + 3 * i, cost="0.10", secs=301.0) for i in range(3)]
    base, cheap = report_rows(runs)
    assert cheap.max_diff == pytest.approx(15.0) and cheap.passes["max_diff"] is True  # 15 는 통과
    assert cheap.stability == pytest.approx(base.stability + 2.0) and cheap.passes["stability"] is True
    assert cheap.passes["cost"] is True  # 0.10 = 0.30 / 3
    assert cheap.passes["p90"] is False and base.passes["p90"] is True


def test_spearman_ties_and_flat_series():
    assert spearman([1, 2, 3], [3, 2, 1]) == pytest.approx(-1.0)
    assert spearman([1, 2, 2, 3], [1, 2, 3, 4]) == pytest.approx(0.9486833)
    assert spearman([5, 5, 5], [1, 2, 3]) is None
    assert spearman([1], [1]) is None


def test_percentile_and_ci():
    assert percentile([10, 20, 30, 40], 50) == pytest.approx(25.0)
    assert percentile([10, 20, 30, 40], 90) == pytest.approx(37.0)
    assert percentile([], 50) is None
    assert ci95_half_width([2.0, 4.0, 0.0]) == pytest.approx(4.303 * 2.0 / 3**0.5)
    assert ci95_half_width([1.0]) is None


def test_without_baseline_only_the_absolute_criteria_are_judged():
    (cheap,) = report_rows([r for r in _fixture() if r.row == CHEAP])
    assert cheap.mean_diff is None and cheap.spearman is None
    assert {k for k, v in cheap.passes.items() if v is not None} == {"evidence", "trouble", "p90"}


def test_markdown_and_csv_carry_the_limits_and_marks():
    reports = report_rows(_fixture())
    notes = limits_note(reports, repeat=3)
    assert notes[0] == "제출 3건 × 회차 3."
    assert "넓다" in notes[1]  # 제출 셋으로는 ±5점을 가르지 못한다
    md = to_markdown("실험 x", reports, notes, repeat=3, full_submissions=16)
    assert md.startswith("# 실험 x\n") and "| self_loop:gpt-4.1-mini | 3 | 10 | 9 | 1 | 0 | 2.00 | 4.00 |" in md
    # 실측 건당 비용과 전체(제출 16 × 회차 3) 예상: 0.10 × 48 = 4.80, 기준 0.20 × 48 = 9.60.
    assert "| 0.1000 | 4.80 |" in md and "| 0.2000 | 9.60 |" in md
    assert "제출 16 × 회차 3 — 줄 모두 합계 14.40 USD." in md
    assert "| 통과 | 통과 | 통과 | 통과 | 미달 | 미달 | 미달 | 통과 |" in md
    rows = to_csv(reports, repeat=3, full_submissions=16).splitlines()
    assert rows[0].startswith("줄,제출,회차") and len(rows) == 3
    assert limits_note([], repeat=3) == ["돈 회차가 없다."]


def test_one_round_report_says_stability_cannot_be_measured():
    runs = [r for r in _fixture() if r.round == 0]
    reports = report_rows(runs)
    assert all(r.stability is None for r in reports)
    notes = limits_note(reports, repeat=1)
    assert "회차 1 — 흔들림은 잴 수 없다." in notes
    md = to_markdown("x", reports, notes, repeat=1, full_submissions=3)
    assert md.count("회차 1 — 잴 수 없음") == 2


def test_a_row_without_measured_cost_is_not_measured_and_left_out_of_the_total():
    # #1257: 실행기에 못 닿아 돈이 안 든 줄을 0.00 으로 세면 전체 예상 합계가 낮아 보인다.
    agent = "agent:claude-haiku-5-5"
    runs = [_run(1, BASELINE_ROW, 1, 80, cost="0.20"), _run(1, CHEAP, 1, None, status="failed", cost="0", offered=0, real=0)]
    reports = report_rows(runs, baseline=BASELINE_ROW, row_names=[BASELINE_ROW, CHEAP, agent])

    assert [r.row for r in reports] == [BASELINE_ROW, agent, CHEAP]
    by_row = {r.row: r for r in reports}
    assert by_row[CHEAP].cost_per_run is None and by_row[agent].runs == 0 and by_row[agent].cost_per_run is None
    md = to_markdown("t", reports, [], repeat=1, full_submissions=10)
    assert "줄 모두 합계 6.00 USD. 「실측 없음」 줄 2개는 합계에 없다." in md
    assert f"| {CHEAP} | 0 | 1 | 0 | 0 | 1 |" in md and md.count("| 실측 없음 |") == 2


# 요구사항 단위(#1261) — 필수 1·2, 선택 9.
REQUIRED = frozenset({1, 2})


def _met(*unmet: int) -> tuple[tuple[int, bool], ...]:
    return tuple((rid, rid not in unmet) for rid in (1, 2, 9))


def test_requirement_agreement_and_flip_against_the_baseline():
    runs = [
        # 기준: 제출 10 은 두 회차 모두 전부 충족, 제출 20 은 회차 2 에서 필수 2 가 미충족(흔들림).
        _run(10, BASELINE_ROW, 1, 100, verdicts=_met()),
        _run(10, BASELINE_ROW, 2, 100, verdicts=_met()),
        _run(20, BASELINE_ROW, 1, 100, verdicts=_met()),
        _run(20, BASELINE_ROW, 2, 50, verdicts=_met(2)),
        # 싼 줄: 제출 10 회차 1 에서 필수 1·선택 9 미충족, 제출 20 은 늘 필수 2 미충족.
        _run(10, CHEAP, 1, 50, verdicts=_met(1, 9)),
        _run(10, CHEAP, 2, 100, verdicts=_met()),
        _run(20, CHEAP, 1, 50, verdicts=_met(2)),
        _run(20, CHEAP, 2, 50, verdicts=_met(2)),
        # 보류 칸의 판정은 세지 않는다.
        _run(20, CHEAP, 3, None, status="held", verdicts=_met(1, 2, 9)),
    ]
    base, cheap = report_rows(runs, required_ids=REQUIRED)

    # 필수 (10,1): 1/2 · (10,2): 1 · (20,1): 1 · (20,2): 싼 줄 [F,F] × 기준 [T,F] → 2/4 = 1/2. 평균 0.75.
    assert cheap.agreement_required == pytest.approx(0.75)
    # 선택 (10,9): 1/2 · (20,9): 1 → 0.75.
    assert cheap.agreement_optional == pytest.approx(0.75)
    # 필수 흔들림: 싼 줄은 (10,1) 하나가 바뀜 / 넷, 기준은 (20,2) 하나 / 넷.
    assert cheap.flip_required == pytest.approx(0.25) and base.flip_required == pytest.approx(0.25)
    assert cheap.flip_optional == pytest.approx(0.5) and base.flip_optional == 0
    assert base.agreement_required is None and base.agreement_optional is None
    assert cheap.passes["agreement"] is False and cheap.passes["flip"] is True
    assert base.passes["agreement"] is None and base.passes["flip"] is None


def test_requirement_thresholds_at_their_edges():
    # 필수 20개 가운데 1개가 다르면 일치 95% — 문턱 위. 흔들림은 기준 + 2%p 까지 통과.
    required = frozenset(range(1, 21))
    every = tuple((rid, True) for rid in required)
    one_off = tuple((rid, rid != 1) for rid in required)
    runs = [
        _run(1, BASELINE_ROW, 1, 100, verdicts=every), _run(1, BASELINE_ROW, 2, 100, verdicts=every),
        _run(1, CHEAP, 1, 95, verdicts=one_off), _run(1, CHEAP, 2, 95, verdicts=one_off),
    ]
    _base, cheap = report_rows(runs, required_ids=required)
    assert cheap.agreement_required == pytest.approx(0.95) and cheap.passes["agreement"] is True
    assert cheap.flip_required == 0 and cheap.passes["flip"] is True

    flipping = [*runs[:2], _run(1, CHEAP, 1, 95, verdicts=one_off), _run(1, CHEAP, 2, 100, verdicts=every)]
    _base, cheap = report_rows(flipping, required_ids=required)
    assert cheap.flip_required == pytest.approx(0.05) and cheap.passes["flip"] is False  # 5% > 0 + 2%p


def test_all_scores_and_verdicts_met_like_contest3_four_s4():
    """`contest3-four-s4`(4건 × 네 줄 × 2회, 전부 100·전부 충족)과 같은 꼴 — 지표는 계산되지만 아무것도 가르지 못한다."""

    rows = [BASELINE_ROW, "single_call:claude-haiku-5-5", "agent:claude-haiku-5-5", "single_call:gpt-4.1-mini"]
    runs = [_run(sub, row, rnd, 100, verdicts=_met()) for sub in (1, 2, 3, 4) for row in rows for rnd in (1, 2)]
    reports = report_rows(runs, row_names=rows, required_ids=REQUIRED)

    assert len(reports) == 4
    for r in reports[1:]:
        assert (r.agreement_required, r.agreement_optional, r.flip_required, r.flip_optional) == (1, 1, 0, 0)
        assert r.passes["agreement"] is True and r.passes["flip"] is True
        assert r.spearman is None  # 점수가 모두 같아 순위를 못 잰다
    md = to_markdown("contest3-four-s4", reports, [COST_ONLY_NOTE, NO_TRUTH_NOTE], repeat=2, full_submissions=16)
    assert "| single_call:gpt-4.1-mini | 4 | 8 | 8 | 0 | 0 | 0.00 | 0.00 | — | 0.00 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | — | — |" in md
    assert f"- {COST_ONLY_NOTE}" in md and f"- {NO_TRUTH_NOTE}" in md
