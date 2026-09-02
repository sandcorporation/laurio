"""Withdrawal — 계정 삭제가 아니라 신원 파기 (#100, #101, ADR-0025).

`Withdrawal`은 Developer나 Sponsor가 자기 신원을 파기하고 계정을 닫는 것이다.
계정 행은 지우지 않는다 — `User.is_active = False`로 로그인만 막는다. 지우는
것은 값이다: CI·DI·전화번호·표시 이름·소개가 즉시 사라지고, 실명·생년월일은
거래가 있었던 사람에 한해 `RetainedIdentity`로 옮겨 남는다(#101).

**두 가지 다른 질문이 이 모듈에 섞여 있지 않다.**

- 「탈퇴할 수 있는가」(`blocking_reasons`) — *진행 중인* 거래가 있는가. 있으면
  거부한다: 신원이 사라지면 그 거래가 주인을 잃기 때문이다(심사할 사람이
  없어지고, Escrow에 돈이 묶인 채 임자가 없어지고, 지급할 수취인 정보가
  사라진다).
- 「거래가 있었는가」(`has_transacted`) — 신원 파기 뒤 실명을 남길지 결정하는
  전혀 다른 질문이다. 끝난 거래(과거)도 "있었다"에 포함된다 — 그래서
  `blocking_reasons`가 통과시킨(=진행 중인 거래가 없는) 사람도 `has_transacted`는
  참일 수 있다.

**판정은 여기(백엔드) 한 곳에서만 한다.** 화면이 Contest 상태·Payout 상태에서
재파생하지 않는다 — 이 저장소는 화면이 원시 상태에서 파생하다 새 상태가 어느
분기에도 안 걸리는 실패를 반복해 겪었다(`submissions.participation.NextAction`,
`contests.curation.HomeCurationBucket`과 같은 이유). `WithdrawalBlockReason`이
enum인 이유도 같다 — 생성된 프론트 타입에 리터럴 유니온으로 나타나 값이 하나
늘면 번역표를 가진 파일에서 `tsc --noEmit`이 빌드타임에 잡는다.

**상태 분류는 fail-closed다.** 새 `Contest.Status`나 `Payout.Status` 값이 생겨
아래 분류 함수 어느 분기에도 안 걸리면, 통과시키지 않고 막는 쪽(더 안전한 쪽)을
고르며 ERROR를 남긴다 — "이 상태가 탈퇴를 막아야 하는지 모른다"는 상태에서
신원을 지워버리는 사고보다, 탈퇴가 한 번 더 막히는 쪽이 되돌리기 쉽다.
"""

from __future__ import annotations

import logging

from django.db import models, transaction

from core.clock import Clock

from .models import DeveloperProfile, PhoneContact, SponsorProfile, Withdrawal

logger = logging.getLogger(__name__)


class WithdrawalBlockReason(models.TextChoices):
    """탈퇴를 막는 사유. 응답에 실려 화면이 무엇을 끝내야 하는지 말하게 한다."""

    SPONSOR_CONTEST_IN_PROGRESS = (
        "sponsor_contest_in_progress",
        "진행 중인(심사가 끝나지 않은) Contest가 있어 탈퇴할 수 없습니다",
    )
    DEVELOPER_PAYOUT_IN_PROGRESS = (
        "developer_payout_in_progress",
        "지급이 끝나지 않은 Payout이 있어 탈퇴할 수 없습니다",
    )
    # #100 한정 — 실명을 남길 자리(RetainedIdentity)가 아직 없어 거래 이력이
    # 있는 사람은 통째로 막는다. #101이 RetainedIdentity를 만들며 이 사유를
    # 더는 내지 않는다(코드에서 제거된다) — 지울 수 없는 것을 지우려 하지
    # 않는다는 임시 제한이다.
    RETENTION_NOT_YET_SUPPORTED = (
        "retention_not_yet_supported",
        "거래 이력이 있는 계정의 탈퇴는 아직 지원되지 않습니다",
    )


