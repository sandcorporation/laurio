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
)
from .social import SocialLoginError, get_adapter
from .tokens import TokenError, blacklist_token, issue_token_pair, rotate_refresh_token

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
