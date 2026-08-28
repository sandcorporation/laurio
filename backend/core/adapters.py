"""어댑터 모드(fake/dotted-path) 선택 공용 헬퍼 (ADR-0007).

PG·스토리지·LLM 등 외부 의존성은 전부 같은 모양으로 갈아끼운다: 설정값이
`"fake"`면 결정적인 fake 구현체를, 아니면 그 값을 dotted path로 보고
`import_string`으로 실제 구현체를 불러온다. 이 선택 로직 자체를 각 앱(`scoring`,
`contests`)이 따로 구현하지 않고 여기서 하나로 공유한다 — #20(AI grill)이
두 번째 LLM 연동을 만들지 않고 #12(AI 채점)가 이미 쓰는 것과 같은 선택 방식을
재사용하기 위해서다.
"""

from __future__ import annotations

from typing import Callable, TypeVar

from django.utils.module_loading import import_string

T = TypeVar("T")


def resolve_adapter(*, mode: str, fake_factory: Callable[[], T], not_implemented_hint: str) -> T:
    """`mode`가 `"fake"`면 `fake_factory()`를, 아니면 dotted path를 import해 인스턴스화한다."""

    if mode == "fake":
        return fake_factory()
    try:
        return import_string(mode)()
    except ImportError as exc:
        raise NotImplementedError(not_implemented_hint) from exc
