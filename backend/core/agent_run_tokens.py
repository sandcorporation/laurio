"""에이전트 채점 실행 토큰 — 발급(채점기 쪽)과 확인·사용량 기록(`llm-proxy` 쪽), #998.

에이전트 CLI 는 벤더 키를 env·파일로 받는데, 참가자 저장소를 읽는 프로세스에 진짜 키를 두면 판정 근거
글 등으로 새어 나갈 길이 생긴다. 그래서 에이전트에는 **진짜 키 대신 실행 토큰**을 주고, 프록시가 토큰을
확인해 진짜 키를 붙인다(#992 보고서 6-4).

- **발급**: `issue_run_token` — 채점기(신뢰 영역)가 실행마다 부른다. 묶인 값은 제출 id·용도·벤더·모델·
  예산(기본 $1)·만료(15분)·키 출처(플랫폼 / 강의실 클래스 id, #1036).
  단가를 모르는 모델은 상한을 걸 수 없으므로 발급하지 않는다.
- **확인**: `authorize` — 프록시가 요청마다 부른다. 거절 이유는 `Refusal` 하나로 돌려준다.
- **기록**: `record_usage` — 프록시가 응답을 다 흘려보낸 뒤 usage 와 비용을 그 토큰 행에 더한다.
  `run_usage` 가 그 합을 읽는다(채점 시도 기록에 붙일 값).

**이 모듈을 부르는 운영 코드가 없으면 아무 토큰도 없다** — 프록시가 떠 있어도 모든 요청이 401 이고
벤더로는 아무것도 나가지 않는다(배포해도 운영 동작이 바뀌지 않는다).

상한 검사는 요청 **전에** 지금까지 쓴 비용으로 한다. 응답 하나의 비용은 그 응답이 끝나야 알 수 있으므로
마지막 요청 하나만큼은 넘칠 수 있다(동시 요청이면 그 수만큼). 하루 합계는 그날(KST 0시부터) 발급한 토큰의
`spent_usd` 합이다 — 토큰은 15분이면 끝나므로 자정을 넘는 실행 하나의 몫만큼 어긋날 수 있다.

**클래스 키 실행**(#1036, 키 출처가 클래스)은 그 클래스 소유자의 키로 나가므로 플랫폼 하루 상한
(`agent_scoring_daily_limit_usd`)에 세지도, 그 상한으로 막히지도 않는다. 실행 예산은 같다. 클래스 몫의 하루
합은 `spent_today_usd(key_class_id=…)` 로 따로 센다(상한은 두지 않는다).
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal, TypedDict

from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone

# 모델 단가표는 강의실 비용 어림(`classroom.scoring_cost`)에 있다 — 프록시 상한이 같은 표를 쓴다(#998). 강의실이 등록한다(#1085).
from core.agent_ports import ModelPrice, price_for
from core.clock import Clock
from core.models import AgentRunToken
from core.runtime_settings_port import ScoringVendor, agent_experiment_daily_limit_usd, agent_scoring_daily_limit_usd

#: 실행 하나의 기본 예산(USD) — 공모전 3 실측 1건 $0.09~0.21 의 다섯 배쯤.
DEFAULT_RUN_BUDGET_USD = Decimal("1")
#: 실행 토큰의 수명. 실행 하나의 상한(10분)보다 조금 길다.
RUN_TOKEN_TTL = timedelta(minutes=15)

Purpose = Literal["scoring", "quality", "experiment"]
_PURPOSES: frozenset[str] = frozenset(
    {AgentRunToken.PURPOSE_SCORING, AgentRunToken.PURPOSE_QUALITY, AgentRunToken.PURPOSE_EXPERIMENT}
)
_VENDORS: frozenset[str] = frozenset({"openai", "anthropic"})

#: Anthropic 프롬프트 캐시의 단가 배율(입력 단가 기준) — 쓰기 1.25배, 읽기 0.1배(5분 캐시, 공개 단가표).
_ANTHROPIC_CACHE_WRITE_MULTIPLIER = Decimal("1.25")
_ANTHROPIC_CACHE_READ_MULTIPLIER = Decimal("0.1")
_PER_MILLION = Decimal(1_000_000)
_TOKEN_PREFIX = "cmrt_"


class RunTokenRefused(Exception):
    """발급하지 않는다 — 이유는 메시지에."""


@dataclass(frozen=True)
class IssuedRunToken:
    #: 에이전트 컨테이너의 키 자리에 넣을 값. 여기서만 한 번 보인다(DB 에는 해시만).
    token: str
    record_id: int
    vendor: ScoringVendor
    model: str
    budget_usd: Decimal
    expires_at: datetime


@dataclass(frozen=True)
class Usage:
    """벤더 응답 하나(또는 합)의 토큰 수. OpenAI 의 `input_tokens` 는 캐시 읽기를 포함하고, Anthropic 의
    `input_tokens` 는 캐시를 뺀 나머지다 — 벤더가 준 그대로 담고 비용 계산이 벤더별로 읽는다."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0


