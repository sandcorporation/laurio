"""이메일이 계정을 찾는 데 어떻게 쓰이는가(2026-09-16, ADR-0049).

**식별 키는 여전히 소셜 계정 `(provider, provider_uid)` 하나다.** 이메일은 로그인
키가 아니라 **사람을 찾고 보이는 보조 단서**이며, 딱 한 자리에서만 계정 자체에
영향을 준다 — 제공자가 **인증했다고 말한** 이메일이 같을 때 두 소셜 계정을 한
계정으로 묶는 것(계정 연결). 인증되지 않은 이메일로 묶으면 남의 이메일을 적어 그
사람의 계정에 들어가는 길이 열린다.

여기 사는 규칙 넷:

1. **로그인마다 갱신한다.** 닉네임과 같은 자리에서 이메일·인증 여부도 최신값으로
   맞춘다 — 예전에는 가입 시점 값이 영원히 남아, 카카오에서 이메일을 받기 시작해도
   기존 계정은 빈 채였다.
2. **비어 있지 않은 이메일은 계정마다 유일하다**(`accounts/migrations/
   0004_unique_non_empty_user_email.py` 의 부분 유일 인덱스).
3. **이미 다른 계정이 그 이메일을 쓰고 있고 연결 조건도 아니면, 이메일 칸을 비워
   두고 로그인은 그대로 된다.** 이메일이 없다고 로그인을 막지 않는다는 결정이
   유일 제약보다 앞선다 — 사용자가 스스로 풀 수 없는 상태로 막히기 때문이다.
4. **연결은 기록을 남긴다**(`AccountLink`) — 계정 병합은 되돌리기 어렵다.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.contrib.auth import get_user_model
from django.db.models import Q

from core.clock import Clock

from .models import AccountLink, SocialAccount
from .social import SocialProfile


@dataclass(frozen=True)
class EmailDecision:
    """이 계정에 이메일을 실을 수 있는가, 그리고 인증된 것으로 볼 것인가."""

    email: str
    verified: bool


def decide_email(profile: SocialProfile, *, for_user_id: int | None) -> EmailDecision:
    """제공자가 준 이메일을 이 계정에 실을 수 있는지 판정한다.

    다른 계정이 이미 그 이메일을 쓰고 있으면 빈 값으로 떨어진다(위 규칙 3) —
    `for_user_id` 는 자기 자신을 「다른 계정」으로 세지 않기 위한 값이다.
    """

    email = (profile.email or "").strip()
    if not email:
        return EmailDecision(email="", verified=False)

    taken = get_user_model().objects.filter(email__iexact=email)
    if for_user_id is not None:
        taken = taken.exclude(pk=for_user_id)
    if taken.exists():
        return EmailDecision(email="", verified=False)

    return EmailDecision(email=email, verified=bool(profile.email_verified))


def refresh_social_account(social_account: SocialAccount, profile: SocialProfile) -> None:
    """로그인할 때마다 그 소셜 계정 행과 계정 이메일을 최신값으로 맞춘다."""

    decision = decide_email(profile, for_user_id=social_account.user_id)

    social_fields: list[str] = []
    if social_account.nickname != profile.nickname:
        social_account.nickname = profile.nickname
        social_fields.append("nickname")
    if social_account.email != decision.email:
        social_account.email = decision.email
        social_fields.append("email")
    if social_account.email_verified != decision.verified:
        social_account.email_verified = decision.verified
        social_fields.append("email_verified")
    if social_fields:
        social_account.save(update_fields=social_fields)

    user = social_account.user
    if user.email != decision.email:
        user.email = decision.email
        user.save(update_fields=["email"])


def find_linkable_user(profile: SocialProfile):
    """이 프로필을 붙일 기존 계정. 없으면 None.

    조건이 좁다 — **제공자가 인증한 이메일**이고, 그 이메일을 계정 이메일로 가진
    **살아 있는** 계정이 정확히 하나이며, 그 계정의 어느 소셜 계정도 같은 이메일을
    **인증된 것으로** 들고 있어야 한다. 탈퇴한 계정은 이메일이 파기돼 있어 여기
    걸리지 않고(ADR-0025), Operator 계정은 소셜 로그인 자체가 막혀 있다(ADR-0018,
    `assert_can_use_social_login` 이 그 문을 지킨다).
    """

    email = (profile.email or "").strip()
    if not email or not profile.email_verified:
        return None

    candidates = list(
        get_user_model()
        .objects.filter(is_active=True, is_staff=False, email__iexact=email)
        .filter(
            Q(social_accounts__email__iexact=email) & Q(social_accounts__email_verified=True)
        )
        .exclude(social_accounts__provider=profile.provider)
        .distinct()[:2]
    )
    if len(candidates) != 1:
        return None
    return candidates[0]


def attach_social_account(user, profile: SocialProfile, *, linked: bool) -> SocialAccount:
    """소셜 계정 행을 만든다. 기존 계정에 붙은 것이면 연결 이력도 남긴다."""

    decision = decide_email(profile, for_user_id=user.pk)
    social_account = SocialAccount.objects.create(
        user=user,
        provider=profile.provider,
        provider_uid=profile.provider_uid,
        email=decision.email,
        nickname=profile.nickname,
        email_verified=decision.verified,
    )
    if linked:
        AccountLink.objects.create(
            user=user,
            social_account=social_account,
            matched_email=(profile.email or "").strip(),
            linked_at=Clock.now(),
        )
    return social_account
