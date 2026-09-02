"""2년 미이용 신원 파기 + 보존 기간 만료 RetainedIdentity 파기 (#102, ADR-0025).

앞 티켓들(#100·#101)은 **사람이 탈퇴를 신청했을 때**를 다뤘다. 대부분은 탈퇴하지
않고 그냥 안 온다 — 그 사람들의 CI는 스캔이 없으면 영원히 남는다. 이 모듈이 그
빈 자리를 채운다: 사람이 잊어도 의무가 지켜지도록, 스캔이 대신 파기한다.

**신원만 지운다.** 계정·Submission·공개 프로필은 그대로 둔다 — 본인의 탈퇴
의사가 없는 경우라 포트폴리오를 뺏지 않는다(`Withdrawal`과 다른 점: 계정이
비활성화되지 않고 로그인도 그대로 된다). 돌아와서 개최·제출을 하려 할 때
본인확인을 한 번 더 요구받을 뿐이다(ADR-0011의 "행위 시점" 원칙 그대로).

**같은 판정처를 재사용한다.** 거래가 있었으면 실명을 `RetainedIdentity`로
옮기는 것(`accounts.withdrawal._transaction_basis`)과, 진행 중인 거래가 있으면
건드리지 않는 것(`accounts.withdrawal.blocking_reasons`)은 `Withdrawal`이 이미
푼 문제와 같다 — 갈라 두면 언젠가 두 경로가 다른 답을 하게 된다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction

from core.clock import Clock

from .models import PhoneContact
from .withdrawal import _transaction_basis, blocking_reasons

# 개인정보 유효기간제(휴면 1년 의무)는 2023년 9월 폐지되어 기간은 자율이다(ADR-0025).
# 2년은 Contest 한 사이클(마감 21일 + 심사 7일 + 배분 대기 14일 = 42일)을 여러 번
# 건너뛴 길이로 골랐다 — 그 정도 무행위면 본인확인을 계속 들고 있을 근거가 약하다.
DORMANCY_PERIOD = timedelta(days=365 * 2)


def last_activity_at(user):
    """이 계정이 마지막으로 "행위"한 시각. 기준을 한 곳에 명시한다.

    다음 중 가장 늦은 시각이다:

    - `User.date_joined` — 아무 행위가 없어도 갖는 바닥값.
    - `Verification.updated_at` — 본인확인·재확인 자체가 행위다.
    - Sponsor로서 만든 가장 최근 `Contest.created_at` — 개최도 행위다.
    - Developer로서 낸 가장 최근 `Submission.created_at` — 제출도 행위다.

    이 목록이 플랫폼에서 일어나는 모든 행위를 망라하지는 않는다 — 로그인 자체는
    JWT 발급이 서버에 세션을 남기지 않아 추적하지 않는다(#100 티켓의 로그인 차단이
    쿼리 시점 `is_active` 확인이지, 로그인 이벤트 기록이 아닌 것과 같은 이유).
    그러나 신원이 실제로 쓰이는 지점(본인확인·제출·개최)은 모두 포함하므로, 이
    지점들이 2년간 하나도 없었다면 신원을 계속 들고 있을 근거가 실질적으로 없다.
    """

    from contests.models import Contest
    from submissions.models import Submission

    candidates = [user.date_joined]

    verification = getattr(user, "verification", None)
    if verification is not None:
        candidates.append(verification.updated_at)

    sponsor_profile = getattr(user, "sponsor_profile", None)
    if sponsor_profile is not None:
        latest_contest_at = (
            Contest.objects.filter(sponsor=sponsor_profile)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if latest_contest_at is not None:
            candidates.append(latest_contest_at)

    developer_profile = getattr(user, "developer_profile", None)
    if developer_profile is not None:
        latest_submission_at = (
            Submission.objects.filter(developer=developer_profile)
            .order_by("-created_at")
            .values_list("created_at", flat=True)
            .first()
        )
        if latest_submission_at is not None:
            candidates.append(latest_submission_at)

    return max(candidates)


def _purge_dormant_identities(*, now) -> list[int]:
    """2년간 행위가 없었던 계정의 신원을 파기한다. 계정·Submission·프로필은
    건드리지 않는다.

    **진행 중인 거래가 있으면 건드리지 않는다**(`Withdrawal`이 사람의 탈퇴 신청을
    막는 것과 같은 이유 — 신원이 사라지면 그 거래가 주인을 잃는다). 실무에서는
    거의 도달하지 않는 방어선이다: Contest 한 사이클(최대 몇 주)이 2년보다 훨씬
    짧아, 그 안에 스케줄러가 자동으로 정리한다(ADR-0003). 걸리면 이번 스캔에서는
    건너뛰고 다음 스캔이 다시 본다 — 파기하지 않는 쪽 실수가 되돌리기 쉽다.
    """

    from verification.models import RETAINED_IDENTITY_RETENTION_PERIOD, RetainedIdentity, Verification

    purged_user_ids: list[int] = []

    candidates = Verification.objects.filter(
        status__in=[Verification.Status.VERIFIED, Verification.Status.UNDERAGE]
    ).select_related("user")

    for verification in candidates:
        user = verification.user

        if last_activity_at(user) > now - DORMANCY_PERIOD:
            continue
        if blocking_reasons(user):
            continue

        with transaction.atomic():
            basis = _transaction_basis(user)
            if basis is not None and not RetainedIdentity.objects.filter(user=user).exists():
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

            verification.status = Verification.Status.EXPIRED
            verification.reason = "2년간 행위가 없어 신원이 파기되었습니다."
            verification.real_name_encrypted = ""
            verification.birth_date_encrypted = ""
            verification.ci_encrypted = ""
            verification.ci_hash = ""
            verification.di_encrypted = ""
            verification.verified_at = None
            verification.save()

            PhoneContact.objects.filter(user=user).delete()

        purged_user_ids.append(user.id)

    return purged_user_ids


def _purge_expired_retained_identities(*, now) -> list[int]:
    """보존 기간(`retained_until`)이 지난 `RetainedIdentity`를 지운다."""

    from verification.models import RetainedIdentity

    expired_ids = list(
        RetainedIdentity.objects.filter(retained_until__lte=now).values_list("id", flat=True)
    )
    if expired_ids:
        RetainedIdentity.objects.filter(id__in=expired_ids).delete()
    return expired_ids


def purge_expired_identities(*, now=None) -> dict:
    """스캔 진입점 — 내부 엔드포인트(`accounts.internal_api`)가 그대로 부른다.

    두 스캔을 한 번의 호출로 묶는다: 2년 미이용 신원 파기와, 보존 기간이 지난
    RetainedIdentity 파기. 각각 이미 파기된(또는 이미 지워진) 행은 조건절에서
    자연히 제외되므로 **같은 시각에 두 번 불러도(워커가 겹쳐 돌아도) 두 번째
    호출은 아무것도 하지 않는다**(ADR-0003).
    """

    now = now or Clock.now()
    dormant_user_ids = _purge_dormant_identities(now=now)
    expired_retained_ids = _purge_expired_retained_identities(now=now)
    return {
        "as_of": now.isoformat(),
        "dormant_identities_purged": len(dormant_user_ids),
        "dormant_user_ids": dormant_user_ids,
        "expired_retained_identities_purged": len(expired_retained_ids),
        "expired_retained_identity_ids": expired_retained_ids,
    }
