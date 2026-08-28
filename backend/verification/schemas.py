from datetime import datetime

from ninja import Schema


class VerifyIn(Schema):
    verification_token: str


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
