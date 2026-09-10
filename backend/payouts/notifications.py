"""지급이 당신을 기다린다 — Hold 의 차례가 Developer 로 바뀐 Payout 을 알린다 (#169).

Hold 표(`payouts.progress`)에서 「Developer 의 차례」는 넷이다(주민등록번호 제출 ·
연락처 제출(#168) · 지급대행사의 본인인증 문자 · 실이체 재시도). 넷 다 지급
화면에 제 발로 들어와야만 보인다 — ADR-0020 이 "침묵은 상금이 사라진 것으로
읽힌다"고 경고한 자리다.

이 모듈은 확정 후 대기 중인 Payout(CONFIRMED_IDENTITY_PENDING·CONFIRMED_SELLER_
PENDING)을 스캔하며 `hold_of` 로 Hold 를 계산하고, 차례가 Developer 로 바뀌었으면
SMS 를 멱등 발송한다. 알림 유형은 하나다(`NotificationType.PAYOUT_AWAITS_YOU`) —
어느 Hold 인지는 유형이 아니라 알림의 context 로 싣는다. 상태마다 유형을 만들면
`Hold` → 문구 규칙이 두 곳에 생긴다(#130 이 세 렌더러에서 하나로 모은 것을 다시
쪼개는 셈이다).

**발화 지점이 스캔인 이유.** Payout 이 두 대기 중 하나로 들어오는 지점은 넷
이상이다(확정 · 신원/연락처 제출 · 재시도 · 두 웹훅) — 그중 하나를 빠뜨리면
조용해진다. 스캔은 그 전부를 한 곳에서 뒤늦게라도 따라잡는다. `Hold` 를 저장하지
않는다는 결정(파생값을 저장하면 언젠가 갈린다, `payouts.progress` 모듈 독스트링)은
그대로다 — 스캔도 매번 다시 계산할 뿐 결과를 남기지 않는다. 발송 이력 자체가
"이미 알렸다"의 기록이다.

**멱등은 기존 관용구를 그대로 쓴다**(`notifications.services.notify_once`).
dedup_context 는 Payout 식별자 · `HoldKind` · 실이체 시도 횟수(`transfer_attempt`)
셋이다 — 시도 횟수는 이미 "벤더 거래를 식별하는 유일한 키"로 끝까지 끌고 가기로
한 값(#57 5차 코드리뷰)이라 새 개념을 들이지 않는다. 스캔이 60초마다 돌아도
같은 차례에는 한 번만 나가고, 재시도로 시도 횟수가 오른 뒤 다시 실패하면 그 값이
달라져 있으므로 두 번째 실패도 다시 알려진다.

**알림 실패가 지급을 막지 않는다**(ADR-0009) — `notify_once` 가 이미 모든 예외를
삼킨다(`notifications.services.notify_safely`). 이 스캔의 `handle_row` 도 스캔
뼈대(`core.scans.run_scan`)가 행 단위로 예외를 격리하므로, Payout 하나의 알림
실패나 예외가 나머지 Payout 처리를 막지 않고 Payout 상태 자체를 건드리지도 않는다.
"""

from __future__ import annotations

from core.contest_switch import contest_product_enabled
from core.scans import ScanSpec

from notifications.models import NotificationType
from notifications.services import notify_once

from .models import Payout
from .progress import Turn, hold_of, next_action_message, with_hold_facts

# 코드리뷰 지적 — 이 스캔의 후보 집합은 「Hold 를 다시 계산해야 하는 대상」이지
# 「이미 Developer 의 차례인 대상」이 아니다(벤더의 차례인 Payout 도 이 status
# 둘 안에서 함께 대기한다). 배치가 매 실행 id 오름차순으로 같은 앞쪽 50건을
# 다시 집는 기본값(`core.scans.DEFAULT_BATCH_SIZE`)이면, 벤더 심사가 오래
# 걸리는 Payout 이 앞쪽에 몰릴 경우 그 뒤의 Payout 이 영원히 이번 배치에
# 들지 못해 알림이 조용히 밀릴 수 있다 — 이 스캔이 막으려는 바로 그 침묵이다.
# `notifications.services._DISPATCH_BATCH_SIZE` 와 같은 선례를 따라 배치를
# 넉넉히 키운다 — Hold 계산 자체는 가볍고(추가 쿼리 두어 번), 이 스캔이
# 다루는 두 대기 상태에 실시간으로 몇백 건이 동시에 머무는 규모는 이
# 플랫폼에서 아직 상정하지 않는다. 근본 해결(예: 거친 축을 넘어 Turn 까지
# SQL 로 옮기는 것)은 `payouts.progress` 가 이미 경계한 "번역표가 둘이 되면
# 갈린다"는 위험을 새로 만들므로 여기서 하지 않는다.
_BATCH_SIZE = 500


