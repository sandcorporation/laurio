"""DeliverableType 운영자 관리 도메인 로직 (#80, ADR-0023).

API 레이어(`contests.operator_api`)에서만 호출된다 — 테스트의 유일한 시임은
HTTP이므로 여기 함수를 테스트에서 직접 부르지 않는다(CLAUDE.md).

`policies.services.update_policy`와 같은 규율이다 — 이유 없는 변경은 거부하고,
바뀐 값과 이전 값을 같은 트랜잭션 안에서 `DeliverableTypeChange` 한 건으로
남긴다. 다만 `PlatformPolicy`(단일 행)와 달리 `DeliverableType`은 행이 여러
개이고 서로 독립이므로, 정책 API처럼 낙관적 동시성(`expected_version`)을 요구
하지 않는다 — 두 Operator가 **같은** 종류를 동시에 편집하는 것은 `select_for_
update()`로 직렬화되고(마지막에 커밋한 쪽이 이긴다), **다른** 종류를 동시에
편집하는 것은 애초에 서로 겹치지 않는다.
"""

from __future__ import annotations

from django.db import IntegrityError, transaction

from core.clock import Clock

from .models import DeliverableType, DeliverableTypeChange


class DeliverableTypeValidationError(Exception):
    """말이 안 되는 입력(이유 없음·빈 이름 등) — 호출자는 422로 옮긴다."""


class DeliverableTypeConflictError(Exception):
    """이름 중복, 이미 비활성인 종류의 재비활성화 등 — 호출자는 409로 옮긴다."""


def _require_reason(reason: str) -> str:
    stripped = reason.strip()
    if not stripped:
        raise DeliverableTypeValidationError("이유(reason)를 남겨야 합니다.")
    return stripped


def create_deliverable_type(*, operator, name: str, minimum_prize: int, reason: str) -> DeliverableType:
    """새 종류를 만든다. 추가 즉시 공개 목록(`GET /api/contests/deliverable-types`)에
    나타난다 — 그 엔드포인트가 `is_active=True`를 매 요청마다 다시 조회하지,
    캐시된 목록을 쓰지 않기 때문이다."""

    reason = _require_reason(reason)
    stripped_name = name.strip()
    if not stripped_name:
        raise DeliverableTypeValidationError("이름을 입력해야 합니다.")

    with transaction.atomic():
        try:
            # 세이브포인트로 감싼다(payments.api.initiate_payment와 같은 이유) —
            # unique 제약 위반이 바깥 트랜잭션 전체를 abort시키지 않게 한다.
            with transaction.atomic():
                deliverable_type = DeliverableType.objects.create(
                    name=stripped_name, minimum_prize=minimum_prize
                )
        except IntegrityError:
            raise DeliverableTypeConflictError(f"이미 존재하는 이름입니다: {stripped_name}")

        DeliverableTypeChange.objects.create(
            deliverable_type=deliverable_type,
            operator=operator,
            action=DeliverableTypeChange.Action.CREATED,
            reason=reason,
            before={},
            after={"name": deliverable_type.name, "minimum_prize": deliverable_type.minimum_prize},
            changed_at=Clock.now(),
        )

    return deliverable_type


def update_minimum_prize(
    deliverable_type: DeliverableType, *, operator, minimum_prize: int, reason: str
) -> DeliverableType:
    """최소 제안 상금을 바꾼다. 이 값이 바뀌면 "상금미달" 배지 판정
    (`contests.api._minimum_total`)이 다음 Contest 개최 견적부터 새 값을 쓴다 —
    이미 만들어진 Contest의 `required_minimum_prize`는 개최 시점의 스냅샷이라
    소급되지 않는다(`contests/api.py`의 create_contest가 그 합을 계산해 저장하는
    시점에 고정된다)."""

    reason = _require_reason(reason)

    with transaction.atomic():
        locked = DeliverableType.objects.select_for_update().get(pk=deliverable_type.pk)
        before = {"minimum_prize": locked.minimum_prize}
        locked.minimum_prize = minimum_prize
        locked.save(update_fields=["minimum_prize"])

        DeliverableTypeChange.objects.create(
            deliverable_type=locked,
            operator=operator,
            action=DeliverableTypeChange.Action.UPDATED,
            reason=reason,
            before=before,
            after={"minimum_prize": minimum_prize},
            changed_at=Clock.now(),
        )

    return locked


def deactivate_deliverable_type(
    deliverable_type: DeliverableType, *, operator, reason: str
) -> DeliverableType:
    """종류를 비활성화한다 — 지우지 않는다. 이미 이 종류를 쓰는 Contest는 그대로
    동작한다(`Contest.deliverable_types`가 여전히 이 행을 가리킨다). 새 Contest의
    선택지(`GET /api/contests/deliverable-types`)에서만 빠진다 — 그 엔드포인트가
    `is_active=True`만 돌려주기 때문이다."""

    reason = _require_reason(reason)

    with transaction.atomic():
        locked = DeliverableType.objects.select_for_update().get(pk=deliverable_type.pk)
        if not locked.is_active:
            raise DeliverableTypeConflictError("이미 비활성화된 종류입니다.")

        locked.is_active = False
        locked.save(update_fields=["is_active"])

        DeliverableTypeChange.objects.create(
            deliverable_type=locked,
            operator=operator,
            action=DeliverableTypeChange.Action.DEACTIVATED,
            reason=reason,
            before={"is_active": True},
            after={"is_active": False},
            changed_at=Clock.now(),
        )

    return locked
