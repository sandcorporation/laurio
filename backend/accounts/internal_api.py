"""Withdrawal 내부 스캔 — 2년 미이용 신원 파기 + 보존 기간 만료 RetainedIdentity
파기 (#102, ADR-0003, ADR-0025).

기존 내부 스캔 관용구를 그대로 따른다: Celery beat가 이 경로를 주기적으로
호출하고(`core/tasks.py`·`config/celery.py`), 사람이 판단하는 행위가 아니라
`core.auth.InternalAuth`(공유 시크릿) 하나로 보호된다 — Operator 표면
(`OperatorAuth`)과 다르다.
"""

from __future__ import annotations

from ninja import Router

from core.auth import InternalAuth

from .dormancy import purge_expired_identities

internal_router = Router(tags=["internal", "accounts"], auth=InternalAuth())


@internal_router.post("/purge-expired-identities")
def purge_expired_identities_endpoint(request):
    """2년간 행위가 없던 계정의 신원을 파기하고, 보존 기간이 지난
    `RetainedIdentity`를 지운다. 같은 시각에 두 번 불러도 결과가 같다.
    """

    return purge_expired_identities()
