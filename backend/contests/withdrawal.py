"""탈퇴 판정 중 공모전 몫 — `accounts.ports` 에 `contests.apps` 가 올린다(#1086, ADR-0025, #171).

판정의 순서와 사유 목록은 `accounts.withdrawal` 이 든다. 여기는 공모전 상태로 답하는 두 질문뿐이다.
"""

from __future__ import annotations

from accounts.models import SponsorProfile
from accounts.ports import TransactionBasis
from verification.models import RetainedIdentity

from .models import Contest


def sponsor_has_contest_in_progress(sponsor_profile: SponsorProfile) -> bool:
    """ADR-0025 "심사가 끝나기 전에는 탈퇴할 수 없다"(User Story 7) — 어느 status 가 「심사가 끝나기
    전」인지는 Contest.Status.BLOCKS_SPONSOR_WITHDRAWAL 이 답한다(#142). 예전의 status 별 if 사슬과
    fail-closed 가지는 그 사상이 빠짐없음을 테스트로 강제하면서 사라졌다."""

    # 필터(status__in)가 아니라 사상 조회다 — DB 에 enum 밖 값이 남는 마이그레이션 사고를 조용히
    # 「막지 않음」으로 지나치지 않고 KeyError 로 드러낸다(#121).
    statuses = set(Contest.objects.filter(sponsor=sponsor_profile).values_list("status", flat=True))
    return any(Contest.Status.BLOCKS_SPONSOR_WITHDRAWAL(status) for status in statuses)


def sponsor_transaction_basis(sponsor_profile: SponsorProfile) -> TransactionBasis | None:
    """결제된(=DRAFT를 벗어난 적이 있는) Contest를 하나라도 가졌으면 그 Contest가 근거다. `Contest.status`가
    DRAFT를 벗어나는 유일한 경로가 결제 확인이라(`Contest.Status.PUBLISHED`의 주석), 지금 상태가 무엇이든
    DRAFT가 아니면 과거에 결제가 있었다는 뜻이다."""

    contest = (
        Contest.objects.filter(sponsor=sponsor_profile, status__in=Contest.Status.REQUIRES_IDENTITY_RETENTION.statuses)
        .order_by("id")
        .first()
    )
    if contest is None:
        return None
    return RetainedIdentity.Reason.SPONSOR_PAID_CONTEST, contest.id
