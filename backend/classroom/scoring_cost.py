"""예상 채점 비용 — 강사가 모델·추론 강도를 고를 때 미리 보는 값 (#591, CONTEXT.md
「예상 채점 비용」).

**채점은 시도 하나에 LLM 호출 한 번이다**(체크리스트 전부를 한 프롬프트로,
`classroom.scoring`). 그래서 비용은 프롬프트 길이(거의 제출 소스 길이)와 모델·추론
강도로 정해진다 — 이 모듈이 그 셈을 혼자 든다. 화면(클래스 설정·문제 설정)과 연결된
앱(`get_class`·`get_problem`)이 같은 값을 읽는다.

**어림이다, 청구서가 아니다.** 실제 청구액은 OpenAI 사용량 화면이 기준이다 — 토큰은
글자 수로 어림하고(`CHARS_PER_TOKEN`), 출력 토큰은 상수로 둔다(`*_OUTPUT_TOKENS`). #585 가
시도마다 실제 토큰을 남기면 그 평균으로 바꾼다.

**호환 서버는 토큰만이다**(#604). 단가를 모른다 — 서버가 OpenAI 와 같은 모델 이름을 내놓아도
그 값을 받는다는 보장이 없다. 그래서 그 클래스의 표는 지금 설정만 원화·배율 없이 토큰으로
보이고(`unit="tokens"`), 서버가 usage 를 주지 않은 시도는 같은 어림(`estimated_usage_tokens`)으로
사용량에 더해진다.

**셈의 기준은 내려간다**: 이 문제의 지난 시도 평균 프롬프트 길이 → (시도가
`MIN_SAMPLE_COUNT` 건 미만이면) 이 클래스 전체 평균 → (그것도 미만이면) 소스 크기별(약
1만·5만·20만 자). 플랫폼 전체 평균은
쓰지 않는다 — 과제 성격이 클래스마다 달라 오해를 산다. 플랫폼 자동 미달
(`model_version` 이 `platform-auto` 로 시작)은 LLM 을 부르지 않았으니 평균에서 뺀다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.db.models import Avg, Count
from django.db.models.functions import Length

from .models import Class, ClassroomScore, ClassroomSubmission, Problem
from .scoring_models import REASONING_EFFORT_CHOICES, is_claude_model_id, is_reasoning_model_id

#: 원화 환산 고정 환율(2026-10 기준). 달러 단가를 원화로 보일 때만 쓴다.
KRW_PER_USD = 1_380

#: 글자 수 → 토큰 어림. 한글 주석이 섞인 소스와 채점 지시문을 OpenAI 토크나이저로 셌을 때
#: 영문 코드는 4자 안팎, 한글은 1~2자가 한 토큰이라 그 사이 값을 쓴다 — 2026-10-06 클래스 5
#: 실측(프롬프트 약 5.5만 자 ↔ 입력 약 1.7만 토큰)과 맞는다.
CHARS_PER_TOKEN = 3.3

#: 추론하지 않는 모델의 출력(판정 JSON) 토큰 — 체크리스트 수십 항목에 근거 한두 문장씩.
NON_REASONING_OUTPUT_TOKENS = 2_500

#: 추론 모델의 출력 토큰(추론 토큰 + 판정 JSON) 어림 — 강도별. 높음은 문제·소스에 따라
#: 크게 늘어 위로 열어 둔다(`AttemptCost.open_ended`).
REASONING_OUTPUT_TOKENS = {"low": 4_000, "medium": 7_500, "high": 15_000}
_OPEN_ENDED_EFFORTS = frozenset({"high"})

#: 이 클래스에 아직 시도가 없을 때 보일 소스 크기(글자 수) — 작은 과제·보통·큰 프로젝트.
SOURCE_SIZE_BANDS = (10_000, 50_000, 200_000)
#: 소스 크기별로 셈할 때 배율 안내가 기대는 「보통」 크기.
_REFERENCE_CHARS = 50_000

#: 평균을 낼 최소 시도 수 — 이보다 적으면 다음 기준으로 내려간다(#617). 시험 삼아 낸 짧은 제출
#: 몇 건이 비용을 실제보다 훨씬 작게 보이게 하지 않도록.
MIN_SAMPLE_COUNT = 3

#: 「문제 하나」를 셈할 때 이 클래스의 실측이 없으면 쓰는 1인 평균 시도 수.
DEFAULT_ATTEMPTS_PER_PARTICIPANT = 2.5

#: 배율의 기준 모델.
BASELINE_MODEL = "gpt-4.1-mini"

_PLATFORM_AUTO_PREFIX = "platform-auto"


@dataclass(frozen=True)
class ModelPrice:
    input_usd_per_million: float
    output_usd_per_million: float
    #: 입력이 이 토큰 수를 넘으면 그 호출 전체에 할증이 붙는다(없으면 `None`).
    long_context_input_tokens: int | None = None
    long_context_input_multiplier: float = 1.0
    long_context_output_multiplier: float = 1.0


#: 모델별 단가(USD / 100만 토큰, 2026-10 기준, 표준 등급). 여기 없는 모델은 「단가 모름」이다(`price_for`) —
#: 모델 카탈로그가 아는 모델(`scoring_models._KNOWN_CONTEXT_WINDOWS`)은 전부 여기 있어야 한다(#617).
#: 출처: https://developers.openai.com/api/docs/pricing (2026-10-06 확인 — gpt-5.1 도 이 표에서
#: 확인했다), 교차 확인 https://www.morphllm.com/openai-api-pricing ·
#: https://spendlint.dev/pricing/openai-api . gpt-5.4·gpt-5.5 는 입력 27.2만 토큰을 넘으면 그 호출
#: 전체가 입력 2배·출력 1.5배다.
_LONG_CONTEXT = {
    "long_context_input_tokens": 272_000,
    "long_context_input_multiplier": 2.0,
    "long_context_output_multiplier": 1.5,
}
PRICES: dict[str, ModelPrice] = {
    "gpt-4o": ModelPrice(2.50, 10.00),
    "gpt-4o-mini": ModelPrice(0.15, 0.60),
    "gpt-4.1": ModelPrice(2.00, 8.00),
    "gpt-4.1-mini": ModelPrice(0.40, 1.60),
    "gpt-4.1-nano": ModelPrice(0.10, 0.40),
    "gpt-5": ModelPrice(1.25, 10.00),
    "gpt-5-mini": ModelPrice(0.25, 2.00),
    "gpt-5-nano": ModelPrice(0.05, 0.40),
    "gpt-5.1": ModelPrice(1.25, 10.00),
    "gpt-5.2": ModelPrice(1.75, 14.00),
    "gpt-5.4": ModelPrice(2.50, 15.00, **_LONG_CONTEXT),
    "gpt-5.4-mini": ModelPrice(0.75, 4.50),
    "gpt-5.4-nano": ModelPrice(0.20, 1.25),
    "gpt-5.5": ModelPrice(5.00, 30.00, **_LONG_CONTEXT),
    # Claude(Anthropic) 키 연결(#795) — 출처: https://platform.claude.com/docs/en/about-claude/pricing
    # (2026-10-28 확인, 표준 입력·출력). Haiku 5.5 는 프롬프트가 10만 토큰을 넘으면 그 호출 전체가
    # 입력·출력 모두 5배다(0.10→0.50, 0.50→2.50). Sonnet 5.5·5·4.6 은 1M 컨텍스트 전체가 표준 단가다.
    # 사고(adaptive thinking) 토큰은 출력으로 청구된다 — 추론 강도별 출력 어림(`REASONING_OUTPUT_TOKENS`)을 쓴다.
    "claude-haiku-5-5": ModelPrice(
        0.10,
        0.50,
        long_context_input_tokens=100_000,
        long_context_input_multiplier=5.0,
        long_context_output_multiplier=5.0,
    ),
    "claude-sonnet-5-5": ModelPrice(2.00, 10.00),
    "claude-sonnet-5": ModelPrice(2.00, 10.00),
    "claude-sonnet-4-6": ModelPrice(3.00, 15.00),
}


#: 단가표에 없는 모델의 비용을 부르는 한 이름(#797) — 화면·MCP 가 같은 낱말을 쓴다. 호환 서버의
#: 「토큰만」(#604)과는 다르다: 그쪽은 단가를 **알 수 없는** 연결이고, 이쪽은 단가를 **아직 못 적은** 모델이다.
PRICE_UNKNOWN = "단가 모름"

#: 모델 이름 끝의 날짜 접미사(`-2024-07-18`·`-20251001`)와 `-latest` — 같은 모델의 변형이다.
#: Claude 의 `-5-5` 같은 버전 마디는 날짜가 아니라 이름의 일부라 떼지 않는다(마디가 두 자리 수까지).
_NAME_VARIANT_SUFFIX = re.compile(r"(?:-\d{4}-\d{2}-\d{2}|-\d{8}|-latest)$")


def canonical_model_id(model_id: str) -> str:
    """날짜·`-latest` 접미사를 뗀 표준 이름(#797) — `gpt-4o-mini-2024-07-18` → `gpt-4o-mini`,
    `claude-haiku-4-5-20251001` → `claude-haiku-4-5`. 접미사가 없으면 그대로, 접두어만 같은 다른 모델
    (`gpt-4o` 와 `gpt-4o-mini`)은 건드리지 않는다. 단가표에 있는지는 보지 않는다 — `price_for` 가 본다."""

    return _NAME_VARIANT_SUFFIX.sub("", model_id.strip(), count=1)


def price_for(model_id: str) -> ModelPrice | None:
    """모델의 단가 — 이름을 표준으로 맞춘 뒤에도 표에 없으면 `None`(「단가 모름」, #797)."""

    return PRICES.get(model_id) or PRICES.get(canonical_model_id(model_id))


def sum_known_krw(amounts: "list[float | None]") -> tuple[float, bool]:
    """여러 모델의 원화를 더한다 — (합계, 일부 미포함). 단가를 모르는 항목(`None`)은 합계에 넣지 않고
    `True` 로 알린다: 모르는 것을 0원으로 더해 합계가 작아 보이게 하지 않는다(#797)."""

    known = [a for a in amounts if a is not None]
    return sum(known), len(known) < len(amounts)


@dataclass(frozen=True)
class AttemptCost:
    input_tokens: int
    output_tokens: int
    usd: float
    #: 위로 열린 어림인가 — 화면은 「약 N원~」으로 보인다.
    open_ended: bool = False

    @property
    def krw(self) -> float:
        return self.usd * KRW_PER_USD

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def tokens_for_chars(chars: int) -> int:
    return round(chars / CHARS_PER_TOKEN)


def attempt_tokens(reasoning_effort: str | None, *, prompt_chars: int) -> AttemptCost:
    """시도 하나가 쓸 토큰만 — 단가를 모르는 호환 서버(#604). `reasoning_effort` 는 채점 요청에
    실을 값 그대로다(`None` 이면 추론하지 않는 출력으로 센다)."""

    output_tokens = NON_REASONING_OUTPUT_TOKENS if reasoning_effort is None else REASONING_OUTPUT_TOKENS[reasoning_effort]
    return AttemptCost(
        input_tokens=tokens_for_chars(prompt_chars),
        output_tokens=output_tokens,
        usd=0.0,
        open_ended=reasoning_effort in _OPEN_ENDED_EFFORTS,
    )


def estimated_usage_tokens(prompt: str, reasoning_effort: str | None) -> int:
    """응답에 usage 가 없을 때 이 시도를 사용량에 더할 어림(#604) — 예상 비용과 같은 셈이다."""

    return attempt_tokens(reasoning_effort, prompt_chars=len(prompt)).total_tokens


def _effort_for(model_id: str, reasoning_effort: str | None) -> str | None:
    return (reasoning_effort or "low") if _takes_effort(model_id) else None


def _takes_effort(model_id: str) -> bool:
    """채점 요청에 추론 강도가 실리는 모델인가 — GPT-5 이후와 모든 Claude 채점 모델(#795, ADR-0066)."""

    return is_reasoning_model_id(model_id) or is_claude_model_id(model_id)


def attempt_cost(model_id: str, reasoning_effort: str | None, *, prompt_chars: int) -> AttemptCost | None:
    """시도 하나를 이 모델·강도로 채점하는 어림 비용 — 단가표에 없는 모델은 `None`."""

    price = price_for(model_id)
    if price is None:
        return None
    effort = _effort_for(model_id, reasoning_effort)
    input_tokens = tokens_for_chars(prompt_chars)
    output_tokens = NON_REASONING_OUTPUT_TOKENS if effort is None else REASONING_OUTPUT_TOKENS[effort]
    input_rate, output_rate = price.input_usd_per_million, price.output_usd_per_million
    if price.long_context_input_tokens is not None and input_tokens > price.long_context_input_tokens:
        input_rate *= price.long_context_input_multiplier
        output_rate *= price.long_context_output_multiplier
    usd = (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000
    return AttemptCost(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        usd=usd,
        open_ended=effort in _OPEN_ENDED_EFFORTS,
    )


def ratio_to_baseline(model_id: str, reasoning_effort: str | None, *, prompt_chars: int) -> float | None:
    cost = attempt_cost(model_id, reasoning_effort, prompt_chars=prompt_chars)
    baseline = attempt_cost(BASELINE_MODEL, None, prompt_chars=prompt_chars)
    if cost is None or baseline is None or baseline.usd == 0:
        return None
    return cost.usd / baseline.usd


# --- 기준: 이 클래스·문제의 실측 ---------------------------------------------------


@dataclass(frozen=True)
class CostRow:
    model_id: str
    #: 추론 모델이면 그 강도, 아니면 `None`.
    reasoning_effort: str | None
    priced: bool
    #: 위로 열린 어림인가(추론 강도 높음) — 「약 N원~」.
    open_ended: bool
    #: 기준 길이(문제·클래스 평균)에서 시도 1건 — 소스 크기별 기준이면 `None`.
    per_attempt: AttemptCost | None
    per_problem_krw: float | None
    #: 참여자 수 × 1인 평균 시도 수 × 시도 1건의 토큰 — 토큰으로 셈한 표(호환 서버)에서만.
    per_problem_tokens: int | None
    ratio_to_baseline: float | None
    #: `SOURCE_SIZE_BANDS` 순서의 시도 1건 — 단가가 없으면 빈 튜플.
    by_source_size: tuple[AttemptCost, ...]


@dataclass(frozen=True)
class CostEstimate:
    #: "problem" | "class" | "source_sizes"
    basis: str
    sample_count: int
    avg_prompt_chars: int | None
    participant_count: int
    attempts_per_participant: float
    attempts_per_participant_measured: bool
    rows: tuple[CostRow, ...]
    #: "krw"(OpenAI 키 — 단가표로 원화) | "tokens"(호환 서버 — 단가를 몰라 토큰만, #604)
    unit: str = "krw"

    def row_for(self, model_id: str, reasoning_effort: str | None) -> CostRow | None:
        if self.unit == "tokens":
            # 토큰 줄의 강도는 이미 「채점 요청에 실을 값」으로 풀려 있다 — 모델로만 찾는다.
            return next((r for r in self.rows if r.model_id == model_id), None)
        effort = _effort_for(model_id, reasoning_effort)
        return next((r for r in self.rows if r.model_id == model_id and r.reasoning_effort == effort), None)


def _llm_scores():
    return ClassroomScore.objects.exclude(model_version__startswith=_PLATFORM_AUTO_PREFIX)


def _prompt_average(scores) -> tuple[int, int | None]:
    """(시도 수, 평균 프롬프트 길이) — 시도가 `MIN_SAMPLE_COUNT` 건 미만이면 평균은 `None`."""

    agg = scores.aggregate(n=Count("id"), avg=Avg(Length("prompt")))
    if agg["n"] < MIN_SAMPLE_COUNT:
        return agg["n"], None
    return agg["n"], round(agg["avg"])


def _attempts_per_participant(class_obj: Class) -> tuple[float, bool]:
    agg = ClassroomSubmission.objects.filter(problem__classroom=class_obj).aggregate(n=Count("id"))
    pairs = (
        ClassroomSubmission.objects.filter(problem__classroom=class_obj)
        .values("problem_id", "member_id")
        .distinct()
        .count()
    )
    if not pairs:
        return DEFAULT_ATTEMPTS_PER_PARTICIPANT, False
    return agg["n"] / pairs, True


def _setting_keys(model_ids: list[str]) -> list[tuple[str, str | None]]:
    keys: list[tuple[str, str | None]] = []
    for model_id in model_ids:
        if _takes_effort(model_id):
            keys.extend((model_id, effort) for effort, _label in REASONING_EFFORT_CHOICES)
        else:
            keys.append((model_id, None))
    return keys


def estimate(
    class_obj: Class,
    *,
    participant_count: int,
    catalog_model_ids: list[str],
    current_model_ids: list[str],
    problem: Problem | None = None,
    token_settings: list[tuple[str, str | None]] | None = None,
) -> CostEstimate:
    """이 클래스(와 문제)의 예상 채점 비용표.

    줄은 이 키로 쓸 수 있는 모델(`catalog_model_ids`) 전부를 카탈로그 순서로, 그 뒤에 카탈로그에
    없는 지금 설정(`current_model_ids`)을 — 단가가 없는 모델만 「단가 모름」 줄이다(#617)."""

    sample_count, avg_chars = 0, None
    basis = "source_sizes"
    if problem is not None:
        sample_count, avg_chars = _prompt_average(_llm_scores().filter(submission__problem=problem))
        if avg_chars is not None:
            basis = "problem"
    if avg_chars is None:
        sample_count, avg_chars = _prompt_average(_llm_scores().filter(submission__problem__classroom=class_obj))
        if avg_chars is not None:
            basis = "class"

    attempts, measured = _attempts_per_participant(class_obj)

    if token_settings is not None:
        return CostEstimate(
            basis=basis,
            sample_count=sample_count,
            avg_prompt_chars=avg_chars,
            participant_count=participant_count,
            attempts_per_participant=attempts,
            attempts_per_participant_measured=measured,
            rows=tuple(
                _token_row(model_id, effort, avg_chars, participant_count * attempts)
                for model_id, effort in dict.fromkeys(token_settings)
            ),
            unit="tokens",
        )

    model_ids = list(dict.fromkeys(m for m in [*catalog_model_ids, *current_model_ids] if m))
    reference_chars = avg_chars if avg_chars is not None else _REFERENCE_CHARS

    rows: list[CostRow] = []
    for model_id, effort in _setting_keys(model_ids):
        per_attempt = (
            attempt_cost(model_id, effort, prompt_chars=avg_chars) if avg_chars is not None else None
        )
        bands = tuple(
            cost
            for chars in SOURCE_SIZE_BANDS
            if (cost := attempt_cost(model_id, effort, prompt_chars=chars)) is not None
        )
        rows.append(
            CostRow(
                model_id=model_id,
                reasoning_effort=effort,
                priced=price_for(model_id) is not None,
                open_ended=price_for(model_id) is not None and effort in _OPEN_ENDED_EFFORTS,
                per_attempt=per_attempt,
                per_problem_krw=(
                    per_attempt.krw * participant_count * attempts if per_attempt is not None else None
                ),
                per_problem_tokens=None,
                ratio_to_baseline=ratio_to_baseline(model_id, effort, prompt_chars=reference_chars),
                by_source_size=bands,
            )
        )

    return CostEstimate(
        basis=basis,
        sample_count=sample_count,
        avg_prompt_chars=avg_chars,
        participant_count=participant_count,
        attempts_per_participant=attempts,
        attempts_per_participant_measured=measured,
        rows=tuple(rows),
    )


def _token_row(model_id: str, effort: str | None, avg_chars: int | None, attempts_in_problem: float) -> CostRow:
    per_attempt = attempt_tokens(effort, prompt_chars=avg_chars) if avg_chars is not None else None
    return CostRow(
        model_id=model_id,
        reasoning_effort=effort,
        priced=False,
        open_ended=effort in _OPEN_ENDED_EFFORTS,
        per_attempt=per_attempt,
        per_problem_krw=None,
        per_problem_tokens=(
            round(per_attempt.total_tokens * attempts_in_problem) if per_attempt is not None else None
        ),
        ratio_to_baseline=None,
        by_source_size=tuple(attempt_tokens(effort, prompt_chars=chars) for chars in SOURCE_SIZE_BANDS),
    )
