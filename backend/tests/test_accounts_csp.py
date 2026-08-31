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

    `/api`(슬래시 없이)를 요청하면 CommonMiddleware가 `/api/`로 301을 돌려주며 그
    자리에서 응답을 끝낸다 — 뷰도, 그 뒤의 다른 미들웨어도 거치지 않는다.
    ContentSecurityPolicyMiddleware가 CommonMiddleware보다 안쪽에 있으면 이 301은
    CSP를 아예 거치지 않고 나간다.

    예전에는 `/admin`으로 같은 것을 확인했다. #46(ADR-0019)이 admin을 내리면서 그
    경로가 사라졌지만 **검증하려던 성질은 그대로**이므로, 같은 메커니즘으로 301을
    내는 다른 경로로 옮겼을 뿐이다.
    """

    response = client.get("/api", follow=False)

    assert response.status_code == 301
    assert "Content-Security-Policy" in response


def test_csp_header_present_on_a_response_returned_by_our_own_middleware(client):
    """우리 미들웨어가 직접 만들어 돌려주는 응답에도 CSP가 붙어야 한다.

    운영자 경로의 Origin 검증(#43)은 뷰에 닿기 전에 403을 만들어 반환한다 — 위의
    301과 같은 부류지만 이쪽은 **이 저장소가 직접 쓴** 미들웨어다. 새 미들웨어를
    체인 어디에 끼우느냐에 따라 CSP를 건너뛸 수 있으므로, 그 자리도 함께 고정한다.
    """

    response = client.post(
        "/api/operator/login", data={}, content_type="application/json"
    )

    assert response.status_code == 403
    assert "Content-Security-Policy" in response
