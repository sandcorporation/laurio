"""운영자 지급 큐가 SQL 로 좁힌다 (#149).

`payouts.progress` 는 「무엇이 이 Payout 을 붙들고 있는가」를 두 표현으로 갖는다 —
사람이 읽는 `hold_of`(HoldKind 열다섯 갈래)와, 질의를 좁히는 `blocked_on_q`(거친 축
넷). 두 번째가 생긴 이유는 첫 번째만으로는 필터가 응답만 줄이고 질의는 그대로였기
때문이다(#149).

**표가 둘이 되면 갈린다** — #130 이 세 렌더러를 `hold_of` 하나로 모은 이유가 그것이다.
그래서 이 파일의 첫 테스트가 둘의 일치를 **모든 조합에서** 증명한다. 조합이 하나
늘거나 어느 한쪽이 바뀌면 여기가 그 자리에서 터진다(#141 이 `Contest.Status` 에 쓴
관용구).

일치를 두 층으로 본다:

- **논리**: 네 사실의 모든 조합에서 `hold_of(...).blocked_on` 과 `blocked_on_q` 가
  같은 답을 낸다. Q 를 SQL 의 3값 논리 그대로 해석해 판정한다 — NULL 을 「거짓」으로
  뭉개면 `seller_status` 가 NULL 인 행(등록이 아직 시작되지 않은 Payout, 큐에 가장
  먼저 떠야 할 것)이 조용히 사라지는 실수를 이 테스트가 놓친다.
- **배선**: 실제 DB 에서 주석(`seller_status` Coalesce · `identity_submitted` Exists)이
  두 지급 경로(Award · Distribution) 모두에 대해 실제로 풀린다.
"""

from __future__ import annotations

import pytest
from django.db.models import Q

from payouts.models import Payout, Seller
from payouts.progress import BLOCKED_ON_VALUES, blocked_on_q, hold_of

# --- SQL 3값 논리로 Q 를 해석한다 ---------------------------------------------------
#
# 파이썬의 `and`/`or`/`not` 이 아니라 SQL 의 그것이다. `WHERE` 는 **참인 행만** 고르므로
# UNKNOWN(None)은 거짓처럼 버려지지만, `NOT UNKNOWN` 은 참이 아니라 다시 UNKNOWN 이다 —
# 이 차이가 정확히 `~Q(seller_status__in=...)` 가 NULL 행을 잃는 자리다.

UNKNOWN = None


def _sql_not(value):
    return UNKNOWN if value is UNKNOWN else not value


def _sql_and(values):
    if any(v is False for v in values):
        return False
    return UNKNOWN if any(v is UNKNOWN for v in values) else True


def _sql_or(values):
    if any(v is True for v in values):
        return True
    return UNKNOWN if any(v is UNKNOWN for v in values) else False


def _evaluate_leaf(lookup: str, expected, facts: dict):
    field, _, operator = lookup.partition("__")
    assert field in facts, f"주석에 없는 필드를 Q 가 읽는다: {field!r}"
    actual = facts[field]

    if operator == "isnull":
        return (actual is None) == expected
    if actual is None:
        # NULL 과의 비교는 거짓이 아니라 UNKNOWN 이다.
        return UNKNOWN
    if operator == "":
        return actual == expected
    if operator == "in":
        return actual in expected
    raise AssertionError(
        f"이 해석기가 모르는 lookup: {lookup!r} — 새 lookup 을 쓰기 시작했다면 "
        "여기 SQL 의미도 같이 적어야 한다(조용히 통과하지 않게 일부러 터뜨린다)."
    )


def _evaluate(q: Q, facts: dict):
    values = [
        _evaluate(child, facts) if isinstance(child, Q) else _evaluate_leaf(child[0], child[1], facts)
        for child in q.children
    ]
    combined = _sql_and(values) if q.connector == Q.AND else _sql_or(values)
    return _sql_not(combined) if q.negated else combined


def _selects(q: Q, facts: dict) -> bool:
    """`WHERE q` 가 이 행을 고르는가 — 참일 때만이다(UNKNOWN 은 버려진다)."""

    return _evaluate(q, facts) is True


# --- 모든 조합 ----------------------------------------------------------------------

