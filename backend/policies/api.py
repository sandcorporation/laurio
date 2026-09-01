"""정책 운영자 API (#76, ADR-0023).

- `GET /operator/policy` — 현재 정책값. 일반 등급 Operator도 조회할 수 있다 —
  참가자 문의에 답하려면 지금 값을 봐야 하고, 보는 것과 바꾸는 것은 다르다.
- `POST /operator/policy` — 정책을 바꾼다. **상위 등급만** — 수수료율을 바꾸는
  것은 이의 하나가 아니라 앞으로의 모든 돈을 움직이는 판단이다(계정 관리와
  같은 등급, `SuperuserOperatorAuth`).
- `GET /operator/policy/changes` — 변경 이력. 조회이므로 일반 등급도 볼 수
  있다.

라우터 기본값이 이미 거부(`OperatorAuth`)다 — 로그인은 됐지만 Operator가
아니면 403. `POST`는 그 위에 상위 등급까지 요구한다.
"""

from __future__ import annotations

from django.http import HttpRequest
from ninja import Router

from core.operator_auth import OperatorAuth, SuperuserOperatorAuth

from .models import PlatformPolicy, PolicyChange
from .schemas import ErrorOut, PolicyChangeOut, PolicyOut, PolicyUpdateIn
from .services import (
    PolicyConflictError,
    PolicyValidationError,
    UPDATABLE_FIELDS,
    get_current_policy,
    update_policy,
)

operator_router = Router(tags=["operator", "policies"], auth=OperatorAuth())

_SUPERUSER = SuperuserOperatorAuth()

# 이력 조회는 최근 것부터 이만큼만 돌려준다. 정책 변경은 회의·결재를 거치는
# 드문 사건이라(수수료율을 하루에 수백 번 바꾸지 않는다) 페이지네이션 없이도
# 실용적인 상한이다 — 나중에 실제로 넘치면 그때 페이지네이션을 추가한다.
_HISTORY_LIMIT = 200


def _serialize_policy(policy: PlatformPolicy) -> PolicyOut:
    return PolicyOut(
        platform_fee_bps=policy.platform_fee_bps,
        withholding_tax_bps=policy.withholding_tax_bps,
        withholding_necessary_expense_bps=policy.withholding_necessary_expense_bps,
        withholding_minor_income_exempt_won=policy.withholding_minor_income_exempt_won,
        version=policy.version,
        updated_at=policy.updated_at,
    )


def _serialize_change(change: PolicyChange) -> PolicyChangeOut:
    return PolicyChangeOut(
        id=change.id,
        operator_username=change.operator.username,
        reason=change.reason,
        before=change.before,
        after=change.after,
        changed_at=change.changed_at,
    )


@operator_router.get("/policy", response={200: PolicyOut})
def get_policy(request: HttpRequest):
    return 200, _serialize_policy(get_current_policy())


@operator_router.post(
    "/policy",
    response={200: PolicyOut, 409: ErrorOut, 422: ErrorOut},
    auth=_SUPERUSER,
)
def change_policy(request: HttpRequest, payload: PolicyUpdateIn):
    """정책을 바꾼다. 상위 등급만 — `SuperuserOperatorAuth`가 일반 등급을
    403으로 거절한다(401과 구별된다: 세션 자체가 없으면 401·`OperatorAuth`).

    `changes`는 페이로드에서 실제로 값이 온 필드만 뽑는다 — `None`은 "이
    필드는 건드리지 마라"는 뜻이다.
    """

    changes = {
        field: getattr(payload, field)
        for field in UPDATABLE_FIELDS
        if getattr(payload, field) is not None
    }

    try:
        policy, _change = update_policy(
            operator=request.auth,
            reason=payload.reason,
            expected_version=payload.expected_version,
            changes=changes,
        )
    except PolicyConflictError as exc:
        return 409, {"detail": str(exc), "code": "conflict"}
    except PolicyValidationError as exc:
        return 422, {"detail": str(exc), "code": "invalid"}

    return 200, _serialize_policy(policy)


@operator_router.get("/policy/changes", response={200: list[PolicyChangeOut]})
def list_policy_changes(request: HttpRequest):
    changes = PolicyChange.objects.select_related("operator").order_by("-changed_at", "-id")[
        :_HISTORY_LIMIT
    ]
    return 200, [_serialize_change(change) for change in changes]
