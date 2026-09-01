"""PlatformPolicy 읽기·쓰기 (#75, #76, ADR-0023).

읽기(`get_current_policy`)는 호출 스코프당 한 번이다 — `core.transitions`가
`Clock.now()`를 스캔 한 번당 한 번만 구해 그 값을 인자로 넘기는 것과 같은
관용구다: 값마다(또는 Payout마다) 정책을 다시 조회하면 채점·배분·지급 경로에서
쿼리가 값의 수·건수만큼 늘어난다. 이 모듈의 읽기 함수는 호출자가 요청(또는
스캔) 시작 시점에 정확히 한 번만 부르고, 그 뒤로는 반환값을 계속 재사용해야
한다.

쓰기(`update_policy`)는 이 앱 밖에서 부르지 않는다 — `policies.api`(운영자
API, #76)에서만 호출된다. 테스트의 유일한 시임은 HTTP이므로(CLAUDE.md) 이
함수를 테스트에서 직접 부르지 않는다.
"""

from __future__ import annotations

from django.db import transaction

from core.clock import Clock

from .models import PlatformPolicy, PolicyChange

# 운영자 API가 바꿀 수 있는 필드. #76이 다루는 것은 체인 1(#75)이 이미 넣은
# 요율 둘(platform_fee_bps, withholding_tax_bps)과 그 부속값 둘뿐이다 —
# 나머지 정책값(개최비·기간·리드타임·컷라인)은 #78·#79가 각자의 티켓에서
# `PlatformPolicy`에 필드를 더한 뒤 이 집합에 편입시킨다.
UPDATABLE_FIELDS = frozenset(
    {
        "platform_fee_bps",
        "withholding_tax_bps",
        "withholding_necessary_expense_bps",
        "withholding_minor_income_exempt_won",
    }
)

# (하한, 상한) — PlatformPolicy.Meta.constraints의 개별 CheckConstraint와
# 정확히 같은 경계다. 이 값들이 어긋나면 그 제약이 IntegrityError(500)로
# 막아버리므로, API 레이어가 저장을 시도하기 전에 같은 경계로 4xx를 돌려줘야
# 한다(ADR-0023: "제약은 최후의 방어선이지 사용자에게 보여줄 오류가 아니다").
_FIELD_BOUNDS: dict[str, tuple[int, int]] = {
    "platform_fee_bps": (0, 9000),
    "withholding_tax_bps": (0, 9000),
    "withholding_necessary_expense_bps": (0, 9999),
    "withholding_minor_income_exempt_won": (0, 2**31 - 1),
}


class PolicyValidationError(Exception):
    """말이 안 되는 입력(음수·상한 초과·이유 없음 등) — 호출자는 4xx로 옮긴다."""


class PolicyConflictError(Exception):
    """다른 변경이 먼저 커밋되어 `expected_version`이 더 이상 최신이 아니다 — 409."""


def get_current_policy() -> PlatformPolicy:
    """현재 정책 행을 읽는다. 행이 없으면(신선한 DB) 기본값으로 만든다.

    `distributions.services.get_cutline_percentage`가 `DistributionCutline`에
    대해 하는 것과 같은 get_or_create 관용구 — 부팅과 첫 요청이 마이그레이션
    직후에도 그냥 동작해야 한다(ADR-0023).
    """

    policy, _created = PlatformPolicy.objects.get_or_create(pk=1)
    return policy


def _validate(
    changes: dict[str, int], reason: str
) -> tuple[list[str], int | None, int | None]:
    problems: list[str] = []

    if not reason.strip():
        problems.append("이유(reason)를 남겨야 합니다.")

    if not changes:
        problems.append("변경할 값이 없습니다.")

    unknown = set(changes) - UPDATABLE_FIELDS
    if unknown:
        problems.append(f"알 수 없는 필드입니다: {', '.join(sorted(unknown))}")

    for field, value in changes.items():
        bounds = _FIELD_BOUNDS.get(field)
        if bounds is None:
            continue
        low, high = bounds
        if value < low or value > high:
            problems.append(f"{field}는 {low}~{high} 사이여야 합니다(받은 값: {value}).")

    fee = changes.get("platform_fee_bps")
    withholding = changes.get("withholding_tax_bps")
    return problems, fee, withholding


