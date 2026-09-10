"""AssignmentPermission 부여·회수 (#206, ADR-0028/0029).

API 레이어(`accounts.assignment_permission_operator_api`)에서만 호출된다 — 테스트의
유일한 시임은 HTTP이므로(CLAUDE.md) 이 함수들을 테스트에서 직접 부르지 않는다.

`contests.deliverable_type_services`와 같은 규율이다 — 이유 없는 변경은 거부하고,
바뀐 값과 이전 값을 같은 트랜잭션 안에서 `AssignmentPermissionChange` 한 건으로
남긴다. 대상 행이 `SponsorProfile`(사용자마다 최대 하나)이라 두 Operator가 같은
Sponsor를 동시에 편집하는 것은 `select_for_update()`로 직렬화되고(마지막에 커밋한
쪽이 이긴다), 다른 Sponsor를 동시에 편집하는 것은 애초에 서로 겹치지 않는다 —
`PlatformPolicy`(단일 행)와 달리 낙관적 동시성(`expected_version`)을 요구하지
않는다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import transaction

from core.clock import Clock

from .models import AssignmentPermissionChange, SponsorProfile
from .operators import is_operator


class AssignmentPermissionValidationError(Exception):
    """말이 안 되는 입력(이유 없음·사용자명 없음·Operator 계정 등) — 호출자는 422로 옮긴다."""


class AssignmentPermissionNotFoundError(Exception):
    """그 사용자명의 User가 없다 — 호출자는 404로 옮긴다."""


class AssignmentPermissionConflictError(Exception):
    """이미 부여됨(재부여)·이미 회수됨(재회수) — 호출자는 409로 옮긴다."""


def _require_reason(reason: str) -> str:
    stripped = reason.strip()
    if not stripped:
        raise AssignmentPermissionValidationError("이유(reason)를 남겨야 합니다.")
    return stripped


def grant_assignment_permission(*, operator, username: str, reason: str) -> SponsorProfile:
    """username으로 찾은 사용자에게 과제 개최 자격을 준다.

    `SponsorProfile`이 아직 없으면 지연 생성한다(`accounts.api.ensure_sponsor_profile`과
    같은 관용구) — Operator가 출제자에게 자격을 먼저 주고, 출제자가 나중에 처음
    Sponsor로 행동하는 순서가 자연스럽다(과제를 열기 전에는 이 프로필을 만들
    이유가 없었다).
    """

    reason = _require_reason(reason)
    stripped_username = username.strip()
    if not stripped_username:
        raise AssignmentPermissionValidationError("사용자명을 입력해야 합니다.")

    User = get_user_model()
    user = User.objects.filter(username=stripped_username).first()
    if user is None:
        raise AssignmentPermissionNotFoundError(f"사용자를 찾을 수 없습니다: {stripped_username}")

    # 서로소 불변식(ADR-0018)이 구조적으로 막는 조합이지만(Operator는 소셜 계정이
    # 없어 정상 경로로 SponsorProfile에 닿지 않는다), 사용자명으로 임의의 User를
    # 지정하는 이 입력구는 그 구조를 우회한다 — 여기서 다시 명시적으로 막는다.
    if is_operator(user):
        raise AssignmentPermissionValidationError(
            "Operator 계정에는 과제 개최 자격을 줄 수 없습니다(ADR-0018의 서로소 불변식)."
        )

    with transaction.atomic():
        profile, _created = SponsorProfile.objects.get_or_create(user=user)
        locked = SponsorProfile.objects.select_for_update().get(pk=profile.pk)

        if locked.can_open_assignments:
            raise AssignmentPermissionConflictError("이미 과제 개최 자격이 있습니다.")

        locked.can_open_assignments = True
        locked.save(update_fields=["can_open_assignments"])

        AssignmentPermissionChange.objects.create(
            sponsor_profile=locked,
            operator=operator,
            action=AssignmentPermissionChange.Action.GRANTED,
            reason=reason,
            before={"can_open_assignments": False},
            after={"can_open_assignments": True},
            changed_at=Clock.now(),
        )

    # `select_for_update().get(pk=...)`가 다시 읽은 행이라 `.user`가 캐시돼 있지
    # 않다 — 위에서 이미 조회한 `user`를 재부착해 호출부(API 레이어의
    # `_serialize_holder`)가 `locked.user.username`을 읽을 때 쿼리를 한 번 더
    # 내지 않게 한다(revoke_assignment_permission의 호출부가 같은 이유로
    # `updated.user = profile.user`를 하는 것과 같다).
    locked.user = user

    return locked


def revoke_assignment_permission(
    sponsor_profile: SponsorProfile, *, operator, reason: str
) -> SponsorProfile:
    """과제 개최 자격을 거둔다.

    이미 열린 Assignment는 이 호출로 영향받지 않는다 — `can_open_assignments`는
    **새 과제를 열 수 있는가**만 게이트하고, 이미 존재하는 `Contest` 행에는 이
    값을 참조하는 필드가 전혀 없다(ADR-0029: "자격을 거두어도 이미 열린 과제는
    끝까지 돈다"). 그래서 이 함수는 Contest를 전혀 건드리지 않는다.
    """

    reason = _require_reason(reason)

    with transaction.atomic():
        locked = SponsorProfile.objects.select_for_update().get(pk=sponsor_profile.pk)

        if not locked.can_open_assignments:
            raise AssignmentPermissionConflictError("이미 과제 개최 자격이 없습니다.")

        locked.can_open_assignments = False
        locked.save(update_fields=["can_open_assignments"])

        AssignmentPermissionChange.objects.create(
            sponsor_profile=locked,
            operator=operator,
            action=AssignmentPermissionChange.Action.REVOKED,
            reason=reason,
            before={"can_open_assignments": True},
            after={"can_open_assignments": False},
            changed_at=Clock.now(),
        )

    return locked
