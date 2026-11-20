"""호환 서버의 모델을 고를 때 시험 호출로 채점 형식을 확인하고, 추론 모델 여부는 소유자가 정한다(#602).

CONTEXT.md 「채점 연결」, ADR-0058. 강사의 서버는 HTTP 로 칠 수 없는 경계라 `FakeCompatibleServer`
를 안전한 바깥 호출 자리에 꽂는다 — 시험 호출은 채점과 같은 어댑터·같은 요청 모양으로 나간다.
"""

from __future__ import annotations

import pytest

from tests.classroom_scenarios import (
    CLASSES_URL,
    FakeCompatibleServer,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    openai_success_body,
    patch_class,
    run_scan,
    set_compatible_server,
    submit_repository,
)

SERVER_URL = "https://probe.example.com/v1"
SERVER_MODELS = ["llama-3.1-8b-instruct", "my-team/coder-7b", "tiny-chat"]
FORMAT_SENTENCE = "이 모델은 시험 판정에서 채점 형식(구조화된 판정)을 지키지 못했습니다"


@pytest.fixture
def real_adapter():
    with force_real_scoring_adapter():
        yield


def _setup(client, monkeypatch, **server):
    fake = FakeCompatibleServer(model_ids=SERVER_MODELS, **server).install(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=False)
    set_compatible_server(client, instructor["access"], class_id, SERVER_URL)
    return fake, instructor, class_id


def _patch(client, access, class_id, payload):
    return client.patch(
        f"{CLASSES_URL}/{class_id}", data=payload, content_type="application/json", **auth_header(access)
    )


def _scored_request(client, fake, instructor, class_id, problem) -> dict:
    fake.verdicts = openai_success_body(problem.item_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    assert run_scan(client)["count"] == 1
    (request,) = fake.scoring_requests
    return request["json"]


def test_a_model_that_keeps_the_format_is_chosen_once_per_connection_and_model(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _setup(client, monkeypatch)

    patch_class(client, instructor["access"], class_id, {"default_model": "my-team/coder-7b"})
    patch_class(client, instructor["access"], class_id, {"default_model": "llama-3.1-8b-instruct"})
    patch_class(client, instructor["access"], class_id, {"default_model": "my-team/coder-7b"})

    probes = fake.probe_requests
    assert [p["json"]["model"] for p in probes] == ["my-team/coder-7b", "llama-3.1-8b-instruct"]
    assert probes[0]["url"] == f"{SERVER_URL}/chat/completions"
    assert probes[0]["json"]["response_format"]["type"] == "json_schema"
    assert get_class(client, instructor["access"], class_id)["default_model"] == "my-team/coder-7b"


def test_a_model_that_breaks_the_format_is_refused_with_its_sentence(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _setup(client, monkeypatch, keeps_format=False)
    before = get_class(client, instructor["access"], class_id)["default_model"]

    refused = _patch(client, instructor["access"], class_id, {"default_model": "tiny-chat"})
    again = _patch(client, instructor["access"], class_id, {"default_model": "tiny-chat"})

    assert refused.status_code == 422
    assert refused.json()["detail"].startswith(FORMAT_SENTENCE)
    assert again.status_code == 422  # 실패는 캐시하지 않는다 — 서버를 고치면 바로 다시 고른다
    assert len(fake.probe_requests) == 2
    assert get_class(client, instructor["access"], class_id)["default_model"] == before


def test_a_server_that_rejects_the_bearer_value_at_probe_time_says_so(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _setup(client, monkeypatch)
    fake.accepted_auth = "rotated-token"

    refused = _patch(client, instructor["access"], class_id, {"default_model": "my-team/coder-7b"})

    assert refused.status_code == 422
    assert refused.json()["detail"].startswith("서버가 인증 값을 거절했습니다")


def test_choosing_a_model_per_problem_goes_through_the_same_probe(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _setup(client, monkeypatch, keeps_format=False)

    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"], "model": "tiny-chat"},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    fake.keeps_format = True
    problem = create_open_problem(client, instructor["access"], class_id)
    fake.keeps_format = False
    edited = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem.id}",
        data={"model": "tiny-chat"},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )

    assert created.status_code == 422
    assert created.json()["detail"].startswith(FORMAT_SENTENCE)
    assert edited.status_code == 422
    assert edited.json()["detail"].startswith(FORMAT_SENTENCE)


def test_the_reasoning_switch_puts_the_effort_on_scoring_calls(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _setup(client, monkeypatch)

    saved = patch_class(
        client,
        instructor["access"],
        class_id,
        {"default_model": "my-team/coder-7b", "default_model_is_reasoning": True, "default_reasoning_effort": "high"},
    )
    problem = create_open_problem(client, instructor["access"], class_id)
    body = _scored_request(client, fake, instructor, class_id, problem)

    assert saved["default_model_is_reasoning"] is True
    assert fake.probe_requests[-1]["json"]["reasoning_effort"] == "high"
    assert body["reasoning_effort"] == "high"
    assert "temperature" not in body


def test_with_the_switch_off_no_effort_is_sent(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _setup(client, monkeypatch)
    patch_class(client, instructor["access"], class_id, {"default_model": "my-team/coder-7b", "default_model_is_reasoning": True})

    saved = patch_class(client, instructor["access"], class_id, {"default_model_is_reasoning": False})
    problem = create_open_problem(client, instructor["access"], class_id)
    body = _scored_request(client, fake, instructor, class_id, problem)

    assert saved["default_model_is_reasoning"] is False
    assert "reasoning_effort" not in body
    assert body["temperature"] == 0


def test_a_problem_model_marked_reasoning_sends_its_effort(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id = _setup(client, monkeypatch)

    problem = create_open_problem(
        client, instructor["access"], class_id, model="llama-3.1-8b-instruct", model_is_reasoning=True, reasoning_effort="medium"
    )
    shown = client.get(f"{CLASSES_URL}/{class_id}/problems/{problem.id}", **auth_header(instructor["access"])).json()
    body = _scored_request(client, fake, instructor, class_id, problem)

    assert shown["model_is_reasoning"] is True
    assert shown["effective_model_is_reasoning"] is True
    assert body["model"] == "llama-3.1-8b-instruct"
    assert body["reasoning_effort"] == "medium"


def test_an_openai_key_class_is_not_probed_and_ignores_the_switch(client, db, monkeypatch):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], key="sk-test-1234")

    saved = patch_class(client, instructor["access"], class_id, {"default_model": "gpt-4o", "default_model_is_reasoning": True})

    assert saved["default_model"] == "gpt-4o"
    assert saved["default_model_is_reasoning"] is False  # OpenAI 키는 이름으로 판단한다
