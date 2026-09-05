"""접수되지 않은 Seller 등록의 자력 회복 스캔 (#178).

**문제.** Developer 가 연락처를 냈고 Laurio 가 토스에 등록을 시도했는데 토스가
5xx 를 냈다 — 우리 코드는 그것을 옳게 다룬다(예외를 흡수하고 Seller 상태를
보존하고 원장 분개를 건드리지 않는다, `payouts.services.ensure_seller_registered`).
그런데 그 다음이 없었다: `Seller` 는 `PENDING` 이고 `seller_id` 는 빈 값인데,
`Hold` 판정이 그 조합을 「벤더의 차례」로 읽어(등록이 접수됐고 응답을 기다리는
것처럼) 아무도 다시 부르지 않았다. 웹훅은 원리적으로 불가능하다 — 등록이
접수되지 않아 토스는 이 셀러를 모른다.

**핵심 불변식.** 등록이 접수되지 않았다면(= `seller_id` 를 받지 못했다면) 그것은
벤더의 차례가 아니다 — 회복은 사람이 아니라 스캔이 한다. Developer 는 이미 할
일을 다 했다(연락처를 냈다).

**후보.** 「연락처는 다 있는데 `seller_id` 가 없는 Seller」— `ensure_seller_
registered` 가 조립하는 등록 요청이 필수로 요구하는 값(전화번호·이메일, 실명은
Verification 에서 온다)이 이미 채워져 있는데도 등록이 끝나지 않은 것들이다.

**기존 재시도 경로와 한 곳을 지난다.** 이 스캔은 `ensure_seller_registered`
자체를 그대로 부른다 — Developer 의 「다시 시도」버튼(`retry_seller_
registration` → `ensure_seller_registered`)과 새 Payout 확정(`advance`)이 이미
쓰는 바로 그 함수다. 등록이 이번에 접수되면(READY 로 바뀌면) 그 함수 안에서
`advance_seller_pending_payouts` 가 대기 중이던 이 Developer 의 Payout 들을
그대로 밀어준다 — 새 진행 경로를 만들지 않는다.

**멈추는 조건 — 재시도가 영원히 늘어나지 않는다.** 후보 질의 자체가
`registration_error_count < MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS`(#178, 상한
근거는 `payouts.progress` 의 상수 주석)인 Seller 만 고른다. 상한에 이른
Seller 는 이 스캔의 후보에서 조용히 빠지고, `payouts.progress.hold_of` 가 그
사실(등록 error 횟수)만으로 `HoldKind.SELLER_REGISTRATION_STUCK`(Operator 의
차례)을 판정한다 — 스캔이 벤더에 같은 요청을 무한히 다시 쏘지 않는다.

**원장은 그대로다**(ADR-0004). 이 스캔은 `ensure_seller_registered` 를 부를
뿐이고, 그 함수는 원장을 건드리지 않는다 — 수수료·원천징수 공제 분개는 이미
Payout 확정 시점에 남아 있다.
"""

from __future__ import annotations

from core.scans import ScanSpec, scan_params

from .models import Seller
from .progress import MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS
from .services import ensure_seller_registered


def _unaccepted_seller_registrations(as_of, ctx):
    """연락처는 다 있는데 `seller_id` 가 없는 Seller — 등록이 벤더 오류로 접수되지
    못한 채 머문 것들. 오류 횟수가 상한 미만인 것만 후보다(위 모듈 독스트링의
    멈추는 조건)."""

    return (
        Seller.objects.filter(
            status=Seller.Status.PENDING,
            seller_id="",
            registration_error_count__lt=MAX_AUTO_SELLER_REGISTRATION_ATTEMPTS,
        )
        .exclude(phone_number_encrypted="")
        .exclude(email="")
        .select_related("developer")
    )


def _retry_unaccepted_registration(seller: Seller, as_of, ctx):
    """`ensure_seller_registered` 를 그대로 부른다 — Developer 의 「다시 시도」와
    같은 함수다. `seller_simulate`(scan_params)는 fake 셀러 어댑터 전용 시나리오
    선택이다(#178) — 실제 어댑터에서는 무시된다."""

    simulate = scan_params(ctx).get("seller_simulate")
    before = (seller.status, seller.seller_id, seller.registration_error_count)

    ensure_seller_registered(seller.developer, simulate=simulate)

    seller.refresh_from_db()
    after = (seller.status, seller.seller_id, seller.registration_error_count)
    if after == before:
        # 여전히 벤더 오류다 — registration_error_count 는 이미
        # ensure_seller_registered 안에서 늘었다. 이번 실행이 바꾼 것이
        # 없으므로 rows 에 넣지 않는다(스캔 뼈대의 관용구).
        return None

    return {
        "developer_id": seller.developer_id,
        "seller_status": seller.status,
        "registration_error_count": seller.registration_error_count,
    }


SELLER_REGISTRATION_RECOVERY_SCANS = (
    ScanSpec(
        name="seller-registration-recovery",
        candidates=_unaccepted_seller_registrations,
        handle_row=_retry_unaccepted_registration,
    ),
)
