"""2년 미이용 신원 파기 + 보존 기간 만료 RetainedIdentity 파기 (#102, #138, ADR-0025).

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

두 스캔은 core.scans 등록부의 항목이다(#138) — `identity-dormancy-purge` 와
`retained-identity-purge`. 마지막 행위 시각은 저장하지 않고 후보 쿼리가 SQL 에서
`Greatest(...)` 로 계산해 걸러낸다 — 그래야 배치 상한과 정렬이 성립한다(전에는 모든
VERIFIED 행을 파이썬으로 훑으며 행마다 쿼리를 셋씩 더 냈다).
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.db.models import F, Max
from django.db.models.functions import Greatest

from core.scans import ScanSpec

from .models import PhoneContact
from .withdrawal import _transaction_basis, blocking_reasons

# 개인정보 유효기간제(휴면 1년 의무)는 2023년 9월 폐지되어 기간은 자율이다(ADR-0025).
# 2년은 Contest 한 사이클(마감 21일 + 심사 7일 + 배분 대기 14일 = 42일)을 여러 번
# 건너뛴 길이로 골랐다 — 그 정도 무행위면 본인확인을 계속 들고 있을 근거가 약하다.
DORMANCY_PERIOD = timedelta(days=365 * 2)


def _dormant_verifications(as_of, ctx):
    """마지막 "행위"가 2년 넘게 없었던, 살아 있는 신원. 기준을 한 곳에 명시한다.

    마지막 행위 시각은 다음 중 가장 늦은 시각이다(Postgres 의 GREATEST 는 NULL 을 무시한다):

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

    from verification.models import Verification

    return (
        Verification.objects.filter(
            status__in=[Verification.Status.VERIFIED, Verification.Status.UNDERAGE]
        )
        .annotate(
            last_activity_at=Greatest(
                F("user__date_joined"),
                F("updated_at"),
                Max("user__sponsor_profile__contests__created_at"),
                Max("user__developer_profile__submissions__created_at"),
            )
        )
        .filter(last_activity_at__lte=as_of - DORMANCY_PERIOD)
        .select_related("user")
    )


def _purge_dormant_identity(verification, as_of, ctx):
    """계정 하나의 신원을 파기한다. 계정·Submission·프로필은 건드리지 않는다.

    **진행 중인 거래가 있으면 건드리지 않는다**(`Withdrawal`이 사람의 탈퇴 신청을
    막는 것과 같은 이유 — 신원이 사라지면 그 거래가 주인을 잃는다). 실무에서는
    거의 도달하지 않는 방어선이다: Contest 한 사이클(최대 몇 주)이 2년보다 훨씬
    짧아, 그 안에 스케줄러가 자동으로 정리한다(ADR-0003). 걸리면 이번 스캔에서는
    건너뛰고 다음 스캔이 다시 본다 — 파기하지 않는 쪽 실수가 되돌리기 쉽다.
    """

    from verification.models import RETAINED_IDENTITY_RETENTION_PERIOD, RetainedIdentity, Verification

    user = verification.user
    if blocking_reasons(user):
        return None

    with transaction.atomic():
        basis = _transaction_basis(user)
        if basis is not None and not RetainedIdentity.objects.filter(user=user).exists():
            reason, retained_because_id = basis
            retained = RetainedIdentity(
                user=user,
                reason=reason,
                retained_because_id=retained_because_id,
                retained_until=as_of + RETAINED_IDENTITY_RETENTION_PERIOD,
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

    return {"user_id": user.id, "verification_id": verification.id}


def _expired_retained_identities(as_of, ctx):
    from verification.models import RetainedIdentity

    return RetainedIdentity.objects.filter(retained_until__lte=as_of)


def _purge_retained_identity(retained, as_of, ctx):
    """보존 기간(`retained_until`)이 지난 `RetainedIdentity` 하나를 지운다. 이미 지워졌으면
    (같은 시각에 두 스캔이 겹쳐 돌았다) 아무 일도 없었다."""

    deleted, _ = type(retained).objects.filter(pk=retained.pk).delete()
    if not deleted:
        return None
    return {"retained_identity_id": retained.pk, "user_id": retained.user_id}


IDENTITY_DORMANCY_PURGE_SCAN = ScanSpec(
    name="identity-dormancy-purge",
    candidates=_dormant_verifications,
    handle_row=_purge_dormant_identity,
)
RETAINED_IDENTITY_PURGE_SCAN = ScanSpec(
    name="retained-identity-purge",
    candidates=_expired_retained_identities,
    handle_row=_purge_retained_identity,
)
