"""OpenAPI 스키마.

django-ninja가 실제로 마운트되어 있고 등록된 라우트가 스키마에 드러나는지 확인한다.
이후 티켓이 추가하는 엔드포인트도 같은 스키마에 쌓인다.
"""

import pytest


@pytest.fixture
def built_schema():
    """스키마 빌드는 엔드포인트 수에 비례하는 준비다(CI CPU 1.5초 남짓) — 앱이 한 번만 만들고
    다시 쓴다(`config.api.CodemitAPI`). 시험 본문은 그것이 제공되는지만 잰다."""

    from config.api import api

    return api.get_openapi_schema(path_params={})


def test_openapi_schema_is_served(client, built_schema):
    response = client.get("/api/openapi.json")

    assert response.status_code == 200

    schema = response.json()
    assert schema["info"]["title"] == "Codemit API"
    assert "/api/health" in schema["paths"]
    assert schema["paths"].keys() == built_schema["paths"].keys()
