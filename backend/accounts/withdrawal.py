"""Withdrawal — 계정 삭제가 아니라 신원 파기 (#100, #101, ADR-0025).

`Withdrawal`은 Developer나 Sponsor가 자기 신원을 파기하고 계정을 닫는 것이다.
계정 행은 지우지 않는다 — `User.is_active = False`로 로그인만 막는다. 지우는
것은 값이다: CI·DI·전화번호·표시 이름·소개가 즉시 사라지고, Developer 라면
`payouts.models.Seller`의 연락처(전화번호·이메일)도 함께 사라진다(#171) —
`seller_id`와 상태는 남긴다(과거 Payout의 감사 추적, ADR-0025의 "신원은
지우되 계정은 남긴다"와 같은 선). 실명·생년월일은 거래가 있었던 사람에 한해
`RetainedIdentity`로 옮겨 남는다(#101).

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


from django.db import models, transaction

from core.clock import Clock

from .models import DeveloperProfile, PhoneContact, SponsorProfile, Withdrawal



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
    INSTRUCTOR_CLASS_IN_PROGRESS = (
        "instructor_class_in_progress",
        "보관하지 않은 클래스가 있어 탈퇴할 수 없습니다",
    )


def _sponsor_has_contest_in_progress(sponsor_profile: SponsorProfile) -> bool:
    """ADR-0025 "심사가 끝나기 전에는 탈퇴할 수 없다"(User Story 7) — 어느 status 가 「심사가 끝나기
    전」인지는 Contest.Status.BLOCKS_SPONSOR_WITHDRAWAL 이 답한다(#142). 예전의 status 별 if 사슬과
    fail-closed 가지는 그 사상이 빠짐없음을 테스트로 강제하면서 사라졌다."""

    # APP-BOUNDARY-EXCEPTION: 탈퇴 자격이 공모전 status 에 달려 있다 (ADR-0025)
    from contests.models import Contest

    # 필터(status__in)가 아니라 사상 조회다 — DB 에 enum 밖 값이 남는 마이그레이션 사고를 조용히
    # 「막지 않음」으로 지나치지 않고 KeyError 로 드러낸다(#121).
    statuses = set(Contest.objects.filter(sponsor=sponsor_profile).values_list("status", flat=True))
    return any(Contest.Status.BLOCKS_SPONSOR_WITHDRAWAL(status) for status in statuses)


def _developer_has_payout_in_progress(developer_profile: DeveloperProfile) -> bool:
    """ADR-0025 "지급이 끝나기 전에는 탈퇴할 수 없다"(User Story 6) — Payout.Status.
    BLOCKS_DEVELOPER_WITHDRAWAL 이 답한다(#142)."""

    # APP-BOUNDARY-EXCEPTION: 탈퇴 자격이 지급 status 에 달려 있다 (ADR-0025)
    from payouts.models import Payout

    statuses = set(
        Payout.objects.filter(
            models.Q(handover__award__submission__contestsubmission__developer=developer_profile)
            | models.Q(distribution_share__submission__contestsubmission__developer=developer_profile)
        ).values_list("status", flat=True)
    )
    return any(Payout.Status.BLOCKS_DEVELOPER_WITHDRAWAL(status) for status in statuses)


def _instructor_has_class_in_progress(user) -> bool:
    """강사(강의실의 Class.instructor)로 있는 클래스 중 보관되지 않은 것이 있는가
    (#302). Sponsor/Developer 와 달리 강의실은 프로필을 두지 않고 계정(User)을
    직접 가리킨다(ADR-0037, CONTEXT.md 「당사자」) — 그래서 여기는 profile 이 아니라
    user 자체로 조회한다. 신원이 사라지면 참여자들이 새 문제를 열어 줄 사람도 명단을
    손볼 사람도 없는 클래스에 남는다."""

    # APP-BOUNDARY-EXCEPTION: 탈퇴 자격이 강의실 Class 의 보관 여부에 달려 있다 (#302)
    from classroom.models import Class

    return Class.objects.filter(instructor=user, archived_at__isnull=True).exists()


def _transaction_basis(user) -> tuple[str, int] | None:
    """이 계정에 결제나 지급 같은 금전 이동이 **있었던 적이 있는가**(끝났든 아니든),
    있다면 그 근거는 무엇인가 — `(RetainedIdentity.Reason, 그 거래의 PK)`.

    `blocking_reasons`("탈퇴할 수 있는가" — *진행 중인가*)와는 다른 질문이다(#101).
    이 함수 하나가 `has_transacted`(있었는가)와 `RetainedIdentity`를 채우는
    근거(왜, 어느 거래) 양쪽의 유일한 판정처다 — 갈라 두면 언젠가 둘이 다른
    답을 하게 된다(이 저장소가 반복해 겪은 실패 모양).

    - Sponsor: 결제된(=DRAFT를 벗어난 적이 있는) Contest를 하나라도 가졌으면
      그 Contest가 근거다. `Contest.status`가 DRAFT를 벗어나는 유일한 경로가
      결제 확인이라(`contests.models.Contest.Status.PUBLISHED`의 주석), 지금
      상태가 무엇이든 DRAFT가 아니면 과거에 결제가 있었다는 뜻이다.
    - Developer: 확정(CONFIRMED)된 Payout을 하나라도 받았으면 그 Payout이
      근거다 — 원장에 실제로 돈이 움직인 기록이 남은 경우다.

    한 계정이 Sponsor·Developer 양쪽으로 거래했더라도 행은 하나(`RetainedIdentity`
    가 `user`에 대해 OneToOne)뿐이라 근거도 하나만 고른다 — Sponsor 쪽을 먼저
    본다. 실명 하나를 남기는 데는 근거가 하나로 충분하고, 어느 쪽이 먼저인지는
    이 파기 결정의 정당성에 영향을 주지 않는다.
    """

    # APP-BOUNDARY-EXCEPTION: Sponsor 쪽 거래 이력이 공모전에 있다 (#171)
    from contests.models import Contest
    # APP-BOUNDARY-EXCEPTION: Developer 쪽 거래 이력이 지급에 있다 (#171)
    from payouts.models import Payout
    # APP-BOUNDARY-EXCEPTION: 파기 대상이 본인확인 기록 자체다
    from verification.models import RetainedIdentity

    sponsor_profile = getattr(user, "sponsor_profile", None)
    if sponsor_profile is not None:
        contest = (
            Contest.objects.filter(
                sponsor=sponsor_profile, status__in=Contest.Status.REQUIRES_IDENTITY_RETENTION.statuses
            )
            .order_by("id")
            .first()
        )
        if contest is not None:
            return RetainedIdentity.Reason.SPONSOR_PAID_CONTEST, contest.id

    developer_profile = getattr(user, "developer_profile", None)
    if developer_profile is not None:
        payout = (
            Payout.objects.filter(
                models.Q(handover__award__submission__contestsubmission__developer=developer_profile)
                | models.Q(distribution_share__submission__contestsubmission__developer=developer_profile),
                status=Payout.Status.CONFIRMED,
            )
            .order_by("id")
            .first()
        )
        if payout is not None:
            return RetainedIdentity.Reason.DEVELOPER_CONFIRMED_PAYOUT, payout.id

    return None


def has_transacted(user) -> bool:
    """이 계정에 결제나 지급 같은 금전 이동이 있었던 적이 있는가. 판정 기준은
    `_transaction_basis` 한 곳에만 있다."""

    return _transaction_basis(user) is not None


def blocking_reasons(user) -> list[WithdrawalBlockReason]:
    """지금 이 계정이 탈퇴할 수 없는 이유 전부. 비어 있으면 탈퇴할 수 있다.

    거래 이력이 있다는 사실 자체는 막지 않는다(#101) — `execute_withdrawal`이
    그 실명을 `RetainedIdentity`로 옮겨 남기는 것으로 처리한다. 여기서 막는
    것은 오직 *진행 중인* 거래뿐이다.
    """

    reasons: list[WithdrawalBlockReason] = []

    sponsor_profile = getattr(user, "sponsor_profile", None)
    if sponsor_profile is not None and _sponsor_has_contest_in_progress(sponsor_profile):
        reasons.append(WithdrawalBlockReason.SPONSOR_CONTEST_IN_PROGRESS)

    developer_profile = getattr(user, "developer_profile", None)
    if developer_profile is not None and _developer_has_payout_in_progress(developer_profile):
        reasons.append(WithdrawalBlockReason.DEVELOPER_PAYOUT_IN_PROGRESS)

    if _instructor_has_class_in_progress(user):
        reasons.append(WithdrawalBlockReason.INSTRUCTOR_CLASS_IN_PROGRESS)

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
        # 실명·생년월일을 지우기 **전에** 거래 이력을 확인해야 한다 — 순서를
        # 바꾸면 옮길 값이 이미 사라진 뒤에 옮기려는 꼴이 된다.
        basis = _transaction_basis(user)
        if basis is not None:
            # APP-BOUNDARY-EXCEPTION: 보존할 실명을 본인확인 기록에서 옮긴다
            from verification.models import (
                RETAINED_IDENTITY_RETENTION_PERIOD,
                RetainedIdentity,
            )

            reason, retained_because_id = basis
            retained = RetainedIdentity(
                user=user,
                reason=reason,
                retained_because_id=retained_because_id,
                retained_until=now + RETAINED_IDENTITY_RETENTION_PERIOD,
            )
            retained.real_name = verification.real_name
            retained.birth_date = verification.birth_date
            retained.save()

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

        # Seller(#50, ADR-0020)의 연락처도 목적을 다한 개인정보다(#171) — 지급이
        # 끝나야 탈퇴할 수 있으므로(BLOCKS_DEVELOPER_WITHDRAWAL) 이 값들이 앞으로
        # 다시 쓰일 일이 없다. 지울 필드 집합은 `Seller.erase_contact()` 가
        # 소유한다 — `seller_id`와 `status`는 그 메서드가 건드리지 않는다(남긴다)
        # — 지급대행사에 있는 수취인 등록의 외부 참조라 과거 Payout의 감사
        # 추적과 연결돼 있다(ADR-0025 "신원은 지우되 계정은 남긴다"와 같은 선).
        # `TaxIdentity.resident_registration_number_encrypted`는 **건드리지
        # 않는다** — 세무 보존 의무가 걸린 값이라 연락처와 같은 규칙으로 다룰
        # 수 없다(#167 Out of Scope). 보존 기간과 파기 주체는 별도의 세무 정책
        # 결정이다.
        seller = getattr(developer_profile, "seller", None)
        if seller is not None:
            seller.erase_contact()

    user.is_active = False
    user.save(update_fields=["is_active"])

    return Withdrawal.objects.create(user=user, withdrawn_at=now)