class ModelTally(TypedDict):
    """서브에이전트가 있는 실행의 모델 하나 몫(#1352). `spent_usd` 는 Decimal 의 문자열(JSON 칸에 담는다)."""

    requests: int
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    spent_usd: str
    #: 프롬프트가 긴 프롬프트 문턱(Haiku 5.5 는 10만)을 넘어 할증 단가로 센 요청 수.
    long_context_requests: int


@dataclass(frozen=True)
class RunUsage:
    """실행 토큰 하나에 쌓인 합 — 채점 시도 기록에 붙인다."""

    vendor: ScoringVendor
    model: str
    request_count: int
    usage: Usage
    spent_usd: Decimal
    budget_usd: Decimal
    #: 서브에이전트가 있는 실행만 모델별 몫(#1352). 운영 채점은 None.
    model_usage: dict[str, ModelTally] | None = None


@dataclass(frozen=True)
class Grant:
    record_id: int
    vendor: ScoringVendor
    model: str
    #: 키 출처 — `None` 이면 플랫폼 키, 아니면 그 강의실 클래스의 키(#1036).
    key_class_id: int | None = None


RefusalCode = Literal[
    "missing_token",
    "unknown_token",
    "expired",
    "wrong_vendor",
    "wrong_model",
    "run_budget",
    "daily_limit",
    "experiment_daily_limit",
]


@dataclass(frozen=True)
class Refusal:
    code: RefusalCode
    status: int
    message: str


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _vendor(value: str) -> ScoringVendor:
    return "anthropic" if value == "anthropic" else "openai"


def issue_run_token(
    *,
    submission_id: int,
    purpose: Purpose,
    vendor: ScoringVendor,
    model: str,
    budget_usd: Decimal = DEFAULT_RUN_BUDGET_USD,
    key_class_id: int | None = None,
    sub_model: str | None = None,
) -> IssuedRunToken:
    """실행 하나의 토큰을 발급한다. 방침이 덮지 않는 Anthropic·단가 모르는 모델·알 수 없는 용도는 거절한다.
    `key_class_id` 를 주면 프록시가 플랫폼 키 대신 그 클래스의 채점 연결 키를 붙인다(#1036).
    `sub_model` 은 방식 비교 실험의 Anthropic 서브에이전트 모델(#1352) — 이 토큰이 그 모델의 요청도 부를 수 있다.
    예산은 두 모델 몫을 합친 하나다."""

    if purpose not in _PURPOSES:
        raise RunTokenRefused(f"알 수 없는 용도: {purpose}")
    if vendor not in _VENDORS:
        raise RunTokenRefused(f"알 수 없는 벤더: {vendor}")
    if price_for(model) is None:
        raise RunTokenRefused(f"단가를 모르는 모델이라 비용 상한을 걸 수 없다: {model}")
    if budget_usd <= 0:
        raise RunTokenRefused("예산은 0 보다 커야 한다")
    if sub_model is not None:
        if purpose != AgentRunToken.PURPOSE_EXPERIMENT or vendor != "anthropic":
            raise RunTokenRefused("서브에이전트 모델은 방식 비교 실험의 Anthropic 실행에만 붙는다")
        if not sub_model.startswith("claude-") or price_for(sub_model) is None:
            raise RunTokenRefused(f"단가를 모르는 서브에이전트 모델이라 비용 상한을 걸 수 없다: {sub_model}")
    now = Clock.now()
    token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = AgentRunToken.objects.create(
        token_hash=token_hash(token),
        submission_id=submission_id,
        purpose=purpose,
        vendor=vendor,
        model=model,
        key_class_id=key_class_id,
        sub_model=sub_model or "",
        budget_usd=budget_usd,
        created_at=now,
        expires_at=now + RUN_TOKEN_TTL,
    )
    return IssuedRunToken(
        token=token,
        record_id=row.pk,
        vendor=vendor,
        model=model,
        budget_usd=budget_usd,
        expires_at=row.expires_at,
    )


def _day_start(now: datetime) -> datetime:
    return timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)


