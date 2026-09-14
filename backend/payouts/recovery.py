"""접수되지 않은 Seller 등록의 자력 회복 스캔 (#178).

**문제.** Developer 가 연락처를 냈고 Codemit 가 토스에 등록을 시도했는데 토스가
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

from core.contest_switch import contest_product_enabled
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
    선택이다(#178) — 실제 어댑터에서는 무시된다.

    **항상 행을 낸다 — "바뀐 것이 없으면 None" 이 아니다.** 이 스캔의 후보는
    전부 「등록을 다시 시도해야 하는 Seller」이고, 이 함수는 매번 실제로 벤더를
    부른다(스캔 뼈대의 `None` 은 "이번엔 시도조차 안 했다"는 뜻이지 "시도했지만
    실패했다"가 아니다) — `registration_error_count` 는 벤더 오류가 날 때마다
    올라가므로 실패가 계속돼도 이전 값과 절대 같아지지 않는다. 그래서 "값이
    바뀌었는가"로 판정하면 항상 참이 되어 그 판정 자체가 무의미하다. 대신
    시도했다는 사실 자체와 그 결과(성공이든 여전한 실패든)를 매번 그대로
    보고한다 — 벤더가 계속 오류를 내는 동안 스캔이 실제로 계속 재시도하고
    있다는 것을 로그·응답에서 볼 수 있어야 한다."""

    simulate = scan_params(ctx).get("seller_simulate")

    ensure_seller_registered(seller.developer, simulate=simulate)

    seller.refresh_from_db()
    return {
        "developer_id": seller.developer_id,
        "seller_status": seller.status,
        "seller_id_accepted": bool(seller.seller_id),
        "registration_error_count": seller.registration_error_count,
    }


# `enabled=contest_product_enabled`(#271) — Seller(수취인) 등록은 Payout 확정
# 이후에만 호출된다(ADR-0020) — 상금이 있는 공모전 전용이다. 공모전 제품 스위치가
# 꺼지면 이 스캔은 등록부에서 사라진 것처럼 군다.
SELLER_REGISTRATION_RECOVERY_SCANS = (
    ScanSpec(
        name="seller-registration-recovery",
        candidates=_unaccepted_seller_registrations,
        handle_row=_retry_unaccepted_registration,
        enabled=contest_product_enabled,
    ),
)
