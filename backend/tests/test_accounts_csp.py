"""CSP 헤더 (#5, ADR-0012 보완책).

JWT를 localStorage에 두는 결정은 CSP로 XSS의 파급력을 좁히는 것과 한 묶음이다.
"""


def test_csp_header_present_on_every_response(client):
    response = client.get("/api/health")

    assert "Content-Security-Policy" in response
    assert "default-src 'self'" in response["Content-Security-Policy"]
    assert "object-src 'none'" in response["Content-Security-Policy"]
