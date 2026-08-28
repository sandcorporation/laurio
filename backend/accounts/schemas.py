from ninja import Schema
from pydantic import Field


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