def spent_today_usd(
    now: datetime | None = None, *, key_class_id: int | None = None, experiment: bool = False
) -> Decimal:
    """오늘(KST 0시부터) 발급한 실행 토큰들이 쓴 비용 합 — 기본은 플랫폼 키 몫만(하루 상한이 보는 값),
    `key_class_id` 를 주면 그 클래스 키 몫만(#1036). 방식 비교 실험(#1246) 몫은 따로 센다 — `experiment=True`
    면 실험 몫만, 아니면 실험 몫을 뺀다."""

    start = _day_start(now or Clock.now())
    rows = AgentRunToken.objects.filter(created_at__gte=start)
    rows = rows.filter(key_class_id__isnull=True) if key_class_id is None else rows.filter(key_class_id=key_class_id)
    rows = (
        rows.filter(purpose=AgentRunToken.PURPOSE_EXPERIMENT)
        if experiment
        else rows.exclude(purpose=AgentRunToken.PURPOSE_EXPERIMENT)
    )
    total = rows.aggregate(total=Sum("spent_usd"))["total"]
    return total or Decimal(0)


def authorize(token: str | None, *, vendor: ScoringVendor, model: str | None) -> Grant | Refusal:
    """요청 하나를 받아도 되는가 — 토큰·만료·벤더·모델·방침·실행 예산·하루 합계 순으로 본다."""

    if not token:
        return Refusal("missing_token", 401, "실행 토큰이 없다")
    row = AgentRunToken.objects.filter(token_hash=token_hash(token)).first()
    if row is None:
        return Refusal("unknown_token", 401, "알 수 없는 실행 토큰이다")
    now = Clock.now()
    if now >= row.expires_at:
        return Refusal("expired", 401, "실행 토큰이 만료됐다")
    if row.vendor != vendor:
        return Refusal("wrong_vendor", 403, "이 실행 토큰은 다른 벤더 것이다")
    if model != row.model and not (row.sub_model and model == row.sub_model):
        allowed = f"{row.model}·{row.sub_model}" if row.sub_model else row.model
        return Refusal("wrong_model", 403, f"이 실행 토큰은 모델 {allowed} 만 부를 수 있다")
    if row.spent_usd >= row.budget_usd:
        return Refusal("run_budget", 429, f"실행 예산 ${row.budget_usd} 을 다 썼다")
    if row.purpose == AgentRunToken.PURPOSE_EXPERIMENT:
        # 방식 비교 실험(#1246)은 제 하루 상한만 본다 — 운영 채점의 하루 몫을 먹지 않는다. 기본 0 은 꺼짐.
        experiment_limit = agent_experiment_daily_limit_usd()
        if spent_today_usd(now, experiment=True) >= experiment_limit:
            return Refusal("experiment_daily_limit", 429, f"오늘의 채점 방식 비교 실험 비용 상한 ${experiment_limit} 에 닿았다")
    elif row.key_class_id is None:
        # 플랫폼 하루 상한은 플랫폼 키 실행만 본다 — 클래스 키 실행은 그 클래스 소유자의 돈이다(#1036).
        limit = agent_scoring_daily_limit_usd()
        if spent_today_usd(now) >= limit:
            return Refusal("daily_limit", 429, f"오늘의 에이전트 채점 비용 상한 ${limit} 에 닿았다")
    granted = model if row.sub_model and model == row.sub_model else row.model
    return Grant(record_id=row.pk, vendor=_vendor(row.vendor), model=granted, key_class_id=row.key_class_id)


def _price(price: ModelPrice, attr: str, multiplier: float) -> Decimal:
    return Decimal(str(getattr(price, attr))) * Decimal(str(multiplier)) / _PER_MILLION


def _long_context(vendor: ScoringVendor, price: ModelPrice, usage: Usage) -> bool:
    prompt_tokens = usage.input_tokens + (
        usage.cache_read_tokens + usage.cache_write_tokens if vendor == "anthropic" else 0
    )
    return price.long_context_input_tokens is not None and prompt_tokens > price.long_context_input_tokens


