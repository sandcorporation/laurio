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

from core.crypto import decrypt, encrypt

from .phone import normalize_phone_number


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


class PhoneContact(models.Model):
    """알림 채널(SMS/LMS/알림톡)이 실제로 발송할 대상 전화번호(#51, ADR-0009).

    `User`는 Django 기본 `auth.User`라 필드를 직접 늘릴 수 없다 — `SponsorProfile`/
    `DeveloperProfile`과 같은 모양으로, 역할과 무관하게 `User` 하나에 지연 생성되는
    OneToOne을 둔다. Sponsor·Developer 양쪽 다 될 수 있는 계정이 전화번호를 두 번
    등록하지 않게 하기 위해 역할별 프로필이 아니라 `User`에 직접 붙인다.

    이 값은 `verification.api.verify`가 본인확인이 완료될 때 자동으로 채운다
    (#51 코드리뷰 지적 1) — 이 프로젝트는 이미 휴대폰 본인확인을 요구하므로
    (ADR-0011), 그 응답이 실제 연락 가능한 번호를 확보하는 가장 자연스러운
    지점이다. 여기서는 있으면 쓰고 없으면 발송을 시도하지 않는다는 계약만
    정한다(`notifications.adapters_aligo`).

    같은 DB의 다른 신원 정보(Verification의 실명·생년월일·CI/DI)와 같은 규율로
    평문 저장하지 않는다(#51 코드리뷰 지적 3) — `core.crypto`의 Fernet
    암호화를 그대로 재사용한다(같은 VERIFICATION_ENCRYPTION_KEY).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="phone_contact", on_delete=models.CASCADE
    )
    phone_number_encrypted = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def phone_number(self) -> str:
        return decrypt(self.phone_number_encrypted)

    @phone_number.setter
    def phone_number(self, value: str) -> None:
        """정규화(#51 코드리뷰 지적 4)를 거친 뒤에만 암호화해 저장한다 —
        하이픈·공백·국가코드 표기를 흡수하고, 알리고의 콤마 구분 다중 수신자
        파라미터로 오인될 수 있는 값은 `InvalidPhoneNumberError`로 거부한다."""

        self.phone_number_encrypted = encrypt(normalize_phone_number(value))

    def __str__(self) -> str:  # pragma: no cover
        return f"PhoneContact<{self.user_id}>"


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


class Withdrawal(models.Model):
    """`User` 하나가 탈퇴한 사건 (#100, ADR-0025).

    행이 존재한다는 것 자체가 "이 계정은 신원을 파기했다"는 기록이다 — 삭제하지
    않는다(#24 개인정보 담당자 story: 파기했음을 증명해야 한다). `user`는 `PROTECT`다
    — 계정 행 자체를 지우지 않는다는 이 기능 전체의 전제와 같은 이유로, 탈퇴
    기록을 지우면 "파기했다"는 증거가 함께 사라진다.

    실제 파기(CI·DI·전화번호·표시 이름·소개를 지우고 `Verification.status`를
    내리는 것)는 `accounts.withdrawal.execute_withdrawal`이 이 행과 같은
    트랜잭션에서 한다 — 이 모델 자체는 "언제 탈퇴했는가"만 든다.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="withdrawal", on_delete=models.PROTECT
    )
    withdrawn_at = models.DateTimeField()

    def __str__(self) -> str:  # pragma: no cover
        return f"Withdrawal<{self.user_id}>"
