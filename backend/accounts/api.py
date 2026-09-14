"""Authentication API — 소셜 로그인, 토큰 회전, 로그아웃, 프로필 지연 생성.

`Authentication`은 실명과 무관하다: 여기서 다루는 건 "이 요청이 누구 것인가"뿐이다.
신원 확인(`Verification`)은 별도 앱이 담당한다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from .middleware import jwt_auth
from .operators import OperatorInvariantError, assert_can_use_social_login
from .models import DeveloperProfile, SocialAccount, SponsorProfile
from .sanitize import sanitize_free_text
from .schemas import (
    LogoutIn,
    MeOut,
    ProfileIn,
    ProfileOut,
    RefreshIn,
    SocialLoginIn,
    TokenPairOut,
    WithdrawalEligibilityOut,
    WithdrawalOut,
    WithdrawalRejectedOut,
)
from .social import SocialLoginError, get_adapter
from .tokens import TokenError, blacklist_token, issue_token_pair, rotate_refresh_token
from .withdrawal import WithdrawalBlockedError, blocking_reasons, execute_withdrawal

router = Router(tags=["auth"])


def _username_for(provider: str, provider_uid: str) -> str:
    return f"{provider}:{provider_uid}"[:150]


@router.post("/auth/social/{provider}/login", response=TokenPairOut, auth=None)
def social_login(request: HttpRequest, provider: str, payload: SocialLoginIn):
    """카카오·GitHub·구글 access token으로 로그인(최초 로그인 시 가입까지 겸한다).

    비밀번호는 어디에도 없다 — 매칭되는 `SocialAccount`가 없으면 새 `User`를 만들되
    `set_unusable_password()`로 비밀번호 로그인 경로 자체를 봉인한다.
    """

    try:
        adapter = get_adapter(provider)
        profile = adapter.fetch_profile(payload.access_token)
    except SocialLoginError as exc:
        raise HttpError(401, f"소셜 로그인에 실패했습니다: {exc}") from exc

    social_account = (
        SocialAccount.objects.select_related("user")
        .filter(provider=profile.provider, provider_uid=profile.provider_uid)
        .first()
    )
    if social_account is not None:
        user = social_account.user
        # 서로소 불변식의 반대 방향(#42, ADR-0018). 부트스트랩 명령만 막으면 이미
        # Operator 인 계정에 소셜 계정을 붙여 돌아 들어올 수 있다. Operator 가
        # 토큰을 얻지 못해야 `DeveloperProfile` 경로에도 닿지 못하고, 그래야 자기
        # 사건 심판이 구조적으로 불가능하다는 성질이 유지된다.
        try:
            assert_can_use_social_login(user)
        except OperatorInvariantError as exc:
            raise HttpError(403, str(exc)) from exc

        # 탈퇴(#100, ADR-0025)한 계정은 다시 로그인할 수 없다 — `is_active=False`가
        # 그 표시다. `JWTAuthenticationMiddleware`가 이미 발급된 토큰을 걸러내는
        # 것과 같은 이유로, 여기서도 새 토큰 자체를 내주지 않는다. CI를 지웠으므로
        # "재가입" 경로도 없다 — 같은 소셜 계정으로는 영구히 막힌다(ADR-0025의
        # 되돌릴 수 없다는 결정 그대로).
        if not user.is_active:
            raise HttpError(
                403,
                "탈퇴한 계정입니다. 신원이 파기되어 다시 로그인할 수 없습니다.",
            )

        # 닉네임은 로그인마다 최신값으로 갱신한다(#390) — 카카오에서 닉네임을
        # 바꾼 뒤에도 옛 값이 기본값으로 남지 않게 하기 위해서다. 동의를
        # 철회했으면 `profile.nickname`이 빈 문자열로 와 여기서도 비워진다.
        if social_account.nickname != profile.nickname:
            social_account.nickname = profile.nickname
            social_account.save(update_fields=["nickname"])
    else:
        User = get_user_model()
        user = User(
            username=_username_for(profile.provider, profile.provider_uid),
            email=profile.email,
        )
        user.set_unusable_password()
        user.save()
        SocialAccount.objects.create(
            user=user,
            provider=profile.provider,
            provider_uid=profile.provider_uid,
            email=profile.email,
            nickname=profile.nickname,
        )

    pair = issue_token_pair(user.id)
    return TokenPairOut(access=pair.access, refresh=pair.refresh)


@router.post("/auth/refresh", response=TokenPairOut, auth=None)
def refresh_token(request: HttpRequest, payload: RefreshIn):
    """리프레시 토큰을 회전시킨다 — 옛 토큰은 즉시 블랙리스트에 오른다."""

    try:
        pair = rotate_refresh_token(payload.refresh)
    except TokenError as exc:
        raise HttpError(401, "리프레시 토큰이 유효하지 않습니다.") from exc
    return TokenPairOut(access=pair.access, refresh=pair.refresh)


@router.post("/auth/logout", auth=jwt_auth)
def logout(request: HttpRequest, payload: LogoutIn | None = None):
    """현재 액세스 토큰(과 있다면 리프레시 토큰)을 즉시 블랙리스트에 올린다.

    블랙리스트 기록이 실패하면 로그아웃도 실패해야 한다. 200을 돌려주고도 토큰이
    여전히 유효한 상태로 남는 것은 ADR-0012가 명시적으로 금지하는 상황이다 — 여기서
    예외를 삼키지 않는다. 클라이언트가 보낸 토큰 자체가 문제면 401로, 블랙리스트
    저장이 인프라 문제로 실패하면 그대로 전파돼 500으로 드러난다.
    """

    header = request.META.get("HTTP_AUTHORIZATION", "")
    access_token = header[len("Bearer ") :].strip() if header.startswith("Bearer ") else None
    if not access_token:
        raise HttpError(400, "액세스 토큰이 필요합니다.")

    try:
        blacklist_token(access_token, expected_type="access")
        if payload and payload.refresh:
            blacklist_token(payload.refresh, expected_type="refresh")
    except TokenError as exc:
        raise HttpError(401, "토큰이 유효하지 않아 로그아웃할 수 없습니다.") from exc

    return {"status": "ok"}


@router.get("/accounts/me", response=MeOut, auth=jwt_auth)
def me(request: HttpRequest):
    user = request.auth_user
    return MeOut(
        id=user.id,
        username=user.username,
        email=user.email,
        has_sponsor_profile=SponsorProfile.objects.filter(user=user).exists(),
        has_developer_profile=DeveloperProfile.objects.filter(user=user).exists(),
    )


def _apply_profile_update(profile, payload: ProfileIn) -> None:
    """None(안 보냄)과 ""(명시적으로 비움)을 구분해 보내진 필드만 갱신한다."""

    changed = False
    if payload.display_name is not None:
        profile.display_name = sanitize_free_text(payload.display_name)
        changed = True
    if payload.bio is not None:
        profile.bio = sanitize_free_text(payload.bio)
        changed = True
    if changed:
        profile.save()


@router.post("/accounts/sponsor-profile", response=ProfileOut, auth=jwt_auth)
def ensure_sponsor_profile(request: HttpRequest, payload: ProfileIn):
    """Sponsor 프로필을 필요할 때 처음으로 만든다(지연 생성, get-or-create)."""

    profile, _created = SponsorProfile.objects.get_or_create(user=request.auth_user)
    _apply_profile_update(profile, payload)
    return ProfileOut(display_name=profile.display_name, bio=profile.bio)


@router.post("/accounts/developer-profile", response=ProfileOut, auth=jwt_auth)
def ensure_developer_profile(request: HttpRequest, payload: ProfileIn):
    """Developer 프로필을 필요할 때 처음으로 만든다(지연 생성, get-or-create)."""

    profile, _created = DeveloperProfile.objects.get_or_create(user=request.auth_user)
    _apply_profile_update(profile, payload)
    return ProfileOut(display_name=profile.display_name, bio=profile.bio)


@router.get("/accounts/withdrawal", response=WithdrawalEligibilityOut, auth=jwt_auth)
def get_withdrawal_eligibility(request: HttpRequest):
    """탈퇴 화면이 무엇이 막는지 미리 보여줄 수 있게 판정만 돌려준다 (#100 AC).

    화면은 이 응답을 그대로 읽어 목록을 보여줄 뿐, Contest·Payout 상태에서 다시
    판정하지 않는다 — `accounts.withdrawal.blocking_reasons`가 유일한 판정처다.
    """

    reasons = blocking_reasons(request.auth_user)
    return WithdrawalEligibilityOut(can_withdraw=not reasons, blocking_reasons=reasons)


@router.post(
    "/accounts/withdrawal",
    response={200: WithdrawalOut, 409: WithdrawalRejectedOut},
    auth=jwt_auth,
)
def withdraw(request: HttpRequest):
    """신원을 파기한다. 유예 없이 즉시 실행되고 되돌릴 수 없다(ADR-0025).

    막는 사유가 있으면 409로 그 목록을 그대로 돌려준다 — 화면이 버튼을 감추는
    것과 서버가 거절하는 것은 둘 다 필요하다(#67과 같은 구분).
    """

    try:
        withdrawal = execute_withdrawal(request.auth_user)
    except WithdrawalBlockedError as exc:
        return 409, WithdrawalRejectedOut(
            detail="진행 중인 거래가 있어 탈퇴할 수 없습니다.", blocking_reasons=exc.reasons
        )

    return 200, WithdrawalOut(withdrawn_at=withdrawal.withdrawn_at)
