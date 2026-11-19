from django.conf import settings
from django.db import connection, transaction
from django.http import JsonResponse
from typing import Any

from ninja import NinjaAPI

from accounts.api import router as accounts_router
from accounts.operator_api import router as operator_router
from appeals.api import operator_router as appeals_operator_router
from appeals.api import router as appeals_router
from awards.api import router as awards_router
from classroom.api import router as classroom_router
from classroom.connected_app_api import router as classroom_connected_app_router
from contests.connected_app_api import router as contests_connected_app_router
from classroom.template_api import router as classroom_template_router
from classroom.template_operator_api import operator_router as classroom_template_operator_router
from classroom.usage_operator_api import usage_operator_router as classroom_usage_operator_router
from contests.api import router as contests_router
from contests.operator_api import operator_router as contests_operator_router
from contests.submission_api import router as submissions_router
from core import heartbeat
from core.api import router as core_internal_router
from handovers.api import router as handovers_router
from ledger.api import router as ledger_router
from notifications.api import public_router as notifications_router
from notifications.api import router as notifications_internal_router
from ops_metrics.operator_api import ops_metrics_operator_router
from notifications.operator_api import operator_router as notifications_operator_router
from payments.api import router as payments_router
from payouts.api import operator_router as payouts_operator_router
from payouts.api import router as payouts_router
from policies.api import operator_router as policies_operator_router
from policies.runtime_settings_api import runtime_settings_router
from scoring.api import router as scoring_internal_router
from storage.api import router as storage_router
from storage.policy import StorageAccessDenied
from verification.api import router as verification_router
from verification.operator_api import operator_router as verification_operator_router

class CodemitAPI(NinjaAPI):
    """OpenAPI 스키마를 한 번만 만든다 — 라우터는 import 때 다 붙고 그 뒤로 바뀌지 않는다.

    ninja 는 `/api/openapi.json` 요청마다 엔드포인트 전부(지금 197개)의 pydantic 스키마를 다시 만든다.
    로컬 CPU 0.4초, CI 1.5초 남짓이고 엔드포인트 수에 비례해 는다. 시험 CPU 한도(#1014)를 넘은 까닭이다.
    """

    _openapi_cache: dict[str, Any]

    def get_openapi_schema(self, *, path_prefix: str | None = None, path_params: dict[str, Any] | None = None) -> Any:
        if path_prefix is None:
            path_prefix = self.get_root_path(path_params or {})
        cache = self.__dict__.setdefault("_openapi_cache", {})
        if path_prefix not in cache:
            cache[path_prefix] = super().get_openapi_schema(path_prefix=path_prefix)
        return cache[path_prefix]


api = CodemitAPI(title="Codemit API", version="0.1.0")

api.add_router("", accounts_router)
api.add_router("", verification_router)
# 공모전 연결된 앱(#870)은 공모전 라우터보다 먼저 — 아니면 `/contests/{contest_id}` 가
# `/contests/connected-apps` 를 먼저 잡아 422 를 낸다.
api.add_router("/contests", contests_connected_app_router)
api.add_router("", contests_router)
api.add_router("", payments_router)
api.add_router("", submissions_router)
api.add_router("", awards_router)
api.add_router("", handovers_router)
api.add_router("", payouts_router)
api.add_router("", appeals_router)
api.add_router("/notifications", notifications_router)
api.add_router("/ledger", ledger_router)
api.add_router("/classroom", classroom_router)
api.add_router("/classroom", classroom_template_router)
api.add_router("/classroom", classroom_connected_app_router)


def _check_db() -> bool:
    try:
        with transaction.atomic(), connection.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout = 1000")  # 각 점검 1초(#949)
            cur.execute("SELECT 1")
        return True
    except Exception:  # noqa: BLE001 — 어떤 오류든 「못 닿음」으로만 알린다(원문은 내지 않는다)
        return False


def _check_redis() -> bool:
    try:
        return bool(heartbeat.store().ping())
    except Exception:  # noqa: BLE001
        return False


@api.get("/health")
def health(request):
    """db(`SELECT 1`)·redis(`PING`)·백그라운드 워커 생존 신호를 본다. 하나라도 실패면 503 + 실패한 점검 이름(#949).

    `?scope=ready` 는 db·redis 만(롤링 교체·배포 스모크·컨테이너 healthcheck 용 — 워커 신호가 아직 없는 새 api 를 막지 않는다).
    워커 점검은 `HEALTH_REQUIRED_WORKERS`(쉼표 목록)가 있을 때만 — 개발·CI 스택은 워커가 없다.
    호스트·버전·예외 원문은 응답에 넣지 않는다.
    """

    failed: list[str] = []
    if not _check_db():
        failed.append("db")
    redis_ok = _check_redis()
    if not redis_ok:
        failed.append("redis")
    required = settings.HEALTH_REQUIRED_WORKERS
    if required and request.GET.get("scope") != "ready":
        if redis_ok:
            try:
                gone = heartbeat.missing_roles(required)
            except Exception:  # noqa: BLE001
                gone = list(required)
        else:
            gone = list(required)
        failed.extend(gone)
    if not failed:
        return {"status": "ok"}
    return JsonResponse({"status": "error", "failed": failed}, status=503)


api.add_router("/internal", core_internal_router)
api.add_router("/internal/notifications", notifications_internal_router)
api.add_router("/internal/scoring", scoring_internal_router)


@api.exception_handler(StorageAccessDenied)
def storage_access_denied(request, exc: StorageAccessDenied):
    return api.create_response(request, {"detail": str(exc)}, status=403)


# 운영자 표면(#43, ADR-0019). InternalAuth 와 다르다 — 저쪽은 Celery beat 가 부르는
# 자동 스캔 전용이고, 사람이 판단하는 행위는 전부 이 접두어 아래에서 신원과 함께
# 이루어진다. 라우터 자체가 기본 거부이며 Origin 검증 미들웨어가 경로 접두어로
# 걸려 있다.
api.add_router("/operator", operator_router)
api.add_router("/operator", appeals_operator_router)
api.add_router("/operator", payouts_operator_router)
api.add_router("/operator", policies_operator_router)
api.add_router("/operator", runtime_settings_router)
api.add_router("/operator", contests_operator_router)
api.add_router("/operator", verification_operator_router)
api.add_router("/operator", classroom_template_operator_router)
api.add_router("/operator", classroom_usage_operator_router)
api.add_router("/operator", notifications_operator_router)
api.add_router("/operator", ops_metrics_operator_router)

api.add_router("/storage", storage_router)
