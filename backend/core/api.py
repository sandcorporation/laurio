from ninja import Router
from ninja.errors import HttpError

from .auth import InternalAuth
from .scans import SCAN_REGISTRY, run_all, run_scan

router = Router(tags=["internal"])


@router.post("/tick", auth=InternalAuth())
def tick(request):
    """등록부의 스캔 전부를 등록 순서로 한 바퀴 — 수동용 진입점(#137, ADR-0003).

    staging 운영자가 21일 시나리오를 몇 초에 재현할 때 쓴다. Celery beat 는 이것을 부르지
    않고 스캔마다 `/scans/{name}` 을 부른다 — 열일곱 스캔을 각자 예산으로 순차 실행하면 30초
    HTTP 타임아웃 안에 못 들 수 있다. 같은 시각에 두 번 불러도 각 행은 정확히 한 번만
    처리된다(조건부 UPDATE, `core.transitions.claim_transition`).
    """

    return run_all()


@router.post("/scans/{name}", auth=InternalAuth())
def scan(request, name: str):
    """등록부의 스캔 하나. Celery beat 가 스캔마다 이것을 부른다 — 이름은 등록부에서만 온다."""

    if name not in SCAN_REGISTRY:
        raise HttpError(404, f"등록되지 않은 스캔입니다: {name}")
    return run_scan(name)