def _is_blocking_contest_status(status: str) -> bool:
    """이 Contest.status가 Sponsor의 탈퇴를 막는가 — 「심사가 끝나기 전」인가.

    ADR-0025: "심사가 끝나기 전에는 탈퇴할 수 없다"(User Story 7). DRAFT는 결제
    전이라 묶인 돈이 없고, AWARDED·JUDGING_ENDED는 심사가 이미 끝난 상태다.
    """

    from contests.models import Contest

    if status == Contest.Status.DRAFT:
        return False
    if status == Contest.Status.PUBLISHED:
        return True
    if status == Contest.Status.CLOSED:
        return True
    if status in (Contest.Status.AWARDED, Contest.Status.JUDGING_ENDED):
        return False

    logger.error(
        "알 수 없는 Contest.Status(%r) — 탈퇴 차단 판정이 분류하지 못해 "
        "fail-closed로 막는다. contests.models.Contest.Status에 새 값이 추가됐다면 "
        "accounts.withdrawal._is_blocking_contest_status도 함께 고쳐야 한다.",
        status,
    )
    return True


def _is_blocking_payout_status(status: str) -> bool:
    """이 Payout.status가 Developer의 탈퇴를 막는가 — 「지급이 끝나기 전」인가.

    ADR-0025: "지급이 끝나기 전에는 탈퇴할 수 없다"(User Story 6). CONFIRMED는
    지급이 실제로 끝난 상태이고(payouts.models.Payout 문서 참고 — TransferStatus가
    COMPLETED일 때만 status가 CONFIRMED로 전진한다), FAILED는 그 시도 자체가
    끝난 상태다 — 재시도는 새 REQUESTED 행으로 남으므로(#57) FAILED 행 하나가
    "미지급 상태"를 뜻하지 않는다.
    """

    from payouts.models import Payout

    if status == Payout.Status.REQUESTED:
        return True
    if status == Payout.Status.CONFIRMED_IDENTITY_PENDING:
        return True
    if status == Payout.Status.CONFIRMED_SELLER_PENDING:
        return True
    if status == Payout.Status.CONFIRMED:
        return False
    if status == Payout.Status.FAILED:
        return False

    logger.error(
        "알 수 없는 Payout.Status(%r) — 탈퇴 차단 판정이 분류하지 못해 "
        "fail-closed로 막는다. payouts.models.Payout.Status에 새 값이 추가됐다면 "
        "accounts.withdrawal._is_blocking_payout_status도 함께 고쳐야 한다.",
        status,
    )
    return True


def _sponsor_has_contest_in_progress(sponsor_profile: SponsorProfile) -> bool:
    from contests.models import Contest

    statuses = set(Contest.objects.filter(sponsor=sponsor_profile).values_list("status", flat=True))
    return any(_is_blocking_contest_status(status) for status in statuses)


def _developer_has_payout_in_progress(developer_profile: DeveloperProfile) -> bool:
    from payouts.models import Payout

    statuses = set(
        Payout.objects.filter(
            models.Q(handover__award__submission__developer=developer_profile)
            | models.Q(distribution_share__submission__developer=developer_profile)
        ).values_list("status", flat=True)
    )
    return any(_is_blocking_payout_status(status) for status in statuses)


def has_transacted(user) -> bool:
    """이 계정에 결제나 지급 같은 금전 이동이 **있었던 적이 있는가**(끝났든 아니든).

    `blocking_reasons`("탈퇴할 수 있는가" — 진행 중인가)와는 다른 질문이다. 이
    함수는 RetainedIdentity로 실명을 남길지를 정하는 데만 쓰인다(#101) — 판정
    기준은 한 곳(여기)에만 있다.

    - Sponsor: 결제된(=DRAFT를 벗어난 적이 있는) Contest를 하나라도 가졌으면
      참이다. `Contest.status`가 DRAFT를 벗어나는 유일한 경로가 결제 확인이라
      (`contests.models.Contest.Status.PUBLISHED`의 주석), 지금 상태가 무엇이든
      DRAFT가 아니면 과거에 결제가 있었다는 뜻이다.
    - Developer: 확정(CONFIRMED)된 Payout을 하나라도 받았으면 참이다 — 원장에
      실제로 돈이 움직인 기록이 남은 경우다.
    """

    from contests.models import Contest
    from payouts.models import Payout

    sponsor_profile = getattr(user, "sponsor_profile", None)
    if sponsor_profile is not None:
        if Contest.objects.filter(sponsor=sponsor_profile).exclude(
            status=Contest.Status.DRAFT
        ).exists():
            return True

    developer_profile = getattr(user, "developer_profile", None)
    if developer_profile is not None:
        if Payout.objects.filter(
            models.Q(handover__award__submission__developer=developer_profile)
            | models.Q(distribution_share__submission__developer=developer_profile),
            status=Payout.Status.CONFIRMED,
        ).exists():
            return True

    return False


