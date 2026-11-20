from django.conf import settings
from django.db import connection, transaction
from django.http import JsonResponse

from config.routes import API_ROUTERS, CodemitAPI, build_api
from core import heartbeat

__all__ = ["CodemitAPI", "api"]

# 라우터와 붙는 순서는 `config/routes.py` 의 표다(#1087) — 앱 시험은 같은 표에서 제 앱 줄만 쓴다.
api = build_api(API_ROUTERS)


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


