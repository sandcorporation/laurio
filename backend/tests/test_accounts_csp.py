"""CSP 헤더 (#5, ADR-0012 보완책).

JWT를 localStorage에 두는 결정은 CSP로 XSS의 파급력을 좁히는 것과 한 묶음이다.
"""


def test_csp_header_present_on_every_response(client):
    response = client.get("/api/health")

    assert "Content-Security-Policy" in response
    assert "default-src 'self'" in response["Content-Security-Policy"]
    assert "object-src 'none'" in response["Content-Security-Policy"]


def test_csp_header_present_on_a_redirect_short_circuited_inside_the_middleware_chain(client):
    """CommonMiddleware의 APPEND_SLASH 301처럼, 뷰까지 가지 않고 미들웨어 체인
    중간에서 곧장 반환되는 응답도 CSP를 걸치고 나가야 한다(ADR-0012 — 세 보완책 중
    하나라도 빠지면 결정 자체가 무효).

    `/admin`(슬래시 없이)을 요청하면 CommonMiddleware가 `/admin/`으로 301을 돌려주며
    그 자리에서 응답을 끝낸다 — 뷰도, 그 뒤의 다른 미들웨어도 거치지 않는다.
    ContentSecurityPolicyMiddleware가 CommonMiddleware보다 안쪽에 있으면 이 301은
    CSP를 아예 거치지 않고 나간다. (직접 확인함: 미들웨어 순서를 옛 배치로 되돌리면
    이 응답에서 헤더가 사라진다 — 이 테스트는 실제로 그 버그를 잡아낸다.)
    """

    response = client.get("/admin", follow=False)

    assert response.status_code == 301
    assert "Content-Security-Policy" in response
