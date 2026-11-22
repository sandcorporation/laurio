"""채점 방식 비교 실험의 보고표(#1246, 스펙 #1244) — 실험 줄마다 기준 줄과 견준 숫자와 통과 기준 넷.

계산은 DB 를 모르는 순수 함수다(`report_rows`) — `manage.py experiment_report` 가 실험 기록을 `RunRow` 로 바꿔 넘긴다.

- 점수 차: 제출마다 그 줄의 회차 평균 − 기준 줄의 회차 평균, 그 **절댓값**의 평균·최대.
- 순위 일치: 제출마다 회차 평균으로 두 줄의 스피어만 상관(같은 값은 평균 순위).
- 흔들림: 제출마다 회차 점수의 표본 표준편차, 그 평균(회차가 하나면 없음).
- 근거 실재율: 모델이 낸 근거 중 박제본에 실재한 몫 — 우리 루프가 다시 물어 버린 근거(`evidence_dropped`)도 분모에 든다.
- 건당 비용: 회차 하나의 평균 비용(실패·보류 포함 — 돈은 썼다). 시간은 끝난 회차의 p50·p90.
- 요구사항 단위(#1261): 점수가 같아도 판정이 다를 수 있다(공모전 3 은 16건 모두 100 이라 점수로는 아무것도 못 갈랐다).
  - 판정 일치율: (제출, 요구사항)마다 이 줄의 회차 판정과 기준 줄의 회차 판정을 모든 짝으로 견준 일치 몫, 그 평균.
    필수와 선택(선택·가산)을 나눈다. 기준 줄 자신은 없음.
  - 판정 흔들림: 채점된 회차가 둘 이상인 (제출, 요구사항) 가운데 회차마다 판정이 바뀐 몫. 필수·선택을 나눈다.
  - 미충족 재현율·오탐률은 기준 판정(알려진 미충족)이 있어야 잰다 — 운영 재료에는 없어 「—」다.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from statistics import mean, stdev

BASELINE_ROW = "agent:claude-sonnet-5-5"
#: 통과 문턱(스펙 #1244 넷 + 대장 #4345 설계안) — 점수는 0~100.
MAX_MEAN_DIFF = 5.0
MAX_MAX_DIFF = 15.0
MIN_SPEARMAN = 0.8
STABILITY_SLACK = 2.0  # 흔들림 ≤ 기준 + 이만큼
MIN_EVIDENCE_RATE = 0.95
MAX_TROUBLE_RATE = 1 / 16  # 실패 + 보류
COST_DIVISOR = 3  # 건당 비용 × 3 ≤ 기준 건당 비용(1/3 을 Decimal 로 나누면 끝자리가 잘린다)
MAX_P90_SECONDS = 300.0
#: 필수 판정 일치율 ≥ 이것(#1261). 평균 차 문턱(5점)을 판정 수로 옮긴 값이다 — 공모전 3 의 필수 14개에서 판정 하나가
#: 다르면 점수가 100/14 ≈ 7.1점 움직이므로, 평균 차 5점은 제출당 0.7개 ≈ 필수의 5% 가 다른 것과 같다.
MIN_REQUIRED_AGREEMENT = 0.95
#: 필수 판정 흔들림 ≤ 기준 줄의 흔들림 + 이것(#1261). 점수 흔들림 문턱(기준 + 2점)을 같은 식으로 옮겼다 — 2점은 필수
#: 14개에서 판정 0.28개 ≈ 2%p.
FLIP_SLACK = 0.02
FULL_REPEAT = 3  # 「전체」 예상 금액의 회차
#: 대장이 매긴 항목별 기준 판정을 칸으로 남기는 줄(#1288) — 보고표가 이 줄을 줄로 세지 않고 일치·재현율·오탐률의 기준으로만 쓴다. 값은 이미 저장된 칸 이름이라 그대로 둔다(보이는 라벨이 아니다).
TRUTH_ROW = "정답:사람"
CRITERIA = ("diff", "max_diff", "spearman", "stability", "evidence", "trouble", "cost", "p90", "agreement", "flip")


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
    verdicts: tuple[tuple[int, bool], ...] = ()  # (요구사항 id, 충족) — 채점됐을 때만
    #: staged 줄(#1295)만 — 기계가 정한 항목 수·모델에 간 항목 수. 다른 줄은 None.
    machine_items: int | None = None
    model_items: int | None = None


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
    passes: dict[str, bool | None]  # 문턱마다(`CRITERIA`), 판단 못 하면 None
    agreement_required: float | None = None  # 기준 줄 대비 필수 판정 일치율
    agreement_optional: float | None = None
    flip_required: float | None = None  # 회차 사이 필수 판정 흔들림
    flip_optional: float | None = None
    # 대장이 매긴 항목별 기준 판정(#1288)과 견준 것 — 기준 판정이 있는 재료만. 미충족이 찾아야 할 쪽이다.
    item_accuracy: float | None = None  # 기준 판정과 판정이 같은 칸의 몫
    unmet_recall: float | None = None  # 기준이 미충족인 칸 가운데 미충족으로 판정한 몫
    false_positive_rate: float | None = None  # 기준이 충족인 칸 가운데 미충족으로 판정한 몫(오탐)
    # staged 줄(#1295)만 — 채점된 칸 평균. 다른 줄은 None.
    machine_items: float | None = None
    model_items: float | None = None


Verdicts = dict[tuple[int, int], list[bool]]  # (제출, 요구사항) → 회차마다의 충족


def _verdicts(rows: Iterable[RunRow]) -> Verdicts:
    out: Verdicts = {}
    for r in rows:
        if r.status == "scored":
            for requirement_id, met in r.verdicts:
                out.setdefault((r.submission_id, requirement_id), []).append(met)
    return out


def agreement(mine: Verdicts, base: Verdicts, *, required: frozenset[int], want_required: bool) -> float | None:
    """(제출, 요구사항)마다 두 줄의 회차 판정을 모든 짝으로 견준 일치 몫의 평균. 견줄 것이 없으면 None."""

    keys = [k for k in mine if k in base and (k[1] in required) == want_required]
    if not keys:
        return None
    return mean(sum(a == b for a in mine[k] for b in base[k]) / (len(mine[k]) * len(base[k])) for k in keys)


def truth_scores(mine: Verdicts, truth: Verdicts) -> tuple[float | None, float | None, float | None]:
    """기준 판정(칸마다 판정 하나)과 이 줄의 판정(회차마다)을 칸·회차 단위로 견준다 → (정확도, 미충족 재현율, 오탐률).
    견줄 칸이 없으면 셋 다 None, 기준에 미충족(충족)이 없으면 재현율(오탐률)만 None."""

    hits = total = unmet = unmet_found = met = met_flagged = 0
    for key, answers in truth.items():
        for judged in mine.get(key, []):
            expected = answers[0]
            total += 1
            hits += judged == expected
            if expected:
                met += 1
                met_flagged += not judged
            else:
                unmet += 1
                unmet_found += not judged
    if not total:
        return None, None, None
    return hits / total, unmet_found / unmet if unmet else None, met_flagged / met if met else None


def flip_rate(mine: Verdicts, *, required: frozenset[int], want_required: bool) -> float | None:
    """채점된 회차가 둘 이상인 (제출, 요구사항) 가운데 판정이 회차마다 같지 않은 몫. 그런 것이 없으면 None."""

    keys = [k for k, v in mine.items() if len(v) >= 2 and (k[1] in required) == want_required]
    if not keys:
        return None
    return sum(1 for k in keys if len(set(mine[k])) > 1) / len(keys)


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


def _row_report(
    name: str,
    rows: list[RunRow],
    baseline: dict[int, list[float]],
    base: RowReport | None,
    *,
    base_verdicts: Verdicts,
    required: frozenset[int],
    truth: Verdicts | None = None,
) -> RowReport:
    per = _per_submission(rows)
    mine = _verdicts(rows)
    compared = base is not None
    common = sorted(set(per) & set(baseline))
    signed = [mean(per[s]) - mean(baseline[s]) for s in common]
    diffs = [abs(d) for d in signed]
    spreads = [stdev(v) for v in per.values() if len(v) >= 2]
    offered = sum(r.evidence_offered for r in rows)
    real = sum(r.evidence_real for r in rows)
    durations = [r.duration_seconds for r in rows if r.status != "failed" and r.duration_seconds is not None]
    # 돈이 든 칸이 하나도 없으면 실측이 없다(#1257) — 0 으로 세면 전체 예상 합계를 낮춰 보인다.
    measured = any(r.cost_usd > 0 for r in rows)
    cost = sum((r.cost_usd for r in rows), Decimal(0)) / len(rows) if measured else None
    accuracy, recall, false_positive = truth_scores(mine, truth) if truth else (None, None, None)
    staged = [r for r in rows if r.status == "scored" and r.machine_items is not None and r.model_items is not None]
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
        agreement_required=agreement(mine, base_verdicts, required=required, want_required=True) if compared else None,
        agreement_optional=agreement(mine, base_verdicts, required=required, want_required=False) if compared else None,
        flip_required=flip_rate(mine, required=required, want_required=True),
        flip_optional=flip_rate(mine, required=required, want_required=False),
        item_accuracy=accuracy,
        unmet_recall=recall,
        false_positive_rate=false_positive,
        machine_items=mean(r.machine_items for r in staged) if staged else None,  # type: ignore[misc]  # staged 는 None 을 걸렀다
        model_items=mean(r.model_items for r in staged) if staged else None,  # type: ignore[misc]
    )
    passes: dict[str, bool | None] = dict.fromkeys(CRITERIA)
    if report.runs:
        passes["trouble"] = (report.held + report.failed) / report.runs <= MAX_TROUBLE_RATE
    if report.evidence_rate is not None:
        passes["evidence"] = report.evidence_rate >= MIN_EVIDENCE_RATE
    if report.p90_seconds is not None:
        passes["p90"] = report.p90_seconds <= MAX_P90_SECONDS
    if base is not None and base is not report:
        if report.mean_diff is not None:
            passes["diff"] = report.mean_diff <= MAX_MEAN_DIFF
        if report.max_diff is not None:
            passes["max_diff"] = report.max_diff <= MAX_MAX_DIFF
        if report.spearman is not None:
            passes["spearman"] = report.spearman >= MIN_SPEARMAN
        if report.stability is not None and base.stability is not None:
            passes["stability"] = report.stability <= base.stability + STABILITY_SLACK
        if report.cost_per_run is not None and base.cost_per_run:
            passes["cost"] = report.cost_per_run * COST_DIVISOR <= base.cost_per_run
        if report.agreement_required is not None:
            passes["agreement"] = report.agreement_required >= MIN_REQUIRED_AGREEMENT
        if report.flip_required is not None and base.flip_required is not None:
            passes["flip"] = report.flip_required <= base.flip_required + FLIP_SLACK
    return RowReport(**{**report.__dict__, "passes": passes})


def report_rows(
    runs: Sequence[RunRow],
    *,
    baseline: str = BASELINE_ROW,
    row_names: Sequence[str] = (),
    required_ids: frozenset[int] = frozenset(),
) -> list[RowReport]:
    """줄마다 보고 — 기준 줄이 맨 앞. 기준 줄이 없으면 점수 차·순위·흔들림·비용·판정 일치 기준은 판단하지 않는다(None).
    `row_names`(실험의 줄)에 있는데 남은 칸이 없는 줄도 빈 줄로 보인다 — 빠지면 그 줄이 안 돈 것을 놓친다.
    `required_ids` 는 공모전의 필수 요구사항 — 판정 일치율·흔들림을 필수와 그 밖으로 나눈다."""

    by_row: dict[str, list[RunRow]] = {name: [] for name in row_names if name != TRUTH_ROW}
    truth_runs = [r for r in runs if r.row == TRUTH_ROW]
    for r in runs:
        if r.row != TRUTH_ROW:
            by_row.setdefault(r.row, []).append(r)
    base_rows = by_row.get(baseline, [])
    base_scores = _per_submission(base_rows)
    common = {"base_verdicts": _verdicts(base_rows), "required": required_ids, "truth": _verdicts(truth_runs)}
    base_report = _row_report(baseline, base_rows, base_scores, None, **common) if baseline in by_row else None
    out = [base_report] if base_report is not None else []
    out += [
        _row_report(name, rows, base_scores, base_report, **common)
        for name, rows in sorted(by_row.items())
        if name != baseline
    ]
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
    if repeat == 1:
        notes.append("회차 1 — 흔들림은 잴 수 없다.")
    elif repeat < 3:
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
    "필수 판정 일치", "선택 판정 일치", "필수 판정 흔들림", "선택 판정 흔들림", "기준 판정과의 일치", "기준 미충족 재현율", "기준 대비 오탐률",
    "실측 건당 비용(USD)", "전체 예상(USD)", "p50(초)", "p90(초)",
    "평균 차 ≤5", "최대 차 ≤15", "순위 ≥0.8", "흔들림 ≤기준+2", "근거 ≥95%", "실패·보류 ≤1/16", "비용 ≤기준/3", "p90 ≤300초",
    "필수 일치 ≥95%", "필수 판정 흔들림 ≤기준+2%p",
    "기계 확정 항목 수", "모델에 간 항목 수",
]
NO_TRUTH_NOTE = "기준 판정(알려진 미충족)이 없는 재료 — 기준 미충족 재현율·기준 대비 오탐률은 「—」."
TRUTH_NOTE = (
    "기준 판정과의 일치·기준 미충족 재현율·기준 대비 오탐률은 항목별 기준 판정과 견준 값 — 미충족이 찾는 쪽이다"
    "(재현율 = 기준 미충족 중 미충족으로 판정, 오탐률 = 기준 충족 중 미충족으로 판정). 기준 판정 없는 제출은 뺐다."
)
COST_ONLY_NOTE = "비용 측정 전용 — 점수 비교 아님(뽑힌 재료의 기준 점수가 모두 같았다)."


NOT_MEASURED = "실측 없음"


def full_estimate_usd(r: RowReport, full_submissions: int) -> Decimal | None:
    """이 줄을 공모전 전체(제출 N × 회차 3)로 돌리면 드는 돈 — 실측 건당 비용으로."""

    return None if r.cost_per_run is None else (r.cost_per_run * full_submissions * FULL_REPEAT).quantize(Decimal("0.01"))


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _cells(r: RowReport, *, repeat: int, full_submissions: int) -> list[str]:
    stability = "회차 1 — 잴 수 없음" if repeat == 1 else _fmt(r.stability, ".2f")
    return [
        r.row, str(r.submissions), str(r.runs), str(r.scored), str(r.held), str(r.failed),
        _fmt(r.mean_diff, ".2f"), _fmt(r.max_diff, ".2f"), _fmt(r.spearman, ".3f"), stability,
        _pct(r.evidence_rate),
        _pct(r.agreement_required), _pct(r.agreement_optional),
        _pct(r.flip_required), _pct(r.flip_optional),
        _pct(r.item_accuracy), _pct(r.unmet_recall), _pct(r.false_positive_rate),
        _fmt(r.cost_per_run, "f"),
        NOT_MEASURED if (e := full_estimate_usd(r, full_submissions)) is None else format(e, "f"),
        _fmt(r.p50_seconds, ".1f"), _fmt(r.p90_seconds, ".1f"),
        *(_mark(r.passes.get(k)) for k in CRITERIA),
        _fmt(r.machine_items, ".1f"), _fmt(r.model_items, ".1f"),
    ]


def to_markdown(
    title: str, reports: Sequence[RowReport], notes: Sequence[str], *, repeat: int, full_submissions: int
) -> str:
    total = sum((e for r in reports if (e := full_estimate_usd(r, full_submissions)) is not None), Decimal(0))
    lines = [f"# {title}", "", *(f"- {n}" for n in notes)]
    unmeasured = sum(1 for r in reports if r.cost_per_run is None)
    left_out = f" 「{NOT_MEASURED}」 줄 {unmeasured}개는 합계에 없다." if unmeasured else ""
    lines.append(
        f"- 전체 예상 = 실측 건당 비용 × 제출 {full_submissions} × 회차 {FULL_REPEAT} — 줄 모두 합계 {total:.2f} USD.{left_out}"
    )
    lines += ["", "| " + " | ".join(HEADERS) + " |", "| " + " | ".join("---" for _ in HEADERS) + " |"]
    lines += ["| " + " | ".join(_cells(r, repeat=repeat, full_submissions=full_submissions)) + " |" for r in reports]
    return "\n".join(lines) + "\n"


#: 운영 점수 구간(필수 충족 비율) — 사본 재료의 보고표가 구간마다 평균 차를 보인다(#1262).
BANDS = ("0~20", "20~40", "40~60", "60~80", "80~100")


def _band(score: float) -> str:
    return BANDS[min(int(score // 20), len(BANDS) - 1)]


def band_diffs(runs: Sequence[RunRow], *, production_row: str) -> dict[str, dict[str, tuple[float, int]]]:
    """줄마다 운영 점수 구간별 (평균 차 = 줄 점수 − 운영 점수, 칸 수). 운영 점수가 없는 제출·채점 안 된 칸은 뺀다."""

    truth = {r.submission_id: r.score for r in runs if r.row == production_row and r.score is not None}
    acc: dict[str, dict[str, list[float]]] = {}
    for r in runs:
        if r.row == production_row or r.score is None or r.submission_id not in truth:
            continue
        base = truth[r.submission_id]
        acc.setdefault(r.row, {}).setdefault(_band(base), []).append(r.score - base)
    return {row: {band: (mean(d), len(d)) for band, d in bands.items()} for row, bands in acc.items()}


def band_lines(runs: Sequence[RunRow], *, production_row: str, row_names: Sequence[str]) -> str:
    """운영 점수 구간별 평균 차 표(마크다운) — 칸이 없는 구간은 「—」."""

    diffs = band_diffs(runs, production_row=production_row)
    head = ["줄", *(f"운영 {b}%" for b in BANDS)]
    lines = ["", f"## 운영 점수 구간별 평균 차(줄 − {production_row})", "", "| " + " | ".join(head) + " |"]
    lines.append("| " + " | ".join("---" for _ in head) + " |")
    for name in row_names:
        cells = []
        for band in BANDS:
            cell = diffs.get(name, {}).get(band)
            cells.append("—" if cell is None else f"{cell[0]:+.1f} (n={cell[1]})")
        lines.append("| " + " | ".join([name, *cells]) + " |")
    return "\n".join(lines) + "\n"


def to_csv(reports: Sequence[RowReport], *, repeat: int, full_submissions: int) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(HEADERS)
    for r in reports:
        writer.writerow(_cells(r, repeat=repeat, full_submissions=full_submissions))
    return buf.getvalue()


# ── 청구 대조(#1259) ──────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class BillPart:
    """청구 한 덩어리 — 실행 토큰 하나(프록시가 요청마다 센 합) 또는 한 번 호출 칸 하나(벤더 직접 호출)."""

    source: str  # "proxy" | "direct"
    vendor: str
    model: str
    at: datetime  # 토큰 발급·칸 기록 시각(UTC 로 묶는다)
    requests: int
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    usd: Decimal


@dataclass(frozen=True)
class BillLine:
    vendor: str
    model: str
    day: str  # UTC "YYYY-MM-DD"
    window: str  # UTC "HH:00–HH:59"
    requests: int
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    usd: Decimal


def bill_lines(parts: Iterable[BillPart]) -> list[BillLine]:
    """벤더·모델·UTC 날짜·UTC 한 시간 창마다 더한다 — 벤더 콘솔의 사용량 표(UTC)와 줄 단위로 맞춰 보는 꼴."""

    groups: dict[tuple[str, str, str, int], list[BillPart]] = {}
    for part in parts:
        at = part.at.astimezone(UTC)
        groups.setdefault((part.vendor, part.model, at.strftime("%Y-%m-%d"), at.hour), []).append(part)
    lines = []
    for (vendor, model, day, hour), group in sorted(groups.items()):
        lines.append(
            BillLine(
                vendor=vendor,
                model=model,
                day=day,
                window=f"{hour:02d}:00–{hour:02d}:59",
                requests=sum(p.requests for p in group),
                input_tokens=sum(p.input_tokens for p in group),
                cache_read_tokens=sum(p.cache_read_tokens for p in group),
                cache_write_tokens=sum(p.cache_write_tokens for p in group),
                output_tokens=sum(p.output_tokens for p in group),
                usd=sum((p.usd for p in group), Decimal(0)),
            )
        )
    return lines


def bill_markdown(title: str, lines: Sequence[BillLine], notes: Sequence[str]) -> str:
    out = [
        f"# {title}",
        "",
        "| 벤더 | 모델 | 날짜(UTC) | 시간(UTC) | 요청 | 입력 | 캐시 읽기 | 캐시 쓰기 | 출력 | 금액(USD) |",
        "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for line in lines:
        out.append(
            f"| {line.vendor} | {line.model} | {line.day} | {line.window} | {line.requests} | {line.input_tokens} | "
            f"{line.cache_read_tokens} | {line.cache_write_tokens} | {line.output_tokens} | {line.usd:.6f} |"
        )
    total = sum((line.usd for line in lines), Decimal(0))
    out.append(f"| 합계 | | | | {sum(line.requests for line in lines)} | | | | | {total:.6f} |")
    out += ["", *notes]
    return "\n".join(out) + "\n"
