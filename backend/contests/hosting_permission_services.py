"""무료 공모전 개최 권한 운영자 관리 도메인 로직 (#414, ADR-0023, ADR-0048).

API 레이어(`contests.operator_api`)에서만 호출된다 — 테스트의 유일한 시임은
HTTP이므로 여기 함수를 테스트에서 직접 부르지 않는다(CLAUDE.md).

`contests.deliverable_type_services`와 같은 규율이다 — 이유 없는 변경은 거부하고,
현재값(`HostingPermission`)과 append-only 이력(`HostingPermissionChange`)을 같은
트랜잭션 안에서 함께 남긴다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, QuerySet

from core.clock import Clock

from .models import HostingPermission, HostingPermissionChange


class HostingPermissionValidationError(Exception):
    """말이 안 되는 입력(사유 없음 등) — 호출자는 422로 옮긴다."""


class HostingPermissionConflictError(Exception):
    """이미 그 상태다(이미 켜져 있는데 다시 켜려 하는 등) — 호출자는 409로 옮긴다."""


def _require_reason(reason: str) -> str:
    stripped = reason.strip()
    if not stripped:
        raise HostingPermissionValidationError("이유(reason)를 남겨야 합니다.")
    return stripped


def search_accounts(query: str) -> QuerySet:
    """이메일·닉네임으로 계정을 찾는다 — `User.username`은 소셜 로그인이 지어낸
    값(`kakao:12345` 꼴, `accounts.api._username_for`)이라 사람이 검색어로 쓸 수
    없고, 사람이 읽을 이름은 `SocialAccount.nickname`에 있다(로그인마다 최신값으로
    갱신된다, #390).

    빈 검색어는 아무것도 찾지 않는다 — 운영자가 실수로 빈 채로 눌러도 계정
    전체가 쏟아지지 않게 한다.
    """

    stripped = query.strip()
    if not stripped:
        return get_user_model().objects.none()

    return (
        get_user_model()
        .objects.filter(Q(email__icontains=stripped) | Q(social_accounts__nickname__icontains=stripped))
        .distinct()
        .select_related("hosting_permission")
        .order_by("email", "id")[:50]
    )


def set_hosting_permission(*, user, operator, granted: bool, reason: str) -> HostingPermission:
    """계정의 개최 권한을 켜거나 끈다. 이미 그 상태면 409 — 의도한 변경이 실제로
    일어났을 때만 이력을 남긴다(중복 이력은 「언제 진짜로 바뀌었는가」를 흐린다).

    권한을 꺼도 그 계정이 이미 공개한 무료 공모전은 영향받지 않는다(#414 —
    이 함수는 `HostingPermission` 행만 바꾸고 `Contest`는 건드리지 않는다) —
    무료 개최 자체는 #415의 몫이라 여기서 확인할 대상도 아직 없다.
    """

    reason = _require_reason(reason)

    with transaction.atomic():
        permission, _created = HostingPermission.objects.get_or_create(user=user)
        locked = HostingPermission.objects.select_for_update().get(pk=permission.pk)

        if locked.is_granted == granted:
            state = "있습니다" if granted else "없습니다"
            raise HostingPermissionConflictError(f"이미 개최 권한이 {state}.")

        locked.is_granted = granted
        locked.save(update_fields=["is_granted", "updated_at"])

        HostingPermissionChange.objects.create(
            user=user,
            operator=operator,
            action=(
                HostingPermissionChange.Action.GRANTED
                if granted
                else HostingPermissionChange.Action.REVOKED
            ),
            reason=reason,
            changed_at=Clock.now(),
        )

    return locked
