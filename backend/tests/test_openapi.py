"""OpenAPI 스키마.

django-ninja가 실제로 마운트되어 있고 등록된 라우트가 스키마에 드러나는지 확인한다.
이후 티켓이 추가하는 엔드포인트도 같은 스키마에 쌓인다.
"""


def test_openapi_schema_is_served(client):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200

    schema = response.json()
    assert schema["info"]["title"] == "Codemit API"
    assert "/api/health" in schema["paths"]
