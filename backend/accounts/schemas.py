from ninja import Schema


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
    display_name: str = ""
    bio: str = ""


class ProfileOut(Schema):
    display_name: str
    bio: str
