import io
import json

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from ninja import Router
from ninja.errors import HttpError

from .auth import InternalAuth
from .e2e_seeds import E2E_SEED_REGISTRY
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


@router.post("/e2e/seed/{name}", auth=InternalAuth())
def e2e_seed(request, name: str):
    """e2e 픽스처를 심는다 — 서브프로세스 대신 이미 떠 있는 프로세스가 답한다 (#156).

    이름과 옵션은 `core.e2e_seeds.E2E_SEED_REGISTRY` 에서만 온다(`/scans/{name}` 과 같은
    규약). 구현은 관리 명령이 그대로 갖고 여기는 두 번째 입구일 뿐이라, `call_command` 로
    in-process 호출한다 — 로직이 두 벌이 되지 않는다.
    """

    entry = E2E_SEED_REGISTRY.get(name)
    if entry is None:
        raise HttpError(404, f"등록되지 않은 e2e 시드입니다: {name}")

    # **입구에서도 배포 환경을 막는다.** 관리 명령 셋 중 둘은 스스로 거부하지만
    # `seed_e2e_contests` 에는 그 가드가 없다 — CLI 로만 부르던 시절에는 사람이 그
    # 명령을 배포 환경에서 칠 일이 없다는 것이 실질적인 방어였는데, HTTP 로 열면서
    # 그 전제가 사라진다.
    if settings.IS_DEPLOYED_ENVIRONMENT:
        raise HttpError(
            403,
            f"LAURIO_DEPLOYMENT_TARGET={settings.LAURIO_DEPLOYMENT_TARGET} 에서는 "
            "e2e 시드를 심을 수 없습니다 — 실제 데이터를 만들거나 지웁니다.",
        )

    options = _seed_options(request)
    missing = set(entry.required) - set(options)
    if missing:
        raise HttpError(422, f"{name} 시드에 반드시 줘야 하는 옵션입니다: {sorted(missing)}")
    unknown = set(options) - set(entry.options)
    if unknown:
        raise HttpError(
            422,
            f"{name} 시드가 받지 않는 옵션입니다: {sorted(unknown)}. "
            f"받는 것: {sorted(entry.options)}",
        )

    out = io.StringIO()
    try:
        call_command(entry.command, stdout=out, **options)
    except CommandError as exc:
        # 명령의 거부(배포 환경·잘못된 네임스페이스 등)는 500 이 아니라 4xx 다 —
        # 호출부가 「내가 잘못 불렀다」와 「서버가 깨졌다」를 구별할 수 있어야 한다.
        raise HttpError(422, str(exc)) from exc
    except Exception as exc:
        # **역추적을 본문에 실어 보낸다.** 서브프로세스 시절에는 stderr 가 호출부의
        # 터미널로 그대로 흘러 시드가 왜 죽었는지가 그 자리에 보였다. 그것을 잃으면
        # 호출부는 Django 의 DEBUG HTML 500 을 400자만 잘라 보게 되고, 이 명령들이
        # 실제로 겪은 종류의 실패(ProtectedError 로 Category 삭제가 죽는 것 같은)를
        # 진단할 길이 사라진다. 이 표면은 내부 토큰 뒤에 있고 배포 환경에서는 아예
        # 거부되므로 역추적이 새어도 잃을 것이 없다.
        import traceback

        raise HttpError(500, f"{entry.command} 가 죽었다:\n{traceback.format_exc()}") from exc

    # 명령들은 마지막 줄에 JSON 한 덩어리를 찍는다(각 명령 docstring 참고). 그 규약이
    # 깨지면 조용히 이상한 값을 돌려주는 대신 여기서 터뜨린다.
    last_line = out.getvalue().strip().split("\n")[-1] if out.getvalue().strip() else ""
    try:
        return json.loads(last_line)
    except ValueError:
        return {"output": last_line}


def _seed_options(request) -> dict:
    if request.content_type != "application/json" or not request.body:
        return {}
    try:
        body = json.loads(request.body)
    except ValueError as exc:
        raise HttpError(400, "본문은 JSON 이어야 합니다.") from exc
    if not isinstance(body, dict):
        raise HttpError(400, "본문은 객체여야 합니다.")
    # 값이 None 인 키는 「안 줬다」로 본다 — 호출부가 선택 인자를 항상 실어 보내도 된다.
    return {key: value for key, value in body.items() if value is not None}
