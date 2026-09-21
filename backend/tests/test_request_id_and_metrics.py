"""요청 id·배포 로그 포맷·지표 엔드포인트(2026-09-21).

prod 로그가 Loki 에 30일 남게 되면서(CLAUDE.md 「운영」) 세 가지를 고정한다:

- **요청 id** — 응답 헤더와 그 요청 동안의 로그 레코드가 **같은 값**이어야 GlitchTip 의
  오류 하나에서 Loki 의 앞뒤 로그로 건너갈 수 있다. HTTP 로 친다.
- **배포 로그 포맷** — 한 줄 JSON 이어야 Loki 가 필드로 거른다. 포매터는 네트워크
  앞단의 순수 변환이라 `test_observability.py` 처럼 직접 부른다.
- **`/metrics`** — 감시 스택이 긁는 자리. **내부 이름으로 온 요청에만** 답해야 한다.
"""

from __future__ import annotations

import json
import logging
import re

from core.json_logging import JsonFormatter

HEX32 = re.compile(r"^[0-9a-f]{32}$")


# --- 요청 id ------------------------------------------------------------------


def test_every_response_carries_a_request_id(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert HEX32.match(response["X-Request-ID"])


def test_two_requests_get_different_ids(client):
    first = client.get("/api/health")["X-Request-ID"]
    second = client.get("/api/health")["X-Request-ID"]

    assert first != second


def test_a_well_formed_incoming_id_is_carried_through(client):
    """앞단(BFF 등)이 준 id 를 그대로 잇는다 — 여러 서비스를 지나는 한 요청이 같은 id 를 갖게."""

    response = client.get("/api/health", HTTP_X_REQUEST_ID="bff-7f3a.2")

    assert response["X-Request-ID"] == "bff-7f3a.2"


def test_a_malformed_incoming_id_is_replaced(client):
    """모양이 틀린 값(개행·공백·과도한 길이)은 버리고 새로 만든다 — 로그 주입을 끊는다."""

    for bad in ("evil\nlevel=ERROR", "has space", "x" * 65):
        response = client.get("/api/health", HTTP_X_REQUEST_ID=bad)
        assert HEX32.match(response["X-Request-ID"]), bad


def test_logs_written_during_a_request_carry_its_id(client, caplog):
    """응답 헤더의 id 와 그 요청 동안 나온 로그 레코드의 id 가 같다.

    404 는 Django 가 `django.request` 로 WARNING 을 남기는 경로라 뷰를 새로 만들지 않고도
    요청 안의 로그를 하나 얻는다.
    """

    with caplog.at_level(logging.WARNING, logger="django.request"):
        response = client.get("/api/no-such-route-for-request-id-test")

    assert response.status_code == 404
    records = [r for r in caplog.records if r.name == "django.request"]
    assert records, "요청 안에서 로그가 하나도 남지 않았다"
    assert {r.request_id for r in records} == {response["X-Request-ID"]}


def test_logs_outside_a_request_get_a_placeholder():
    record = logging.getLogger("codemit.test").makeRecord(
        "codemit.test", logging.INFO, __file__, 1, "요청 밖", None, None
    )
    # makeRecord 는 레코드 팩토리를 지난다.
    assert record.request_id == "-"


# --- 배포 로그 포맷 ----------------------------------------------------------------


def _record(message: str, *, exc_info=None) -> logging.LogRecord:
    record = logging.getLogger("codemit.test").makeRecord(
        "codemit.test", logging.ERROR, __file__, 1, message, None, exc_info
    )
    record.request_id = "abc123"
    return record


def test_json_line_has_the_fields_loki_filters_on():
    line = JsonFormatter().format(_record("채점이 실패했다"))

    payload = json.loads(line)
    assert "\n" not in line
    assert payload["level"] == "ERROR"
    assert payload["logger"] == "codemit.test"
    assert payload["message"] == "채점이 실패했다"
    assert payload["request_id"] == "abc123"
    assert payload["time"].endswith("+00:00")


def test_korean_stays_readable_in_the_json_line():
    """docker logs 로도 사람이 읽는다 — 한국어를 \\uXXXX 로 부풀리지 않는다."""

    assert "채점" in JsonFormatter().format(_record("채점"))


def test_exceptions_are_kept_on_the_same_line():
    try:
        raise ValueError("터졌다")
    except ValueError:
        import sys

        line = JsonFormatter().format(_record("예외", exc_info=sys.exc_info()))

    payload = json.loads(line)
    assert "\n" not in line
    assert "ValueError: 터졌다" in payload["exc"]


# --- /metrics --------------------------------------------------------------------


def test_metrics_answers_only_to_the_internal_service_name(client):
    """감시 스택은 compose 네트워크 안에서 `backend` 로 긁는다. 그 밖의 Host 로 오면
    존재를 알려주지 않는다(404) — 공개 프록시는 언제나 공개 도메인을 Host 로 넘긴다."""

    outside = client.get("/metrics", HTTP_HOST="codemit.example")
    inside = client.get("/metrics", HTTP_HOST="backend:8000")

    assert outside.status_code == 404
    assert inside.status_code == 200
    assert inside["Content-Type"].startswith("text/plain")


def test_requests_are_counted_by_url_pattern_not_raw_path(client):
    """`/api/…/17` 같은 실제 경로를 라벨로 쓰면 시계열이 끝없이 늘어난다 — 패턴으로 센다."""

    client.get("/api/health")
    client.get("/api/no-such-route-for-metrics-test")

    body = client.get("/metrics", HTTP_HOST="backend").content.decode()

    assert re.search(r'codemit_http_requests_total\{method="GET",route="api/health",status="200"\} \d', body)
    assert 'route="unmatched"' in body
    assert "no-such-route-for-metrics-test" not in body


def test_scraping_itself_is_not_counted(client):
    client.get("/metrics", HTTP_HOST="backend")
    body = client.get("/metrics", HTTP_HOST="backend").content.decode()

    assert 'route="metrics"' not in body
