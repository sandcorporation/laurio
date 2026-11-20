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
from typing import Literal

from django.db.models import F, Sum
from django.utils import timezone

# 모델 단가표는 강의실 비용 어림(`classroom.scoring_cost`)에 있다 — 프록시 상한이 같은 표를 쓴다(#998). 강의실이 등록한다(#1085).
from core.agent_ports import ModelPrice, price_for
from core.clock import Clock
from core.models import AgentRunToken
from core.runtime_settings_port import ScoringVendor, agent_scoring_daily_limit_usd

#: 실행 하나의 기본 예산(USD) — 공모전 3 실측 1건 $0.09~0.21 의 다섯 배쯤.
DEFAULT_RUN_BUDGET_USD = Decimal("1")
#: 실행 토큰의 수명. 실행 하나의 상한(10분)보다 조금 길다.
RUN_TOKEN_TTL = timedelta(minutes=15)

Purpose = Literal["scoring", "quality"]
_PURPOSES: frozenset[str] = frozenset({AgentRunToken.PURPOSE_SCORING, AgentRunToken.PURPOSE_QUALITY})
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


@dataclass(frozen=True)
class RunUsage:
    """실행 토큰 하나에 쌓인 합 — 채점 시도 기록에 붙인다."""

    vendor: ScoringVendor
    model: str
    request_count: int
    usage: Usage
    spent_usd: Decimal
    budget_usd: Decimal


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
) -> IssuedRunToken:
    """실행 하나의 토큰을 발급한다. 방침이 덮지 않는 Anthropic·단가 모르는 모델·알 수 없는 용도는 거절한다.
    `key_class_id` 를 주면 프록시가 플랫폼 키 대신 그 클래스의 채점 연결 키를 붙인다(#1036)."""

    if purpose not in _PURPOSES:
        raise RunTokenRefused(f"알 수 없는 용도: {purpose}")
    if vendor not in _VENDORS:
        raise RunTokenRefused(f"알 수 없는 벤더: {vendor}")
    if price_for(model) is None:
        raise RunTokenRefused(f"단가를 모르는 모델이라 비용 상한을 걸 수 없다: {model}")
    if budget_usd <= 0:
        raise RunTokenRefused("예산은 0 보다 커야 한다")
    now = Clock.now()
    token = _TOKEN_PREFIX + secrets.token_urlsafe(32)
    row = AgentRunToken.objects.create(
        token_hash=token_hash(token),
        submission_id=submission_id,
        purpose=purpose,
        vendor=vendor,
        model=model,
        key_class_id=key_class_id,
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


def spent_today_usd(now: datetime | None = None, *, key_class_id: int | None = None) -> Decimal:
    """오늘(KST 0시부터) 발급한 실행 토큰들이 쓴 비용 합 — 기본은 플랫폼 키 몫만(하루 상한이 보는 값),
    `key_class_id` 를 주면 그 클래스 키 몫만(#1036)."""

    start = _day_start(now or Clock.now())
    rows = AgentRunToken.objects.filter(created_at__gte=start)
    rows = rows.filter(key_class_id__isnull=True) if key_class_id is None else rows.filter(key_class_id=key_class_id)
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
    if model != row.model:
        return Refusal("wrong_model", 403, f"이 실행 토큰은 모델 {row.model} 만 부를 수 있다")
    if row.spent_usd >= row.budget_usd:
        return Refusal("run_budget", 429, f"실행 예산 ${row.budget_usd} 을 다 썼다")
    if row.key_class_id is None:
        # 플랫폼 하루 상한은 플랫폼 키 실행만 본다 — 클래스 키 실행은 그 클래스 소유자의 돈이다(#1036).
        limit = agent_scoring_daily_limit_usd()
        if spent_today_usd(now) >= limit:
            return Refusal("daily_limit", 429, f"오늘의 에이전트 채점 비용 상한 ${limit} 에 닿았다")
    return Grant(record_id=row.pk, vendor=_vendor(row.vendor), model=row.model, key_class_id=row.key_class_id)


def _price(price: ModelPrice, attr: str, multiplier: float) -> Decimal:
    return Decimal(str(getattr(price, attr))) * Decimal(str(multiplier)) / _PER_MILLION


def usage_cost_usd(vendor: ScoringVendor, model: str, usage: Usage) -> Decimal:
    """응답 하나의 비용(USD). 단가를 모르는 모델은 발급 단계에서 막히므로 여기서는 0 이 아니라 예외다."""

    price = price_for(model)
    if price is None:
        raise RunTokenRefused(f"단가를 모르는 모델: {model}")
    prompt_tokens = usage.input_tokens + (
        usage.cache_read_tokens + usage.cache_write_tokens if vendor == "anthropic" else 0
    )
    long_context = price.long_context_input_tokens is not None and prompt_tokens > price.long_context_input_tokens
    in_mult = price.long_context_input_multiplier if long_context else 1.0
    out_mult = price.long_context_output_multiplier if long_context else 1.0
    unit_in = _price(price, "input_usd_per_million", in_mult)
    unit_out = _price(price, "output_usd_per_million", out_mult)
    cost = Decimal(usage.input_tokens) * unit_in + Decimal(usage.output_tokens) * unit_out
    if vendor == "anthropic":
        cost += Decimal(usage.cache_write_tokens) * unit_in * _ANTHROPIC_CACHE_WRITE_MULTIPLIER
        cost += Decimal(usage.cache_read_tokens) * unit_in * _ANTHROPIC_CACHE_READ_MULTIPLIER
    # OpenAI 의 캐시 읽기(`input_tokens_details.cached_tokens`)는 `input_tokens` 안에 있다 — 할인 없이
    # 입력 단가로 센다(상한은 넉넉히 세는 쪽이 안전하다).
    return cost.quantize(Decimal("0.000001"))


def record_usage(record_id: int, usage: Usage) -> Decimal:
    """응답 하나의 usage 와 비용을 토큰 행에 더한다. 더한 비용을 돌려준다."""

    row = AgentRunToken.objects.filter(pk=record_id).values("vendor", "model").first()
    if row is None:
        return Decimal(0)
    cost = usage_cost_usd(_vendor(row["vendor"]), row["model"], usage)
    AgentRunToken.objects.filter(pk=record_id).update(
        request_count=F("request_count") + 1,
        input_tokens=F("input_tokens") + usage.input_tokens,
        output_tokens=F("output_tokens") + usage.output_tokens,
        cache_read_tokens=F("cache_read_tokens") + usage.cache_read_tokens,
        cache_write_tokens=F("cache_write_tokens") + usage.cache_write_tokens,
        spent_usd=F("spent_usd") + cost,
    )
    return cost


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
    )
