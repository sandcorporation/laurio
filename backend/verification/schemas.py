from datetime import datetime

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
