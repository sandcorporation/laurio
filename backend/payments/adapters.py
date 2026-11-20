"""PG 어댑터의 옛 자리 — 몸은 `ledger.pg` 로 옮겼다(#1086, contests ↔ payments 순환 끊기).

이 모듈은 이름만 다시 내놓는다. `PAYMENT_ADAPTER_MODE` 는 dotted path 를 받는 값이라 배포 환경·시험이
`payments.adapters.FakePGAdapter` 같은 경로를 들고 있다 — 그 경로가 같은 클래스를 가리키도록 남긴다.
새 코드는 `ledger.pg` 를 import 한다.
"""

from __future__ import annotations

from ledger.pg import (
    FakePGAdapter,
    PaymentRequestResult,
    PGAdapter,
    PGError,
    PGTimeoutError,
    checkout_flow_for_current_mode,
    get_adapter,
)

__all__ = [
    "FakePGAdapter",
    "PGAdapter",
    "PGError",
    "PGTimeoutError",
    "PaymentRequestResult",
    "checkout_flow_for_current_mode",
    "get_adapter",
]
