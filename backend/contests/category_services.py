"""Category 운영자 관리 도메인 로직 (#231, ADR-0023 준용).

API 레이어(`contests.operator_api`)에서만 호출된다 — 테스트의 유일한 시임은
HTTP이므로 여기 함수를 테스트에서 직접 부르지 않는다(CLAUDE.md).

`contests.deliverable_type_services`와 같은 규율이다 — 이유 없는 변경은
거부하고, 바뀐 값과 이전 값을 같은 트랜잭션 안에서 `CategoryChange` 한 건으로
남긴다. `DeliverableType`과 달리 낙관적 동시성(`expected_version`)을 요구하지
않는 것도 같은 이유다 — 행이 여러 개이고 서로 독립이므로 `select_for_update()`
로 충분하다.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from core.clock import Clock

from .models import Category, CategoryChange


class CategoryValidationError(Exception):
    """말이 안 되는 입력(이유 없음·빈 이름 등) — 호출자는 422로 옮긴다."""


class CategoryConflictError(Exception):
    """이름 중복, 이미 비활성인 Category의 재비활성화 등 — 호출자는 409로 옮긴다."""


def _require_reason(reason: str) -> str:
    stripped = reason.strip()
    if not stripped:
        raise CategoryValidationError("이유(reason)를 남겨야 합니다.")
    return stripped


def _require_name(name: str) -> str:
    stripped = name.strip()
    if not stripped:
        raise CategoryValidationError("이름을 입력해야 합니다.")
    return stripped


def create_category(*, operator, name: str, reason: str) -> Category:
    """새 Category를 만든다. 추가 즉시 공개 목록(`GET /api/contests/categories`)에
    나타난다 — 그 엔드포인트가 `is_active=True`를 매 요청마다 다시 조회하지,
    캐시된 목록을 쓰지 않기 때문이다."""

    reason = _require_reason(reason)
    stripped_name = _require_name(name)

    with transaction.atomic():
        try:
            # 세이브포인트로 감싼다(deliverable_type_services.create_deliverable_type과
            # 같은 이유) — unique 제약 위반이 바깥 트랜잭션 전체를 abort시키지 않게 한다.
            with transaction.atomic():
                category = Category.objects.create(name=stripped_name)
        except IntegrityError:
            raise CategoryConflictError(f"이미 존재하는 이름입니다: {stripped_name}")

        CategoryChange.objects.create(
            category=category,
            operator=operator,
            action=CategoryChange.Action.CREATED,
            reason=reason,
            before={},
            after={"name": category.name},
            changed_at=Clock.now(),
        )

    return category


def rename_category(category: Category, *, operator, name: str, reason: str) -> Category:
    """이름을 고친다."""

    reason = _require_reason(reason)
    stripped_name = _require_name(name)

    with transaction.atomic():
        locked = Category.objects.select_for_update().get(pk=category.pk)
        before = {"name": locked.name}
        locked.name = stripped_name
        try:
            with transaction.atomic():
                locked.save(update_fields=["name"])
        except IntegrityError:
            raise CategoryConflictError(f"이미 존재하는 이름입니다: {stripped_name}")

        CategoryChange.objects.create(
            category=locked,
            operator=operator,
            action=CategoryChange.Action.UPDATED,
            reason=reason,
            before=before,
            after={"name": stripped_name},
            changed_at=Clock.now(),
        )

    return locked


def deactivate_category(category: Category, *, operator, reason: str) -> Category:
    """Category를 감춘다 — 지우지 않는다. 이미 이 Category를 쓰는 Contest는 그대로
    동작한다(`Contest.category`가 여전히 이 행을 가리킨다). 공개 목록의 필터·개최
    화면의 선택지(`GET /api/contests/categories`)에서만 빠진다 — 그 엔드포인트가
    `is_active=True`만 돌려주기 때문이다. 예약된 Assignment Category는 거부한다
    (모듈 docstring) — 애초에 이미 비활성이라 통상적인 "이미 비활성" 409와
    구별되지 않게 두지 않고, 이유를 분명히 한다."""

    reason = _require_reason(reason)

    with transaction.atomic():
        locked = Category.objects.select_for_update().get(pk=category.pk)
        if not locked.is_active:
            raise CategoryConflictError("이미 감춰진 Category입니다.")

        locked.is_active = False
        locked.save(update_fields=["is_active"])

        CategoryChange.objects.create(
            category=locked,
            operator=operator,
            action=CategoryChange.Action.DEACTIVATED,
            reason=reason,
            before={"is_active": True},
            after={"is_active": False},
            changed_at=Clock.now(),
        )

    return locked
