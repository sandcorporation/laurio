"""Authentication 도메인 모델.

`Authentication`은 "이 요청이 누구 것인가"만 답한다 — 실명·생년월일 같은 신원 정보는
다루지 않는다. 그 정보는 `verification` 앱의 `Verification`이 담당한다 (ADR-0011).
이 앱과 `verification` 앱은 절대 같은 이름을 공유하지 않는다.

비밀번호: 소셜 로그인 전용이므로(ADR-0013) 앱 사용자는 비밀번호로 로그인할 수 없다.
`User.set_unusable_password()`를 항상 호출해 어떤 자격증명 스터핑도 통하지 않게 한다.
Django의 `password` 컬럼 자체는 `AbstractBaseUser`가 강제하는 프레임워크 배선이며,
운영자가 쓰는 Django admin 백오피스 로그인(ticket 01부터 존재)에만 쓰인다 — 이 둘은
서로 다른 관심사다: 운영자 인증은 내부 백오피스, `User`는 플랫폼 사용자다.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class SocialAccount(models.Model):
    """소셜 로그인 제공자와 연결된 계정 하나.

    카카오·GitHub·구글 중 하나로, 같은 (provider, provider_uid) 조합은 항상 같은
    `User`로 귀결된다.
    """

    class Provider(models.TextChoices):
        KAKAO = "kakao", "카카오"
        GITHUB = "github", "GitHub"
        GOOGLE = "google", "구글"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="social_accounts", on_delete=models.CASCADE
    )
    provider = models.CharField(max_length=16, choices=Provider.choices)
    provider_uid = models.CharField(max_length=191)
    email = models.EmailField(blank=True)
    connected_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "provider_uid"], name="unique_social_identity"
            )
        ]

    def __str__(self) -> str:  # pragma: no cover - admin display only
        return f"{self.provider}:{self.provider_uid}"


class SponsorProfile(models.Model):
    """`User`가 Sponsor로 처음 행동할 때 지연 생성되는 프로필."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="sponsor_profile", on_delete=models.CASCADE
    )
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Sponsor<{self.user_id}>"


class DeveloperProfile(models.Model):
    """`User`가 Developer로 처음 행동할 때 지연 생성되는 프로필."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="developer_profile", on_delete=models.CASCADE
    )
    display_name = models.CharField(max_length=100, blank=True)
    bio = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Developer<{self.user_id}>"


class RefreshToken(models.Model):
    """회전형 리프레시 토큰의 서버측 원장.

    리프레시가 일어날 때마다 기존 행은 `revoked_at`이 찍히고 새 행이 생긴다 —
    탈취된 리프레시 토큰의 재사용을 탐지·차단할 수 있는 지점이다.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="refresh_tokens", on_delete=models.CASCADE
    )
    jti = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return self.jti


class BlacklistedToken(models.Model):
    """로그아웃 등으로 즉시 무효화된 토큰의 jti.

    액세스·리프레시 토큰 검증 경로 둘 다 이 테이블을 먼저 조회한다. 여기 있으면
    서명이 유효하고 만료 전이어도 즉시 거부된다 (ADR-0012 블랙리스트 보완책).
    """

    jti = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    blacklisted_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return self.jti
