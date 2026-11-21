"""채점 방식 비교 실험(#1246, 스펙 #1244) — 줄(방식:모델) × 제출 × 회차 칸을 돌려 `ScoringExperimentRun` 에만 남긴다.

**운영 동작을 바꾸지 않는다**: 운영 설정(`CONTEST_SCORING_METHOD`·`LLM_SCORING_VENDOR`·모델)을 읽거나 쓰지 않고 벤더·모델을
인자로 넘긴다. `Score`·`ScoreCorrection`·`AgentRun`·순위·지급은 쓰지 않는다. 입력은 운영 채점이 실제로 본 것과 같다 —
정정 채점처럼 `Score` 에 남은 처음 커밋으로 다시 받는다(`scoring.corrections._fixed_inputs`).

돈: 에이전트·우리 루프는 실행 토큰 용도 `experiment` 로 `llm-proxy` 를 지나고, 프록시가 실험 하루 상한
(`AGENT_EXPERIMENT_DAILY_LIMIT_USD`, 기본 0 = 꺼짐)을 운영 몫과 따로 센다. 한 번 호출은 벤더를 직접 부르므로 비용을 이
표에 적고, 명령이 칸마다 「오늘 실험에 쓴 돈 + 이 칸의 최대 비용 ≤ 상한」을 먼저 본다.

칸 예산(#1259): 에이전트·우리 루프 칸 하나(에이전트는 시도 둘 모두)의 하드 상한은 `CELL_BUDGET_USD` 하나다. 실행 토큰 예산은
min(칸 예산, 남은 하루 돈)으로 발급해 하루 상한에 닿기 전에 토큰이 먼저 끊긴다. 칸은 남은 돈이 칸 예산 이상일 때만 시작한다
(추정이 아니라 실제로 끊기는 값으로 견준다). 프록시는 요청 **전에** 쓴 돈만 보므로 마지막 요청 하나만큼은 넘칠 수 있다.
"""

from __future__ import annotations

import logging
import tempfile
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from contests.models import Contest, ContestSubmission, Requirement
from core.adapters import is_fake_adapter_binding
from core.agent_ports import agent_grader, price_for
from core.agent_prompt import ID_KEY, ITEMS_KEY, SCORING_OUTPUT_SCHEMA, build_scoring_prompt
from core.agent_run_tokens import RunTokenRefused, Usage, spent_today_usd, usage_cost_usd
from core.agent_scoring import RUN_BUDGET_USD as AGENT_RUN_BUDGET_USD
from core.agent_scoring import (
    JSON,
    AgentJob,
    AgentRunHeld,
    AgentVendorRefused,
    Snapshot,
    provided_snapshot,
    run_agent_job,
)
from core.clock import Clock
from core.models import AgentRunToken
from core.llm_scoring import LLMScoringAdapter, RequirementInput, RequirementVerdict, ScoringInput, get_adapter
from core.runtime_settings_port import ScoringVendor, agent_experiment_daily_limit_usd, setting_value

from . import selfloop
from .corrections import _fixed_inputs
from .current import latest_done_correction
from .experiment_report import BillPart
from .models import Score, ScoringExperiment, ScoringExperimentRun
from .selfloop_scoring import RUN_BUDGET_USD as SELFLOOP_RUN_BUDGET_USD
from .selfloop_scoring import run_selfloop_scoring
from .services import (
    CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS,
    _agent_snapshot,
    _asset_label,
    _build_prompt,
    _measure_source_fit,
    _percentage,
    _requirement_inputs,
)

logger = logging.getLogger(__name__)

Method = Literal["single_call", "agent", "self_loop"]
METHODS: tuple[Method, ...] = ("single_call", "agent", "self_loop")

BASELINE = "agent:claude-sonnet-5-5"
DEFAULT_ROWS = (
    BASELINE,
    "single_call:claude-haiku-5-5",
    "agent:claude-haiku-5-5",
    "self_loop:claude-haiku-5-5",
    "single_call:gpt-4.1-mini",
    "agent:gpt-4.1-mini",
    "self_loop:gpt-4.1-mini",
)

