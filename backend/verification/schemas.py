from datetime import date, datetime

from ninja import Schema


class VerifyIn(Schema):
    verification_token: str


class VerificationStartOut(Schema):
    """서버가 발급한 identityVerificationId(#85 코드리뷰 지적 1).

    브라우저 SDK는 이 값을 그대로 실어 인증창을 연다. `verify()`는 실물
    어댑터를 쓸 때 이 값이 실제로 요청자 본인에게 발급된 것인지 확인한다.
    """

    identity_verification_id: str


class VerificationStatusOut(Schema):
    status: str  # "unverified" | "verified" | "underage"
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
