"""AssignmentPermission 운영자 API (#206, ADR-0028/0029).

- `GET /operator/assignment-permissions` — 지금 자격을 가진 Sponsor 목록. 일반
  등급도 조회할 수 있다(정책 조회와 같은 규율, #76).
- `POST /operator/assignment-permissions/grant` — 자격을 준다. 상위 등급만 —
  과제에는 결제가 없어 비용이 스스로 제어되지 않으므로(ADR-0029), 이 문을 여는
  것도 정책값·산출물 최소 상금을 바꾸는 것과 같은 무게의 판단이다.
- `GET /operator/assignment-permissions/changes` — 변경 이력. 일반 등급도 조회
  가능. **정의 순서가 아래 `{sponsor_profile_id}` 라우트보다 앞이어야 한다** —
  `contests.operator_api`의 같은 주석이 이유를 설명한다(정적 경로가 동적
  컨버터보다 먼저 매치돼야 한다).
- `POST /operator/assignment-permissions/{sponsor_profile_id}/revoke` — 자격을
  거둔다. 상위 등급만.

라우터 기본값이 이미 거부(`OperatorAuth`)다. 변경 엔드포인트는 그 위에 상위
등급까지 요구한다(`SuperuserOperatorAuth`).

`accounts.operator_api`(운영자 로그인·세션)와 분리한다 — `contests.api`/
`contests.operator_api`가 이미 같은 이유로 갈라져 있다: 인증 계층이 다른 표면을
한 파일에 두지 않는다.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router, Schema

from core.operator_auth import OperatorAuth, SuperuserOperatorAuth

from .assignment_permission_services import (
    AssignmentPermissionConflictError,
    AssignmentPermissionNotFoundError,
    AssignmentPermissionValidationError,
    grant_assignment_permission,
    revoke_assignment_permission,
)
from .models import AssignmentPermissionChange, SponsorProfile
from .schemas import (
    AssignmentPermissionChangeOut,
    AssignmentPermissionGrantIn,
    AssignmentPermissionHolderOut,
    AssignmentPermissionRevokeIn,
)

operator_router = Router(tags=["operator", "accounts"], auth=OperatorAuth())

_SUPERUSER = SuperuserOperatorAuth()


# django-ninja의 response= 선언에 쓸 간단한 오류 스키마 — contests.operator_api.
# OperatorErrorOut과 같은 계약(문자열 detail + 안정적인 code)이다.
class AssignmentPermissionErrorOut(Schema):
    detail: str
    code: str = "error"


def _serialize_holder(profile: SponsorProfile) -> AssignmentPermissionHolderOut:
    return AssignmentPermissionHolderOut(
        sponsor_profile_id=profile.id,
        user_id=profile.user_id,
        username=profile.user.username,
        display_name=profile.display_name,
        can_open_assignments=profile.can_open_assignments,
    )


def _serialize_change(change: AssignmentPermissionChange) -> AssignmentPermissionChangeOut:
    return AssignmentPermissionChangeOut(
        id=change.id,
        sponsor_profile_id=change.sponsor_profile_id,
        username=change.sponsor_profile.user.username,
        operator_username=change.operator.username,
        action=change.action,
        reason=change.reason,
        before=change.before,
        after=change.after,
        changed_at=change.changed_at,
    )


@operator_router.get(
    "/assignment-permissions", response={200: list[AssignmentPermissionHolderOut]}
)
def list_assignment_permission_holders(request: HttpRequest):
    holders = (
        SponsorProfile.objects.filter(can_open_assignments=True)
        .select_related("user")
        .order_by("user__username")
    )
    return 200, [_serialize_holder(profile) for profile in holders]


@operator_router.post(
    "/assignment-permissions/grant",
    response={
        200: AssignmentPermissionHolderOut,
        404: AssignmentPermissionErrorOut,
        409: AssignmentPermissionErrorOut,
        422: AssignmentPermissionErrorOut,
    },
    auth=_SUPERUSER,
)
def grant_assignment_permission_endpoint(
    request: HttpRequest, payload: AssignmentPermissionGrantIn
):
    try:
        profile = grant_assignment_permission(
            operator=request.auth, username=payload.username, reason=payload.reason
        )
    except AssignmentPermissionNotFoundError as exc:
        return 404, {"detail": str(exc), "code": "not_found"}
    except AssignmentPermissionConflictError as exc:
        return 409, {"detail": str(exc), "code": "already_granted"}
    except AssignmentPermissionValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}

    return 200, _serialize_holder(profile)


@operator_router.get(
    "/assignment-permissions/changes", response={200: list[AssignmentPermissionChangeOut]}
)
def list_assignment_permission_changes(request: HttpRequest):
    changes = AssignmentPermissionChange.objects.select_related(
        "operator", "sponsor_profile__user"
    ).order_by("-changed_at", "-id")[:200]
    return 200, [_serialize_change(change) for change in changes]


@operator_router.post(
    "/assignment-permissions/{sponsor_profile_id}/revoke",
    response={
        200: AssignmentPermissionHolderOut,
        404: AssignmentPermissionErrorOut,
        409: AssignmentPermissionErrorOut,
        422: AssignmentPermissionErrorOut,
    },
    auth=_SUPERUSER,
)
def revoke_assignment_permission_endpoint(
    request: HttpRequest, sponsor_profile_id: int, payload: AssignmentPermissionRevokeIn
):
    profile = (
        SponsorProfile.objects.filter(id=sponsor_profile_id).select_related("user").first()
    )
    if profile is None:
        return 404, {"detail": "Sponsor를 찾을 수 없습니다.", "code": "not_found"}

    try:
        updated = revoke_assignment_permission(
            profile, operator=request.auth, reason=payload.reason
        )
    except AssignmentPermissionConflictError as exc:
        return 409, {"detail": str(exc), "code": "already_revoked"}
    except AssignmentPermissionValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}

    updated.user = profile.user  # select_for_update()로 다시 읽은 행이라 재부착한다
    return 200, _serialize_holder(updated)
