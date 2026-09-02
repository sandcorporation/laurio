"""본인확인 어댑터 인터페이스 (ADR-0007, #83).

실제 PortOne 통합인증 연동은 이 티켓 범위 밖이다(#85). 인터페이스만 정의하고
dev/test는 fake로 바인딩한다. 실제 구현체가 필요해지면 이 `VerificationAdapter`
계약만 만족시키면 된다.

어댑터 선택은 `core.adapters.resolve_adapter`를 쓴다 — scoring이 이미 쓰는 것과
같은 선택 방식이다(#83). `VERIFICATION_ADAPTER_MODE`가 `"fake"`면 Fake를, 아니면
그 값을 dotted path로 보고 실제 클래스를 import한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol, runtime_checkable

from django.conf import settings

from core.adapters import resolve_adapter


class VerificationAdapterError(Exception):
    """제공자가 본인확인 토큰을 거부했거나 파싱할 수 없을 때."""


@dataclass(frozen=True)
class VerificationResult:
    real_name: str
    birth_date: date
    ci: str
    di: str


@runtime_checkable
class VerificationAdapter(Protocol):
    def resolve(self, verification_token: str) -> VerificationResult: ...


class FakeVerificationAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작한다.

    토큰 형식: ``"<실명>|<YYYY-MM-DD>|<ci>|<di>"``.
    """

    def resolve(self, verification_token: str) -> VerificationResult:
        parts = verification_token.split("|")
        if len(parts) != 4:
            raise VerificationAdapterError(
                "fake verification token must be '<name>|<YYYY-MM-DD>|<ci>|<di>'"
            )
        real_name, birth_iso, ci, di = parts
        if not real_name or not ci or not di:
            raise VerificationAdapterError("fake verification token missing fields")
        try:
            birth_date = date.fromisoformat(birth_iso)
        except ValueError as exc:
            raise VerificationAdapterError("fake verification token has an invalid date") from exc
        return VerificationResult(real_name=real_name, birth_date=birth_date, ci=ci, di=di)


def get_adapter() -> VerificationAdapter:
    return resolve_adapter(
        mode=settings.VERIFICATION_ADAPTER_MODE,
        fake_factory=FakeVerificationAdapter,
        not_implemented_hint=(
            "실제 본인확인 연동은 아직 구현되지 않았다 — VerificationAdapter 계약만 "
            "만족시키는 dotted path를 VERIFICATION_ADAPTER_MODE에 설정하면 된다 "
            "(ADR-0007)."
        ),
    )
