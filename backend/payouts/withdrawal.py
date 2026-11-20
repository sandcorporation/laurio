"""탈퇴 판정 중 지급 몫 — `accounts.ports` 에 `payouts.apps` 가 올린다(#1086, ADR-0025, #171).

판정의 순서와 사유 목록은 `accounts.withdrawal` 이 든다. 여기는 Payout 상태로 답하는 두 질문뿐이다.
"""

from __future__ import annotations

from django.db.models import Q

from accounts.models import DeveloperProfile
from accounts.ports import TransactionBasis
from verification.models import RetainedIdentity

from .models import Payout


def _developer_payouts(developer_profile: DeveloperProfile) -> Q:
    return Q(handover__award__submission__contestsubmission__developer=developer_profile) | Q(
        distribution_share__submission__contestsubmission__developer=developer_profile
    )


def developer_has_payout_in_progress(developer_profile: DeveloperProfile) -> bool:
    """ADR-0025 "지급이 끝나기 전에는 탈퇴할 수 없다"(User Story 6) — Payout.Status.
    BLOCKS_DEVELOPER_WITHDRAWAL 이 답한다(#142)."""

    statuses = set(Payout.objects.filter(_developer_payouts(developer_profile)).values_list("status", flat=True))
    return any(Payout.Status.BLOCKS_DEVELOPER_WITHDRAWAL(status) for status in statuses)


def developer_transaction_basis(developer_profile: DeveloperProfile) -> TransactionBasis | None:
    """확정(CONFIRMED)된 Payout을 하나라도 받았으면 그 Payout이 근거다 — 원장에 실제로 돈이 움직인 기록이
    남은 경우다."""

    payout = (
        Payout.objects.filter(_developer_payouts(developer_profile), status=Payout.Status.CONFIRMED)
        .order_by("id")
        .first()
    )
    if payout is None:
        return None
    return RetainedIdentity.Reason.DEVELOPER_CONFIRMED_PAYOUT, payout.id
