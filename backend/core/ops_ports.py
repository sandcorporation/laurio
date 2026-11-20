"""공유층이 위 앱(운영 지표·정책)을 import 하지 않고 부르는 자리 셋 — #1086, spec #1079.

`ops_metrics`·`policies` 는 `core`(시계·지표 경계·스캔 등록부) 위에 선다. `core` 가 그 둘을 다시 import 하면
`core ↔ ops_metrics`·`core ↔ policies` 가 한 순환이 된다. 그래서 위 앱이 `ready()` 에서 모듈(또는 함수)을 이
자리에 올리고 `core` 는 부를 때 꺼낸다. 모듈을 올리는 자리는 부를 때 모듈 속성을 읽으므로, 그 모듈의 함수를
바꿔 끼운 시험도 그대로 듣는다.

- `OPS_RECORDER` — 1분 집계 기록기(`ops_metrics.recorder`, #827). `core.llm_metrics` 가 쓴다.
- `REQUEST_RECORDER` — 요청 1분 집계 버퍼(`ops_metrics.request_buffer`, #828). `core.metrics.MetricsMiddleware` 가 쓴다.
- `SCAN_SCOPE` — 스캔 실행 하나를 감싸는 정책 스코프(`policies.scope.policy_scope`, #145). `core.scans` 가 쓴다.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Protocol

from core.registry import Slot


class OpsRecorder(Protocol):
    """`core` 가 쓰는 `ops_metrics.recorder` 의 셋."""

    def record_llm_call(
        self, *, product: str, model: str, result: str, seconds: float, input_tokens: int = 0, output_tokens: int = 0
    ) -> None: ...

    async def record_llm_call_async(
        self, *, product: str, model: str, result: str, seconds: float, input_tokens: int = 0, output_tokens: int = 0
    ) -> None: ...

    async def record_in_flight_async(self, *, product: str, count: int) -> None: ...


class RequestRecorder(Protocol):
    """`core` 가 쓰는 `ops_metrics.request_buffer` 의 하나."""

    def record_request(self, *, method: str, route: str, status: int, seconds: float) -> None: ...


OPS_RECORDER: Slot[OpsRecorder] = Slot("1분 집계 기록기", "ops_metrics.apps")
REQUEST_RECORDER: Slot[RequestRecorder] = Slot("요청 1분 집계", "ops_metrics.apps")
SCAN_SCOPE: Slot[Callable[[], AbstractContextManager[None]]] = Slot("스캔 정책 스코프", "policies.apps")
