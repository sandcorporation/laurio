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
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from policies.models import PlatformPolicy

from django.conf import settings

from core.adapters import resolve_adapter


class PayoutError(Exception):
    """토스가 지급 요청·확인을 명시적으로 거부했을 때."""


class PayoutTimeoutError(PayoutError):
    """토스 호출이 타임아웃됐다.

    응답을 받지 못했을 뿐 실제 처리 결과는 알 수 없다 — 호출자는 이걸 실패로
    간주해서는 안 되고, `query_status`로 실제 상태를 조회해 확정해야 한다.

    `PayoutError`의 서브클래스다(코드리뷰 지적 5) — `except PayoutTimeoutError`가
    항상 `except PayoutError`보다 먼저 걸리도록 호출부가 이미 순서를 지키고
    있으므로(`payouts.api.confirm_payout`, `payouts.services.
    _request_real_transfer_if_ready`) 기존 분기 동작은 그대로다. 서브클래스가
    아니었을 때는 `query_status`가 다시 타임아웃하면 그 `PayoutTimeoutError`가
    `except PayoutError`에 잡히지 않고 `transaction.atomic()` 블록 밖으로 새어
    나가 이미 커밋 대기 중이던 원장 분개까지 롤백시켰다.
    """


@dataclass(frozen=True)
class TransferRequest:
    """caller 가 실어 보내는 실이체 요청 (#134/#135, ADR-0020 보완).

    adapter 는 이 밖의 것을 모른다 — Payout 도 Seller 도 읽지 않는다. 수취인·금액·벤더 참조를
    caller(`payouts.progress`)가 조립해 넘기므로 Fake 와 실물이 같은 요청을 받고 같은 응답을
    돌려준다 — 두 adapter 가 진짜로 교체 가능한 seam 이 된다.
    """

    idempotency_key: str
    amount: int
    # Seller 의 지급대행사 식별자. 비어 있으면 아직 수취인이 없다 — 벤더는 이체를 받을 수 없고
    # (sellerId 없이는 이체 API 가 없다), 이 요청은 「Laurio 내부 확정」이 된다.
    seller_id: str
    # 벤더에 보내는 참조 — `{idempotency_key}-{transfer_attempt}`. 재시도마다 달라야 한다
    # (같은 값을 재사용하면 벤더가 예전 FAILED 응답을 그대로 재생한다).
    vendor_ref: str
    # 벤더가 이전 응답으로 준 자기 식별자. 있으면 조회는 이것으로, 없으면 vendor_ref 로.
    vendor_payout_id: str = ""


@dataclass(frozen=True)
class VendorResult:
    """벤더가 말한 것 — "paid" | "failed" | "pending", 그리고 벤더가 발급한 자기 식별자(있으면).
    caller 가 이 식별자를 Payout 에 저장한다 — adapter 는 DB 를 쓰지 않는다."""

    status: str
    vendor_payout_id: str = ""


@runtime_checkable
class PayoutAdapter(Protocol):
    def confirm(self, request: TransferRequest, *, simulate: str | None = None) -> VendorResult:
        """이 요청을 벤더에 동기 확인한다.

        `status` 는 "paid" | "failed" | "pending". `request.seller_id` 가 비어 있으면 벤더는 이체를
        받을 수 없으므로 실물 adapter 는 HTTP 없이 "paid"(내부 확정)를 돌려준다.
        `PayoutTimeoutError` 를 던질 수 있다 — 그 경우 caller 는 `query_status` 로 실제 결과를
        확정한다. `PayoutError` 는 벤더의 명시적 거절이다.
        """
        ...

    def query_status(self, request: TransferRequest) -> VendorResult:
        """이 요청(의 attempt)의 실제 상태를 조회한다. 순수 조회 — `simulate` 를 받지 않는다."""
        ...


class FakePayoutAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작하며 장애 흐름을 주입할 수 있다.

    `confirm`의 `simulate` 값(`payments.adapters.FakePGAdapter`와 동일한 어휘):
    - None / "success" (기본) — 즉시 성공
    - "failed" — 즉시 실패
    - "timeout_then_success" — `confirm`은 타임아웃하지만 토스 쪽에서는 실제로
      성공했다. 뒤이어 같은 어댑터 인스턴스로 `query_status`를 부르면 "paid"가 나온다.
    - "timeout_then_failed" — `confirm`은 타임아웃하고 토스 쪽에서도 실패했다.
    - "timeout_then_query_error" — `confirm`도 타임아웃하고 뒤이은 `query_status`도
      실패한다(#125). 재확인 자체가 죽는 실물 경로를 흉내낸다.

    Seller 가 있든 없든 시나리오대로 답한다 — 실물과 달리 "수취인이 없어 내부 확정" 갈래를
    흉내내지 않는다. 그 갈래를 흉내내려면 테스트가 `request.seller_id` 를 보는 더블을 쓴다.
    """

    _QUERY_ERROR = "__query_error__"

    def __init__(self) -> None:
        self._final_status: dict[str, str] = {}

    def confirm(self, request: TransferRequest, *, simulate: str | None = None) -> VendorResult:
        scenario = simulate or "success"
        key = request.idempotency_key
        if scenario == "success":
            return VendorResult(status="paid")
        if scenario == "failed":
            return VendorResult(status="failed")
        if scenario == "timeout_then_success":
            self._final_status[key] = "paid"
            raise PayoutTimeoutError(
                f"fake 토스 지급대행이 confirm(idempotency_key={key})에서 타임아웃했다 — "
                "실제 결과는 query_status로 확정해야 한다."
            )
        if scenario == "timeout_then_failed":
            self._final_status[key] = "failed"
            raise PayoutTimeoutError(
                f"fake 토스 지급대행이 confirm(idempotency_key={key})에서 타임아웃했다 — "
                "실제 결과는 query_status로 확정해야 한다."
            )
        if scenario == "timeout_then_query_error":
            self._final_status[key] = self._QUERY_ERROR
            raise PayoutTimeoutError(
                f"fake 토스 지급대행이 confirm(idempotency_key={key})에서 타임아웃했다 — "
                "그리고 재확인도 실패할 것이다."
            )
        raise PayoutError(f"알 수 없는 fake 토스 지급대행 시나리오: {scenario!r}")

    def query_status(self, request: TransferRequest) -> VendorResult:
        final = self._final_status.get(request.idempotency_key, "pending")
        if final == self._QUERY_ERROR:
            raise PayoutTimeoutError(
                f"fake 토스 지급대행 query_status(idempotency_key={request.idempotency_key})가 타임아웃했다."
            )
        return VendorResult(status=final)


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


# --- Seller(지급대행사 수취인) 등록 어댑터 (#50, ADR-0007, ADR-0020) -----------------
#
# `PayoutAdapter`와 같은 원칙으로 별도 Protocol을 둔다 — "지급"과 "수취인 등록"은
# 토스 지급대행에서도 서로 다른 API고, 무엇보다 시점이 다르다(등록은 Payout이
# 확정된 뒤에만 시작된다). 계약을 하나로 합치면 그 시점 차이를 코드가 표현할
# 수 없다.
#
# dev/test는 `FakeSellerAdapter`로 바인딩된다(`SELLER_ADAPTER_MODE=fake`).
# `register`의 `simulate`로 부분 승인·한도 초과·심사 필요·거절 네 시나리오를
# 흉내낸다 — `FakePGAdapter`/`FakePayoutAdapter`와 같은 관용구다.
#
# 실제 토스 지급대행 셀러 등록 연동은 이 티켓 범위 밖이다(#57). `SellerAdapter`
# 계약만 만족시키면 된다.


class SellerError(Exception):
    """지급대행사가 Seller 등록을 명시적으로 거절했을 때(REJECTED)가 아니라,
    어댑터 자체가 예기치 못하게 실패했을 때만 던진다 — 거절은 예외가 아니라
    `SellerRegistrationResult.status == "rejected"`로 표현한다(한도 초과와 같은
    이유: 정상 응답의 한 갈래이지, 어댑터 장애가 아니다).
    """


@dataclass(frozen=True)
class SellerRegistrationResult:
    # 등록 시도 자체가 지급대행사에 접수되면(승인이든 심사든 거절이든) 식별자를
    # 받는다. 접수조차 안 된 예외적 경우("pending", 아래 참고)에만 빈 문자열일
    # 수 있다.
    seller_id: str
    # `payouts.models.Seller.Status`의 값 문자열과 정확히 일치해야 한다 —
    # "pending"(#57, 실물 어댑터가 이메일·실명·전화번호 중 하나라도 없어 벤더를
    # 아직 부르지 않았다) | "approval_required"(#57, 등록은 됐지만 본인인증
    # 전) | "partially_approved" | "under_review" | "approved"(#57, KYC 완료 —
    # 한도 없음) | "rejected" 중 하나.
    status: str
    # status가 "partially_approved"일 때만 채워진다. "approved"는 한도 자체가
    # 없으므로 None이다.
    weekly_limit_amount: int | None


@runtime_checkable
class SellerAdapter(Protocol):
    def register(
        self,
        *,
        developer_id: int,
        simulate: str | None = None,
        policy: "PlatformPolicy | None" = None,
    ) -> SellerRegistrationResult:
        """이 Developer를 지급대행사에 Seller로 등록(또는 재조회·재시도)한다.

        동기 응답이다 — 실물 어댑터가 비동기라면(웹훅으로 뒤늦게 승인/거절이
        온다면) 어댑터 내부에서 "under_review"로 우선 응답하고, 이후 별도
        경로(웹훅 또는 재시도 엔드포인트)가 최종 상태를 반영한다. 이미 부분
        승인된 Seller에 대해 이 메서드를 다시 부르지 않는 것은 호출자의
        책임이다(`payouts.services.ensure_seller_registered`가 그 규율을
        지킨다) — sellerId가 재등록을 막는다는 요구가 여기 있지 않다.

        `policy`는 호출 스코프에서 이미 읽은 `PlatformPolicy`를 넘기는
        자리다(#78, ADR-0023) — 생략하면(단독 호출 편의용) 구현체가 대신
        한 번 읽는다. 실물 어댑터는 이 값을 쓰지 않는다(주간 한도는 벤더가
        응답으로 알려준다) — 이 매개변수는 Fake 구현체가 "토스가 알려주는
        한도"를 우리 쪽에서 결정론적으로 흉내내기 위한 자리일 뿐이다.
        """
        ...


class FakeSellerAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 동작하며 여섯 시나리오를 흉내낸다.

    `register`의 `simulate` 값:
    - None / "success" (기본) — 즉시 부분 승인. 주간 한도는
      `PlatformPolicy.seller_weekly_limit_amount`(토스가 정한 사실, #78/
      ADR-0020 — 우리 판단으로 올릴 수 있는 값이 아니다).
    - "limit_exceeded" — 주간 한도를 넘겨 심사 대기가 된다. **실패가 아니다**
      (ADR-0020) — 짧은 기간에 여러 번 수상한 Developer를 성공했다는 이유로
      막지 않는다.
    - "review_required" — 한도와 무관하게 지급대행사가 추가 확인을 요구해
      심사 대기가 된다. 도메인 관점에서는 "under_review"로 limit_exceeded와
      같은 결과지만, 원인이 다르므로 Fake가 흉내낼 수 있는 시나리오는 둘 다
      남겨둔다(#50 AC — "부분 승인·한도 초과·심사 필요·거절").
    - "rejected" — 등록이 거절된다.
    - "approval_required"(#57) — 등록만 접수되고 아직 본인인증 전이다. 실물
      어댑터의 첫 등록 응답이 실제로 가장 흔하게 이 값이다(ADR-0020 토스
      재확인 결과) — "아무도 할 일이 없다"는 PENDING과 달리 "Developer가
      본인인증을 해야 한다"는 것을 이 상태가 구분해 알려준다.
    - "approved"(#57) — KYC 심사까지 마쳐 주간 한도 자체가 없다.
    """

    def register(
        self,
        *,
        developer_id: int,
        simulate: str | None = None,
        policy: "PlatformPolicy | None" = None,
    ) -> SellerRegistrationResult:
        if policy is None:
            # 단독 호출 편의용 — 스캔 스코프에서 이미 읽은 정책을 넘기지 않은
            # 호출자를 위해 여기서 한 번 읽는다(#78, ADR-0023). 스캔 루프
            # 안에서 이 메서드를 부르는 호출자(`distributions.services`)는
            # 반드시 이미 읽은 policy를 넘겨야 한다 — 그러지 않으면 Payout
            # 수만큼 이 조회가 반복된다.
            from policies.services import get_current_policy

            policy = get_current_policy()

        scenario = simulate or "success"
        seller_id = f"fake-seller-{developer_id}"

        if scenario == "success":
            return SellerRegistrationResult(
                seller_id=seller_id,
                status="partially_approved",
                weekly_limit_amount=policy.seller_weekly_limit_amount,
            )
        if scenario in ("limit_exceeded", "review_required"):
            return SellerRegistrationResult(
                seller_id=seller_id, status="under_review", weekly_limit_amount=None
            )
        if scenario == "rejected":
            return SellerRegistrationResult(
                seller_id=seller_id, status="rejected", weekly_limit_amount=None
            )
        if scenario == "approval_required":
            return SellerRegistrationResult(
                seller_id=seller_id, status="approval_required", weekly_limit_amount=None
            )
        if scenario == "approved":
            return SellerRegistrationResult(
                seller_id=seller_id, status="approved", weekly_limit_amount=None
            )
        raise SellerError(f"알 수 없는 fake Seller 등록 시나리오: {scenario!r}")


def get_seller_adapter() -> SellerAdapter:
    return resolve_adapter(
        mode=settings.SELLER_ADAPTER_MODE,
        fake_factory=FakeSellerAdapter,
        not_implemented_hint=(
            "실제 토스 지급대행 Seller 등록 연동은 아직 구현되지 않았다 — SellerAdapter "
            "계약만 만족시키는 dotted path를 SELLER_ADAPTER_MODE에 설정하면 된다"
            "(ADR-0007/0020, #57)."
        ),
    )
