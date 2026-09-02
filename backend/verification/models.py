"""Verification 도메인 모델.

`Verification`은 `Authentication`과 다른 것이다 — 여기서만 실명·생년월일·CI를 다룬다.
가입·열람에는 요구되지 않고, Submission 제출과 Contest 개최 같은 행위 시점에만
요구된다(ADR-0011). 코드에서 두 개념을 같은 이름으로 부르지 않는다.
"""

from __future__ import annotations

from datetime import date

from django.conf import settings
from django.db import models

from .crypto import ci_hash, decrypt, encrypt


class Verification(models.Model):
    class Status(models.TextChoices):
        VERIFIED = "verified", "본인확인 완료"
        UNDERAGE = "underage", "만 19세 미만"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="verification", on_delete=models.CASCADE
    )
    status = models.CharField(max_length=16, choices=Status.choices)
    reason = models.CharField(max_length=200, blank=True)

    real_name_encrypted = models.CharField(max_length=500)
    birth_date_encrypted = models.CharField(max_length=500)

    # 성인일 때만 채운다 — 미성년자는 플랫폼 신원(CI/DI)을 남길 이유가 없다.
    ci_encrypted = models.CharField(max_length=500, blank=True)
    ci_hash = models.CharField(max_length=64, blank=True, db_index=True)
    di_encrypted = models.CharField(max_length=500, blank=True)

    verified_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"Verification<{self.user_id}:{self.status}>"

    # --- 암호화된 필드 접근자 -------------------------------------------------
    @property
    def real_name(self) -> str:
        return decrypt(self.real_name_encrypted)

    @real_name.setter
    def real_name(self, value: str) -> None:
        self.real_name_encrypted = encrypt(value)

    @property
    def birth_date(self) -> date:
        return date.fromisoformat(decrypt(self.birth_date_encrypted))

    @birth_date.setter
    def birth_date(self, value: date) -> None:
        self.birth_date_encrypted = encrypt(value.isoformat())

    @property
    def ci(self) -> str:
        return decrypt(self.ci_encrypted)

    def set_ci(self, value: str) -> None:
        """CI를 암호화해 저장하고 조회용 해시를 같이 남긴다.

        빈 문자열은 거부한다(#84) — `ci_hash("")`는 빈 해시가 아니라
        `HMAC(key, "")`라는 정상적인 64자 hex라서, 이 가드가 없으면 CI 없는
        사용자 전원이 같은 해시를 갖게 되어 서로 남남인 사람들이 동일인으로
        오차단된다. `VerificationResult`(어댑터 계약 타입)가 이미 빈 CI로는
        생성 자체를 막지만(verification.adapters), 이 메서드를 직접 부르는
        어떤 미래의 호출자도 같은 실수를 반복할 수 없도록 모델 층에서도
        명시적으로 막는다 — 두 가드가 서로 다른 말을 하게 두지 않는다.
        """
        if not value:
            raise ValueError(
                "CI 없이 본인확인을 완료 처리할 수 없다 — 빈 CI는 HMAC(key, '')라는 "
                "정상 해시를 만들어 서로 다른 사용자를 동일인으로 오판시킨다."
            )
        self.ci_encrypted = encrypt(value)
        self.ci_hash = ci_hash(value)

    @property
    def di(self) -> str:
        return decrypt(self.di_encrypted)

    @di.setter
    def di(self, value: str) -> None:
        self.di_encrypted = encrypt(value)

    @property
    def is_verified(self) -> bool:
        return self.status == self.Status.VERIFIED

    @classmethod
    def find_by_ci(cls, ci: str):
        """동일 CI를 가진 `Verification`들을 찾는다 — 자전거래 탐지의 재료(ADR-0011).

        판정 로직(자기거래 차단) 자체는 이 티켓 범위 밖이다. 여기선 조회만 제공한다.
        """

        return cls.objects.filter(status=cls.Status.VERIFIED, ci_hash=ci_hash(ci))

    def would_change_identity(self, ci: str) -> bool:
        """이 계정에 이미 확정된 CI가 있고, `ci`가 그것과 다른지(#99, ADR-0025).

        **한 계정의 신원은 다른 사람의 것으로 바뀌지 않는다.** 이미 CI가 있는
        계정에 다른 CI로 본인확인이 들어오면 재확인 전체를 거부해야 한다 —
        그러지 않으면 성인으로 확인받아 Contest를 개최한 사람이 재확인 한 번으로
        미성년이 되어 그 Contest의 자전거래 차단이 조용히 꺼진다(#90).

        `ci_hash`가 아직 비어 있는 계정(첫 본인확인이거나, 미성년 판정으로
        지워진 뒤)은 비교 대상이 없으므로 항상 False다 — "바뀐다"는 판단은
        바뀔 대상이 있어야 성립한다. 이 경우는 정상적인 첫 확인·재확인이다.
        """
        if not self.ci_hash:
            return False
        return self.ci_hash != ci_hash(ci)


class VerificationRequest(models.Model):
    """실물 어댑터에 보낼 identityVerificationId를 서버가 발급해 요청자에게 귀속시킨 기록.

    포트원 브라우저 SDK가 받는 identityVerificationId는 리다이렉트 URL과 브라우저
    히스토리에 노출된다(#85 코드리뷰 지적 1). 그 값을 클라이언트가 스스로 만들면
    아무 관계 없는 다른 계정이 그 값을 그대로 `POST /verification/verify`에 실어
    보낼 수 있고, 서버는 그게 "누가 요청했는지" 확인할 방법이 없어 피해자의
    CI/DI로 그 공격자 계정이 VERIFIED가 된다 — 미성년자가 성년 게이트를
    통과하거나, 실소유자가 자전거래로 오차단된다.

    그래서 identityVerificationId는 반드시 이 서버가 먼저 발급하고
    (`verification.api.start_verification`), 그 사용자에게 귀속시켜 둔다.
    `verify()`는 실물 어댑터를 쓸 때 이 표에서 "요청자 본인이 발급받은 값인가"를
    확인한 뒤에만 진행하고, 성공하든 실패하든 1회용으로 소모한다(재사용 방지).

    Fake 어댑터(dev/test)는 토큰 자체가 사용자가 직접 지어내는 자기완결적 문자열
    이라 이 표를 쓰지 않는다 — 클라이언트가 자기 CI를 자기 이름으로 주장하는
    설계 자체가 fake의 목적이라, 여기서 막을 「남의 정체성 도용」이 성립하지
    않는다.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="verification_requests", on_delete=models.CASCADE
    )
    identity_verification_id = models.CharField(max_length=100, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:  # pragma: no cover
        return f"VerificationRequest<{self.user_id}:{self.identity_verification_id}>"
