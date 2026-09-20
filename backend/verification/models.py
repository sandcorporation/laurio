"""Verification 도메인 모델.

`Verification`은 `Authentication`과 다른 것이다 — 여기서만 실명·생년월일·CI를 다룬다.
가입·열람에는 요구되지 않고, Submission 제출과 Contest 개최 같은 행위 시점에만
요구된다(ADR-0011). 코드에서 두 개념을 같은 이름으로 부르지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.db import models

from core.crypto import ci_hash, decrypt, encrypt

# 전자상거래법 시행령의 "대금결제 및 재화등의 공급에 관한 기록" 보존 기간(5년)을
# 따른다 — RetainedIdentity가 실명을 남기는 이유가 결제·지급이 실제로 있었던
# 계약 상대방을 나중에도 식별할 수 있어야 한다는 것이기 때문이다(ADR-0025).
# 이 값은 법률 자문이 아니다 — 실제 방침은 확인이 필요하다(ADR-0025 본문 참고).
RETAINED_IDENTITY_RETENTION_PERIOD = timedelta(days=365 * 5)


class Verification(models.Model):
    class Status(models.TextChoices):
        VERIFIED = "verified", "본인확인 완료"
        UNDERAGE = "underage", "만 19세 미만"
        # 탈퇴로 신원이 파기된 계정(#100, ADR-0025). 미성년 판정이 이미 쓰는 모양
        # 그대로 행은 남기고 상태만 내린다 — 그래야 "신원이 파기된 계정"과 "한 번도
        # 확인하지 않은 계정"(Verification 행 자체가 없음)이 구별되고, 파기
        # 이행 여부를 셀 수 있다(개인정보 담당자 story). CI·DI·전화번호·실명·
        # 생년월일은 이 상태로 내려가는 순간 함께 지워진다
        # (`accounts.withdrawal.execute_withdrawal`).
        WITHDRAWN = "withdrawn", "탈퇴(신원 파기)"
        # 2년간 행위가 없어 스캔이 신원만 파기한 계정(#102, ADR-0025). WITHDRAWN과
        # 일부러 값을 나눈다 — 이쪽은 계정이 비활성화되지 않고(User.is_active는
        # 그대로 True), 로그인도 그대로 되며, 다음에 개최·제출을 시도할 때 본인확인을
        # 다시 요구받을 뿐이다. WITHDRAWN(탈퇴)을 재사용하면 "계정이 닫혔다"는
        # 사실과 어긋난 상태가 하나의 값으로 뭉개진다.
        EXPIRED = "expired", "미이용으로 신원 파기"

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


class RetainedIdentity(models.Model):
    """탈퇴했지만 거래가 있었던 사람의 실명·생년월일을, 법이 요구하는 기간만 따로
    보관한 것 (#101, ADR-0025).

    **살아 있는 신원(`Verification`)과 같은 자리에 두지 않는다.** 별도 DB가
    아니라 별도 테이블인 이유는, 법이 파기 의무와 보존 의무의 충돌에 요구하는
    답이 "다른 개인정보와 분리하여 저장·관리"이고, CI 고시가 논리적 분리를
    명시적으로 인정하기 때문이다. 암호화는 `Verification`과 같은 방식
    (`core.crypto`의 Fernet)을 그대로 쓴다.

    **CI·DI·전화번호가 들어올 칼럼 자체가 없다.** 그 값들은 동일인 판별과
    통지를 위한 것이라 목적이 탈퇴로 끝난다 — 자리를 아예 두지 않아야 나중에
    "그래도 남겨두면 쓸모 있지 않을까" 하고 채워 넣는 실수가 코드 리뷰가 아니라
    스키마 단계에서 막힌다.

    **「거래가 있었다」의 판정 기준은 `accounts.withdrawal._transaction_basis`
    한 곳에만 있다** — 「탈퇴할 수 있는가」(`accounts.withdrawal.blocking_reasons`,
    진행 중인가)와는 다른 질문(있었는가)이라는 것이 이 모듈 분리로 드러난다.
    이 행을 실제로 만드는 자리는 `verification.purge.purge_identity`(#470) —
    탈퇴와 휴면 파기가 그 함수를 통해서만 이 행을 만든다.
    """

    class Reason(models.TextChoices):
        SPONSOR_PAID_CONTEST = "sponsor_paid_contest", "결제된 Contest 개최 이력"
        DEVELOPER_CONFIRMED_PAYOUT = "developer_confirmed_payout", "확정된 Payout 수령 이력"

    # PROTECT — 계정 행 자체를 지우지 않는다는 Withdrawal 전체의 전제와 같은
    # 이유로, 이 보존 기록도 계정 삭제에 딸려 조용히 사라지면 안 된다(애초에
    # User 행을 지우는 경로가 이 저장소에 없지만, 그 불변식을 스키마로 한 번 더
    # 못 박는다).
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, related_name="retained_identity", on_delete=models.PROTECT
    )

    real_name_encrypted = models.CharField(max_length=500)
    birth_date_encrypted = models.CharField(max_length=500)

    reason = models.CharField(max_length=32, choices=Reason.choices)
    # `reason`이 가리키는 거래(Contest 또는 Payout)의 PK. FK로 두지 않는다 —
    # reason에 따라 가리키는 테이블이 다형적으로 갈리고, 어느 테이블인지는
    # reason 자체가 이미 답한다. FK로 두면 verification 앱이 contests·payouts
    # 앱에 스키마 의존을 새로 지는데, 이 값은 "왜 남았는지"를 사람이 추적할
    # 실마리면 충분해 그 결합을 감수할 이유가 없다(#103, 운영자 열람 화면이
    # 생기면 그때 필요에 맞춰 다시 연다 — 이 티켓 범위 밖).
    retained_because_id = models.PositiveIntegerField()

    # 파기 예정 시각 — `RETAINED_IDENTITY_RETENTION_PERIOD`가 생성 시점 값을
    # 스냅샷으로 고정한다(정책이 나중에 바뀌어도 이미 만들어진 행은 흔들리지
    # 않는다, `payouts.Payout`이 요율을 자기 안에 기억하는 것과 같은 원칙).
    # #102의 만료 스캔이 이 값을 기준으로 지운다.
    retained_until = models.DateTimeField()

    created_at = models.DateTimeField(auto_now_add=True)

    # --- 암호화된 필드 접근자 (Verification과 같은 모양) -----------------------
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

    def __str__(self) -> str:  # pragma: no cover
        return f"RetainedIdentity<{self.user_id}:{self.reason}>"


class IdentityReading(models.Model):
    """Operator가 탈퇴 참가자의 보존된 실명(`RetainedIdentity`)을 펼쳐 본 사건 하나
    (#103, ADR-0022).

    `appeals.SourceReading`과 같은 모양이다 — 상태가 아니라 사건이다. 같은
    Operator가 같은 `RetainedIdentity`를 다시 펼치면 행이 하나 더 쌓인다.
    중복 제거하면 "한 번 봤다"와 "열 번 봤다"가 구별되지 않아 기록의 값이
    사라진다.

    둘 다 PROTECT다 — 열람한 Operator 계정이나 그 대상 `RetainedIdentity`를
    지우는 것만으로 "누가 이 실명을 봤는가"가 사라지면, ADR-0022가 세운 약속
    (감춘다는 말이 운영자 앞에서 조용히 사라지지 않는다)이 삭제 한 번으로
    무효가 된다.
    """

    retained_identity = models.ForeignKey(
        RetainedIdentity, related_name="identity_readings", on_delete=models.PROTECT
    )
    read_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="identity_readings", on_delete=models.PROTECT
    )
    read_at = models.DateTimeField()

    class Meta:
        ordering = ["-read_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"IdentityReading(retained_identity={self.retained_identity_id})"
