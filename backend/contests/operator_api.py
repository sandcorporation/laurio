"""DeliverableType·Category 운영자 API (#80/#231, ADR-0023).

`accounts.operator_api`와 같은 분리 이유 — `contests.api`(공개 표면, 인증 계층이
다르고 파일이 이미 크다)와 이 표면(세션 인증, 등급이 갈린다)을 한 파일에 두지
않는다.

- `GET /operator/deliverable-types` — 활성·비활성 전부. 일반 등급도 조회할 수
  있다(정책 조회와 같은 규율, #76) — 운영자가 "왜 이 종류가 선택지에 없지"에
  답하려면 비활성 종류도 봐야 한다.
- `POST /operator/deliverable-types` — 새 종류 생성. 상위 등급만.
- `GET /operator/deliverable-types/changes` — 변경 이력. 일반 등급도 조회
  가능. **정의 순서가 아래 `{id}` 라우트보다 앞이어야 한다** — 이유는 그
  라우트 정의부의 주석을 보라.
- `POST /operator/deliverable-types/{id}` — 최소 제안 상금 수정. 상위 등급만.
- `POST /operator/deliverable-types/{id}/deactivate` — 비활성화. 상위 등급만.

`/operator/categories`도 같은 다섯 모양(목록·생성·이력·이름 수정·감추기)을
그대로 반복한다(#231) — Category에는 최소 제안 상금이 없는 대신 이름을 고칠
`contests.category_services`가 거부한다.

라우터 기본값이 이미 거부(`OperatorAuth`)다. 변경 엔드포인트는 그 위에 상위
등급까지 요구한다(`SuperuserOperatorAuth`) — 최소 제안 상금은 "상금미달" 배지
판정에 그대로 쓰이므로, 이 값을 바꾸는 것도 정책값과 같은 무게의 판단이다.
Category도 같은 무게로 다룬다(공개 목록의 분류 축이고 Contest가 참조를
붙든다) — 정책값이 없다는 차이가 등급 요구까지 낮추지는 않는다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.http import HttpRequest
from ninja import Router, Schema

from core.operator_auth import OperatorAuth, SuperuserOperatorAuth

from .category_services import (
    CategoryConflictError,
    CategoryValidationError,
    create_category,
    deactivate_category,
    rename_category,
)
from .deliverable_type_services import (
    DeliverableTypeConflictError,
    DeliverableTypeValidationError,
    create_deliverable_type,
    deactivate_deliverable_type,
    update_minimum_prize,
)
from .hosting_permission_services import (
    HostingPermissionConflictError,
    HostingPermissionValidationError,
    search_accounts,
    set_hosting_permission,
)
from .models import (
    Category,
    CategoryChange,
    Contest,
    DeliverableType,
    DeliverableTypeChange,
    HostingPermission,
    HostingPermissionChange,
)
from .schemas import (
    CategoryChangeOut,
    CategoryCreateIn,
    CategoryRenameIn,
    DeactivateCategoryIn,
    DeactivateDeliverableTypeIn,
    DeliverableTypeChangeOut,
    DeliverableTypeCreateIn,
    DeliverableTypeUpdateIn,
    HostingPermissionAccountOut,
    HostingPermissionChangeOut,
    OperatorCategoryOut,
    OperatorDeliverableTypeOut,
    OperatorFreeContestOut,
    OperatorFreeContestWinnerOut,
    SetHostingPermissionIn,
)

operator_router = Router(tags=["operator", "contests"], auth=OperatorAuth())

_SUPERUSER = SuperuserOperatorAuth()


# django-ninja의 response= 선언에 쓸 간단한 오류 스키마 — accounts.operator_api.
# ErrorOut과 같은 계약(문자열 detail + 안정적인 code)이다. 여기서 새로 정의하는
# 이유는 이 앱의 스키마 모듈(contests.schemas)이 그 계약을 아직 갖고 있지 않기
# 때문이다.
class OperatorErrorOut(Schema):
    detail: str
    code: str = "error"


def _serialize(deliverable_type: DeliverableType) -> OperatorDeliverableTypeOut:
    return OperatorDeliverableTypeOut(
        id=deliverable_type.id,
        name=deliverable_type.name,
        minimum_prize=deliverable_type.minimum_prize,
        is_active=deliverable_type.is_active,
    )


def _serialize_change(change: DeliverableTypeChange) -> DeliverableTypeChangeOut:
    return DeliverableTypeChangeOut(
        id=change.id,
        deliverable_type_id=change.deliverable_type_id,
        operator_username=change.operator.username,
        action=change.action,
        reason=change.reason,
        before=change.before,
        after=change.after,
        changed_at=change.changed_at,
    )


def _get_or_404(deliverable_type_id: int) -> DeliverableType | None:
    return DeliverableType.objects.filter(id=deliverable_type_id).first()


@operator_router.get("/deliverable-types", response={200: list[OperatorDeliverableTypeOut]})
def list_deliverable_types(request: HttpRequest):
    return 200, [
        _serialize(dt) for dt in DeliverableType.objects.all().order_by("name")
    ]


@operator_router.post(
    "/deliverable-types",
    response={201: OperatorDeliverableTypeOut, 409: OperatorErrorOut, 422: OperatorErrorOut},
    auth=_SUPERUSER,
)
def create_deliverable_type_endpoint(request: HttpRequest, payload: DeliverableTypeCreateIn):
    try:
        deliverable_type = create_deliverable_type(
            operator=request.auth,
            name=payload.name,
            minimum_prize=payload.minimum_prize,
            reason=payload.reason,
        )
    except DeliverableTypeValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    except DeliverableTypeConflictError as exc:
        return 409, {"detail": str(exc), "code": "duplicate"}

    return 201, _serialize(deliverable_type)


# **등록 순서가 중요하다.** django-ninja는 `{deliverable_type_id}` 같은 자리를
# 별도의 정수 컨버터 없이 "슬래시 없는 아무 문자열"에 매치시키므로, 아래
# `/deliverable-types/{deliverable_type_id}`(POST)가 먼저 등록되면 Django의
# URL 리졸버가 `/deliverable-types/changes`(GET)로 온 요청까지 그 패턴에
# 먼저 매치시켜버린다 — 매치된 패턴에 그 메서드(GET)가 없으므로 405가 나고,
# 리졸버는 다음 패턴으로 넘어가지 않는다(실제로 겪은 버그). 정적 경로
# `changes`를 동적 `{deliverable_type_id}`보다 먼저 등록해 이 충돌을 피한다.
@operator_router.get("/deliverable-types/changes", response={200: list[DeliverableTypeChangeOut]})
def list_deliverable_type_changes(request: HttpRequest):
    changes = DeliverableTypeChange.objects.select_related("operator").order_by(
        "-changed_at", "-id"
    )[:200]
    return 200, [_serialize_change(change) for change in changes]


@operator_router.post(
    "/deliverable-types/{deliverable_type_id}",
    response={200: OperatorDeliverableTypeOut, 404: OperatorErrorOut, 422: OperatorErrorOut},
    auth=_SUPERUSER,
)
def update_deliverable_type_endpoint(
    request: HttpRequest, deliverable_type_id: int, payload: DeliverableTypeUpdateIn
):
    deliverable_type = _get_or_404(deliverable_type_id)
    if deliverable_type is None:
        return 404, {"detail": "DeliverableType을 찾을 수 없습니다.", "code": "not_found"}

    try:
        updated = update_minimum_prize(
            deliverable_type,
            operator=request.auth,
            minimum_prize=payload.minimum_prize,
            reason=payload.reason,
        )
    except DeliverableTypeValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}

    return 200, _serialize(updated)


@operator_router.post(
    "/deliverable-types/{deliverable_type_id}/deactivate",
    response={200: OperatorDeliverableTypeOut, 404: OperatorErrorOut, 409: OperatorErrorOut, 422: OperatorErrorOut},
    auth=_SUPERUSER,
)
def deactivate_deliverable_type_endpoint(
    request: HttpRequest, deliverable_type_id: int, payload: DeactivateDeliverableTypeIn
):
    deliverable_type = _get_or_404(deliverable_type_id)
    if deliverable_type is None:
        return 404, {"detail": "DeliverableType을 찾을 수 없습니다.", "code": "not_found"}

    try:
        updated = deactivate_deliverable_type(
            deliverable_type, operator=request.auth, reason=payload.reason
        )
    except DeliverableTypeValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    except DeliverableTypeConflictError as exc:
        return 409, {"detail": str(exc), "code": "already_inactive"}

    return 200, _serialize(updated)


# --- Category (#231) — 위 DeliverableType 다섯 엔드포인트와 같은 모양이다 ------------------


def _serialize_category(category: Category) -> OperatorCategoryOut:
    return OperatorCategoryOut(
        id=category.id,
        name=category.name,
        is_active=category.is_active,
    )


def _serialize_category_change(change: CategoryChange) -> CategoryChangeOut:
    return CategoryChangeOut(
        id=change.id,
        category_id=change.category_id,
        operator_username=change.operator.username,
        action=change.action,
        reason=change.reason,
        before=change.before,
        after=change.after,
        changed_at=change.changed_at,
    )


def _get_category_or_404(category_id: int) -> Category | None:
    return Category.objects.filter(id=category_id).first()


@operator_router.get("/categories", response={200: list[OperatorCategoryOut]})
def list_categories(request: HttpRequest):
    return 200, [_serialize_category(c) for c in Category.objects.all().order_by("name")]


@operator_router.post(
    "/categories",
    response={201: OperatorCategoryOut, 409: OperatorErrorOut, 422: OperatorErrorOut},
    auth=_SUPERUSER,
)
def create_category_endpoint(request: HttpRequest, payload: CategoryCreateIn):
    try:
        category = create_category(
            operator=request.auth,
            name=payload.name,
            reason=payload.reason,
        )
    except CategoryValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    except CategoryConflictError as exc:
        return 409, {"detail": str(exc), "code": "duplicate"}

    return 201, _serialize_category(category)


# **등록 순서가 중요하다** — 위 `/deliverable-types/changes` 주석과 같은 이유
# (`{category_id}`가 별도 컨버터 없이 "changes"까지 매치해버린다).
@operator_router.get("/categories/changes", response={200: list[CategoryChangeOut]})
def list_category_changes(request: HttpRequest):
    changes = CategoryChange.objects.select_related("operator").order_by("-changed_at", "-id")[
        :200
    ]
    return 200, [_serialize_category_change(change) for change in changes]


@operator_router.post(
    "/categories/{category_id}",
    response={200: OperatorCategoryOut, 404: OperatorErrorOut, 409: OperatorErrorOut, 422: OperatorErrorOut},
    auth=_SUPERUSER,
)
def rename_category_endpoint(request: HttpRequest, category_id: int, payload: CategoryRenameIn):
    category = _get_category_or_404(category_id)
    if category is None:
        return 404, {"detail": "Category를 찾을 수 없습니다.", "code": "not_found"}

    try:
        updated = rename_category(
            category, operator=request.auth, name=payload.name, reason=payload.reason
        )
    except CategoryValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    except CategoryConflictError as exc:
        return 409, {"detail": str(exc), "code": "duplicate"}

    return 200, _serialize_category(updated)


@operator_router.post(
    "/categories/{category_id}/deactivate",
    response={200: OperatorCategoryOut, 404: OperatorErrorOut, 409: OperatorErrorOut, 422: OperatorErrorOut},
    auth=_SUPERUSER,
)
def deactivate_category_endpoint(
    request: HttpRequest, category_id: int, payload: DeactivateCategoryIn
):
    category = _get_category_or_404(category_id)
    if category is None:
        return 404, {"detail": "Category를 찾을 수 없습니다.", "code": "not_found"}

    try:
        updated = deactivate_category(category, operator=request.auth, reason=payload.reason)
    except CategoryValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    except CategoryConflictError as exc:
        return 409, {"detail": str(exc), "code": "already_inactive"}

    return 200, _serialize_category(updated)


# --- 무료 공모전 개최 권한 (#414, ADR-0048) -----------------------------------
#
# - `GET /operator/hosting-permissions/search?q=` — 이메일·닉네임으로 계정을
#   찾는다. 일반 등급도 조회할 수 있다(위 DeliverableType/Category 조회와 같은
#   규율).
# - `GET /operator/hosting-permissions` — 지금 권한이 있는 계정 목록.
# - `GET /operator/hosting-permissions/changes` — 변경 이력.
# - `POST /operator/hosting-permissions/{user_id}` — 켜기/끄기(사유 필수). 상위
#   등급만 — DeliverableType 값을 바꾸는 것과 같은 무게의 판단이다(누가 상금 없이
#   공모전을 열 수 있는지를 정한다).
#
# **정적 경로(`search`·`changes`)를 동적 `{user_id}`보다 먼저 등록한다** — 위
# `/deliverable-types/changes` 주석과 같은 이유(django-ninja가 `{user_id}`를
# 별도 정수 컨버터 없이 매치시킨다).


def _nickname_for(user) -> str:
    account = user.social_accounts.exclude(nickname="").order_by("id").first()
    return account.nickname if account is not None else ""


def _serialize_account(user) -> HostingPermissionAccountOut:
    permission = getattr(user, "hosting_permission", None)
    return HostingPermissionAccountOut(
        user_id=user.id,
        email=user.email,
        nickname=_nickname_for(user),
        is_granted=permission.is_granted if permission is not None else False,
    )


def _serialize_hosting_permission_change(change: HostingPermissionChange) -> HostingPermissionChangeOut:
    return HostingPermissionChangeOut(
        id=change.id,
        user_id=change.user_id,
        user_email=change.user.email,
        operator_username=change.operator.username,
        action=change.action,
        reason=change.reason,
        changed_at=change.changed_at,
    )


@operator_router.get(
    "/hosting-permissions/search", response={200: list[HostingPermissionAccountOut]}
)
def search_hosting_permission_accounts(request: HttpRequest, q: str = ""):
    return 200, [_serialize_account(user) for user in search_accounts(q)]


@operator_router.get(
    "/hosting-permissions/changes", response={200: list[HostingPermissionChangeOut]}
)
def list_hosting_permission_changes(request: HttpRequest):
    changes = HostingPermissionChange.objects.select_related("operator", "user").order_by(
        "-changed_at", "-id"
    )[:200]
    return 200, [_serialize_hosting_permission_change(change) for change in changes]


@operator_router.get("/hosting-permissions", response={200: list[HostingPermissionAccountOut]})
def list_hosting_permission_accounts(request: HttpRequest):
    granted = (
        HostingPermission.objects.filter(is_granted=True)
        .select_related("user")
        .order_by("user__email", "user_id")
    )
    return 200, [
        HostingPermissionAccountOut(
            user_id=permission.user_id,
            email=permission.user.email,
            nickname=_nickname_for(permission.user),
            is_granted=True,
        )
        for permission in granted
    ]


@operator_router.post(
    "/hosting-permissions/{user_id}",
    response={200: HostingPermissionAccountOut, 404: OperatorErrorOut, 409: OperatorErrorOut, 422: OperatorErrorOut},
    auth=_SUPERUSER,
)
def set_hosting_permission_endpoint(
    request: HttpRequest, user_id: int, payload: SetHostingPermissionIn
):
    user = get_user_model().objects.filter(id=user_id).first()
    if user is None:
        return 404, {"detail": "계정을 찾을 수 없습니다.", "code": "not_found"}

    try:
        permission = set_hosting_permission(
            user=user, operator=request.auth, granted=payload.granted, reason=payload.reason
        )
    except HostingPermissionValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}
    except HostingPermissionConflictError as exc:
        return 409, {"detail": str(exc), "code": "unchanged"}

    return 200, HostingPermissionAccountOut(
        user_id=user.id,
        email=user.email,
        nickname=_nickname_for(user),
        is_granted=permission.is_granted,
    )


# --- 무료 공모전 목록 (#420) --------------------------------------------------
#
# `GET /operator/contests/free` — 상태·마감·수상 여부·수상자. 수상자 옆의
# 「운영팀 알림 보내기」가 이 응답의 `winner`를 그대로 받는 사람으로 채운다
# (notifications.operator_api의 `RecipientOut`과 같은 필드 모양). 유료
# 공모전은 `is_free=True` 필터로 아예 섞이지 않는다 — 상금·본인확인·환불 같은
# 유료 전용 필드가 없는 목록이라 구별 플래그를 더하는 대신 필터로 뺐다.


def _serialize_free_contest(contest: Contest) -> OperatorFreeContestOut:
    award = getattr(contest, "award", None)
    winner = None
    if award is not None:
        winner_user = award.submission.user
        winner = OperatorFreeContestWinnerOut(
            user_id=winner_user.id,
            email=winner_user.email,
            nickname=_nickname_for(winner_user),
        )
    return OperatorFreeContestOut(
        id=contest.id,
        title=contest.title,
        status=contest.status,
        deadline_at=contest.deadline_at,
        judging_ends_at=contest.judging_ends_at,
        winner=winner,
    )


@operator_router.get("/contests/free", response={200: list[OperatorFreeContestOut]})
def list_free_contests(request: HttpRequest):
    contests = (
        Contest.objects.filter(is_free=True)
        .select_related("award__submission__user")
        .order_by("-created_at")
    )
    return 200, [_serialize_free_contest(contest) for contest in contests]
