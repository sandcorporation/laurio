"""운영 지표를 그 분의 Redis 해시에 더한다(#827) — prometheus 계측(`core.llm_metrics`)과 **나란히** 쓴다.

**키 규칙.** `ops:<종류>:<분 시작의 epoch 초(UTC)>` 해시 하나가 한 분이다. 필드는 `라벨|…|지표` 다:

| 종류 | 필드 | 지표 |
| --- | --- | --- |
| `llm` | `<product>|<model>|<result>|<지표>` | `n` 호출 수 · `ms` 지연 합(밀리초) · `in`/`out` 토큰 · `b<i>` 지연 칸 |
| `llmq` | `<product>|<지표>` | `n` 대기 수 · `ms` 대기 합 · `b<i>` 대기 칸 · `max_inflight` 동시 채점 최댓값 |
| `req` | `<method>|<route>|<status>|<지표>` | `n` 요청 수 · `ms` 지연 합 · `b<i>` 지연 칸(`core.metrics.DURATION_BOUNDS`) — #828, `request_buffer` |

`b<i>` 는 경계(`llm_metrics.DURATION_BOUNDS`·`QUEUE_WAIT_BOUNDS`)의 i 번째 칸 — 값이 그 경계 이하인
첫 칸이고, 마지막 칸(i = 경계 수)이 +Inf 다. `max_` 로 시작하는 지표는 더하지 않고 큰 값을 남긴다
(flush 도 같은 규칙으로 DB 에 합친다). 새 종류는 같은 꼴로 `ops:<종류>:` 를 더하고
`flush.KINDS` 에 옮기는 함수를 단다.

생존 신호는 낱값 `ops:heartbeat:<이름>` = 마지막으로 산 epoch 초(TTL `OPS_METRICS_HEARTBEAT_TTL_SECONDS`).

**Redis 가 실패해도 채점은 막히지 않는다.** 여기 함수는 예외를 내지 않는다 — 그 기록을 버리고, 실패가
이어지는 동안 경고 로그를 한 번만 남긴다(다시 성공하면 다음 실패에 또 한 번).
"""

from __future__ import annotations

import logging
import time
from bisect import bisect_left

from django.conf import settings

from core.llm_metrics import DURATION_BOUNDS, QUEUE_WAIT_BOUNDS

from .store import get_store

logger = logging.getLogger("codemit.ops_metrics")

KEY_PREFIX = "ops"
LLM = "llm"
LLM_QUEUE = "llmq"
REQUEST = "req"
MAX_PREFIX = "max_"

_failing = False


def minute_of(ts: float) -> int:
    return int(ts // 60) * 60


def minute_key(kind: str, minute: int) -> str:
    return f"{KEY_PREFIX}:{kind}:{minute}"


def heartbeat_key(name: str) -> str:
    return f"{KEY_PREFIX}:heartbeat:{name}"


def bucket_index(bounds: tuple, value: float) -> int:
    return bisect_left(bounds, value)


def _label(value: str) -> str:
    return str(value).replace("|", "_")


def _ok() -> None:
    global _failing
    _failing = False


def _failed(exc: BaseException) -> None:
    global _failing
    if not _failing:
        logger.warning("운영 지표를 Redis 에 쓰지 못해 버린다(채점·응답은 계속된다): %s", type(exc).__name__)
    _failing = True


def llm_call_fields(*, product, model, result, seconds, input_tokens, output_tokens) -> dict[str, int]:
    prefix = f"{_label(product)}|{_label(model)}|{_label(result)}"
    fields = {
        f"{prefix}|n": 1,
        f"{prefix}|ms": int(round(max(seconds, 0.0) * 1000)),
        f"{prefix}|b{bucket_index(DURATION_BOUNDS, seconds)}": 1,
    }
    if input_tokens:
        fields[f"{prefix}|in"] = int(input_tokens)
    if output_tokens:
        fields[f"{prefix}|out"] = int(output_tokens)
    return fields


def queue_wait_fields(*, product, seconds) -> dict[str, int]:
    prefix = _label(product)
    return {
        f"{prefix}|n": 1,
        f"{prefix}|ms": int(round(max(seconds, 0.0) * 1000)),
        f"{prefix}|b{bucket_index(QUEUE_WAIT_BOUNDS, seconds)}": 1,
    }


def _key(kind: str, at: float | None) -> str:
    return minute_key(kind, minute_of(time.time() if at is None else at))


def _add(kind: str, increments: dict, maxes: dict, at: float | None) -> None:
    try:
        get_store().add(_key(kind, at), increments, maxes, settings.OPS_METRICS_KEY_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - 지표가 채점을 막으면 안 된다
        _failed(exc)
    else:
        _ok()


async def _add_async(kind: str, increments: dict, maxes: dict, at: float | None) -> None:
    try:
        await get_store().add_async(_key(kind, at), increments, maxes, settings.OPS_METRICS_KEY_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001 - 지표가 채점을 막으면 안 된다
        _failed(exc)
    else:
        _ok()


# --- 호출 지점 --------------------------------------------------------------------------


def record_llm_call(*, product, model, result, seconds, input_tokens=0, output_tokens=0, at=None) -> None:
    fields = llm_call_fields(
        product=product, model=model, result=result, seconds=seconds, input_tokens=input_tokens, output_tokens=output_tokens
    )
    _add(LLM, fields, {}, at)


async def record_llm_call_async(*, product, model, result, seconds, input_tokens=0, output_tokens=0, at=None) -> None:
    fields = llm_call_fields(
        product=product, model=model, result=result, seconds=seconds, input_tokens=input_tokens, output_tokens=output_tokens
    )
    await _add_async(LLM, fields, {}, at)


async def record_queue_wait_async(*, product, seconds, at=None) -> None:
    await _add_async(LLM_QUEUE, queue_wait_fields(product=product, seconds=seconds), {}, at)


async def record_in_flight_async(*, product, count, at=None) -> None:
    await _add_async(LLM_QUEUE, {}, {f"{_label(product)}|{MAX_PREFIX}inflight": int(count)}, at)


async def beat_async(name: str, *, at: float | None = None) -> None:
    """생존 신호 — grader 가 `OPS_METRICS_HEARTBEAT_SECONDS` 마다 부른다."""

    now = time.time() if at is None else at
    try:
        await get_store().set_value_async(heartbeat_key(name), str(int(now)), settings.OPS_METRICS_HEARTBEAT_TTL_SECONDS)
    except Exception as exc:  # noqa: BLE001
        _failed(exc)
    else:
        _ok()


def last_beat(name: str) -> int | None:
    """마지막 생존 신호의 epoch 초 — 없거나(TTL 이 지났다) 읽지 못하면 None. 경보(#830)가 읽는다."""

    try:
        value = get_store().get_value(heartbeat_key(name))
    except Exception as exc:  # noqa: BLE001
        _failed(exc)
        return None
    return int(value) if value else None