def blocking_reasons(user) -> list[WithdrawalBlockReason]:
    """지금 이 계정이 탈퇴할 수 없는 이유 전부. 비어 있으면 탈퇴할 수 있다."""

    reasons: list[WithdrawalBlockReason] = []

    sponsor_profile = getattr(user, "sponsor_profile", None)
    if sponsor_profile is not None and _sponsor_has_contest_in_progress(sponsor_profile):
        reasons.append(WithdrawalBlockReason.SPONSOR_CONTEST_IN_PROGRESS)

    developer_profile = getattr(user, "developer_profile", None)
    if developer_profile is not None and _developer_has_payout_in_progress(developer_profile):
        reasons.append(WithdrawalBlockReason.DEVELOPER_PAYOUT_IN_PROGRESS)

    # #100 한정 임시 제한 — 진행 중인 거래는 없지만(위에서 걸리지 않았지만)
    # 거래 이력이 있으면 실명을 남길 자리가 아직 없어 통째로 막는다. #101이
    # RetainedIdentity를 만들며 이 분기를 지운다.
    if not reasons and has_transacted(user):
        reasons.append(WithdrawalBlockReason.RETENTION_NOT_YET_SUPPORTED)

    return reasons


def can_withdraw(user) -> bool:
    return not blocking_reasons(user)


class WithdrawalBlockedError(Exception):
    def __init__(self, reasons: list[WithdrawalBlockReason]):
        self.reasons = reasons
        super().__init__(f"탈퇴가 거부되었습니다: {reasons}")


@transaction.atomic
def execute_withdrawal(user) -> Withdrawal:
    """신원을 파기하고 계정을 비활성화한다. 유예 없이 즉시 실행된다.

    호출부(API)가 먼저 `blocking_reasons`를 확인해야 한다 — 여기서는 방어로
    한 번 더 확인한다(화면이 버튼을 감추는 것과 서버가 거절하는 것은 둘 다
    필요하다는 이 저장소의 규율).
    """

    reasons = blocking_reasons(user)
    if reasons:
        raise WithdrawalBlockedError(reasons)

    now = Clock.now()

    verification = getattr(user, "verification", None)
    if verification is not None:
        verification.status = verification.Status.WITHDRAWN
        verification.reason = "탈퇴로 신원이 파기되었습니다."
        verification.real_name_encrypted = ""
        verification.birth_date_encrypted = ""
        verification.ci_encrypted = ""
        verification.ci_hash = ""
        verification.di_encrypted = ""
        verification.verified_at = None
        verification.save()

    PhoneContact.objects.filter(user=user).delete()

    sponsor_profile = getattr(user, "sponsor_profile", None)
    if sponsor_profile is not None:
        sponsor_profile.display_name = ""
        sponsor_profile.bio = ""
        sponsor_profile.save(update_fields=["display_name", "bio"])

    developer_profile = getattr(user, "developer_profile", None)
    if developer_profile is not None:
        developer_profile.display_name = ""
        developer_profile.bio = ""
        developer_profile.save(update_fields=["display_name", "bio"])

    user.is_active = False
    user.save(update_fields=["is_active"])

    return Withdrawal.objects.create(user=user, withdrawn_at=now)