def update_policy(
    *, operator, reason: str, expected_version: int, changes: dict[str, int]
) -> tuple[PlatformPolicy, PolicyChange]:
    """정책을 바꾸고 같은 트랜잭션 안에서 `PolicyChange` 한 건을 남긴다.

    **동시성.** `select_for_update()`로 이 단일 행을 잠근 뒤 `version`이
    `expected_version`과 같을 때만 진행한다 — 다르면 `PolicyConflictError`를
    던진다(호출자는 409). 두 Operator가 동시에 PATCH하면 먼저 도착한 트랜잭션이
    잠금을 얻어 커밋하고 `version`을 올리고, 뒤에 대기하던 트랜잭션은 잠금이
    풀린 뒤 다시 읽어 자신이 봤던 `expected_version`이 이미 낡았음을 발견한다 —
    `core.transitions.claim_transition`의 "조건부 UPDATE, rowcount로 성공 여부
    판정"과 같은 정신이다. 이렇게 하지 않으면 두 번째 쓰기가 첫 번째의 결과를
    조용히 덮어써, `before`가 실제 이전 값과 어긋나는 거짓 이력을 남긴다.

    **검증은 저장 전에 끝낸다.** `PlatformPolicy`의 CheckConstraint가 최후의
    방어선으로 남아 있지만, 여기서 먼저 막아야 지급 요청 경로가 예전에 겪었던
    "중단된 트랜잭션 안에서 재조회하다 다른 500을 만드는" 사고를 이 표면에서도
    반복하지 않는다.

    `changes`는 실제로 바뀌는 필드만 담는다 — `before`·`after`는 그 필드들만의
    적용 직전·직후 값이므로, 건드리지 않은 필드는 이력에 나타나지 않는다.
    """

    problems, fee, withholding = _validate(changes, reason)

    with transaction.atomic():
        # `select_for_update().get(pk=1)`은 행의 존재를 전제한다 — 신선한
        # DB(GET을 한 번도 안 거친 채 POST부터 오는 경우, 예: expected_
        # version=0으로 바로 시도)에서는 행이 없어 DoesNotExist로 500이 났다
        # (코드리뷰 지적, 재현됨). `get_current_policy()`가 바로 그 지연
        # 생성(get_or_create)을 담당하므로, 잠그기 전에 먼저 불러 행이
        # 반드시 있게 만든다.
        get_current_policy()
        current = PlatformPolicy.objects.select_for_update().get(pk=1)

        if current.version != expected_version:
            raise PolicyConflictError(
                "다른 변경이 먼저 반영되었습니다. 최신 값을 다시 불러온 뒤 재시도하세요."
            )

        # 부분 변경(fee만, withholding만)이어도 "합이 10000을 넘지 않는다"는
        # 결과 상태를 검증해야 하므로, 건드리지 않은 쪽은 현재 값을 그대로 쓴다.
        effective_fee = fee if fee is not None else current.platform_fee_bps
        effective_withholding = (
            withholding if withholding is not None else current.withholding_tax_bps
        )
        if effective_fee + effective_withholding > 10_000:
            problems.append(
                "platform_fee_bps + withholding_tax_bps 합계는 10000(100%)을 "
                f"넘을 수 없습니다(받은 합계: {effective_fee + effective_withholding})."
            )

        if problems:
            raise PolicyValidationError(" ".join(problems))

        before = {field: getattr(current, field) for field in changes}

        for field, value in changes.items():
            setattr(current, field, value)
        current.version = expected_version + 1

        current.save(update_fields=[*changes.keys(), "version", "updated_at"])

        after = {field: getattr(current, field) for field in changes}

        change = PolicyChange.objects.create(
            operator=operator,
            reason=reason.strip(),
            before=before,
            after=after,
            changed_at=Clock.now(),
        )

    return current, change
