"""PG 어댑터 인터페이스 (ADR-0007).

돈이 새는 경로는 정상 흐름이 아니라 장애 흐름이다 — 웹훅 중복 수신, 웹훅이 결제
승인보다 먼저 도착, 지급 API 타임아웃 후 실제로는 성공. PG 샌드박스로는 이걸
재현할 수 없으므로 Fake PG가 이 세 가지를 의도적으로 주입할 수 있어야 한다.

dev/test는 `FakePGAdapter`로 바인딩된다(`PAYMENT_ADAPTER_MODE=fake`). 이 프로젝트의
다른 어댑터들(`verification.adapters.FakeVerificationAdapter`,
`accounts.social`의 fake 소셜 로그인)과 같은 원칙을 따른다 — Fake는 네트워크 없이
결정적으로 동작하고, 테스트는 요청 payload에 담긴 `simulate` 값으로 시나리오를
고른다.

`PGAdapter` 계약에는 `confirm`의 `simulate`만 남는다 — 이건 "PG에 무엇을
요청할지"의 일부이므로 실제 어댑터도 (쓰지 않더라도) 받아넘길 수 있는 자리다.
반면 `query_status`는 실서비스에서 order_id만으로 PG 서버에 직접 묻는 순수
조회이지 시나리오를 골라 넣는 자리가 아니다 — Fake가 confirm에서 무엇을
시뮬레이션했는지는 (같은 요청 안에서 재사용되는) 어댑터 인스턴스 자신이
기억한다. Protocol에 없는 키워드를 호출부가 넘기면 실제 토스 어댑터가
`TypeError`로 죽으므로, "PGAdapter 계약만 만족시키면 된다"는 문서화된 규칙이
실제로 지켜지려면 이 선을 지켜야 한다.

실제 토스 연동은 이 티켓 범위 밖이다(#87). `PGAdapter` 계약만 만족시키면 된다.

어댑터 선택은 `core.adapters.resolve_adapter`를 쓴다(#83) — scoring이 이미 쓰는
것과 같은 선택 방식이다. `PAYMENT_ADAPTER_MODE`가 `"fake"`면 Fake를, 아니면 그
값을 dotted path로 보고 실제 클래스를 import한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from django.conf import settings

from core.adapters import resolve_adapter


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


@runtime_checkable
class PGAdapter(Protocol):
    def request_payment(self, *, order_id: str, amount: int) -> PaymentRequestResult: ...

    def confirm(self, *, order_id: str, simulate: str | None = None) -> str:
        """PG에 결제 승인을 동기 요청한다. "paid" | "failed" 를 돌려준다.

        `PGTimeoutError`를 던질 수 있다 — 그 경우 호출자는 `query_status`로 실제
        결과를 확정해야 한다.
        """
        ...

    def query_status(self, *, order_id: str) -> str:
        """order_id의 실제 결제 상태를 조회한다. "paid" | "failed" | "pending" 중 하나.

        순수 조회다 — `simulate` 같은 시나리오 선택 인자를 받지 않는다. 이 자리에
        Fake 전용 키워드를 추가하면 이 계약대로 작성된 실제 어댑터가
        `query_status(order_id=...)`만 받다가 `TypeError`로 죽는다.
        """
        ...

    def refund(self, *, order_id: str, amount: int, simulate: str | None = None) -> str:
        """이미 승인된 결제를 환불한다. "refunded" | "failed" 를 돌려준다.

        `confirm`과 같은 규율이다 — `PGTimeoutError`를 던질 수 있고, 그 경우 호출자는
        `query_refund_status`로 실제 결과를 확정해야 한다(#17, ADR-0007).
        """
        ...

    def query_refund_status(self, *, order_id: str) -> str:
        """order_id의 실제 환불 상태를 조회한다. "refunded" | "failed" | "pending" 중 하나.

        `query_status`와 같은 규율의 순수 조회다 — 시나리오 선택 인자를 받지 않는다.
        """
        ...


class FakePGAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작하며 장애 흐름을 주입할 수 있다.

    `confirm`의 `simulate` 값:
    - None / "success" (기본) — 즉시 성공
    - "failed" — 즉시 실패
    - "timeout_then_success" — `confirm`은 타임아웃하지만 PG 쪽에서는 실제로
      성공했다. 뒤이어 같은 어댑터 인스턴스로 `query_status`를 부르면 "paid"가
      나온다.
    - "timeout_then_failed" — `confirm`은 타임아웃하고 PG 쪽에서도 실패했다.
      뒤이어 `query_status`를 부르면 "failed"가 나온다.

    "PG 쪽 실제 결과"는 `simulate` 인자를 `query_status`까지 다시 실어 나르는
    방식이 아니라, 이 인스턴스 자신의 상태(`_final_status`)에 기억해 둔다 —
    `payments.api.confirm_payment`가 `confirm`과 `query_status`를 같은
    어댑터 인스턴스로 순서대로 부르므로 이걸로 충분하고, `PGAdapter` 계약도
    실제 어댑터가 구현 가능한 모양 그대로 유지된다.
    """

    # 리뷰 지적 3: run_pending_refunds의 재확인 경로는 서로 다른 HTTP 요청(각각
    # get_adapter()로 새 인스턴스를 받는다)에 걸쳐 같은 환불 시도를 다시 물어야
    # 한다 — 실제 PG라면 그 결과가 PG 서버에 영속되어 있어 어느 인스턴스로 묻든
    # 같은 답을 받는다. Fake가 이를 흉내내려면 인스턴스가 아니라 클래스 레벨
    # (프로세스 전역)에 상태를 들어야 한다 — `_final_status`(결제 확인)는 항상
    # 같은 요청·같은 인스턴스 안에서만 confirm 다음에 query_status를 부르므로
    # 인스턴스 레벨로 충분하지만, `_final_refund_status`(환불)는 그렇지 않다.
    _final_refund_status: dict[str, str] = {}
    _QUERY_ERROR_SENTINEL = "__query_error__"

    def __init__(self) -> None:
        self._final_status: dict[str, str] = {}

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
        if scenario == "timeout_then_success":
            self._final_status[order_id] = "paid"
            raise PGTimeoutError(
                f"fake PG timed out on confirm(order_id={order_id}) — "
                "실제 결과는 query_status로 확정해야 한다."
            )
        if scenario == "timeout_then_failed":
            self._final_status[order_id] = "failed"
            raise PGTimeoutError(
                f"fake PG timed out on confirm(order_id={order_id}) — "
                "실제 결과는 query_status로 확정해야 한다."
            )
        raise PGError(f"알 수 없는 fake PG 시나리오: {scenario!r}")

    def query_status(self, *, order_id: str) -> str:
        return self._final_status.get(order_id, "pending")

    def refund(self, *, order_id: str, amount: int, simulate: str | None = None) -> str:
        """`confirm`과 같은 시나리오 이름을 쓰되 환불 어휘("refunded")로 돌려준다.

        - None / "success" (기본) — 즉시 환불 성공
        - "failed" — 즉시 환불 실패
        - "pending" — 예외 없이 즉시 "pending"을 돌려준다. PG가 요청은 접수했지만
          동기적으로 끝내지 못하는 실제 비동기 흐름을 흉내낸다(#17 리뷰 지적 3) —
          이후 별도의 스캔(run_pending_refunds의 재확인 경로)이나 웹훅이 확정할
          때까지 REFUND_REQUESTED로 남는다.
        - "timeout_then_success" — 이 호출은 타임아웃하지만 PG 쪽에서는 실제로
          환불에 성공했다. 뒤이어(같은 요청이든 다른 요청이든) `query_refund_status`
          를 부르면 "refunded"가 나온다.
        - "timeout_then_failed" — 이 호출은 타임아웃하고 PG 쪽에서도 환불에
          실패했다. 뒤이어 `query_refund_status`를 부르면 "failed"가 나온다.
        - "timeout_then_query_error" — 이 호출은 타임아웃하고, 뒤이은
          `query_refund_status` 호출조차 PG 쪽 오류로 실패한다(#17 리뷰 지적 2) —
          호출자가 그 오류를 잡지 못하면 스캔 전체가 죽는다는 것을 증명하는 용도다.
        """

        scenario = simulate or "success"
        if scenario == "success":
            return "refunded"
        if scenario == "failed":
            return "failed"
        if scenario == "pending":
            return "pending"
        if scenario == "timeout_then_success":
            self._final_refund_status[order_id] = "refunded"
            raise PGTimeoutError(
                f"fake PG timed out on refund(order_id={order_id}) — "
                "실제 결과는 query_refund_status로 확정해야 한다."
            )
        if scenario == "timeout_then_failed":
            self._final_refund_status[order_id] = "failed"
            raise PGTimeoutError(
                f"fake PG timed out on refund(order_id={order_id}) — "
                "실제 결과는 query_refund_status로 확정해야 한다."
            )
        if scenario == "timeout_then_query_error":
            self._final_refund_status[order_id] = self._QUERY_ERROR_SENTINEL
            raise PGTimeoutError(
                f"fake PG timed out on refund(order_id={order_id}) — "
                "실제 결과는 query_refund_status로 확정해야 한다."
            )
        raise PGError(f"알 수 없는 fake PG 환불 시나리오: {scenario!r}")

    def query_refund_status(self, *, order_id: str) -> str:
        status = self._final_refund_status.get(order_id, "pending")
        if status == self._QUERY_ERROR_SENTINEL:
            raise PGError(
                f"fake PG errored on query_refund_status(order_id={order_id}) — "
                "이 오류는 호출자가 잡아서 이 건만 건너뛰고 배치의 나머지는 계속 "
                "처리해야 한다(#17 리뷰 지적 2)."
            )
        return status

    @classmethod
    def resolve_pending_refund_for_testing(cls, order_id: str, status: str) -> None:
        """테스트 전용 — PG가 그 사이 실제로 환불을 확정한 상황을 흉내낸다.

        `FakePGAdapter`는 요청마다(`get_adapter()`) 새 인스턴스로 만들어지지만,
        진짜 PG라면 그 결과가 PG 서버에 영속되어 있어 어느 인스턴스로 조회하든
        같은 답을 받는다. run_pending_refunds의 재확인 경로(#17 리뷰 지적 3)가
        "이전 스캔이 미확정으로 남긴 건을 나중 스캔이 마저 확정한다"는 것을
        증명하려면, "그 사이 PG가 확정했다"는 사실 자체를 테스트가 주입할 방법이
        있어야 한다 — `core.models.ClockOverride`로 시간을 앞당기는 것과 같은
        성격의, 애플리케이션 동작이 아니라 (Fake가 흉내내는) 외부 시스템 상태를
        준비하는 픽스처다.
        """

        cls._final_refund_status[order_id] = status


def get_adapter() -> PGAdapter:
    return resolve_adapter(
        mode=settings.PAYMENT_ADAPTER_MODE,
        fake_factory=FakePGAdapter,
        not_implemented_hint=(
            "실제 토스페이먼츠 연동은 아직 구현되지 않았다 — PGAdapter 계약만 만족시키는 "
            "dotted path를 PAYMENT_ADAPTER_MODE에 설정하면 된다 (ADR-0007). 샌드박스 "
            "연동은 #87의 범위다."
        ),
    )
