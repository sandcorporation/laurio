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


class AssignmentPermissionHolderOut(Schema):
    """지금 과제 개최 자격을 가진 Sponsor 한 명 (#206, ADR-0029)."""

    sponsor_profile_id: int
    user_id: int
    username: str
    display_name: str
    can_open_assignments: bool


class AssignmentPermissionGrantIn(Schema):
    # 사용자명으로 대상을 찾는다 — SponsorProfile은 지연 생성이라 아직 존재하지
    # 않을 수 있고(accounts.assignment_permission_services.grant_assignment_permission
    # 참고), user_id보다 운영자가 지원 대화에서 실제로 들고 오는 값에 더 가깝다.
    username: str
    reason: str


class AssignmentPermissionRevokeIn(Schema):
    reason: str


class AssignmentPermissionChangeOut(Schema):
    """`AssignmentPermissionChange` 한 건 — 누가·언제·무엇을·왜.

    `sponsor_profile_id`만이 아니라 `username`도 함께 준다 — 회수된 Sponsor는
    자격 보유자 목록(`GET /operator/assignment-permissions`)에서 빠지므로,
    `contests.DeliverableTypeChangeOut`처럼 별도 목록과 조인하지 않고 이 행
    하나로 화면이 "누구의 이력인가"에 답할 수 있어야 한다.
    """

    id: int
    sponsor_profile_id: int
    username: str
    operator_username: str
    action: str
    reason: str
    before: dict
    after: dict
    changed_at: datetime