#: 칸 하나의 비용 추정에 쓰는 토큰 범위(입력, 출력) — 낮은·높은. 공모전 3 실측(#992, ADR-0082)에서 잡은 대략값이고,
#: 실험이 이미 돈 칸이 있으면 그 줄의 실제 최소·최대가 이긴다. 에이전트·우리 루프는 낮은 쪽에만 쓴다 — 높은 쪽은 칸 예산이다
#: (#1259: 실측이 4.1-mini 에이전트 시도 하나 198만, 우리 루프 85만~216만 토큰으로 추정의 몇 배였다).
#: 한 번 호출의 높은 쪽은 공모전 3 실험 실측(#1257: 입력 100k~255k)을 덮는다 — 10만 토큰을 넘으면 Haiku 5.5 는 입력·출력
#: 모두 5배 단가라(`classroom.scoring_cost`) 높은 쪽이 그 문턱 아래(옛 90k)에 있으면 칸당 최대가 열 배 가까이 작게 나온다.
_TOKEN_ESTIMATE: dict[Method, tuple[tuple[int, int], tuple[int, int]]] = {
    "single_call": ((20_000, 1_000), (300_000, 4_000)),
    "agent": ((60_000, 2_000), (600_000, 15_000)),
    "self_loop": ((40_000, 2_000), (400_000, 12_000)),
}
#: 칸 하나의 하드 상한(USD) — 실행 토큰이 끊는 값. 에이전트는 시도 둘(최초 + 재실행)을 합쳐 이 안이다(#1259).
#: 한 번 호출은 요청 하나라 토큰이 없다(벤더를 직접 부른다).
CELL_BUDGET_USD: dict[Method, Decimal | None] = {
    "single_call": None,
    "agent": AGENT_RUN_BUDGET_USD,
    "self_loop": SELFLOOP_RUN_BUDGET_USD,
}


class ExperimentError(Exception):
    """줄·공모전·실험 이름이 잘못됐다 — 명령이 그대로 보여 준다."""


# ── 인프라 실패(#1257) ────────────────────────────────────────────────────────────────────────────────

def infra_errors() -> tuple[type[Exception], ...]:
    """방식의 실패가 아니라 인프라 실패인 예외 — 실행기에 닿지 못함·HTTP 오류(`AgentGraderError`)·바쁨(`AgentGraderBusy`),
    실행 토큰 거절(`RunTokenRefused`), 벤더 계정 쪽 거절(`AgentVendorRefused` — 실행 도중 상한 429 가 CLI 에서 이렇게 온다).
    실행기 예외는 `core.agent_ports` 에 등록된 실행 틀 모듈의 것이다(실행기를 직접 들이지 않는다)."""

    grader = agent_grader()
    return (grader.AgentGraderError, grader.AgentGraderBusy, RunTokenRefused, AgentVendorRefused)


#: `problem` 이 이 이름으로 시작하는 `failed` 칸이 인프라 실패다(`infra_errors` 의 클래스 이름과 같다 — 시험이 지킨다).
INFRA_PROBLEM_PREFIXES = ("AgentGraderError:", "AgentGraderBusy:", "RunTokenRefused:", "AgentVendorRefused:")
#: 인프라 실패 칸의 상태 — `CellResult` 에만 쓰고 실험 표에는 남기지 않는다.
INFRA = "infra"


def grader_address() -> str:
    """실행기 주소(`agent-grader:8003`) — 미리 보기·거절 문구에 쓴다."""

    return agent_grader().DEFAULT_SERVICE_URL.removeprefix("http://")
#: 연속으로 이만큼 인프라 실패면 멈춘다 — 실행기·프록시가 죽었는데 남은 칸을 다 부딪쳐 볼 까닭이 없다.
MAX_CONSECUTIVE_INFRA_FAILURES = 3


def is_infra_failure(status: str, problem: str) -> bool:
    """실험 표에 남은 칸이 인프라 실패인가 — 지금은 그런 칸을 남기지 않지만, #1257 전에 `failed` 로 남은 칸
    (`AgentGraderError: URLError` 등)을 같은 판정으로 끝나지 않은 칸으로 본다(데이터를 고치지 않고 규칙으로)."""

    return status == ScoringExperimentRun.Status.FAILED and problem.startswith(INFRA_PROBLEM_PREFIXES)


def needs_grader(rows: Sequence[Row]) -> bool:
    """줄 가운데 실행기(`agent-grader`)를 부르는 것이 있는가 — 한 번 호출은 벤더를 직접 부른다."""

    return any(row.method != "single_call" for row in rows)


def probe_grader() -> None:
    """실행기에 한 번 닿아 본다 — 시험이 바꿔 끼우는 자리."""

    agent_grader().check_health()


