from datetime import datetime

from ninja import Schema
from pydantic import Field

from .withdrawal import WithdrawalBlockReason


class SocialLoginIn(Schema):
    access_token: str


class TokenPairOut(Schema):
    access: str
    refresh: str
    token_type: str = "bearer"


class RefreshIn(Schema):
    refresh: str


class LogoutIn(Schema):
    refresh: str | None = None


class MeOut(Schema):
    id: int
    username: str
    email: str
    has_sponsor_profile: bool
    has_developer_profile: bool


class ProfileIn(Schema):
    """필드가 아예 안 왔으면(None) 손대지 않고, ""가 명시적으로 왔으면 비운다.

    "안 보냄"과 "빈 값으로 지움"을 구분해야 한 필드만 바꾸는 부분 업데이트가
    다른 필드를 조용히 지우지 않는다.
    """

    display_name: str | None = Field(default=None, max_length=100)
    bio: str | None = None


class ProfileOut(Schema):
    display_name: str
    bio: str


class WithdrawalEligibilityOut(Schema):
    """탈퇴 화면이 「막고 있는 것」을 그대로 보여줄 수 있게 하는 판정 결과.

    `blocking_reasons`가 `WithdrawalBlockReason`(enum)이라 생성된 프론트 타입에
    리터럴 유니온으로 나타난다 — 값이 하나 늘면 번역표를 가진 파일에서
    `tsc --noEmit`이 빌드타임에 잡는다(accounts.withdrawal 모듈 독스트링 참고).
    """

    can_withdraw: bool
    blocking_reasons: list[WithdrawalBlockReason]


class WithdrawalOut(Schema):
    withdrawn_at: datetime


class WithdrawalRejectedOut(Schema):
    """탈퇴가 거부될 때의 응답 — 무엇이 막는지 목록으로 준다(#100 AC)."""

    detail: str
    blocking_reasons: list[WithdrawalBlockReason]
