"""채점 비용 계산기 — 프로바이더 × 채점 방식 × 모델 × 체크리스트 × 소스 크기를 골라 제출 한 건 예상을 본다
(#1270, CONTEXT.md 「예상 채점 비용」).

클래스 설정 「채점 방식」 자리와 연결된 앱(`get_problem`)이 이 셈 하나를 읽는다. 단가는 `scoring_cost.PRICES`
한 곳에서 오고, 이 모듈은 숫자를 따로 적지 않는다.

**한 번 호출**은 `scoring_cost.attempt_cost` 를 그대로 쓰되 입력·출력을 연다 — 입력은 소스 크기 + 그 문제의
지시문·체크리스트(`classroom.scoring._build_prompt` 가 소스 없이 만드는 글자 수), 출력은 요구사항 수 ×
`OUTPUT_TOKENS_PER_REQUIREMENT`(추론하는 모델이면 강도별 추론 몫을 더한다). 소스 크기는 그 문제의 지난 한 번 호출
프롬프트에서 지시문 몫을 뺀 실측의 중앙·p90 이고, 실측이 `MIN_SAMPLE_COUNT` 건 미만이면 `SOURCE_SIZE_BANDS` 단계다.

**에이전트**는 한 숫자를 내지 않는다 — 그 클래스·그 모델의 지난 에이전트 채점 실행(클래스 키,
`ClassroomAgentRun.record` 의 시도별 `proxy_usage.spent_usd`·`duration_seconds` 합)의 중앙·p90 이다. 실행이
`MIN_SAMPLE_COUNT` 건 미만이면 「실측 없음」(`None`)이다. 플랫폼 평균·실험 값은 넣지 않는다.

**시간**: 한 번 호출 채점은 걸린 시간을 남기지 않는다 — 그래서 늘 「실측 없음」이다. 지어내지 않는다.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from core.agent_scoring import JSON
from core.model_context import source_budget_bytes

from . import scoring_cost
from .agent_grading import AGENT_VERIFIED_VENDORS
from .models import ANTHROPIC_KEY_FIELDS, OPENAI_KEY_FIELDS, Class, ClassroomAgentRun, ClassroomScore, ClassroomSubmission, Problem
from .scoring_models import is_claude_model_id

Vendor = Literal["openai", "anthropic"]
Method = Literal["single", "agent"]
SourceKey = Literal["median", "p90", "small", "medium", "large"]

VENDORS: tuple[Vendor, ...] = ("openai", "anthropic")

#: 판정 JSON 의 요구사항 하나 몫(id·판정·근거 한두 문장) — `NON_REASONING_OUTPUT_TOKENS`(2,500)를 「체크리스트
#: 수십 항목」 25개로 나눈 값이다. 추론 모델은 여기에 강도별 추론 몫(`REASONING_OUTPUT_TOKENS` − 2,500)을 더한다.
OUTPUT_TOKENS_PER_REQUIREMENT = scoring_cost.NON_REASONING_OUTPUT_TOKENS // 25

#: `SOURCE_SIZE_BANDS` 의 이름 — 작음·보통·큼.
BAND_KEYS: tuple[SourceKey, ...] = ("small", "medium", "large")

_AGENT_SAMPLE_LIMIT = 500


def vendor_of_model(model_id: str) -> Vendor:
    return "anthropic" if is_claude_model_id(model_id) else "openai"


def models_for(vendor: Vendor) -> list[str]:
    """그 프로바이더의 단가표 모델 — 표 순서 그대로."""

    return [m for m in scoring_cost.PRICES if vendor_of_model(m) == vendor]


@dataclass(frozen=True)
class SourceOption:
    key: SourceKey
    chars: int
    #: 그 문제의 실측(중앙·p90)인가 — 아니면 크기 단계.
    measured: bool


@dataclass(frozen=True)
class ProblemOption:
    id: int
    title: str
    requirement_count: int
    #: 소스를 뺀 프롬프트(지시문·채점 지침·체크리스트)의 글자 수.
    instruction_chars: int
    #: 실측 소스 크기에 쓴 한 번 호출 시도 수.
    sample_count: int
    sources: tuple[SourceOption, ...]


@dataclass(frozen=True)
class ProviderOption:
    vendor: Vendor
    has_key: bool
    models: tuple[str, ...]


@dataclass(frozen=True)
class Spread:
    """실측의 중앙·p90 — 표본이 `MIN_SAMPLE_COUNT` 건 미만이면 값은 `None`(「실측 없음」)."""

    sample_count: int
    median: float | None
    p90: float | None


@dataclass(frozen=True)
class SingleCall:
    input_tokens: int
    output_tokens: int
    usd: float
    open_ended: bool
    #: 소스가 모델 컨텍스트에 다 들어가는가 — 아니면 채점이 「크기 초과」 보류다(#989).
    fits: bool
    #: 걸린 시간 실측 — 한 번 호출은 남기지 않아 늘 「실측 없음」.
    seconds: Spread


@dataclass(frozen=True)
class Agent:
    #: 이 프로바이더로 에이전트를 고를 수 있는가(`AGENT_VERIFIED_VENDORS`).
    available: bool
    usd: Spread
    seconds: Spread


@dataclass(frozen=True)
class Selection:
    vendor: Vendor
    method: Method
    model_id: str
    reasoning_effort: str | None
    problem_id: int | None
    source: SourceKey
    source_chars: int


@dataclass(frozen=True)
class Calculation:
    providers: tuple[ProviderOption, ...]
    agent_vendors: tuple[Vendor, ...]
    problems: tuple[ProblemOption, ...]
    selection: Selection
    single: SingleCall
    agent: Agent


def percentile_spread(values: list[float]) -> Spread:
    """중앙값과 p90(가장 가까운 순위) — 표본이 모자라면 둘 다 `None`."""

    n = len(values)
    if n < scoring_cost.MIN_SAMPLE_COUNT:
        return Spread(sample_count=n, median=None, p90=None)
    ordered = sorted(values)
    return Spread(sample_count=n, median=statistics.median(ordered), p90=ordered[math.ceil(0.9 * n) - 1])


def _instruction_chars(problem: Problem) -> int:
    # `scoring` 이 이 모듈 쪽 `scoring_cost` 를 들여오므로 여기서만 늦게 들여온다.
    from .scoring import _build_prompt
    from .syntax_check import SyntaxCheckPass

    prompt = _build_prompt(
        ClassroomSubmission(problem=problem),
        list(problem.checklist_items.all()),
        "",
        asset_kind="source",
        syntax_check=SyntaxCheckPass(resolved={}),
    )
    return len(prompt)


def _problem_option(problem: Problem) -> ProblemOption:
    instruction = _instruction_chars(problem)
    prompts = (
        ClassroomScore.objects.filter(submission__problem=problem)
        .exclude(model_version__startswith="platform-auto")
        .exclude(model_version__startswith="agent:")
        .values_list("prompt", flat=True)
    )
    sizes = [max(len(p) - instruction, 0) for p in prompts]
    spread = percentile_spread([float(s) for s in sizes])
    if spread.median is not None and spread.p90 is not None:
        sources: tuple[SourceOption, ...] = (
            SourceOption("median", round(spread.median), True),
            SourceOption("p90", round(spread.p90), True),
        )
    else:
        sources = tuple(SourceOption(k, c, False) for k, c in zip(BAND_KEYS, scoring_cost.SOURCE_SIZE_BANDS))
    return ProblemOption(
        id=problem.pk,
        title=problem.title,
        requirement_count=problem.checklist_items.count(),
        instruction_chars=instruction,
        sample_count=spread.sample_count,
        sources=sources,
    )


def _has_key(class_obj: Class, vendor: Vendor) -> bool:
    fields = OPENAI_KEY_FIELDS if vendor == "openai" else ANTHROPIC_KEY_FIELDS
    return bool((getattr(class_obj, fields.encrypted) or "").strip())


def _as_vendor(value: str | None) -> Vendor | None:
    if value == "openai":
        return "openai"
    if value == "anthropic":
        return "anthropic"
    return None


def _as_method(value: str | None) -> Method | None:
    if value == "single":
        return "single"
    if value == "agent":
        return "agent"
    return None


def _current_vendor(class_obj: Class) -> Vendor:
    return "anthropic" if class_obj.scoring_connection_kind == Class.ScoringConnectionKind.ANTHROPIC_KEY else "openai"


def single_call(
    model_id: str,
    reasoning_effort: str | None,
    *,
    source_chars: int,
    instruction_chars: int,
    requirement_count: int,
) -> SingleCall:
    effort = scoring_cost.effort_for(model_id, reasoning_effort)
    output_tokens = requirement_count * OUTPUT_TOKENS_PER_REQUIREMENT
    if effort is not None:
        output_tokens += scoring_cost.REASONING_OUTPUT_TOKENS[effort] - scoring_cost.NON_REASONING_OUTPUT_TOKENS
    cost = scoring_cost.attempt_cost(
        model_id, reasoning_effort, prompt_chars=source_chars + instruction_chars, output_tokens=output_tokens
    )
    if cost is None:  # pragma: no cover - 모델 목록이 단가표에서 온다.
        raise ValueError(f"단가표에 없는 모델: {model_id}")
    return SingleCall(
        input_tokens=cost.input_tokens,
        output_tokens=cost.output_tokens,
        usd=cost.usd,
        open_ended=cost.open_ended,
        fits=source_chars <= source_budget_bytes(model_id, instruction_bytes=instruction_chars),
        seconds=Spread(sample_count=0, median=None, p90=None),
    )


def _attempt_number(attempt: JSON, key: str) -> float | None:
    if not isinstance(attempt, dict):
        return None
    value = attempt.get(key)
    if key == "spent_usd":
        usage = attempt.get("proxy_usage")
        value = usage.get("spent_usd") if isinstance(usage, dict) else None
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def agent_runs(class_obj: Class, model_id: str) -> tuple[Spread, Spread]:
    """(건당 USD, 건당 초) — 이 클래스 키로 이 모델이 돈 에이전트 채점 실행의 실측."""

    model = scoring_cost.canonical_model_id(model_id)
    records = (
        ClassroomAgentRun.objects.filter(submission__problem__classroom=class_obj, purpose="scoring")
        .order_by("-created_at")
        .values_list("record", flat=True)[:_AGENT_SAMPLE_LIMIT]
    )
    costs: list[float] = []
    seconds: list[float] = []
    for record in records:
        if not isinstance(record, dict) or record.get("key_source") != "class":
            continue
        if scoring_cost.canonical_model_id(str(record.get("model") or "")) != model:
            continue
        attempts = record.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            continue
        spent = [_attempt_number(a, "spent_usd") for a in attempts]
        if all(s is not None for s in spent):
            costs.append(sum(s for s in spent if s is not None))
        took = [_attempt_number(a, "duration_seconds") for a in attempts]
        if all(t is not None for t in took):
            seconds.append(sum(t for t in took if t is not None))
    return percentile_spread(costs), percentile_spread(seconds)


def calculate(
    class_obj: Class,
    *,
    vendor: str | None = None,
    method: str | None = None,
    model_id: str | None = None,
    problem_id: int | None = None,
    source: str | None = None,
) -> Calculation:
    """고른 값으로 셈한다 — 비거나 고를 수 없는 값은 지금 이 클래스의 조합(없으면 첫 선택지)으로 채운다."""

    providers = tuple(ProviderOption(v, _has_key(class_obj, v), tuple(models_for(v))) for v in VENDORS)
    chosen_vendor = _as_vendor(vendor) or _current_vendor(class_obj)
    vendor_models = models_for(chosen_vendor)
    if model_id not in vendor_models:
        model_id = class_obj.default_model if class_obj.default_model in vendor_models else vendor_models[0]
    agent_ok = chosen_vendor in AGENT_VERIFIED_VENDORS
    chosen_method = _as_method(method) or _as_method(class_obj.scoring_method) or "single"
    if chosen_method == "agent" and not agent_ok:
        chosen_method = "single"

    problems = tuple(_problem_option(p) for p in class_obj.problems.all())
    problem = next((p for p in problems if p.id == problem_id), problems[0] if problems else None)
    if problem is not None:
        sources = problem.sources
        instruction, requirements = problem.instruction_chars, problem.requirement_count
    else:
        sources = tuple(SourceOption(k, c, False) for k, c in zip(BAND_KEYS, scoring_cost.SOURCE_SIZE_BANDS))
        instruction, requirements = 0, 0
    picked = next((s for s in sources if s.key == source), sources[0] if sources[0].measured else sources[1])

    effort = scoring_cost.effort_for(model_id, class_obj.default_reasoning_effort or None)
    agent_usd, agent_seconds = agent_runs(class_obj, model_id) if agent_ok else (
        Spread(0, None, None),
        Spread(0, None, None),
    )
    return Calculation(
        providers=providers,
        agent_vendors=tuple(v for v in VENDORS if v in AGENT_VERIFIED_VENDORS),
        problems=problems,
        selection=Selection(
            vendor=chosen_vendor,
            method=chosen_method,
            model_id=model_id,
            reasoning_effort=effort,
            problem_id=problem.id if problem is not None else None,
            source=picked.key,
            source_chars=picked.chars,
        ),
        single=single_call(
            model_id,
            effort,
            source_chars=picked.chars,
            instruction_chars=instruction,
            requirement_count=requirements,
        ),
        agent=Agent(available=agent_ok, usd=agent_usd, seconds=agent_seconds),
    )
