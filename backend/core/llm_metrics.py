"""LLM 채점 호출을 지표와 호출별 로그로 보이게 한다(#585).

**어디서 세나.** 벤더로 나가는 왕복은 `core.llm_scoring.OpenAIScoringAdapter.score`(동기)·
`score_async`(grader) 두 곳뿐이고, 공모전과 강의실이 둘 다 거기를 지난다 — 그래서 계측도 거기
하나다(`observe_call`·`observe_call_async`). 어댑터가 `product`(`classroom`·`contest`)와 로그용
식별 번호(`log_context`)를 생성자에서 받는다.

**라벨은 닫힌 집합이다.** 제품 둘 · 모델(카탈로그의 이름 — 호환 서버의 모델은 강사가 쓴 문자열이라
`custom` 하나로 접는다) · 결과 일곱. 클래스·제출·강사 id 는 라벨에 넣지 않는다(시계열이 사용자 수만큼
늘어난다) — 그것은 호출별 로그가 맡는다. 시험이 라벨 이름 집합을 못 박는다.

**결과 분류는 새로 판정하지 않는다.** 어댑터가 이미 던지는 예외 계층(`LLMAdapterAuthError`·
`QuotaExhaustedError`·`RateLimitedError`)을 그대로 옮긴다. 5xx 는 `_classify_openai_error` 가 예외에
싣는 `status_code` 로, 타임아웃은 `LLMAdapterTimeoutError` 로 가른다.

**여러 프로세스는 누가 합산하나.** 프로세스가 하나면 그대로 낸다: grader(`manage.py grader`)는
단일 프로세스·asyncio 라 `serve()` 로 연 작은 HTTP 엔드포인트가 전부다. 프로세스가 여럿이면
(gunicorn 워커 넷·celery prefork 자식) `PROMETHEUS_MULTIPROC_DIR` 가 있을 때 prometheus_client 가
값을 파일로 쓰고 `serve()` 가 합산해 낸다. 게이지는 `livesum` — 죽은 프로세스의 값은 더하지 않는다.

**1분 집계와 나란히 쓴다(#827).** 같은 호출이 `ops_metrics.recorder` 로 그 분의 Redis 해시에도 더해진다
(동기는 redis-py, grader 는 `redis.asyncio`) — 운영자 콘솔 `/ops` 가 그것을 DB 로 옮긴 행을 읽는다. 라벨은
여기와 같은 닫힌 집합이고 히스토그램 경계도 같은 상수(`DURATION_BOUNDS`·`QUEUE_WAIT_BOUNDS`)다. 전환
기간에는 prometheus 계측을 지우지 않는다. 동시 채점 최댓값은 비동기 경로의 프로세스 안 수(`async_in_flight`)다.

**로그에 본문을 싣지 않는다.** 호출마다 `codemit.llm` 로거가 한 줄을 남기고, 필드는 번호·모델·
시간·토큰·결과·오류 유형/코드뿐이다 — 프롬프트·소스·응답 본문·키는 이 모듈이 받지도 않는다.
오류 유형/코드는 벤더가 고정된 값만 쓰는 `error.type`/`error.code` 열거형이다(`_extract_openai_error_fields`).
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import Counter as _Tally
from contextlib import asynccontextmanager, contextmanager
from typing import Any

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, REGISTRY, start_http_server

logger = logging.getLogger("codemit.llm")

PRODUCTS = ("classroom", "contest")
RESULTS = ("ok", "timeout", "rate_limited", "quota_exhausted", "auth", "server_error", "other")

#: 히스토그램 경계 — prometheus 와 1분 집계(`ops_metrics`, #827)가 같은 값을 쓴다.
#: 강의실 어댑터 타임아웃이 180초(#582)라 그 위까지 닿는다.
DURATION_BOUNDS = (0.5, 1, 2, 5, 10, 20, 30, 60, 90, 120, 180, 240)
QUEUE_WAIT_BOUNDS = (1, 5, 15, 30, 60, 120, 300, 600, 1800, 3600)

CALLS = Counter(
    "codemit_llm_calls_total",
    "벤더로 나간 LLM 채점 호출 수",
    ["product", "model", "result"],
)
DURATION = Histogram(
    "codemit_llm_call_duration_seconds",
    "LLM 채점 호출 하나가 걸린 시간(초) — 결과와 상관없이 잰다",
    ["product", "model"],
    buckets=DURATION_BOUNDS,
)
TOKENS = Counter(
    "codemit_llm_tokens_total",
    "LLM 채점 호출이 쓴 토큰 수(벤더 응답의 usage)",
    ["product", "model", "direction"],
)
IN_FLIGHT = Gauge(
    "codemit_llm_in_flight",
    "지금 벤더 응답을 기다리는 LLM 채점 호출 수",
    ["product"],
    multiprocess_mode="livesum",
)
QUEUE_WAIT = Histogram(
    "codemit_llm_queue_wait_seconds",
    "강의실 채점이 큐에 들어간 시각부터 임대를 집어 채점이 시작되기까지(초)",
    ["product"],
    buckets=QUEUE_WAIT_BOUNDS,
)

#: 비동기(grader) 경로의 프로세스 안 동시 호출 수 — `async_in_flight` 참고.
_ASYNC_IN_FLIGHT: _Tally = _Tally()

# 값이 한 번도 안 올라도 시계열이 보이게 한다 — 라벨 있는 지표는 처음 쓰기 전에는 아무 줄도 내지 않아,
# 「동시 채점 0」·「큐 대기 없음」이 그래프에서 「데이터 없음」으로 보인다.
for _product in PRODUCTS:
    IN_FLIGHT.labels(_product).set(0)
QUEUE_WAIT.labels("classroom")


def model_label(model: str, *, custom: bool) -> str:
    """호환 서버의 모델 이름은 강사가 쓴 자유 문자열이라 시계열이 끝없이 늘 수 있다 — 하나로 접는다."""

    return "custom" if custom or not model else model[:60]


def classify(exc: BaseException | None) -> str:
    """어댑터 예외를 결과 라벨로 옮긴다(위 모듈 docstring) — 새 판정 규칙이 아니라 기존 계층의 이름 붙이기다."""

    from core.llm_scoring import (
        LLMAdapterAuthError,
        LLMAdapterQuotaExhaustedError,
        LLMAdapterRateLimitedError,
        LLMAdapterTimeoutError,
    )

    if exc is None:
        return "ok"
    # 취소는 grader 의 바깥 한도(`wait_for`)가 거는 것뿐이다 — 벤더가 한도 안에 답하지 않은 것이다.
    if isinstance(exc, (LLMAdapterTimeoutError, asyncio.CancelledError)):
        return "timeout"
    if isinstance(exc, LLMAdapterAuthError):
        return "auth"
    if isinstance(exc, LLMAdapterQuotaExhaustedError):
        return "quota_exhausted"
    if isinstance(exc, LLMAdapterRateLimitedError):
        return "rate_limited"
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status >= 500:
        return "server_error"
    return "other"


def _error_fields(exc: BaseException | None) -> dict[str, Any]:
    if exc is None:
        return {}
    return {
        "error_class": type(exc).__name__,
        "error_status": getattr(exc, "status_code", None),
        "error_type": getattr(exc, "vendor_error_type", "") or "",
        "error_code": getattr(exc, "vendor_error_code", "") or "",
    }


class _Call:
    """호출 하나의 기록 — 바깥은 `output`(성공 때 토큰을 읽는다)·`error` 를 채운다."""

    def __init__(self, *, product: str, model: str, custom: bool, reasoning_effort: str | None, context: dict) -> None:
        self.product = product
        self.model = model_label(model, custom=custom)
        self.reasoning_effort = reasoning_effort
        self.context = context
        self.started = time.perf_counter()
        self.error: BaseException | None = None
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.model_version = ""

    def succeed(self, output: Any) -> None:
        self.input_tokens = int(getattr(output, "input_tokens", 0) or 0)
        self.output_tokens = int(getattr(output, "output_tokens", 0) or 0)
        self.total_tokens = int(getattr(output, "total_tokens", 0) or 0)
        self.model_version = str(getattr(output, "model_version", "") or "")

    def finish(self) -> None:
        elapsed = time.perf_counter() - self.started
        result = classify(self.error)
        self.elapsed = elapsed
        self.result = result
        CALLS.labels(self.product, self.model, result).inc()
        DURATION.labels(self.product, self.model).observe(elapsed)
        if self.input_tokens:
            TOKENS.labels(self.product, self.model, "input").inc(self.input_tokens)
        if self.output_tokens:
            TOKENS.labels(self.product, self.model, "output").inc(self.output_tokens)
        fields = {
            "product": self.product,
            **self.context,
            "model": self.model,
            "reasoning_effort": self.reasoning_effort or "",
            "duration_seconds": round(elapsed, 3),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "result": result,
            **_error_fields(self.error),
        }
        message = f"LLM 호출 product={self.product} model={self.model} result={result} duration={elapsed:.2f}s"
        # `core.json_logging.JsonFormatter` 가 `fields` 를 같은 줄 JSON 에 펼친다.
        logger.log(logging.INFO if result == "ok" else logging.WARNING, message, extra={"fields": fields})


@contextmanager
def observe_call(*, product: str, model: str, custom: bool, reasoning_effort: str | None, context: dict):
    call = _Call(product=product, model=model, custom=custom, reasoning_effort=reasoning_effort, context=context)
    IN_FLIGHT.labels(product).inc()
    try:
        yield call
    except BaseException as exc:
        call.error = exc
        raise
    finally:
        IN_FLIGHT.labels(product).dec()
        call.finish()
        ops_recorder().record_llm_call(**_minute_fields(call))


@asynccontextmanager
async def observe_call_async(*, product: str, model: str, custom: bool, reasoning_effort: str | None, context: dict):
    call = _Call(product=product, model=model, custom=custom, reasoning_effort=reasoning_effort, context=context)
    IN_FLIGHT.labels(product).inc()
    _ASYNC_IN_FLIGHT[product] += 1
    recorder = ops_recorder()
    try:
        # 안에서 부른다 — 이 await 에서 취소돼도 위의 두 수가 finally 에서 내려간다.
        await recorder.record_in_flight_async(product=product, count=_ASYNC_IN_FLIGHT[product])
        yield call
    except BaseException as exc:  # CancelledError(바깥 wait_for 의 한도)도 센다 — 아래에서 타임아웃으로 옮긴다.
        call.error = exc
        raise
    finally:
        IN_FLIGHT.labels(product).dec()
        _ASYNC_IN_FLIGHT[product] -= 1
        call.finish()
        await recorder.record_llm_call_async(**_minute_fields(call))


def async_in_flight(product: str) -> int:
    """이 프로세스에서 지금 벤더를 기다리는 비동기 호출 수 — grader 는 단일 프로세스라 이것이 전부다.
    1분 집계의 「동시 채점 최댓값」이 이 값을 쓴다(호출이 시작될 때, 그리고 grader heartbeat 마다)."""

    return _ASYNC_IN_FLIGHT[product]


def ops_recorder():
    """1분 집계 기록기(`ops_metrics.recorder`, #827) — prometheus 와 **나란히** 쓴다. 지연 import 인 것은
    그 모듈이 이 모듈의 경계 상수를 읽기 때문이다(순환을 끊는다)."""

    from ops_metrics import recorder

    return recorder


def _minute_fields(call: "_Call") -> dict:
    return {
        "product": call.product,
        "model": call.model,
        "result": call.result,
        "seconds": call.elapsed,
        "input_tokens": call.input_tokens,
        "output_tokens": call.output_tokens,
    }


def serve(port: int) -> None:
    """이 프로세스에 `/metrics` 엔드포인트를 연다(grader·celery 주 프로세스). `PROMETHEUS_MULTIPROC_DIR`
    가 있으면 자식 프로세스들의 파일을 합산해 낸다."""

    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        from prometheus_client import multiprocess

        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
        start_http_server(port, registry=registry)
    else:
        start_http_server(port, registry=REGISTRY)
    logger.info("LLM 지표 엔드포인트를 열었다: :%s", port)
