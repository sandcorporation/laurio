import json

from ninja import Router
from ninja.errors import HttpError

from .auth import InternalAuth
from .scans import SCAN_REGISTRY, run_all, run_scan

router = Router(tags=["internal"])


def _scan_params(request) -> dict:
    """본문이 있으면 `{"params": {...}}` 에서 params 를 꺼낸다 — fake 어댑터 전용 시나리오 선택
    (환불의 simulate, 배분 지급의 fail_submission_ids 등)이 스캔 실행 하나에 딸려 들어오는
    자리다(`core.scans.scan_params(ctx)` 로 읽는다). Celery beat 는 본문 없이 부르므로 본문은
    선택이고, 그 경우 빈 dict 다. ninja 의 본문 스키마를 쓰지 않는 이유는 본문 없는 POST(beat
    의 호출 모양)가 400 으로 거부되지 않아야 하기 때문이다."""

    # JSON 본문일 때만 읽는다 — 본문 없는 POST 는 클라이언트에 따라 빈 multipart 로 오기도 한다.
    if request.content_type != "application/json" or not request.body:
        return {}
    try:
        body = json.loads(request.body)
    except ValueError as exc:
        raise HttpError(400, "본문은 JSON 이어야 합니다.") from exc
    params = body.get("params", {}) if isinstance(body, dict) else {}
    if not isinstance(params, dict):
        raise HttpError(400, "params 는 객체여야 합니다.")
    return params


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
    return run_scan(name, params=_scan_params(request))
