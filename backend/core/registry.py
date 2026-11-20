"""기능 앱이 공유층에 제 구현을 올리는 한 모양(#1085, spec #1079 결정 4) — 자리 하나(`Slot`)와 이름별 자리(`Slots`).

공유층은 기능 앱을 import 하지 않고 자리를 선언만 한다. 기능 앱은 `AppConfig.ready()` 에서 `register` 한다. 웹·celery·
`manage.py` 명령 모두 `django.setup()` 이 `ready()` 를 먼저 돌리므로, 부를 때는 이미 올라 있다.

- `Slot.get()` 은 비었으면 `PortNotRegistered` 로 멈춘다 — 조용히 비켜 가지 않는다.
- `Slots.get(key)` 는 없는 이름에 `None` 이다 — 모르는 이름이 정상 입력인 자리(target_ref 접두어 등)를 위한 것이다.
"""

from __future__ import annotations

from typing import Generic, TypeVar

T = TypeVar("T")


class PortNotRegistered(RuntimeError):
    """기능 앱이 아직 올리지 않은 자리를 불렀다 — 그 앱이 INSTALLED_APPS 에 없거나 Django 가 뜨기 전이다."""


class Slot(Generic[T]):
    """구현 하나가 올라오는 자리. `owner` 는 올리는 곳(오류 문구에 쓴다)."""

    def __init__(self, name: str, owner: str) -> None:
        self.name = name
        self.owner = owner
        self._value: T | None = None

    def register(self, value: T) -> None:
        self._value = value

    def get(self) -> T:
        if self._value is None:
            raise PortNotRegistered(f"{self.name} 이(가) 등록되지 않았다({self.owner})")
        return self._value


class Slots(Generic[T]):
    """이름(접두어 등)마다 구현 하나가 올라오는 자리."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._values: dict[str, T] = {}

    def register(self, key: str, value: T) -> None:
        self._values[key] = value

    def get(self, key: str) -> T | None:
        return self._values.get(key)

    def as_dict(self) -> dict[str, T]:
        return dict(self._values)