def usage_cost_usd(vendor: ScoringVendor, model: str, usage: Usage, *, long_context: bool = True) -> Decimal:
    """응답 하나의 비용(USD). 단가를 모르는 모델은 발급 단계에서 막히므로 여기서는 0 이 아니라 예외다.

    긴 프롬프트 할증(Haiku 5.5 의 10만 토큰 초과 5배 등)은 **요청 하나**의 프롬프트에 걸린다. 여러 요청의 합계를
    값으로 받으면 문턱이 합계에 걸려 몇 배로 부푼다(#1259) — 그럴 때는 `long_context=False` 로 할증 없이 근사한다.
    """

    price = price_for(model)
    if price is None:
        raise RunTokenRefused(f"단가를 모르는 모델: {model}")
    surcharge = long_context and _long_context(vendor, price, usage)
    in_mult = price.long_context_input_multiplier if surcharge else 1.0
    out_mult = price.long_context_output_multiplier if surcharge else 1.0
    unit_in = _price(price, "input_usd_per_million", in_mult)
    unit_out = _price(price, "output_usd_per_million", out_mult)
    if vendor == "anthropic":
        cost = Decimal(usage.input_tokens) * unit_in + Decimal(usage.output_tokens) * unit_out
        cost += Decimal(usage.cache_write_tokens) * unit_in * _ANTHROPIC_CACHE_WRITE_MULTIPLIER
        cost += Decimal(usage.cache_read_tokens) * unit_in * _ANTHROPIC_CACHE_READ_MULTIPLIER
        return cost.quantize(Decimal("0.000001"))
    # OpenAI 의 캐시 읽기(`input_tokens_details.cached_tokens`)는 `input_tokens` 안에 있다 — 그 몫은 표의 캐시 입력
    # 단가로 센다(#1259, 청구와 맞춘다). 캐시 단가가 없는 모델만 입력 단가 그대로다.
    cached = min(usage.cache_read_tokens, usage.input_tokens)
    cached_price = price.cached_input_usd_per_million
    unit_cached = unit_in if cached_price is None else Decimal(str(cached_price)) * Decimal(str(in_mult)) / _PER_MILLION
    cost = (
        Decimal(usage.input_tokens - cached) * unit_in + Decimal(cached) * unit_cached + Decimal(usage.output_tokens) * unit_out
    )
    return cost.quantize(Decimal("0.000001"))


def record_usage(record_id: int, usage: Usage, model: str | None = None) -> Decimal:
    """응답 하나의 usage 와 비용을 토큰 행에 더한다. 더한 비용을 돌려준다.

    `model` 은 그 요청의 모델(`Grant.model`) — 서브에이전트가 있는 실행(#1352)이면 그 모델의 단가로 세고 모델별
    장부(`model_usage`)에도 더한다. 비거나 토큰 모델과 같으면 지금처럼 토큰 모델의 단가다."""

    row = AgentRunToken.objects.filter(pk=record_id).values("vendor", "model", "sub_model").first()
    if row is None:
        return Decimal(0)
    vendor = _vendor(row["vendor"])
    priced = model if row["sub_model"] and model == row["sub_model"] else row["model"]
    cost = usage_cost_usd(vendor, priced, usage)
    if row["sub_model"]:
        price = price_for(priced)
        _add_model_usage(record_id, priced, usage, cost, long_context=price is not None and _long_context(vendor, price, usage))
    AgentRunToken.objects.filter(pk=record_id).update(
        request_count=F("request_count") + 1,
        input_tokens=F("input_tokens") + usage.input_tokens,
        output_tokens=F("output_tokens") + usage.output_tokens,
        cache_read_tokens=F("cache_read_tokens") + usage.cache_read_tokens,
        cache_write_tokens=F("cache_write_tokens") + usage.cache_write_tokens,
        spent_usd=F("spent_usd") + cost,
    )
    return cost


def _add_model_usage(record_id: int, model: str, usage: Usage, cost: Decimal, *, long_context: bool) -> None:
    """모델별 장부에 응답 하나를 더한다 — 서브에이전트 요청이 나란히 올 수 있어 행을 잠그고 고친다."""

    with transaction.atomic():
        token = AgentRunToken.objects.select_for_update().only("model_usage").get(pk=record_id)
        tallies: dict[str, ModelTally] = dict(token.model_usage or {})
        t = tallies.get(model) or ModelTally(
            requests=0, input_tokens=0, output_tokens=0, cache_read_tokens=0, cache_write_tokens=0,
            spent_usd="0", long_context_requests=0,
        )
        tallies[model] = ModelTally(
            requests=t["requests"] + 1,
            input_tokens=t["input_tokens"] + usage.input_tokens,
            output_tokens=t["output_tokens"] + usage.output_tokens,
            cache_read_tokens=t["cache_read_tokens"] + usage.cache_read_tokens,
            cache_write_tokens=t["cache_write_tokens"] + usage.cache_write_tokens,
            spent_usd=str(Decimal(t["spent_usd"]) + cost),
            long_context_requests=t["long_context_requests"] + (1 if long_context else 0),
        )
        token.model_usage = tallies
        token.save(update_fields=["model_usage"])


def run_usage(record_id: int) -> RunUsage:
    """실행 토큰 하나에 쌓인 합."""

    row = AgentRunToken.objects.get(pk=record_id)
    return RunUsage(
        vendor=_vendor(row.vendor),
        model=row.model,
        request_count=row.request_count,
        usage=Usage(
            input_tokens=row.input_tokens,
            output_tokens=row.output_tokens,
            cache_read_tokens=row.cache_read_tokens,
            cache_write_tokens=row.cache_write_tokens,
        ),
        spent_usd=row.spent_usd,
        budget_usd=row.budget_usd,
        model_usage=dict(row.model_usage or {}) if row.sub_model else None,
    )
