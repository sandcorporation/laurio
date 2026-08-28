from ninja import Router

from .auth import InternalAuth
from .clock import Clock
from .transitions import run_due_transitions

router = Router(tags=["internal"])


@router.post("/tick", auth=InternalAuth())
def tick(request):
    """스케줄러 틱. Celery beat 가 주기적으로 이 엔드포인트를 호출한다(ADR-0003).

    등록된 모든 전이 규칙을 스캔해 시각이 지난 행을 조건부 UPDATE로 옮긴다. 같은
    시각에 두 번 불러도(워커가 겹쳐 돌아도) 각 전이는 정확히 한 번만 일어난다.
    """

    as_of = Clock.now()
    transitioned = run_due_transitions(as_of=as_of)
    return {
        "as_of": as_of.isoformat(),
        "count": len(transitioned),
        "transitioned": transitioned,
    }