def grader_problem() -> str | None:
    """실행기에 한 번 닿아 본다 — 닿으면 None, 아니면 사람이 읽을 까닭."""

    try:
        probe_grader()
    except agent_grader().AgentGraderError as exc:
        return f"실행기 {grader_address()} 에 닿지 못한다({exc}) — celery-worker 에서 돌린다"
    return None


@dataclass(frozen=True)
class Row:
    method: Method
    model: str
    vendor: ScoringVendor

    @property
    def name(self) -> str:
        return f"{self.method}:{self.model}"


def vendor_for(model: str) -> ScoringVendor:
    if model.startswith("claude-"):
        return "anthropic"
    if model.startswith(("gpt-", "o1", "o3", "o4")):
        return "openai"
    raise ExperimentError(f"벤더를 알 수 없는 모델: {model}")


def parse_rows(text: str | None) -> list[Row]:
    """`방식:모델,…` → 줄 목록. 비면 기본 줄. 단가를 모르는 모델은 비용 상한을 걸 수 없어 거절한다."""

    names = [p.strip() for p in (text or ",".join(DEFAULT_ROWS)).split(",") if p.strip()]
    rows: list[Row] = []
    for name in names:
        method, sep, model = name.partition(":")
        if not sep or method not in METHODS or not model:
            raise ExperimentError(f"줄은 `방식:모델` 이고 방식은 {', '.join(METHODS)} 중 하나다: {name}")
        if price_for(model) is None:
            raise ExperimentError(f"단가를 모르는 모델이라 비용을 셀 수 없다: {model}")
        row = Row(method, model, vendor_for(model))  # type: ignore[arg-type]  # method 는 위에서 METHODS 로 좁혔다
        if row in rows:
            raise ExperimentError(f"같은 줄이 두 번 있다: {name}")
        rows.append(row)
    return rows


Pick = Literal["id", "spread"]
PICKS: tuple[Pick, ...] = ("id", "spread")


