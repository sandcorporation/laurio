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


class VerificationMissingCIError(VerificationAdapterError):
    """본인확인 응답에 CI가 없을 때(#84).

    `VerificationAdapterError`의 하위 타입이므로 `verification.api.verify`의
    기존 예외 처리에 새 분기 없이 그대로 걸린다. CI 없는 응답은 정상 운영에서
    나오면 안 된다 — 실제 벤더(KG이니시스 통합인증)는 카카오 인증에서만 CI를
    주지 않고, 이 플랫폼은 카카오를 본인확인 수단에서 뺐다(ADR-0024). 그래서
    이 예외가 실제로 터졌다면 사용자 잘못이 아니라 벤더 콘솔의 인증 수단 설정이
    되돌려졌다는 뜻이다 — 호출자가 ERROR로 로그를 남겨야 한다.
    """


@dataclass(frozen=True)
class VerificationResult:
    """본인확인 결과 계약.

    `ci`가 빈 문자열이면 생성 자체가 실패한다(#84) — `Verification.set_ci("")`가
    `HMAC(key, "")`라는 정상적인 64자 hex를 만들어, CI 없는 사용자 전원이 같은
    해시를 갖고 서로 남남인 Sponsor와 Developer가 동일인으로 오차단되는 결함의
    근본 원인을 계약 타입 단계에서 막는다. 지금 있는 어댑터도, 나중에 누가
    추가하는 어댑터도 이 가드를 우회할 수 없다.
    """

    real_name: str
    birth_date: date
    ci: str
    di: str

    def __post_init__(self) -> None:
        if not self.ci:
            raise VerificationMissingCIError(
                "본인확인 응답에 CI가 없다 — CI를 주지 않는 인증 수단은 본인확인으로 "
                "인정하지 않는다(ADR-0024)."
            )


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
