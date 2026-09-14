"""compose 내부 서비스 이름으로 들어온 요청은 prod 의 SSL 리다이렉트를 받지 않는다.

prod 는 `SECURE_SSL_REDIRECT` 가 켜져 있고 TLS 는 앞단 프록시가 종단한다(`X-Forwarded-Proto`).
그런데 세 앱의 BFF 는 compose 네트워크 안에서 `http://backend:8000` 을 직접 부른다 — 프록시를
거치지 않으니 헤더가 없고, 백엔드는 `301 → https://backend:8000/...` 을 돌려준다. 평문 gunicorn
에 TLS 로 붙으려던 fetch 가 연결 시간 초과로 죽어 prod 카카오 로그인이 통째로 막혔다(2026-09-14
실측, 콜백 10.5초 뒤 UND_ERR_CONNECT_TIMEOUT). 강의실 스트림(events)도 같다.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def prod_like_ssl(settings):
    settings.SECURE_SSL_REDIRECT = True
    settings.SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    settings.ALLOWED_HOSTS = ["api.codemit.kr", "backend", "events"]


def test_a_request_to_the_internal_service_name_is_not_redirected(client, db, prod_like_ssl):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": "invalid"},
        content_type="application/json",
        HTTP_HOST="backend:8000",
    )

    assert response.status_code != 301
    assert response.status_code in (400, 401, 422)


def test_the_events_service_name_is_internal_too(client, db, prod_like_ssl):
    response = client.get("/api/health", HTTP_HOST="events:8001")

    assert response.status_code == 200


def test_a_plain_request_to_the_public_name_is_still_redirected(client, db, prod_like_ssl):
    response = client.get("/api/health", HTTP_HOST="api.codemit.kr")

    assert response.status_code == 301
    assert response["Location"].startswith("https://api.codemit.kr/")


def test_the_public_name_through_the_tls_proxy_is_served(client, db, prod_like_ssl):
    response = client.get("/api/health", HTTP_HOST="api.codemit.kr", HTTP_X_FORWARDED_PROTO="https")

    assert response.status_code == 200
