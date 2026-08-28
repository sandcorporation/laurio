"""Distribution 내부 스캔 엔드포인트 (#16, ADR-0003).

core의 내부 틱 엔드포인트와는 별개의 주기로 Celery beat가 반복 호출하는 전용
스캔이다 — `scoring.api`/`handovers.api`의 `/internal/.../run-pending`,
`/internal/handovers/release-due`와 같은 구조(core.transitions 레지스트리를 쓰지
않는 이유도 같다: 원장 분개라는 부수효과가 있어 단순 조건부 UPDATE로는 부족하다).
"""

from __future__ import annotations

from ninja import Router

from core.auth import InternalAuth

from .schemas import RunDueDistributionsIn
from .services import run_due_distributions

internal_router = Router(tags=["internal", "distributions"], auth=InternalAuth())


@internal_router.post("/run-due")
def run_due(request, payload: RunDueDistributionsIn = RunDueDistributionsIn()):
    """무응답 14일이 지난 Contest를 스캔해 Distribution을 만들고, 아직 확정되지
    않은 몫에 대한 지급을 시도(또는 재시도)한다.

    같은 시각에 두 번 불러도(워커가 겹쳐 돌아도) 이미 만들어진 Distribution은
    다시 만들지 않고, 이미 확정된 몫은 다시 지급 시도하지 않는다(#16 AC).
    """

    results = run_due_distributions(fail_submission_ids=set(payload.fail_submission_ids))
    return {"count": len(results), "results": results}
