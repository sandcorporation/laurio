"""운영 설정 읽기 자리 — `core` 가 `policies.runtime_settings` 를 import 하지 않고 부른다(#1086, spec #1079).

`policies.runtime_settings` 는 `core`(암호화·시계·어댑터 표식) 위에 선다. `core` 의 채점·프록시·저장소 다운로드가
그 모듈을 다시 import 하면 `core ↔ policies` 가 한 순환이 된다. 그래서 `policies.apps` 가 `ready()` 에서 모듈을
그대로 이 자리에 올리고, `core` 는 부를 때마다 여기서 꺼낸다 — 부를 때 모듈 속성을 읽으므로
`policies.runtime_settings` 의 함수를 바꿔 끼운 시험도 그대로 듣는다.

벤더 값(`ScoringVendor`·`VENDOR_*`)은 이 모듈이 원본이다 — `policies.runtime_settings` 가 여기서 가져다 쓴다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

from core.registry import Slot

ScoringVendor = Literal["openai", "anthropic"]
VENDOR_OPENAI: ScoringVendor = "openai"
VENDOR_ANTHROPIC: ScoringVendor = "anthropic"


class RuntimeSettings(Protocol):
    """`core` 가 쓰는 `policies.runtime_settings` 의 넷."""

    def setting_value(self, key: str) -> str | None: ...

    def scoring_vendor(self) -> ScoringVendor: ...

    def agent_scoring_daily_limit_usd(self) -> Decimal: ...

    def repository_download_limit_bytes(self) -> int: ...


RUNTIME_SETTINGS: Slot[RuntimeSettings] = Slot("운영 설정 읽기", "policies.apps")


def setting_value(key: str) -> str | None:
    return RUNTIME_SETTINGS.get().setting_value(key)


def scoring_vendor() -> ScoringVendor:
    return RUNTIME_SETTINGS.get().scoring_vendor()


def agent_scoring_daily_limit_usd() -> Decimal:
    return RUNTIME_SETTINGS.get().agent_scoring_daily_limit_usd()


def repository_download_limit_bytes() -> int:
    return RUNTIME_SETTINGS.get().repository_download_limit_bytes()
