"""소셜 로그인 제공자 어댑터 (ADR-0007).

외부 제공자 API 호출을 인터페이스 뒤에 두고 환경별로 갈아끼운다. dev/test는 Fake로
바인딩돼 네트워크 없이 결정적으로 동작하고, prod는 실제 제공자의 userinfo 엔드포인트를
호출하는 구현체를 쓴다. 프런트엔드가 카카오·GitHub·구글의 OAuth 흐름을 마치고 얻은
provider access token을 백엔드로 넘기면, 어댑터가 그 토큰으로 제공자에게 프로필을
조회해 신뢰할 수 있는 (provider_uid, email) 쌍을 확정한다.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class SocialLoginError(Exception):
    """제공자가 토큰을 거부했거나 프로필을 내려주지 않았을 때."""


@dataclass(frozen=True)
class SocialProfile:
    provider: str
    provider_uid: str
    email: str


class SocialAdapter(Protocol):
    def fetch_profile(self, access_token: str) -> SocialProfile: ...


def _get_json(url: str, access_token: str) -> dict:
    request = urllib.request.Request(
        url, headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:  # noqa: S310
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError) as exc:
        raise SocialLoginError(f"provider profile fetch failed: {exc}") from exc


class KakaoAdapter:
    """카카오 사용자 정보 조회. https://kapi.kakao.com/v2/user/me"""

    def fetch_profile(self, access_token: str) -> SocialProfile:
        data = _get_json("https://kapi.kakao.com/v2/user/me", access_token)
        uid = data.get("id")
        if uid is None:
            raise SocialLoginError("kakao profile missing id")
        email = (data.get("kakao_account") or {}).get("email") or ""
        return SocialProfile(provider="kakao", provider_uid=str(uid), email=email)


class GithubAdapter:
    """GitHub 사용자 정보 조회. https://api.github.com/user"""

    def fetch_profile(self, access_token: str) -> SocialProfile:
        data = _get_json("https://api.github.com/user", access_token)
        uid = data.get("id")
        if uid is None:
            raise SocialLoginError("github profile missing id")
        email = data.get("email") or ""
        return SocialProfile(provider="github", provider_uid=str(uid), email=email)


class GoogleAdapter:
    """구글 사용자 정보 조회. https://www.googleapis.com/oauth2/v3/userinfo"""

    def fetch_profile(self, access_token: str) -> SocialProfile:
        data = _get_json("https://www.googleapis.com/oauth2/v3/userinfo", access_token)
        uid = data.get("sub")
        if uid is None:
            raise SocialLoginError("google profile missing sub")
        email = data.get("email") or ""
        return SocialProfile(provider="google", provider_uid=str(uid), email=email)


class FakeSocialAdapter:
    """dev/test 전용. 네트워크 없이 access_token 문자열을 그대로 파싱한다.

    형식: ``"<provider_uid>:<email>"``. 프로필 조회 대신 문자열을 그대로 신뢰하므로
    실제 제공자와의 계약을 검증하진 않는다 — 그건 이 어댑터의 목적이 아니다.
    """

    def __init__(self, provider: str) -> None:
        self._provider = provider

    def fetch_profile(self, access_token: str) -> SocialProfile:
        if not access_token or ":" not in access_token:
            raise SocialLoginError("fake token must be '<uid>:<email>'")
        uid, email = access_token.split(":", 1)
        if not uid:
            raise SocialLoginError("fake token missing uid")
        return SocialProfile(provider=self._provider, provider_uid=uid, email=email)


_REAL_ADAPTERS: dict[str, SocialAdapter] = {
    "kakao": KakaoAdapter(),
    "github": GithubAdapter(),
    "google": GoogleAdapter(),
}


def get_adapter(provider: str) -> SocialAdapter:
    from django.conf import settings

    if provider not in _REAL_ADAPTERS:
        raise SocialLoginError(f"unsupported provider: {provider}")
    if settings.SOCIAL_AUTH_MODE == "fake":
        return FakeSocialAdapter(provider)
    return _REAL_ADAPTERS[provider]
