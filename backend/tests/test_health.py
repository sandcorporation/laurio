"""헬스 엔드포인트.

이 프로젝트의 유일한 테스트 시임은 HTTP다. 테스트는 마운트된 django-ninja API를
전체 요청 스택(URLconf + 미들웨어 + 라우터)을 통해 호출한다. 라우터를 직접 부르는
방식은 미들웨어를 건너뛰므로 쓰지 않는다 — 이후 인증·CSRF·CSP가 그 층에 얹힌다.
"""


def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