def _confirmed_payouts_awaiting_the_two_holds(as_of, ctx):
    """확정 후 대기 중인 Payout 전부(#169) — Hold 를 계산해야만 차례를 알 수 있으므로
    후보는 status 두 개(두 대기)로 넓게 잡는다.

    REQUESTED·CONFIRMED 는 이 둘 밖이라 애초에 두 대기 중이 아니다. **FAILED 는
    다르다** — Hold 표에서 FAILED 도 Developer 의 차례다(새 지급 요청을 낼 수
    있다). 그런데도 여기서 뺀 이유는 "차례가 아니라서"가 아니라, 이 스캔이
    다루는 넷(#167 스펙: 주민등록번호 제출 · 연락처 제출 · 본인인증 문자 ·
    실이체 재시도)이 전부 **두 대기 중**의 Hold 이기 때문이다 — FAILED 는
    시도 자체가 끝난 상태라 "다시 요청하라"는 별개의 안내이지, 확정 후 대기가
    아니다.

    `with_hold_facts` 로 `identity_submitted` 를 미리 SQL 에서 주석해 둔다(운영자
    큐가 이미 쓰는 것과 같은 관용구, #149) — 행마다 `TaxIdentity` 를 다시
    조회하지 않는다. `developer__user` 까지 select_related 를 넓혀 알림
    수신자(User) 조회도 추가 쿼리 없이 끝낸다.
    """

    payouts = Payout.objects.filter(
        status__in=(
            Payout.Status.CONFIRMED_IDENTITY_PENDING,
            Payout.Status.CONFIRMED_SELLER_PENDING,
        )
    ).with_target().select_related(
        "handover__award__submission__developer__user",
        "distribution_share__submission__developer__user",
    )
    return with_hold_facts(payouts)


def _notify_if_developer_turn(payout: Payout, as_of, ctx):
    """이 Payout 의 Hold 를 계산해 차례가 Developer 면 멱등 발송한다.

    벤더·Operator 의 차례(그리고 정의되지 않은 조합)에는 보내지 않는다 — Hold 가
    이미 「누구의 차례인가」를 답하므로, 그 답이 Developer 로 바뀔 때만 보낸다.
    """

    seller = payout.seller
    # `with_hold_facts` 가 이미 붙인 주석이다(위 candidates 함수) — 행마다
    # TaxIdentity 를 다시 조회하지 않는다.
    has_identity = payout.identity_submitted
    hold = hold_of(payout, seller=seller, has_identity=has_identity)

    if hold.turn is not Turn.DEVELOPER:
        return None

    notify_once(
        recipient=payout.developer.user,
        notification_type=NotificationType.PAYOUT_AWAITS_YOU,
        dedup_context={
            "payout_id": payout.id,
            "hold_kind": hold.kind.value,
            "transfer_attempt": payout.transfer_attempt,
        },
        # `notify_once` 가 dedup_context 를 여기 안에도 항상 넣어 주므로
        # 여기서 다시 되풀이할 필요는 없다 — 화면·운영 문의용으로 함께 보고
        # 싶은 값만 더한다.
        context={
            "contest_id": payout.contest.id,
            "message": next_action_message(hold),
        },
    )
    return {"payout_id": payout.id, "hold_kind": hold.kind.value}


# `enabled=contest_product_enabled`(#271) — Payout 은 상금이 있는 공모전 전용이다
# (Assignment 에는 지급 자체가 없다). 공모전 제품 스위치가 꺼지면 이 스캔은
# 등록부에서 사라진 것처럼 군다.
PAYOUT_NOTIFICATION_SCANS = (
    ScanSpec(
        name="payout-awaits-you",
        candidates=_confirmed_payouts_awaiting_the_two_holds,
        handle_row=_notify_if_developer_turn,
        batch_size=_BATCH_SIZE,
        enabled=contest_product_enabled,
    ),
)
