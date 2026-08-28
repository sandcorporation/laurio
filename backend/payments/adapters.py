"""PG 어댑터 인터페이스 (ADR-0007).

돈이 새는 경로는 정상 흐름이 아니라 장애 흐름이다 — 웹훅 중복 수신, 웹훅이 결제
승인보다 먼저 도착, 지급 API 타임아웃 후 실제로는 성공. PG 샌드박스로는 이걸
재현할 수 없으므로 Fake PG가 이 세 가지를 의도적으로 주입할 수 있어야 한다.

dev/test는 `FakePGAdapter`로 바인딩된다(`PAYMENT_ADAPTER_MODE=fake`). 이 프로젝트의
다른 어댑터들(`verification.adapters.FakeVerificationAdapter`,
`accounts.social`의 fake 소셜 로그인)과 같은 원칙을 따른다 — Fake는 네트워크 없이
결정적으로 동작하고, 테스트는 요청 payload에 담긴 `simulate` 값으로 시나리오를
고른다. 이 프로젝트의 유일한 테스트 시임은 HTTP이므로, Fake의 동작은 어댑터 내부
상태가 아니라 API에 넘어온 값으로만 결정된다.

실제 토스 연동은 이 티켓 범위 밖이다(#23). `PGAdapter` 계약만 만족시키면 된다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class PGError(Exception):
    """PG가 결제 요청·승인을 명시적으로 거부했을 때."""


class PGTimeoutError(Exception):
    """PG 호출이 타임아웃됐다.

    응답을 받지 못했을 뿐 실제 처리 결과는 알 수 없다 — 호출자는 이걸 실패로
    간주해서는 안 되고, `query_status`로 실제 상태를 조회해 확정해야 한다
    (ADR-0008이 지급 웹훅에 적용한 것과 같은 규율을 결제 확인에도 적용한다).
    """


@dataclass(frozen=True)
class PaymentRequestResult:
    order_id: str
    checkout_url: str


class PGAdapter(Protocol):
    def request_payment(self, *, order_id: str, amount: int) -> PaymentRequestResult: ...

    def confirm(self, *, order_id: str, simulate: str | None = None) -> str:
        """PG에 결제 승인을 동기 요청한다. "paid" | "failed" 를 돌려준다.

        `PGTimeoutError`를 던질 수 있다 — 그 경우 호출자는 `query_status`로 실제
        결과를 확정해야 한다.
        """
        ...

    def query_status(self, *, order_id: str) -> str:
        """order_id의 실제 결제 상태를 조회한다. "paid" | "failed" | "pending" 중 하나."""
        ...


class FakePGAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작하며 장애 흐름을 주입할 수 있다.

    `simulate` 값:
    - None / "success" (기본) — 즉시 성공
    - "failed" — 즉시 실패
    - "timeout_then_success" — `confirm`은 타임아웃하지만 PG 쪽에서는 실제로
      성공했다. `query_status`를 부르면 "paid"가 나온다.
    - "timeout_then_failed" — `confirm`은 타임아웃하고 PG 쪽에서도 실패했다.
      `query_status`를 부르면 "failed"가 나온다.

    "PG 쪽 실제 결과"를 어댑터 인스턴스 상태로 들고 있지 않는다 — 요청마다 새
    어댑터가 만들어질 수 있으므로(장고 요청 사이클마다), `simulate` 값 자체가
    "PG 쪽 진실"을 인코딩한다. `query_status`는 오직 그 문자열만 보고 결정적으로
    답한다.
    """

    def request_payment(self, *, order_id: str, amount: int) -> PaymentRequestResult:
        return PaymentRequestResult(
            order_id=order_id, checkout_url=f"https://fake-pg.test/checkout/{order_id}"
        )

    def confirm(self, *, order_id: str, simulate: str | None = None) -> str:
        scenario = simulate or "success"
        if scenario == "success":
            return "paid"
        if scenario == "failed":
            return "failed"
        if scenario in ("timeout_then_success", "timeout_then_failed"):
            raise PGTimeoutError(
                f"fake PG timed out on confirm(order_id={order_id}) — "
                "실제 결과는 query_status로 확정해야 한다."
            )
        raise PGError(f"알 수 없는 fake PG 시나리오: {scenario!r}")

    def query_status(self, *, order_id: str, simulate: str | None = None) -> str:
        # 실서비스라면 이 조회는 order_id만으로 PG 서버에 직접 묻는다. Fake는 네트워크가
        # 없으므로 "타임아웃 뒤 실제 결과"를 알려면 그 시나리오를 다시 넘겨받아야 한다 —
        # 호출자(`payments.services`)가 confirm에 쓴 것과 같은 `simulate` 값을 그대로
        # 전달한다.
        if simulate == "timeout_then_success":
            return "paid"
        if simulate == "timeout_then_failed":
            return "failed"
        return "pending"


def get_adapter() -> PGAdapter:
    from django.conf import settings

    if settings.PAYMENT_ADAPTER_MODE == "fake":
        return FakePGAdapter()
    raise NotImplementedError(
        "실제 토스페이먼츠 연동은 아직 구현되지 않았다 — PGAdapter 계약만 만족시키면 "
        "된다 (ADR-0007). 샌드박스 연동은 #23의 범위다."
    )
