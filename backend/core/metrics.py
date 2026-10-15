"""백엔드 API 의 요청량·지연·상태코드를 Prometheus 로 낸다(2026-09-21).

oracle 의 감시 스택(저장소 밖, CLAUDE.md 「운영」)이 prod 백엔드를 긁는다. **대시보드용**이다
— 경보는 걸지 않는다(5xx 는 GlitchTip 이 이미 울리므로 같은 사건이 두 번 오지 않게).

**누가 긁을 수 있나.** `/metrics` 는 compose 내부 이름(`backend`)으로 들어온 요청에만
답하고 나머지는 404 다 — `core/internal_hosts.py` 가 내부 호출을 가르는 것과 같은 기준이다.
공개 프록시는 언제나 공개 도메인을 Host 로 넘기고, 세 앱의 BFF 는 허용목록에 이 경로가
없으며, 백엔드 포트는 호스트의 127.0.0.1 에만 열려 있다. 세 겹이지만 이 파일이 지키는
것은 마지막 하나다: **어떤 경로로 닿든 내부 이름이 아니면 존재를 알려주지 않는다.**

**gunicorn 워커가 넷이다.** 워커마다 제 카운터를 들고 있으면 한 번 긁을 때 무작위 워커
하나의 숫자만 와서 값이 튄다. `PROMETHEUS_MULTIPROC_DIR` 가 있으면(prod compose 가 준다)
prometheus_client 가 워커별 값을 그 디렉터리에 파일로 쓰고, 여기서 합산해 낸다. 죽은
워커의 값 정리는 `config/gunicorn.conf.py` 의 `child_exit` 가 한다. 워커 안의 스레드들
(gthread, #725)은 pid 가 같아 한 파일을 함께 쓴다 — prometheus_client 가 값마다 잠근다. 그 값이 없으면(dev·
테스트·events·celery) 프로세스 하나의 값을 그대로 낸다.

**라벨은 URL 패턴이다, 실제 경로가 아니다.** `/api/contests/17` 을 그대로 라벨로 쓰면
공모전 수만큼 시계열이 생긴다(카디널리티 폭발). `resolver_match.route`(`api/contests/
<int:contest_id>` 꼴)를 쓰고, 어디에도 맞지 않은 요청은 `unmatched` 하나로 모은다.
"""

from __future__ import annotations

import os
import time

from django.conf import settings
from django.http import Http404, HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from prometheus_client import multiprocess

REQUESTS = Counter(
    "codemit_http_requests_total",
    "백엔드가 처리한 HTTP 요청 수",
    ["method", "route", "status"],
)
DURATION = Histogram(
    "codemit_http_request_duration_seconds",
    "백엔드 HTTP 요청 처리 시간(초)",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def _route_of(request) -> str:
    match = getattr(request, "resolver_match", None)
    route = getattr(match, "route", None)
    return route or "unmatched"


class MetricsMiddleware:
    """요청 하나마다 수와 걸린 시간을 센다. `/metrics` 자신은 세지 않는다 — 긁는 소리가
    요청량에 섞이면 트래픽이 없는 밤에도 그래프가 평평하지 않다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        if request.path != "/metrics":
            route = _route_of(request)
            REQUESTS.labels(request.method, route, str(response.status_code)).inc()
            DURATION.labels(request.method, route).observe(time.perf_counter() - started)
        return response


def _is_internal(request) -> bool:
    host = request.META.get("HTTP_HOST", "").rsplit(":", 1)[0].strip().lower()
    return host in settings.INTERNAL_SERVICE_HOSTS


def metrics_view(request):
    if not _is_internal(request):
        raise Http404
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
