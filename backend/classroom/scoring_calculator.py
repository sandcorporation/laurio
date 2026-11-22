"""채점 비용 계산기 — 프로바이더 × 채점 방식 × 모델 **예상표**(#1270·#1304, CONTEXT.md 「예상 채점 비용」).

예상은 단가표(`scoring_cost.PRICES`) × **가정**이다 — 빈 클래스(문제·체크리스트·제출 0)에서도 모든 칸에 금액이 있다.
실측은 있으면 **옆에 덧붙이고** 예상을 지우거나 대신하지 않는다. 가정은 코드 기본값(아래 상수, 출처를 단다)이고 화면이
라벨·값으로 보이며 강사가 바꿔 볼 수 있다(저장하지 않는다). 그 클래스에 문제가 있으면 그 문제의 요구사항 수·지시문
길이·소스 크기 실측이 기본값을 대신한다. #617 의 「플랫폼 평균은 쓰지 않는다」는 **실측 칸**에만 남는다 — 실측은 그
클래스·그 모델의 지난 실행만 본다.

단가는 `scoring_cost.PRICES` 한 곳에서 오고, 이 모듈은 단가를 따로 적지 않는다. 연결된 앱(`get_class`·`get_problem`)도
이 셈 하나를 읽는다.

**한 번 호출**은 `scoring_cost.attempt_cost` 를 그대로 쓰되 입력·출력을 연다 — 입력은 소스 크기 + 지시문(문제가 있으면
`classroom.scoring._build_prompt` 가 소스 없이 만드는 글자 수, 없으면 `INSTRUCTION_*` 상수), 출력은 요구사항 수 ×
`OUTPUT_TOKENS_PER_REQUIREMENT`(추론하는 모델이면 강도별 추론 몫을 더한다). **감당 크기**는 채점이 실제로 쓰는
`core.model_context.source_budget_bytes` 를 그대로 부른 값이다(바이트 → 글자는 `BYTES_PER_CHAR`). 소스가 그것을 넘으면
자르지 않고 「크기 초과」 보류다(#989) — 채점하지 않으니 금액은 0 이다. 새 채점기(staged, 2026-11-22 부터 꺼짐
고정 — `classroom_scoring_pipeline`)가 켜져 있으면 「한 번 호출」 칸이 **실제로 돌 갈래의 셈**을 쓴다 — 두 걸음 문턱을 넘거나 모델
예산에 다 안 들어가면 두 걸음이고(1차 지시문만, 2차 소스는 상한까지), 기계 판정 몫은 출력 항목 수에서 뺀다.

**에이전트**는 프로바이더별 토큰 꼴(`AGENT_TOKENS`) × 그 모델 단가(`core.agent_run_tokens.usage_cost_usd`)다. 입력·캐시
몫은 가정 제출 크기에 비례해 늘린다. 실측(그 클래스 키로 돈 지난 실행의 `proxy_usage.spent_usd`·`duration_seconds` 합의
중앙·p90)은 `MIN_SAMPLE_COUNT` 건 이상일 때만 옆에 붙는다. 에이전트를 못 받는 프로바이더(`AGENT_VERIFIED_VENDORS` 밖)는
「지원 안 함」이다.

**의심 재판정**(#1291): 클래스가 고른 의심 재판정 모델의 단가로 **의심 한 건당** 예상 × 의심 비율(가정) × 항목 수다.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Literal

from core import agent_scoring
from core.agent_run_tokens import Usage, usage_cost_usd
from core.agent_scoring import JSON
from core.model_context import BYTES_PER_TOKEN, context_window_tokens, source_budget_bytes
from policies.runtime_settings import (
    CLASSROOM_PIPELINE_STAGED,
    classroom_scoring_pipeline,
    classroom_two_step_budget_chars,
    classroom_two_step_threshold_chars,
)

from . import scoring_cost
from .agent_grading import AGENT_VERIFIED_VENDORS
from .models import ANTHROPIC_KEY_FIELDS, OPENAI_KEY_FIELDS, Class, ClassroomAgentRun, ClassroomScore, ClassroomSubmission, Problem
from .scoring_models import is_claude_model_id

Vendor = Literal["openai", "anthropic"]
Method = Literal["single", "agent"]
SourceKey = Literal["median", "p90", "custom"]
#: 한 번 호출 칸이 실제로 가는 길 — single 한 번에 담김, two_step 두 걸음(staged), hold 담지 못해 「크기 초과」 보류.
Route = Literal["single", "two_step", "hold"]

VENDORS: tuple[Vendor, ...] = ("openai", "anthropic")

#: 판정 JSON 의 요구사항 하나 몫(id·판정·근거 한두 문장) — `NON_REASONING_OUTPUT_TOKENS`(2,500)를 「체크리스트
#: 수십 항목」 25개로 나눈 값이다. 추론 모델은 여기에 강도별 추론 몫(`REASONING_OUTPUT_TOKENS` − 2,500)을 더한다.
OUTPUT_TOKENS_PER_REQUIREMENT = scoring_cost.NON_REASONING_OUTPUT_TOKENS // 25

# --- 가정(코드 기본값) — 화면이 라벨·값으로 보이고 강사가 바꿔 볼 수 있다. 출처는 조율자가 운영 읽기 전용·work dev 실험에서
# 집계한 값이다(2026-11-22, #1304 본문 2·3절). 지어낸 값이 없다 --------------------------------------------------------

#: 제출 크기(프롬프트 글자) — 운영 강의실 채점 831건의 p50·p90(조율자 #5332).
ASSUMED_SOURCE_CHARS_MEDIAN = 32_000
ASSUMED_SOURCE_CHARS_P90 = 307_000
#: 체크리스트 항목 수 — 운영 문제 64개의 항목 수 p50(p90 은 21).
ASSUMED_REQUIREMENTS = 6
#: staged 에서 기계 판정(정적 검사)이 맡는 항목 몫 — 운영 실제 채점 가중 정적 몫 19%(조율자 #5332). 모델에게 묻는 항목에서 빠진다.
MACHINE_JUDGED_SHARE = 0.19

#: 소스 없는 지시문 글자 수 — `_build_prompt` 가 소스 없이 만드는 글자를 시험 고정 문제(항목 1·3·6·12개, 짧은 항목)로 쟀다
#: (2026-11-22: 1,287·1,363·1,478·1,719자 → 머리 약 1,250 + 항목당 약 40). 문제가 없는 클래스의 지시문 몫이다.
INSTRUCTION_BASE_CHARS = 1_250
INSTRUCTION_CHARS_PER_REQUIREMENT = 40

#: 바이트 ↔ 글자 — 실제 채점은 소스를 **바이트**로 자른다(`scoring._scoring_source_files`, `source_budget_bytes`).
#: 운영 제출 30건(truth30 가명 사본, `.git`·`node_modules` 뺀 UTF-8 파일)의 바이트/글자 p50 1.032, 최소 1.0, 최대 1.482,
#: 전체 합 1.006(조율자 2026-11-22). 코드 위주 제출은 바이트 ≈ 글자라 p50 을 쓴다. 감당 글자 = 감당 바이트 ÷ 이 값.
BYTES_PER_CHAR = 1.03

#: 소스 파일 하나의 평균 글자 수 — 화면이 글자 수를 개발자에게 익숙한 「파일 수」로도 보이는 데 쓴다(글자 ÷ 이 값, 반올림 어림).
#: 출처(2026-11-22 조율자 읽기 전용 집계): 운영 강의실 채점 789건(`classroom_classroomscore.prompt` 가운데 파일 머리가 있는 것)에서
#: 프롬프트의 소스 부분을 파일 머리(`# 경로.확장자`) 수로 나눈 파일당 글자 수 — 채점별 중앙 1,799·전체 합 2,502·평균 2,159, 파일 수 중앙 20·p90 109.
#: 머리 셈 보정: 실험 재료 30건(가명 사본)에 같은 셈을 하면 실제 파일 1,642개 중 1,448개만 잡혀(확장자 없는 파일 등) 12% 덜 센다 —
#: 1,799 × 0.88 ≈ 1,590 → 1,600. 표본이 큰 운영 채점의 채점별 중앙값을 쓴다(평균은 큰 제출 몇 건에 끌려간다).
SOURCE_CHARS_PER_FILE = 1_600

#: 글자당 바이트 최대 — 같은 30건의 최대 1.482(한글 주석 많음 제출). 화면의 「한글 주석 많음」 감당 글자 수만 이 값으로 셈하고,
#: 「보류」 판정은 `BYTES_PER_CHAR` 그대로다.
BYTES_PER_CHAR_MAX = 1.48

#: 한 번 호출 채점의 걸린 시간(초) — work dev 실험 `scoring_scoringexperimentrun.duration_seconds` p50. 「가정」이다.
ASSUMED_SINGLE_SECONDS = 5.0
#: 에이전트 한 건의 걸린 시간(초) 프로바이더별 — 같은 실험 p50(Claude 12.5, OpenAI 72.9 — gpt-5-mini 3건).
ASSUMED_AGENT_SECONDS: dict[str, float] = {"anthropic": 12.5, "openai": 72.9}

#: 에이전트 한 건의 토큰 꼴(p50) — work dev 실험 `core_agentruntoken`(가명 재료 clsexp-20261122, 작은 제출 위주).
#: Claude: claude-sonnet-5-5 94건 p50(haiku 97건은 23,122·3,258·3,557 로 비슷하다). OpenAI: gpt-5-mini 5건 p50 —
#: OpenAI 의 입력은 캐시 읽기를 포함한다(98,645 중 88,960). 모델이 달라도 꼴은 프로바이더별로 하나이고 그 모델의 단가를 곱한다.
AGENT_TOKENS: dict[str, Usage] = {
    "anthropic": Usage(input_tokens=6, output_tokens=1_442, cache_read_tokens=19_424, cache_write_tokens=2_736),
    "openai": Usage(input_tokens=98_645, output_tokens=3_606, cache_read_tokens=88_960, cache_write_tokens=0),
}
#: 위 재료의 한 번 호출 입력 토큰 p50 — 같은 재료 24건의 `single_call:gpt-4.1-mini`·`classroom_call:gpt-4.1-mini` 행
#: `input_tokens` 를 재료별 중앙으로 모은 뒤의 p50(최소 1,240, 최대 113,632, 지시문 포함 프롬프트 전체). 가정 제출이 이 재료보다
#: 몇 배 큰지를 재는 기준이고, 그 배수를 에이전트 토큰 꼴의 입력·캐시 몫에 곱한다(출력 몫은 그대로).
REFERENCE_PROMPT_TOKENS = 2_667

#: 강의실 에이전트 채점의 상한 — 숫자는 실행기와 같다. 실행 시간·시도·예산은 `core.agent_scoring`, 올린 zip 크기·풀린 크기·
#: 파일 수는 실행기 실행기 모듈(별도 서비스라 여기서 들여오지 않는다 — 시험이 같은 값인지 못 박는다).
AGENT_MAX_ZIP_BYTES = 100 * 1024 * 1024
AGENT_MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
AGENT_MAX_ZIP_ENTRIES = 50_000

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
    #: 그 문제의 실측(중앙·p90)인가 — 아니면 가정(운영 p50·p90).
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
    """실측의 중앙·p90 — 표본이 `MIN_SAMPLE_COUNT` 건 미만이면 값은 `None`(실측 줄이 없다)."""

    sample_count: int
    median: float | None
    p90: float | None


@dataclass(frozen=True)
class SingleCall:
    input_tokens: int
    output_tokens: int
    #: 이 칸의 예상(USD) — 「크기 초과」 보류면 채점하지 않으니 0 이다.
    usd: float
    open_ended: bool
    #: 소스가 모델 컨텍스트에 다 들어가는가 — 아니면 staged 가 아닐 때 채점이 「크기 초과」 보류다(#989).
    fits: bool
    #: 한 번 호출에 담을 수 있는 소스 글자 수 — `source_budget_bytes` 를 `BYTES_PER_CHAR` 로 나눈 값.
    capacity_chars: int
    #: 글자당 바이트를 `BYTES_PER_CHAR_MAX` 로 셈한 감당 글자 수(한글 주석 많음 소스).
    capacity_chars_hangul: int
    #: 감당 글자 수를 파일 수로 — `files_of_chars`.
    capacity_files: int
    capacity_files_hangul: int
    route: Route
    #: 가정한 걸린 시간(초).
    seconds: float


@dataclass(frozen=True)
class Agent:
    #: 이 프로바이더로 에이전트를 고를 수 있는가(`AGENT_VERIFIED_VENDORS`) — 아니면 「지원 안 함」.
    available: bool
    #: 가정 토큰 꼴 × 그 모델 단가 — 못 받는 프로바이더만 `None`.
    usd: float | None
    #: 가정한 걸린 시간(초).
    seconds: float | None
    #: 그 클래스·그 모델의 지난 실행 실측 — `MIN_SAMPLE_COUNT` 건 미만이면 값이 `None`.
    measured_usd: Spread
    measured_seconds: Spread


@dataclass(frozen=True)
class ModelRow:
    vendor: Vendor
    model_id: str
    context_tokens: int
    single: SingleCall
    agent: Agent


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
class Assumptions:
    """셈에 쓴 가정 — 값과 어디서 왔는지(`*_from`: `problem`·`assumed`·`custom`). 기본값은 `defaults` 에 따로 있다."""

    source_chars: int
    requirements: int
    instruction_chars: int
    requirements_from: Literal["problem", "assumed", "custom"]
    source_from: Literal["problem", "assumed", "custom"]


@dataclass(frozen=True)
class Overrides:
    """강사가 바꿔 본 가정 — 비어 있으면 기본값(또는 그 문제의 값)이다. 저장하지 않는다."""

    source_chars: int | None = None
    requirements: int | None = None


@dataclass(frozen=True)
class AgentLimits:
    max_zip_bytes: int
    max_extracted_bytes: int
    max_zip_entries: int
    attempt_seconds: int
    attempts: int
    budget_usd: float


@dataclass(frozen=True)
class Calculation:
    providers: tuple[ProviderOption, ...]
    agent_vendors: tuple[Vendor, ...]
    problems: tuple[ProblemOption, ...]
    selection: Selection
    assumptions: Assumptions
    rows: tuple[ModelRow, ...]
    staged: bool
    two_step_threshold_chars: int
    two_step_budget_chars: int
    agent_limits: AgentLimits

    @property
    def selected(self) -> ModelRow:
        return next(r for r in self.rows if r.model_id == self.selection.model_id)

    @property
    def selected_usd(self) -> float:
        """고른 칸의 제출 한 건 예상(USD) — 에이전트를 못 받으면 한 번 호출로 돌아와 있다."""

        row = self.selected
        if self.selection.method == "agent" and row.agent.usd is not None:
            return row.agent.usd
        return row.single.usd


def percentile_spread(values: list[float]) -> Spread:
    """중앙값과 p90(가장 가까운 순위) — 표본이 모자라면 둘 다 `None`."""

    n = len(values)
    if n < scoring_cost.MIN_SAMPLE_COUNT:
        return Spread(sample_count=n, median=None, p90=None)
    ordered = sorted(values)
    return Spread(sample_count=n, median=statistics.median(ordered), p90=ordered[math.ceil(0.9 * n) - 1])


def assumed_instruction_chars(requirements: int) -> int:
    return INSTRUCTION_BASE_CHARS + requirements * INSTRUCTION_CHARS_PER_REQUIREMENT


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


def _assumed_sources() -> tuple[SourceOption, ...]:
    return (
        SourceOption("median", ASSUMED_SOURCE_CHARS_MEDIAN, False),
        SourceOption("p90", ASSUMED_SOURCE_CHARS_P90, False),
    )


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
        sources = _assumed_sources()
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


def capacity_chars(model_id: str, *, instruction_chars: int) -> int:
    """한 번 호출에 담을 수 있는 소스 글자 수 — 채점이 쓰는 `source_budget_bytes` 한 함수에서 나온 바이트를 글자로."""

    return int(source_budget_bytes(model_id, instruction_bytes=instruction_chars) // BYTES_PER_CHAR)


def capacity_chars_hangul(model_id: str, *, instruction_chars: int) -> int:
    """`capacity_chars` 와 같은 바이트 예산을 글자당 바이트 최대로 나눈 값 — 한글 주석 많음 소스가 담기는 글자 수."""

    return int(source_budget_bytes(model_id, instruction_bytes=instruction_chars) // BYTES_PER_CHAR_MAX)


def files_of_chars(chars: int) -> int:
    """글자 수를 소스 파일 수로 — `SOURCE_CHARS_PER_FILE` 로 나눠 반올림한 어림."""

    return round(chars / SOURCE_CHARS_PER_FILE)


def fits_source_bytes(model_id: str, *, source_bytes: int, instruction_chars: int) -> bool:
    """소스가 `source_bytes` 바이트일 때 한 번 호출에 다 들어가는가 — 채점의 「크기 초과」 보류 판정과 같은 예산이다."""

    return source_bytes <= source_budget_bytes(model_id, instruction_bytes=instruction_chars)


def single_call(
    model_id: str,
    reasoning_effort: str | None,
    *,
    source_chars: int,
    instruction_chars: int,
    requirement_count: int,
    staged: bool = False,
    two_step_threshold_chars: int = 0,
    two_step_budget_chars: int = 0,
) -> SingleCall:
    """한 번 호출 칸. `staged` 면 실제로 돌 갈래의 셈이다 — 두 걸음 문턱(`two_step_threshold_chars`, 0 이면 끔)을
    넘거나 모델 예산에 다 안 들어가면 1차(지시문만, 파일 목록 몫은 어림하지 않는다) + 2차(소스는 상한까지) 두 번 부르고,
    기계 판정 몫(`MACHINE_JUDGED_SHARE`)은 출력 항목 수에서 뺀다."""

    effort = scoring_cost.effort_for(model_id, reasoning_effort)
    asked = requirement_count
    if staged:
        asked = max(1, round(requirement_count * (1 - MACHINE_JUDGED_SHARE))) if requirement_count else 0
    output_tokens = asked * OUTPUT_TOKENS_PER_REQUIREMENT
    if effort is not None:
        output_tokens += scoring_cost.REASONING_OUTPUT_TOKENS[effort] - scoring_cost.NON_REASONING_OUTPUT_TOKENS
    capacity = capacity_chars(model_id, instruction_chars=instruction_chars)
    hangul = capacity_chars_hangul(model_id, instruction_chars=instruction_chars)
    fits = fits_source_bytes(model_id, source_bytes=source_chars * BYTES_PER_CHAR, instruction_chars=instruction_chars)
    two_step = staged and two_step_threshold_chars > 0 and (source_chars > two_step_threshold_chars or not fits)
    route: Route = "two_step" if two_step else ("single" if fits else "hold")
    seconds = ASSUMED_SINGLE_SECONDS * (2 if two_step else 1)

    if route == "hold":
        cost = scoring_cost.attempt_cost(model_id, reasoning_effort, prompt_chars=0, output_tokens=0)
        if cost is None:  # pragma: no cover - 모델 목록이 단가표에서 온다.
            raise ValueError(f"단가표에 없는 모델: {model_id}")
        hangul = capacity_chars_hangul(model_id, instruction_chars=instruction_chars)
        return SingleCall(
            0, 0, 0.0, cost.open_ended, fits, capacity, hangul, files_of_chars(capacity), files_of_chars(hangul), route, 0.0
        )
    prompt_chars = instruction_chars + (min(source_chars, two_step_budget_chars) if two_step else source_chars)
    cost = scoring_cost.attempt_cost(model_id, reasoning_effort, prompt_chars=prompt_chars, output_tokens=output_tokens)
    if cost is None:  # pragma: no cover - 모델 목록이 단가표에서 온다.
        raise ValueError(f"단가표에 없는 모델: {model_id}")
    input_tokens, usd = cost.input_tokens, cost.usd
    if two_step:
        first = scoring_cost.attempt_cost(
            model_id, reasoning_effort, prompt_chars=instruction_chars, output_tokens=output_tokens
        )
        if first is not None:
            input_tokens += first.input_tokens
            usd += first.usd
    return SingleCall(
        input_tokens=input_tokens,
        output_tokens=cost.output_tokens * (2 if two_step else 1),
        usd=usd,
        open_ended=cost.open_ended,
        fits=fits,
        capacity_chars=capacity,
        capacity_chars_hangul=hangul,
        capacity_files=files_of_chars(capacity),
        capacity_files_hangul=files_of_chars(hangul),
        route=route,
        seconds=seconds,
    )


def agent_estimate(vendor: Vendor, model_id: str, *, source_chars: int, instruction_chars: int) -> tuple[float, float]:
    """(건당 USD, 초) 가정 — 프로바이더별 토큰 꼴(`AGENT_TOKENS`) × 그 모델 단가. 입력·캐시 몫은 가정 프롬프트(소스 바이트 ÷
    `BYTES_PER_TOKEN` + 지시문 토큰)가 실험 재료의 한 번 호출 입력 중앙(`REFERENCE_PROMPT_TOKENS`)의 몇 배인지로 늘린다."""

    prompt_tokens = source_chars * BYTES_PER_CHAR / BYTES_PER_TOKEN + scoring_cost.tokens_for_chars(instruction_chars)
    ratio = prompt_tokens / REFERENCE_PROMPT_TOKENS
    base = AGENT_TOKENS[vendor]
    usage = Usage(
        input_tokens=round(base.input_tokens * ratio),
        output_tokens=base.output_tokens,
        cache_read_tokens=round(base.cache_read_tokens * ratio),
        cache_write_tokens=round(base.cache_write_tokens * ratio),
    )
    # 에이전트 한 건은 요청이 여럿이다 — 합계에 긴 프롬프트 할증 문턱을 걸지 않는다(#1259).
    return float(usage_cost_usd(vendor, model_id, usage, long_context=False)), ASSUMED_AGENT_SECONDS[vendor]


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


def agent_runs_by_model(class_obj: Class) -> dict[str, tuple[Spread, Spread]]:
    """모델(정식 이름)별 (건당 USD, 건당 초) 실측 — 이 클래스 키로 돈 지난 에이전트 채점 실행."""

    records = (
        ClassroomAgentRun.objects.filter(submission__problem__classroom=class_obj, purpose="scoring")
        .order_by("-created_at")
        .values_list("record", flat=True)[:_AGENT_SAMPLE_LIMIT]
    )
    costs: dict[str, list[float]] = {}
    seconds: dict[str, list[float]] = {}
    for record in records:
        if not isinstance(record, dict) or record.get("key_source") != "class":
            continue
        model = scoring_cost.canonical_model_id(str(record.get("model") or ""))
        attempts = record.get("attempts")
        if not isinstance(attempts, list) or not attempts:
            continue
        spent = [_attempt_number(a, "spent_usd") for a in attempts]
        if all(s is not None for s in spent):
            costs.setdefault(model, []).append(sum(s for s in spent if s is not None))
        took = [_attempt_number(a, "duration_seconds") for a in attempts]
        if all(t is not None for t in took):
            seconds.setdefault(model, []).append(sum(t for t in took if t is not None))
    return {m: (percentile_spread(costs.get(m, [])), percentile_spread(seconds.get(m, []))) for m in {*costs, *seconds}}


def agent_runs(class_obj: Class, model_id: str) -> tuple[Spread, Spread]:
    """(건당 USD, 건당 초) — 이 클래스 키로 이 모델이 돈 에이전트 채점 실행의 실측."""

    empty = (Spread(0, None, None), Spread(0, None, None))
    return agent_runs_by_model(class_obj).get(scoring_cost.canonical_model_id(model_id), empty)


def _agent_limits() -> AgentLimits:
    return AgentLimits(
        max_zip_bytes=AGENT_MAX_ZIP_BYTES,
        max_extracted_bytes=AGENT_MAX_EXTRACTED_BYTES,
        max_zip_entries=AGENT_MAX_ZIP_ENTRIES,
        attempt_seconds=agent_scoring.ATTEMPT_TIMEOUT_SECONDS,
        attempts=agent_scoring.MAX_ATTEMPTS,
        budget_usd=float(agent_scoring.RUN_BUDGET_USD),
    )


def calculate(
    class_obj: Class,
    *,
    vendor: str | None = None,
    method: str | None = None,
    model_id: str | None = None,
    problem_id: int | None = None,
    source: str | None = None,
    overrides: Overrides | None = None,
) -> Calculation:
    """예상표를 셈한다 — 비거나 고를 수 없는 값은 지금 이 클래스의 조합(없으면 첫 선택지)으로 채운다. `vendor`·`method`·
    `model_id` 는 표에서 고른 칸(상세 영역)이고, 표 자체는 단가표의 모든 모델 × 두 방식이다."""

    overrides = overrides or Overrides()
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
    sources = problem.sources if problem is not None else _assumed_sources()
    picked = next((s for s in sources if s.key == source), sources[0])
    source_chars, source_key = picked.chars, picked.key
    source_from: Literal["problem", "assumed", "custom"] = "problem" if picked.measured else "assumed"
    if overrides.source_chars is not None and overrides.source_chars > 0:
        source_chars, source_key, source_from = overrides.source_chars, "custom", "custom"

    if overrides.requirements is not None and overrides.requirements > 0:
        requirements = overrides.requirements
        instruction = assumed_instruction_chars(requirements)
        requirements_from: Literal["problem", "assumed", "custom"] = "custom"
    elif problem is not None and problem.requirement_count > 0:
        requirements, instruction, requirements_from = problem.requirement_count, problem.instruction_chars, "problem"
    else:
        requirements = ASSUMED_REQUIREMENTS
        instruction = assumed_instruction_chars(requirements)
        requirements_from = "assumed"
    assumptions = Assumptions(
        source_chars=source_chars,
        requirements=requirements,
        instruction_chars=instruction,
        requirements_from=requirements_from,
        source_from=source_from,
    )

    staged = classroom_scoring_pipeline() == CLASSROOM_PIPELINE_STAGED
    threshold, budget = classroom_two_step_threshold_chars(), classroom_two_step_budget_chars()
    measured = agent_runs_by_model(class_obj)
    empty = Spread(0, None, None)
    rows: list[ModelRow] = []
    for row_vendor in VENDORS:
        for row_model in models_for(row_vendor):
            effort = scoring_cost.effort_for(row_model, class_obj.default_reasoning_effort or None)
            single = single_call(
                row_model,
                effort,
                source_chars=source_chars,
                instruction_chars=instruction,
                requirement_count=requirements,
                staged=staged,
                two_step_threshold_chars=threshold,
                two_step_budget_chars=budget,
            )
            if row_vendor in AGENT_VERIFIED_VENDORS:
                usd, seconds = agent_estimate(row_vendor, row_model, source_chars=source_chars, instruction_chars=instruction)
                run_usd, run_seconds = measured.get(scoring_cost.canonical_model_id(row_model), (empty, empty))
                agent = Agent(True, usd, seconds, run_usd, run_seconds)
            else:
                agent = Agent(False, None, None, empty, empty)
            rows.append(ModelRow(row_vendor, row_model, context_window_tokens(row_model), single, agent))

    selected_effort = scoring_cost.effort_for(model_id, class_obj.default_reasoning_effort or None)
    selection = Selection(
        vendor=chosen_vendor,
        method=chosen_method,
        model_id=model_id,
        reasoning_effort=selected_effort,
        problem_id=problem.id if problem is not None else None,
        source=source_key,
        source_chars=source_chars,
    )
    return Calculation(
        providers=providers,
        agent_vendors=tuple(v for v in VENDORS if v in AGENT_VERIFIED_VENDORS),
        problems=problems,
        selection=selection,
        assumptions=assumptions,
        rows=tuple(rows),
        staged=staged,
        two_step_threshold_chars=threshold,
        two_step_budget_chars=budget,
        agent_limits=_agent_limits(),
    )
