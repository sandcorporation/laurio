"""토스 지급대행 어댑터 인터페이스 (#15, ADR-0007, ADR-0008).

`payments.adapters`(#9)를 그대로 본뜬다 — 돈이 새는 경로는 정상 흐름이 아니라
장애 흐름이라는 원칙이 지급에도 똑같이 적용된다: 웹훅 중복 수신, 웹훅이 동기
확인보다 먼저 도착, 지급 API 타임아웃 후 실제로는 성공. Fake 어댑터가 이 세
가지를 의도적으로 주입할 수 있어야 한다.

dev/test는 `FakePayoutAdapter`로 바인딩된다(`PAYOUT_ADAPTER_MODE=fake`).
`request_payout`/`confirm`/`query_status`의 삼분할과 "confirm이 던지는
PayoutTimeoutError는 query_status로 확정해야 한다"는 규율까지 `payments.adapters`와
동일하다 — 벤더만 다를 뿐 어댑터 계약의 모양은 재사용한다.

실제 토스 지급대행 연동은 이 티켓 범위 밖이다(#82 라운드 2). `PayoutAdapter` 계약만
만족시키면 된다.

어댑터 선택은 `core.adapters.resolve_adapter`를 쓴다(#83) — scoring이 이미 쓰는
것과 같은 선택 방식이다. `PAYOUT_ADAPTER_MODE`가 `"fake"`면 Fake를, 아니면 그
값을 dotted path로 보고 실제 클래스를 import한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from django.conf import settings

from core.adapters import resolve_adapter


class PayoutError(Exception):
    """토스가 지급 요청·확인을 명시적으로 거부했을 때."""


class PayoutTimeoutError(Exception):
    """토스 호출이 타임아웃됐다.

    응답을 받지 못했을 뿐 실제 처리 결과는 알 수 없다 — 호출자는 이걸 실패로
    간주해서는 안 되고, `query_status`로 실제 상태를 조회해 확정해야 한다.
    """


@dataclass(frozen=True)
class PayoutRequestResult:
    idempotency_key: str
    accepted: bool


class PayoutAdapter(Protocol):
    def request_payout(self, *, idempotency_key: str, amount: int) -> PayoutRequestResult: ...

    def confirm(self, *, idempotency_key: str, simulate: str | None = None) -> str:
        """토스에 지급 결과를 동기 확인한다. "paid" | "failed" 를 돌려준다.

        `PayoutTimeoutError`를 던질 수 있다 — 그 경우 호출자는 `query_status`로
        실제 결과를 확정해야 한다.
        """
        ...

    def query_status(self, *, idempotency_key: str) -> str:
        """idempotency_key의 실제 지급 상태를 조회한다.

        "paid" | "failed" | "pending" 중 하나. 순수 조회다 — `simulate` 같은
        시나리오 선택 인자를 받지 않는다.
        """
        ...


class FakePayoutAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작하며 장애 흐름을 주입할 수 있다.

    `confirm`의 `simulate` 값(`payments.adapters.FakePGAdapter`와 동일한 어휘):
    - None / "success" (기본) — 즉시 성공
    - "failed" — 즉시 실패
    - "timeout_then_success" — `confirm`은 타임아웃하지만 토스 쪽에서는 실제로
      성공했다. 뒤이어 같은 어댑터 인스턴스로 `query_status`를 부르면 "paid"가
      나온다.
    - "timeout_then_failed" — `confirm`은 타임아웃하고 토스 쪽에서도 실패했다.
    """

    def __init__(self) -> None:
        self._final_status: dict[str, str] = {}

    def request_payout(self, *, idempotency_key: str, amount: int) -> PayoutRequestResult:
        return PayoutRequestResult(idempotency_key=idempotency_key, accepted=True)

    def confirm(self, *, idempotency_key: str, simulate: str | None = None) -> str:
        scenario = simulate or "success"
        if scenario == "success":
            return "paid"
        if scenario == "failed":
            return "failed"
        if scenario == "timeout_then_success":
            self._final_status[idempotency_key] = "paid"
            raise PayoutTimeoutError(
                f"fake 토스 지급대행이 confirm(idempotency_key={idempotency_key})에서 "
                "타임아웃했다 — 실제 결과는 query_status로 확정해야 한다."
            )
        if scenario == "timeout_then_failed":
            self._final_status[idempotency_key] = "failed"
            raise PayoutTimeoutError(
                f"fake 토스 지급대행이 confirm(idempotency_key={idempotency_key})에서 "
                "타임아웃했다 — 실제 결과는 query_status로 확정해야 한다."
            )
        raise PayoutError(f"알 수 없는 fake 토스 지급대행 시나리오: {scenario!r}")

    def query_status(self, *, idempotency_key: str) -> str:
        return self._final_status.get(idempotency_key, "pending")


def get_adapter() -> PayoutAdapter:
    return resolve_adapter(
        mode=settings.PAYOUT_ADAPTER_MODE,
        fake_factory=FakePayoutAdapter,
        not_implemented_hint=(
            "실제 토스 지급대행 연동은 아직 구현되지 않았다 — PayoutAdapter 계약만 "
            "만족시키는 dotted path를 PAYOUT_ADAPTER_MODE에 설정하면 된다"
            "(ADR-0007/0008)."
        ),
    )
