from datetime import date, datetime

from django.db import models
from ninja import Schema


class VerifyIn(Schema):
    verification_token: str


class VerificationStartOut(Schema):
    """서버가 발급한 identityVerificationId(#85 코드리뷰 지적 1).

    브라우저 SDK는 이 값을 그대로 실어 인증창을 연다. `verify()`는 실물
    어댑터를 쓸 때 이 값이 실제로 요청자 본인에게 발급된 것인지 확인한다.
    """

    identity_verification_id: str


class VerificationStatusValue(models.TextChoices):
    """`Verification.Status` 네 값에 「행 자체가 없음」을 더한, API 응답 전용 값
    (#250). `Verification.Status`를 그대로 재사용하지 못하는 이유는 "한 번도
    확인한 적이 없다"가 그 모델에서는 행이 아예 없다는 뜻이라 값 자체가 없어서다
    (`verification.api._to_status_out`이 그 경우 이 값의 `UNVERIFIED`를 만들어
    낸다).

    `submissions.participation.NextAction`과 같은 이유로 `str` 이 아니라 enum
    이다 — 필드가 `str`이면 생성된 TS 타입도 `status: string`이 되어, 값이
    새로 생기거나(`expired`·`withdrawn`이 그랬다, #102/#100) 화면이 그중 하나만
    분기해도 `tsc`가 누락을 잡지 못한다. 실제로 #250 이전에는 이 필드가 `str`
    이었고, 주석만 "unverified" | "verified" | "underage" 라 적혀 있어 `expired`
    가 이미 실사용에 등장한 지 한참 지나서도 낡은 채였다.
    """

    UNVERIFIED = "unverified", "본인확인 안 함"
    VERIFIED = "verified", "본인확인 완료"
    UNDERAGE = "underage", "만 19세 미만"
    WITHDRAWN = "withdrawn", "탈퇴(신원 파기)"
    EXPIRED = "expired", "미이용으로 신원 파기"


class VerificationStatusOut(Schema):
    status: VerificationStatusValue
    reason: str | None = None
    verified_at: datetime | None = None


class CiLookupIn(Schema):
    ci: str


class CiLookupMatchOut(Schema):
    user_id: int
    verified_at: datetime | None = None


class CiLookupOut(Schema):
    matches: list[CiLookupMatchOut]


# --- Operator: 보존된 실명 열람 (#103, ADR-0022) ------------------------------


class RetainedIdentityOut(Schema):
    """목록·상세 — 접힌 채로 나간다. 실명·생년월일은 여기 없다(#103 AC).

    `펼침`(POST .../reveal) 을 거쳐야만 값이 내려온다 — 목록을 훑거나 상세를
    여는 것만으로는 값이 내려오지 않는다.
    """

    id: int
    user_id: int
    reason: str
    retained_because_id: int
    retained_until: datetime
    created_at: datetime


class RetainedIdentityRevealOut(Schema):
    """펼침 응답 (#103, ADR-0022). 이 요청 자체가 `IdentityReading` 을 남긴다."""

    real_name: str
    birth_date: date
