"""#1246: 비교 실험 보고표 계산 — 고정 자료로 평균 차·최대 차·스피어만·흔들림·근거 실재율·건당 비용·p50/p90·문턱 여덟·전체 예상."""

from __future__ import annotations

from decimal import Decimal

import pytest

from scoring.experiment_report import (
    BASELINE_ROW,
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
         real: int = 10, cost: str = "0.10", secs: float | None = 30.0) -> RunRow:
    return RunRow(sub, row, rnd, status, score, offered, real, Decimal(cost), secs)


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
        "evidence": False, "trouble": False, "cost": False, "p90": True,
    }
    # 기준 줄은 자기와 견주지 않는다 — 절대 문턱만.
    assert base.mean_diff == 0 and base.passes == {
        "diff": None, "max_diff": None, "spearman": None, "stability": None,
        "evidence": True, "trouble": True, "cost": None, "p90": True,
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
