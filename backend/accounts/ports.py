"""계정 앱(공유층)이 탈퇴 때 기능 앱에 묻는 자리 — 기능 앱이 `AppConfig.ready()` 에서 올린다(#1086, `core.registry`).

탈퇴 자격(`accounts.withdrawal.blocking_reasons`)과 거래 이력(`_transaction_basis`)은 공모전·지급·강의실 상태에 달려
있고, 신원 파기는 본인확인 앱의 일이다. 공유층은 그 앱들을 import 하지 않고 여기 자리만 둔다 — 판정의 순서와
fail-closed 규율은 그대로 `accounts.withdrawal` 이 든다.

자리가 비었으면(`PortNotRegistered`) 탈퇴가 멈춘다 — 조용히 「막지 않음」으로 지나치지 않는다.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

from django.db.models import Model

from core.registry import Slot

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

    from .models import DeveloperProfile, SponsorProfile

#: (RetainedIdentity.Reason 값, 그 거래의 pk) — `verification.purge.purge_identity` 의 `transaction_basis`
TransactionBasis = tuple[str, int]


class PurgeIdentity(Protocol):
    """`verification.purge.purge_identity` 의 모양."""

    def __call__(
        self,
        verification: Model,
        *,
        as_of: datetime,
        cause: Literal["withdrawal", "dormancy"],
        transaction_basis: TransactionBasis | None,
    ) -> None: ...


#: `contests.withdrawal.sponsor_has_contest_in_progress` — 심사가 끝나지 않은 Contest 가 있나(ADR-0025)
SPONSOR_CONTEST_IN_PROGRESS: Slot[Callable[[SponsorProfile], bool]] = Slot("Sponsor 진행 중 Contest", "contests.apps")

#: `payouts.withdrawal.developer_has_payout_in_progress` — 지급이 끝나지 않은 Payout 이 있나(ADR-0025)
DEVELOPER_PAYOUT_IN_PROGRESS: Slot[Callable[[DeveloperProfile], bool]] = Slot("Developer 진행 중 Payout", "payouts.apps")

#: `classroom.withdrawal.instructor_has_class_in_progress` — 보관하지 않은 소유 클래스가 있나(#302)
INSTRUCTOR_CLASS_IN_PROGRESS: Slot[Callable[[AbstractBaseUser], bool]] = Slot(
    "강사 보관 전 클래스", "classroom.apps"
)

#: `contests.withdrawal.sponsor_transaction_basis` — 결제된 Contest 개최 이력(#171)
SPONSOR_TRANSACTION_BASIS: Slot[Callable[[SponsorProfile], TransactionBasis | None]] = Slot(
    "Sponsor 거래 근거", "contests.apps"
)

#: `payouts.withdrawal.developer_transaction_basis` — 확정된 Payout 수령 이력(#171)
DEVELOPER_TRANSACTION_BASIS: Slot[Callable[[DeveloperProfile], TransactionBasis | None]] = Slot(
    "Developer 거래 근거", "payouts.apps"
)

#: `verification.purge.purge_identity` — 신원 필드를 비우고 거래가 있었으면 실명을 남긴다(#470)
PURGE_IDENTITY: Slot[PurgeIdentity] = Slot("신원 파기", "verification.apps")