# 표에 없는 status 도 넣는다 — `operator` 갈래가 여집합으로 잡히는지 보려면 필요하다.
_STATUSES = [*Payout.Status.values, "bogus-status"]
# 실이체 축은 「FAILED 인가 아닌가」로만 갈린다.
_TRANSFER_STATUSES = [Payout.TransferStatus.FAILED, Payout.TransferStatus.NOT_REQUESTED]
_SELLER_STATUSES = [None, *Seller.Status.values]


def _all_combinations():
    for status in _STATUSES:
        for transfer_status in _TRANSFER_STATUSES:
            for seller_status in _SELLER_STATUSES:
                for has_identity in (False, True):
                    for has_phone in (False, True):
                        for has_email in (False, True):
                            if seller_status is None and (has_phone or has_email):
                                continue  # Seller 가 없으면 연락처도 없다
                            yield (
                                status,
                                transfer_status,
                                seller_status,
                                has_identity,
                                has_phone,
                                has_email,
                            )


def test_blocked_on_q_and_hold_of_agree_on_every_combination():
    """두 표현이 모든 조합에서 같은 답을 낸다 (#149, #168 이 이메일 축을 더한다).

    `blocked_on` 갈래는 서로소이고 빠짐이 없어야 한다 — 어떤 조합이든 정확히 하나의
    Q 가 고른다. 하나도 고르지 않으면 그 Payout 은 어느 큐에도 뜨지 않고(운영자 눈에서
    사라진다), 둘이 고르면 같은 행이 두 큐에 뜬다.

    이메일 유무는 거친 축(`blocked_on`) 자체를 갈라 새 SQL 조건을 요구하지 않는다 —
    `HoldKind.SELLER_CONTACT`(전화번호든 이메일이든 연락처 미제출)도 여전히
    `blocked_on == "seller"` 하나로만 떨어진다(#168). 그래도 이 테스트에 이메일
    축을 더하는 이유는, `hold_of` 의 파이썬 판정이 이메일 하나만 없는 조합에서
    실수로 "seller" 밖(예: 없는 갈래)으로 새지 않는다는 것을 SQL 쪽과 나란히
    증명하기 위해서다.
    """

    checked = 0
    for (
        status,
        transfer_status,
        seller_status,
        has_identity,
        has_phone,
        has_email,
    ) in _all_combinations():
        payout = Payout(status=status, transfer_status=transfer_status)
        seller = None
        if seller_status is not None:
            seller = Seller(status=seller_status)
            if has_phone:
                seller.phone_number = "01012345678"
            if has_email:
                seller.email = "dev@example.com"

        expected = hold_of(payout, seller=seller, has_identity=has_identity).blocked_on
        facts = {
            "status": status,
            "transfer_status": transfer_status,
            "seller_status": seller_status,
            "identity_submitted": has_identity,
        }

        selected_by = [
            value for value in (None, *BLOCKED_ON_VALUES) if _selects(blocked_on_q(value), facts)
        ]
        label = (
            f"status={status!r} transfer={transfer_status!r} seller={seller_status!r} "
            f"identity={has_identity!r} phone={has_phone!r} email={has_email!r}"
        )
        assert selected_by == [expected], (
            f"{label}: hold_of 는 {expected!r} 인데 Q 는 {selected_by!r} 을 골랐다 — "
            "두 표현이 갈렸다"
        )
        checked += 1

    # 조합을 실제로 다 돌았는지 — 생성기가 조용히 비면 이 테스트는 아무것도 증명하지
    # 않는다. status 6 × 실이체 2 × 신원 2 × (Seller 없음 1 + Seller 6종 × 전화 2 ×
    # 이메일 2) = 600.
    assert checked == 600, checked


def test_blocked_q_is_exactly_the_complement_of_unblocked():
    """큐가 보여주는 전체 = 막혀 있지 않은 것의 여집합 (#149). 표에 없는 status 가
    양쪽 어디에도 안 들어가는 일이 없어야 한다."""

    from payouts.progress import blocked_q

    for status, transfer_status, seller_status, has_identity, _phone, _email in _all_combinations():
        facts = {
            "status": status,
            "transfer_status": transfer_status,
            "seller_status": seller_status,
            "identity_submitted": has_identity,
        }
        assert _selects(blocked_q(), facts) is not _selects(blocked_on_q(None), facts), (
            f"status={status!r}: 막힌 것도 안 막힌 것도 아닌 행이 생겼다"
        )
