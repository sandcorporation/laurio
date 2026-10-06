"""채점 연결 — 강의실 채점이 닿는 길 하나(#599, CONTEXT.md 「채점 연결」, ADR-0058).

이 티켓은 동작을 바꾸지 않는 사전 리팩터다: 클래스마다 연결 종류를 두고(지금은
「OpenAI 키」뿐), 채점 호출·모델 목록 조회·저장 시점 키 확인이 OpenAI 주소를 상수로
박아 두지 않고 **연결에서** 주소·인증 값을 받는다. 여기서는 그 길이 바깥에서 보기에
예전과 똑같이 나가는지(OpenAI 주소, 강사 본인 키)를 본다.
"""

from __future__ import annotations

import pytest

from classroom.models import Class
from classroom.scoring_connection import OPENAI_KEY_BASE_URL, connection_for
from core.llm_scoring import OpenAIScoringAdapter, list_openai_models
from tests.classroom_scenarios import (
    FakeVendorModelsResponse,
    FakeVendorResponse,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    openai_success_body,
    run_scan,
    submit_repository,
)


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with force_real_scoring_adapter():
        yield


def _record_gets(monkeypatch, *, model_ids=("gpt-4o-mini",)) -> list:
    sent: list = []

    def _get(url, **kwargs):
        sent.append((url, kwargs["headers"]["Authorization"]))
        return FakeVendorModelsResponse(200, list(model_ids))

    monkeypatch.setattr("core.llm_scoring.requests.get", _get)
    return sent


def test_a_new_class_reaches_scoring_through_an_openai_key_connection(client, db, monkeypatch):
    _record_gets(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], key="sk-conn-key-1234")

    connection = connection_for(Class.objects.get(id=class_id))

    assert connection.kind == Class.ScoringConnectionKind.OPENAI_KEY
    assert connection.base_url == "https://api.openai.com/v1" == OPENAI_KEY_BASE_URL
    assert connection.auth_value() == "sk-conn-key-1234"


def test_a_class_without_a_key_has_no_connection(client, db):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=False)

    assert connection_for(Class.objects.get(id=class_id)) is None


def test_key_check_and_model_list_go_to_openai_with_the_owner_key(client, db, monkeypatch):
    sent = _record_gets(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], key="sk-conn-key-1234")

    response = client.get(
        f"/api/classroom/classes/{class_id}/scoring-models",
        HTTP_AUTHORIZATION=f"Bearer {instructor['access']}",
    )

    assert response.status_code == 200, response.content
    assert get_class(client, instructor["access"], class_id)["openai_key_status"] == "verified"
    assert sent == [
        ("https://api.openai.com/v1/models", "Bearer sk-conn-key-1234"),
        ("https://api.openai.com/v1/models", "Bearer sk-conn-key-1234"),
    ]


def test_scoring_posts_to_openai_with_the_owner_key(client, db, monkeypatch):
    _record_gets(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], key="sk-conn-key-1234")
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    sent: list = []

    def _post(url, **kwargs):
        sent.append((url, kwargs["headers"]["Authorization"]))
        return FakeVendorResponse(200, openai_success_body(problem.item_id))

    monkeypatch.setattr("core.llm_scoring.requests.post", _post)

    assert run_scan(client)["count"] == 1
    assert sent == [("https://api.openai.com/v1/chat/completions", "Bearer sk-conn-key-1234")]


def test_the_adapter_and_model_list_use_the_base_url_they_are_given(monkeypatch):
    """연결이 주는 주소로 나간다 — 다음 연결 종류(호환 서버, #601)가 이 자리를 쓴다."""

    got: list = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.get",
        lambda url, **kw: got.append(url) or FakeVendorModelsResponse(200, ["m"]),
    )

    adapter = OpenAIScoringAdapter(api_key="k", base_url="https://llm.example.com/v1/")
    adapter.check_key()
    assert list_openai_models("k", base_url="https://llm.example.com/v1") == ["m"]

    assert got == ["https://llm.example.com/v1/models", "https://llm.example.com/v1/models"]
