"""채점 방식 비교 실험의 보고표(#1246, 스펙 #1244) — 실험 줄마다 기준 줄과 견준 숫자와 통과 기준 넷.

계산은 DB 를 모르는 순수 함수다(`report_rows`) — `manage.py experiment_report` 가 실험 기록을 `RunRow` 로 바꿔 넘긴다.

- 점수 차: 제출마다 그 줄의 회차 평균 − 기준 줄의 회차 평균, 그 **절댓값**의 평균·최대.
- 순위 일치: 제출마다 회차 평균으로 두 줄의 스피어만 상관(같은 값은 평균 순위).
- 흔들림: 제출마다 회차 점수의 표본 표준편차, 그 평균(회차가 하나면 없음).
- 근거 실재율: 모델이 낸 근거 중 박제본에 실재한 몫 — 우리 루프가 다시 물어 버린 근거(`evidence_dropped`)도 분모에 든다.
- 건당 비용: 회차 하나의 평균 비용(실패·보류 포함 — 돈은 썼다). 시간은 끝난 회차의 p50·p90.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal
from statistics import mean, stdev

BASELINE_ROW = "agent:claude-sonnet-5-5"
MAX_MEAN_DIFF = 5.0  # 평균 점수 차(점, 0~100)
MIN_EVIDENCE_RATE = 0.95


@dataclass(frozen=True)
class RunRow:
    submission_id: int
    row: str  # "<방식>:<모델>"
    round: int
    status: str  # scored | held | failed
    score: float | None  # 0~100, 채점됐을 때만
    evidence_offered: int
    evidence_real: int
    cost_usd: Decimal
    duration_seconds: float | None


@dataclass(frozen=True)
class RowReport:
    row: str
    submissions: int  # 채점된 회차가 하나라도 있는 제출 수
    runs: int
    scored: int
    held: int
    failed: int
    mean_diff: float | None
    max_diff: float | None
    diff_ci95: float | None  # 평균 차(부호 있는)의 95% 신뢰 구간 반폭
    spearman: float | None
    stability: float | None  # 회차 표준편차의 평균
    evidence_rate: float | None
    cost_per_run: Decimal | None
    p50_seconds: float | None
    p90_seconds: float | None
    passes: dict[str, bool | None]  # 기준 넷: diff·stability·evidence·cost (판단 못 하면 None)


def _per_submission(rows: Iterable[RunRow]) -> dict[int, list[float]]:
    out: dict[int, list[float]] = {}
    for r in rows:
        if r.status == "scored" and r.score is not None:
            out.setdefault(r.submission_id, []).append(r.score)
    return out


def _ranks(values: Sequence[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    """같은 값은 평균 순위로 둔 피어슨 상관. 둘 중 하나가 모두 같으면 None."""

    if len(xs) != len(ys) or len(xs) < 2:
        return None
    rx, ry = _ranks(xs), _ranks(ys)
    mx, my = mean(rx), mean(ry)
    cov = sum((a - mx) * (b - my) for a, b in zip(rx, ry, strict=True))
    vx = sum((a - mx) ** 2 for a in rx)
    vy = sum((b - my) ** 2 for b in ry)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def percentile(values: Sequence[float], p: float) -> float | None:
    """선형 보간 백분위(p 는 0~100)."""

    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * p / 100
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


# t 분포 97.5% 분위(자유도 1~30), 그 위는 1.96.
_T975 = [12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228, 2.201, 2.179, 2.160, 2.145, 2.131,
         2.120, 2.110, 2.101, 2.093, 2.086, 2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042]


def ci95_half_width(values: Sequence[float]) -> float | None:
    if len(values) < 2:
        return None
    df = len(values) - 1
    t = _T975[df - 1] if df <= len(_T975) else 1.96
    return t * stdev(values) / math.sqrt(len(values))


def _row_report(name: str, rows: list[RunRow], baseline: dict[int, list[float]], base: RowReport | None) -> RowReport:
    per = _per_submission(rows)
    common = sorted(set(per) & set(baseline))
    signed = [mean(per[s]) - mean(baseline[s]) for s in common]
    diffs = [abs(d) for d in signed]
    spreads = [stdev(v) for v in per.values() if len(v) >= 2]
    offered = sum(r.evidence_offered for r in rows)
    real = sum(r.evidence_real for r in rows)
    durations = [r.duration_seconds for r in rows if r.status != "failed" and r.duration_seconds is not None]
    cost = sum((r.cost_usd for r in rows), Decimal(0)) / len(rows) if rows else None
    report = RowReport(
        row=name,
        submissions=len(per),
        runs=len(rows),
        scored=sum(1 for r in rows if r.status == "scored"),
        held=sum(1 for r in rows if r.status == "held"),
        failed=sum(1 for r in rows if r.status == "failed"),
        mean_diff=mean(diffs) if diffs else None,
        max_diff=max(diffs) if diffs else None,
        diff_ci95=ci95_half_width(signed),
        spearman=spearman([mean(per[s]) for s in common], [mean(baseline[s]) for s in common]),
        stability=mean(spreads) if spreads else None,
        evidence_rate=real / offered if offered else None,
        cost_per_run=cost.quantize(Decimal("0.0001")) if cost is not None else None,
        p50_seconds=percentile(durations, 50),
        p90_seconds=percentile(durations, 90),
        passes={},
    )
    passes: dict[str, bool | None] = {
        "diff": None if report.mean_diff is None else report.mean_diff <= MAX_MEAN_DIFF,
        "stability": None,
        "evidence": None if report.evidence_rate is None else report.evidence_rate >= MIN_EVIDENCE_RATE,
        "cost": None,
    }
    if base is not None and base is not report:
        if report.stability is not None and base.stability is not None:
            passes["stability"] = report.stability <= base.stability
        if report.cost_per_run is not None and base.cost_per_run is not None:
            passes["cost"] = report.cost_per_run < base.cost_per_run
    return RowReport(**{**report.__dict__, "passes": passes})


def report_rows(runs: Sequence[RunRow], *, baseline: str = BASELINE_ROW) -> list[RowReport]:
    """줄마다 보고 — 기준 줄이 맨 앞. 기준 줄이 없으면 점수 차·순위·흔들림·비용 기준은 판단하지 않는다(None)."""

    by_row: dict[str, list[RunRow]] = {}
    for r in runs:
        by_row.setdefault(r.row, []).append(r)
    base_rows = by_row.get(baseline, [])
    base_scores = _per_submission(base_rows)
    base_report = _row_report(baseline, base_rows, base_scores, None) if base_rows else None
    out = [base_report] if base_report is not None else []
    out += [_row_report(name, rows, base_scores, base_report) for name, rows in sorted(by_row.items()) if name != baseline]
    return out


def limits_note(reports: Sequence[RowReport], *, repeat: int) -> list[str]:
    """표본 수와 한계 — 보고표 머리에 같이 찍는다."""

    if not reports:
        return ["돈 회차가 없다."]
    n = max(r.submissions for r in reports)
    notes = [f"제출 {n}건 × 회차 {repeat}."]
    widths = [r.diff_ci95 for r in reports if r.diff_ci95 is not None]
    if n < 2 or not widths:
        notes.append("제출이 2건 미만이라 점수 차의 신뢰 구간을 낼 수 없다 — 기준 판단은 참고만.")
    else:
        widest = max(widths)
        verdict = "차이 5점을 가르기에 넓다" if widest > MAX_MEAN_DIFF else "차이 5점은 가를 수 있다"
        notes.append(f"평균 점수 차의 95% 신뢰 구간 반폭 최대 ±{widest:.1f}점 — {verdict}.")
    if repeat < 3:
        notes.append("회차가 3보다 적어 흔들림은 거칠다.")
    if n < 30:
        notes.append("순위 일치(스피어만)는 제출이 적으면 크게 흔들린다.")
    return notes


def _fmt(value: float | Decimal | None, spec: str) -> str:
    return "—" if value is None else format(value, spec)


def _mark(value: bool | None) -> str:
    return "—" if value is None else ("통과" if value else "미달")


HEADERS = [
    "줄", "제출", "회차", "채점", "보류", "실패", "평균 차", "최대 차", "순위 일치", "흔들림", "근거 실재율",
    "건당 비용(USD)", "p50(초)", "p90(초)", "기준: 차", "기준: 흔들림", "기준: 근거", "기준: 비용",
]


def _cells(r: RowReport) -> list[str]:
    return [
        r.row, str(r.submissions), str(r.runs), str(r.scored), str(r.held), str(r.failed),
        _fmt(r.mean_diff, ".2f"), _fmt(r.max_diff, ".2f"), _fmt(r.spearman, ".3f"), _fmt(r.stability, ".2f"),
        _fmt(None if r.evidence_rate is None else r.evidence_rate * 100, ".1f") + ("%" if r.evidence_rate is not None else ""),
        _fmt(r.cost_per_run, "f"), _fmt(r.p50_seconds, ".1f"), _fmt(r.p90_seconds, ".1f"),
        *(_mark(r.passes.get(k)) for k in ("diff", "stability", "evidence", "cost")),
    ]


def to_markdown(title: str, reports: Sequence[RowReport], notes: Sequence[str]) -> str:
    lines = [f"# {title}", "", *(f"- {n}" for n in notes), ""]
    lines.append("| " + " | ".join(HEADERS) + " |")
    lines.append("| " + " | ".join("---" for _ in HEADERS) + " |")
    lines += ["| " + " | ".join(_cells(r)) + " |" for r in reports]
    return "\n".join(lines) + "\n"


def to_csv(reports: Sequence[RowReport]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    for r in reports:
        writer.writerow(_cells(r))
    return buf.getvalue()