def spread(ranked: Sequence[int], n: int) -> list[int]:
    """점수 순으로 줄 선 것에서 양 끝을 포함해 고르게 n 개(하나면 가운데)."""

    if n >= len(ranked):
        return list(ranked)
    if n == 1:
        return [ranked[(len(ranked) - 1) // 2]]
    step = (len(ranked) - 1) / (n - 1)
    return [ranked[round(i * step)] for i in range(n)]


def eligible_submissions(contest: Contest, limit: int | None, pick: Pick = "id") -> list[ContestSubmission]:
    """운영 채점이 끝난(`Score` 가 있는) 제출 — 입력을 같은 커밋으로 다시 받을 수 있는 것만. 돌려주는 것은 id 순.

    `limit` 건을 고르는 법: `id` 는 id 순 앞 N 건, `spread` 는 운영 점수 순(같으면 id 순)으로 줄 세워 양 끝을 포함해 고르게
    N 건(점수 분위, #1259). 같은 운영 점수·같은 N 이면 언제나 같은 집합이다."""

    in_contest = ContestSubmission.objects.filter(contest=contest).values("pk")
    scores = Score.objects.filter(submission_id__in=in_contest)
    if limit is None:
        ids = list(scores.values_list("submission_id", flat=True))
    elif pick == "spread":
        ids = spread(list(scores.order_by("percentage", "submission_id").values_list("submission_id", flat=True)), limit)
    else:
        ids = list(scores.order_by("submission_id").values_list("submission_id", flat=True)[:limit])
    return list(ContestSubmission.objects.filter(pk__in=ids).select_related("contest").order_by("pk"))


# ── 재료 — 가를 수 있는가(#1261) ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Material:
    """뽑힌 제출 하나의 기대 점수 — 운영 점수(끝난 정정이 있으면 그 점수)와 그 판정의 미충족 수."""

    submission_id: int
    score: Decimal
    unmet_required: int
    unmet_optional: int  # 선택·가산


def materials(contest: Contest, submissions: Sequence[ContestSubmission]) -> list[Material]:
    required = set(
        Requirement.objects.filter(contest=contest, grade=Requirement.Grade.REQUIRED).values_list("pk", flat=True)
    )
    out = []
    for score in Score.objects.filter(submission_id__in=[s.pk for s in submissions]).order_by("submission_id"):
        correction = latest_done_correction(score)
        current = correction if correction is not None and correction.percentage is not None else None
        percentage = current.percentage if current is not None else score.percentage
        reasoning = current.reasoning if current is not None else score.reasoning
        unmet = [
            item.get("requirement_id")
            for item in (reasoning if isinstance(reasoning, list) else [])
            if isinstance(item, dict) and item.get("is_met") is False
        ]
        out.append(
            Material(
                submission_id=score.submission_id,
                score=Decimal(percentage),
                unmet_required=sum(1 for rid in unmet if rid in required),
                unmet_optional=sum(1 for rid in unmet if rid not in required),
            )
        )
    return out


def same_score(picked: Sequence[Material]) -> Decimal | None:
    """뽑힌 재료의 기대 점수가 모두 같으면 그 점수 — 그 재료로는 방식을 가를 수 없다(`contest3-four-s4`: 16건 모두
    100 이라 32칸·판정 704개가 전부 100·충족이었다). 하나뿐이어도 같다고 본다(순위도 차이도 잴 수 없다)."""

    scores = {m.score for m in picked}
    return next(iter(scores)) if len(scores) == 1 else None


# ── 돈 ────────────────────────────────────────────────────────────────────────────────────────────────


def _day_start(now: datetime) -> datetime:
    return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)


def spent_today_experiment_usd(now: datetime | None = None) -> Decimal:
    """오늘(KST) 실험에 쓴 돈 — 프록시를 지난 실험 토큰 몫 + 벤더를 직접 부른 한 번 호출 몫."""

    now = now or Clock.now()
    direct = (
        ScoringExperimentRun.objects.filter(created_at__gte=_day_start(now), row__startswith="single_call:")
        .aggregate(total=Sum("cost_usd"))["total"]
    )
    return spent_today_usd(now, experiment=True) + (direct or Decimal(0))


def cost_range(row: Row, observed: Sequence[Decimal] = ()) -> tuple[Decimal, Decimal]:
    """칸 하나의 비용 범위(USD). 이미 돈 칸이 있으면 그 최소·최대. 없으면 낮은 쪽은 토큰 추정 × 단가, 높은 쪽은
    에이전트·우리 루프면 칸 예산(하드 상한, #1259), 한 번 호출이면 토큰 추정 × 단가."""

    if observed:
        return min(observed), max(observed)
    (lo_in, lo_out), (hi_in, hi_out) = _TOKEN_ESTIMATE[row.method]
    low = usage_cost_usd(row.vendor, row.model, Usage(input_tokens=lo_in, output_tokens=lo_out))
    cap = CELL_BUDGET_USD[row.method]
    if cap is None:
        high = usage_cost_usd(row.vendor, row.model, Usage(input_tokens=hi_in, output_tokens=hi_out))
    else:
        low, high = min(low, cap), cap
    return low.quantize(Decimal("0.0001")), high.quantize(Decimal("0.0001"))


def per_cell_max(row: Row, observed: Sequence[Decimal] = ()) -> Decimal:
    """칸을 시작하기 전에 남은 돈과 견줄 값 — 에이전트·우리 루프는 칸 예산(실제로 끊기는 값), 한 번 호출은 높은 추정."""

    cap = CELL_BUDGET_USD[row.method]
    return cap if cap is not None else cost_range(row, observed)[1]


def cell_budget_usd(row: Row, now: datetime | None = None) -> Decimal:
    """이 칸의 실행 토큰 예산 — min(칸 예산, 남은 하루 돈)(#1259). 하루 상한에 닿기 전에 토큰이 먼저 끊긴다."""

    cap = CELL_BUDGET_USD[row.method]
    assert cap is not None, row.name
    remaining = agent_experiment_daily_limit_usd() - spent_today_experiment_usd(now)
    return max(min(cap, remaining), Decimal(0))


def bill_parts(experiment: ScoringExperiment) -> list[BillPart]:
    """청구 대조(`experiment_report --bill`, #1259)의 재료 — 이 실험이 만들어진 뒤 그 제출들에 발급된 실험 실행 토큰
    (프록시가 요청마다 센 합)과 한 번 호출 칸(벤더 직접 호출, 칸 하나 = 요청 하나). 결과로 남지 않은 인프라 실패 칸의
    토큰도 든다 — 돈은 썼다. 같은 제출·같은 때 다른 실험을 돌렸으면 그 토큰도 섞인다(토큰은 실험 이름을 모른다)."""

    submissions = set(experiment.runs.values_list("submission_id", flat=True))
    submissions |= {s.pk for s in eligible_submissions(experiment.contest, experiment.limit_submissions, experiment_pick(experiment))}
    tokens = AgentRunToken.objects.filter(
        purpose=AgentRunToken.PURPOSE_EXPERIMENT, submission_id__in=submissions, created_at__gte=experiment.created_at
    ).order_by("created_at")
    parts = [
        BillPart(
            source="proxy", vendor=t.vendor, model=t.model, at=t.created_at, requests=t.request_count,
            input_tokens=t.input_tokens, cache_read_tokens=t.cache_read_tokens, cache_write_tokens=t.cache_write_tokens,
            output_tokens=t.output_tokens, usd=t.spent_usd,
        )
        for t in tokens
    ]
    for run in experiment.runs.filter(row__startswith="single_call:").order_by("created_at"):
        model = run.row.split(":", 1)[1]
        parts.append(
            BillPart(
                source="direct", vendor=vendor_for(model), model=model, at=run.created_at, requests=1,
                input_tokens=run.input_tokens, cache_read_tokens=0, cache_write_tokens=0,
                output_tokens=run.output_tokens, usd=run.cost_usd,
            )
        )
    return parts


def experiment_pick(experiment: ScoringExperiment) -> Pick:
    return "spread" if experiment.pick == "spread" else "id"


# ── 칸 하나 ───────────────────────────────────────────────────────────────────────────────────────────


@dataclass
class _Inputs:
    requirements: list[RequirementInput]
    readable: list
    cloned: list
    snapshot: Snapshot | None


@dataclass
class CellResult:
    status: str
    score: Decimal | None = None
    verdicts: list[dict[str, JSON]] = field(default_factory=list)
    evidence_offered: int = 0
    evidence_real: int = 0
    problem: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal(0)
    model_version: str = ""
    record: dict[str, JSON] = field(default_factory=dict)


def load_inputs(submission: ContestSubmission) -> _Inputs:
    """운영 채점이 본 입력 — `Score` 의 처음 커밋으로 다시 받는다. 박제본은 입력이 하나일 때만(운영과 같다)."""

    score = Score.objects.get(submission_id=submission.pk)
    readable, cloned = _fixed_inputs(score, submission)
    return _Inputs(_requirement_inputs(submission), readable, cloned, _agent_snapshot(readable, cloned))


def _single_call_adapter(row: Row) -> LLMScoringAdapter:
    """줄의 모델로 만든 한 번 호출 어댑터. 가짜 어댑터 모드(dev·시험)면 가짜다 — 진짜 벤더를 부르지 않는다."""

    if is_fake_adapter_binding(settings.LLM_ADAPTER_MODE):
        return get_adapter(timeout=CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS)
    if row.vendor == "anthropic":
        from core.llm_scoring_anthropic import PLATFORM_SCORING_EFFORT, AnthropicScoringAdapter

        return AnthropicScoringAdapter(
            api_key=setting_value("ANTHROPIC_API_KEY") or "",
            model=row.model,
            reasoning_effort=PLATFORM_SCORING_EFFORT,
            timeout=CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS,
            product="contest",
        )
    from core.llm_scoring import OpenAIScoringAdapter

    return OpenAIScoringAdapter(model=row.model, timeout=CONTEST_SCORING_VENDOR_TIMEOUT_SECONDS)


def _verdict_rows(requirements: list[RequirementInput], items: list[dict[str, JSON]]) -> tuple[list[dict[str, JSON]], Decimal]:
    by_id = {item[ID_KEY]: item for item in items}
    verdicts = [
        RequirementVerdict(requirement_id=r.requirement_id, is_met=by_id[r.requirement_id]["met"] is True, reasoning="")
        for r in requirements
    ]
    return [by_id[r.requirement_id] for r in requirements], _percentage(requirements=requirements, verdicts=verdicts)


def _proxy_totals(record: dict[str, JSON]) -> tuple[int, int, Decimal]:
    tokens_in = tokens_out = 0
    spent = Decimal(0)
    attempts = record.get("attempts")
    for attempt in attempts if isinstance(attempts, list) else []:
        usage = attempt.get("proxy_usage") if isinstance(attempt, dict) else None
        if isinstance(usage, dict):
            tokens_in += int(usage.get("input_tokens") or 0)  # type: ignore[arg-type]  # 기록 JSON
            tokens_out += int(usage.get("output_tokens") or 0)  # type: ignore[arg-type]  # 기록 JSON
            spent += Decimal(str(usage.get("spent_usd") or 0))
    return tokens_in, tokens_out, spent


def count_real_evidence(snapshot: Snapshot, items: list[dict[str, JSON]]) -> tuple[int, int]:
    """판정들이 낸 근거 `경로:줄` 가운데 박제본에 실재하는 수 — 우리 루프와 같은 검사(`selfloop.check_evidence`)."""

    evidence = [str(e) for item in items for e in (item.get("evidence") or []) if isinstance(item.get("evidence"), list)]  # type: ignore[union-attr]  # 위에서 list 로 좁혔다
    if not evidence:
        return 0, 0
    with tempfile.TemporaryDirectory(prefix="experiment-evidence-") as tmp:
        zip_path = Path(tmp) / "repo.zip"
        zip_path.write_bytes(snapshot.zip_bytes)
        root = Path(tmp) / "repo"
        agent_grader().extract_repo(zip_path, root)
        tools = selfloop.RepoTools(root)
        real = sum(1 for item in evidence if not selfloop.check_evidence(tools, [item]))
    return len(evidence), real


def _run_single_call(submission: ContestSubmission, row: Row, inputs: _Inputs) -> CellResult:
    llm = _single_call_adapter(row)
    source_files, omission, _budget = _measure_source_fit(
        llm,
        submission_id=submission.pk,
        contest=submission.contest,
        requirements=inputs.requirements,
        sources=[(a.id, _asset_label(a), raw) for a, raw in inputs.readable]
        + [(a.id, _asset_label(a), c.zip_bytes) for a, c in inputs.cloned],
    )
    if omission.any:
        return CellResult("held", problem="소스가 모델 컨텍스트에 다 들어가지 않는다(운영이면 보류)")
    prompt = _build_prompt(contest=submission.contest, requirements=inputs.requirements, source_files=source_files)
    output = llm.score(
        ScoringInput(
            submission_id=submission.pk,
            contest_id=submission.contest_id,
            prompt=prompt,
            source_files=source_files,
            requirements=inputs.requirements,
        )
    )
    cost = usage_cost_usd(row.vendor, row.model, Usage(input_tokens=output.input_tokens, output_tokens=output.output_tokens))
    verdicts: list[dict[str, JSON]] = [
        {"requirement_id": v.requirement_id, "met": v.is_met, "evidence": [], "reason": v.reasoning} for v in output.verdicts
    ]
    return CellResult(
        "scored",
        score=_percentage(requirements=inputs.requirements, verdicts=output.verdicts),
        verdicts=verdicts,
        input_tokens=output.input_tokens,
        output_tokens=output.output_tokens,
        cost_usd=cost,
        model_version=output.model_version,
    )


def _run_agent(submission: ContestSubmission, row: Row, inputs: _Inputs) -> CellResult:
    assert inputs.snapshot is not None
    requirements = inputs.requirements
    job = AgentJob(
        submission=submission,
        purpose="experiment",
        build_prompt=lambda model: build_scoring_prompt(requirements, model=model),
        output_schema=SCORING_OUTPUT_SCHEMA,
        expected_ids=frozenset(r.requirement_id for r in requirements),
        items_key=ITEMS_KEY,
        id_key=ID_KEY,
        evidence_required=lambda item: item.get("met") is True,
        pinned_model=(row.vendor, row.model),
        total_budget_usd=cell_budget_usd(row),
    )
    try:
        with provided_snapshot(submission.pk, inputs.snapshot):
            outcome = run_agent_job(job)
    except AgentRunHeld as held:
        tokens_in, tokens_out, spent = _proxy_totals(held.record)
        return CellResult(
            "held", problem="; ".join(held.reasons), input_tokens=tokens_in, output_tokens=tokens_out,
            cost_usd=spent, model_version=f"agent:{row.vendor}:{row.model}", record=held.record,
        )
    items = outcome.structured_output[ITEMS_KEY]
    verdicts, score = _verdict_rows(requirements, items)
    offered, real = count_real_evidence(inputs.snapshot, verdicts)
    tokens_in, tokens_out, spent = _proxy_totals(outcome.record)
    return CellResult(
        "scored", score=score, verdicts=verdicts, evidence_offered=offered, evidence_real=real,
        input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=spent,
        model_version=outcome.model_version, record=outcome.record,
    )


def _loop(record: dict[str, JSON]) -> dict[str, JSON]:
    attempts = record.get("attempts")
    last = attempts[-1] if isinstance(attempts, list) and attempts else None
    loop = last.get("loop") if isinstance(last, dict) else None
    return loop if isinstance(loop, dict) else {}


def _dropped(record: dict[str, JSON]) -> int:
    subs = _loop(record).get("requirements")
    total = 0
    for sub in subs if isinstance(subs, list) else []:
        dropped = sub.get("evidence_dropped") if isinstance(sub, dict) else None
        total += dropped if isinstance(dropped, int) else 0
    return total


def _items(output: dict[str, JSON]) -> list[dict[str, JSON]]:
    items = output.get(ITEMS_KEY)
    return [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []


def _proxy_requests(record: dict[str, JSON]) -> int:
    attempts = record.get("attempts")
    total = 0
    for attempt in attempts if isinstance(attempts, list) else []:
        usage = attempt.get("proxy_usage") if isinstance(attempt, dict) else None
        count = usage.get("request_count") if isinstance(usage, dict) else None
        total += count if isinstance(count, int) else 0
    return total


def _loop_totals(record: dict[str, JSON]) -> tuple[int, int, Decimal]:
    """우리 루프의 토큰·비용. 비용은 프록시가 요청마다 센 값이다(청구에 가장 가깝다, #1259). 루프가 센 비용은 합계 usage 에
    단가를 곱한 근사라(`selfloop_scoring.LOOP_COST_BASIS`) 프록시 기록이 없을 때만 쓴다. 토큰은 큰 쪽."""

    loop = _loop(record)
    usage = loop.get("usage") if isinstance(loop.get("usage"), dict) else {}
    tokens_in = int(usage.get("input_tokens") or 0)  # type: ignore[union-attr, arg-type]  # 기록 JSON
    tokens_out = int(usage.get("output_tokens") or 0)  # type: ignore[union-attr, arg-type]  # 기록 JSON
    loop_cost = Decimal(str(loop.get("cost_usd") or 0))
    proxy_in, proxy_out, proxy_cost = _proxy_totals(record)
    cost = proxy_cost if _proxy_requests(record) > 0 else loop_cost
    return max(tokens_in, proxy_in), max(tokens_out, proxy_out), cost


def _proxy_stop(record: dict[str, JSON]) -> str | None:
    """우리 루프가 프록시 거절로 멈췄는가 — 실행 토큰 거절(401·403)이나 하루 상한 429. 실행 예산(`run_budget`) 429 는
    방식이 예산 안에 못 끝낸 것이라 여기 들지 않는다."""

    loop = _loop(record)
    stopped = loop.get("stopped")
    detail = str(loop.get("stop_detail") or "")
    if stopped == "proxy_refused" or (stopped == "budget" and "daily_limit" in detail):
        return f"실행 도중 프록시가 멈췄다({stopped}): {detail[:300]}"
    return None


def _run_self_loop(submission: ContestSubmission, row: Row, inputs: _Inputs) -> CellResult:
    assert inputs.snapshot is not None
    try:
        outcome = run_selfloop_scoring(
            submission, inputs.requirements, inputs.snapshot, vendor=row.vendor, model=row.model, purpose="experiment",
            budget_usd=cell_budget_usd(row),
        )
    except AgentRunHeld as held:
        stopped = _proxy_stop(held.record)
        if stopped is not None:
            return CellResult(INFRA, problem=stopped)
        tokens_in, tokens_out, spent = _loop_totals(held.record)
        return CellResult(
            "held", problem="; ".join(held.reasons), evidence_offered=_dropped(held.record), input_tokens=tokens_in,
            output_tokens=tokens_out, cost_usd=spent, model_version=f"agent:selfloop:{row.model}", record=held.record,
        )
    verdicts, score = _verdict_rows(inputs.requirements, _items(outcome.structured_output))
    offered, real = count_real_evidence(inputs.snapshot, verdicts)
    tokens_in, tokens_out, spent = _loop_totals(outcome.record)
    return CellResult(
        "scored", score=score, verdicts=verdicts, evidence_offered=offered + _dropped(outcome.record),
        evidence_real=real, input_tokens=tokens_in, output_tokens=tokens_out, cost_usd=spent,
        model_version=outcome.model_version, record=outcome.record,
    )


_RUNNERS = {"single_call": _run_single_call, "agent": _run_agent, "self_loop": _run_self_loop}


@dataclass(frozen=True)
class InfraFailure:
    """결과로 남기지 않은 칸 — 같은 인자로 다시 부르면 다시 돈다."""

    problem: str


def run_cell(
    experiment: ScoringExperiment, submission: ContestSubmission, row: Row, round_no: int, inputs: _Inputs | Exception
) -> ScoringExperimentRun | InfraFailure:
    """칸 하나를 돌려 남긴다. 방식의 실패(틀린 꼴·시간 초과 등)도 칸으로 남긴다(다시 돌리지 않는다 — 실패율이 보고표의
    숫자다). 인프라 실패(`infra_errors()`·프록시 거절)는 남기지 않고 `InfraFailure` 를 돌려준다. #1257 전에 인프라 실패로
    남은 칸 자리면 그 행을 이번 결과로 바꾼다."""

    started = time.monotonic()
    if isinstance(inputs, Exception):
        result = CellResult("failed", problem=f"입력을 다시 받지 못했다: {inputs}")
    elif row.method != "single_call" and inputs.snapshot is None:
        result = CellResult("failed", problem="채점 입력이 하나가 아니라 에이전트가 읽을 박제본이 없다(운영이면 한 번 호출)")
    else:
        try:
            result = _RUNNERS[row.method](submission, row, inputs)
        except infra_errors() as exc:
            result = CellResult(INFRA, problem=f"{type(exc).__name__}: {exc}"[:2000])
        except Exception as exc:  # noqa: BLE001 - 칸 하나의 실패가 실험 전체를 멈추지 않는다
            logger.warning("실험 %s 칸(제출 %s, %s, %s) 실패: %r", experiment.name, submission.pk, row.name, round_no, exc)
            result = CellResult("failed", problem=f"{type(exc).__name__}: {exc}"[:2000])
    if result.status == INFRA:
        logger.warning("실험 %s 칸(제출 %s, %s, %s) 인프라 실패: %s", experiment.name, submission.pk, row.name, round_no, result.problem)
        return InfraFailure(result.problem)
    run, _created = ScoringExperimentRun.objects.update_or_create(
        experiment=experiment,
        submission=submission,
        row=row.name,
        round=round_no,
        defaults=_run_fields(result, started),
    )
    return run


def _run_fields(result: CellResult, started: float) -> dict[str, object]:
    return dict(
        status=result.status,
        score=result.score,
        verdicts=result.verdicts,
        evidence_offered=result.evidence_offered,
        evidence_real=result.evidence_real,
        evidence_all_real=result.evidence_offered > 0 and result.evidence_real == result.evidence_offered,
        problem=result.problem,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        cost_usd=result.cost_usd,
        duration_seconds=round(time.monotonic() - started, 3),
        model_version=result.model_version,
        record=result.record,
        created_at=Clock.now(),
    )


# ── 계획 ──────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class RowPlan:
    row: Row
    pending: int  # 남은 칸
    done: int
    low_usd: Decimal  # 남은 칸 전체의 비용 범위
    high_usd: Decimal
    per_run_high_usd: Decimal  # 칸당 최대 — 칸을 시작하기 전에 남은 돈과 견준다(`per_cell_max`)


@dataclass(frozen=True)
class Plan:
    submissions: list[ContestSubmission]
    cells: list[tuple[ContestSubmission, Row, int]]  # 남은 칸, 회차 → 제출 → 줄 순(상한에 멈춰도 줄끼리 고르게)
    rows: list[RowPlan]
    daily_limit_usd: Decimal
    spent_today_usd: Decimal

    @property
    def remaining_usd(self) -> Decimal:
        return max(self.daily_limit_usd - self.spent_today_usd, Decimal(0))


def plan(
    contest: Contest,
    rows: list[Row],
    *,
    repeat: int,
    limit: int | None,
    experiment: ScoringExperiment | None,
    pick: Pick = "id",
) -> Plan:
    submissions = eligible_submissions(contest, limit, pick)
    done: set[tuple[int, str, int]] = set()
    observed: dict[str, list[Decimal]] = {}
    if experiment is not None:
        for run in experiment.runs.all().only("submission_id", "row", "round", "cost_usd", "status", "problem"):
            if is_infra_failure(run.status, run.problem):
                continue  # 끝난 칸이 아니다 — 다시 돈다
            done.add((run.submission_id, run.row, run.round))
            if run.status != ScoringExperimentRun.Status.FAILED:
                observed.setdefault(run.row, []).append(run.cost_usd)
    cells = [
        (s, row, rnd)
        for rnd in range(1, repeat + 1)
        for s in submissions
        for row in rows
        if (s.pk, row.name, rnd) not in done
    ]
    row_plans = []
    for row in rows:
        pending = sum(1 for _s, r, _n in cells if r == row)
        seen = observed.get(row.name, ())
        low, high = cost_range(row, seen)
        row_plans.append(
            RowPlan(row, pending, len(submissions) * repeat - pending, low * pending, high * pending, per_cell_max(row, seen))
        )
    return Plan(submissions, cells, row_plans, agent_experiment_daily_limit_usd(), spent_today_experiment_usd())
