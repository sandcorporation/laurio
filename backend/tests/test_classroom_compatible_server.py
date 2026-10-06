"""「호환 서버」 채점 연결 — 소유자가 저장하고 그 서버로 채점된다(#601, ADR-0058).

CONTEXT.md 「채점 연결」. 강사의 서버는 강의실 밖이라 HTTP 로 칠 수 없는 경계다 — 호환 서버로
나가는 왕복은 전부 안전한 바깥 호출(`core.safe_outbound`)을 거치므로, 그 자리에
`FakeCompatibleServer` 를 꽂아 경계 너머를 고른다. 주소 모양 거부(http·사설·내부 이름)는 진짜
모듈이 fake 스위치에서도 그대로 한다.
"""

from __future__ import annotations

import json
import logging
import secrets

import pytest
import sentry_sdk
from sentry_sdk.transport import Transport

from classroom.models import Class
from core.crypto import decrypt
from core.observability import sentry_init_options
from core.safe_outbound import OutboundReason
from tests.classroom_scenarios import (
    CLASSES_URL,
    FakeCompatibleServer,
    add_co_instructor,
    auth_header,
    SCAN_URL,
    internal_headers,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    mine,
    openai_success_body,
    patch_class,
    put_compatible_server,
    run_scan,
    set_compatible_server,
    set_key,
    submit_repository,
    transfer_ownership,
)

SERVER_URL = "https://llm.example.com/v1"
SERVER_MODELS = ["llama-3.1-8b-instruct", "my-team/coder-7b", "gpt-4o-mini"]


@pytest.fixture
def real_adapter():
    with force_real_scoring_adapter():
        yield


def _models(client, access, class_id) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/scoring-models", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def _class_with_compatible_server(client, monkeypatch, *, auth_value="", **server):
    fake = FakeCompatibleServer(**server).install(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=False)
    saved = set_compatible_server(client, instructor["access"], class_id, SERVER_URL, auth_value)
    return fake, instructor, class_id, saved


def _submit(client, instructor, class_id, problem):
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    return participant


def test_a_saved_server_lists_its_models_unfiltered_and_scores_with_the_chosen_model(
    client, db, monkeypatch, real_adapter
):
    fake, instructor, class_id, saved = _class_with_compatible_server(
        client, monkeypatch, auth_value="tok-secret-9876", model_ids=SERVER_MODELS, accepted_auth="tok-secret-9876"
    )

    assert saved["scoring_connection_kind"] == "compatible_server"
    assert saved["scoring_server_host"] == "llm.example.com"
    assert saved["scoring_server_url"] == SERVER_URL
    assert saved["scoring_auth_masked"].endswith("9876")
    assert saved["openai_key_masked"] is None
    catalog = _models(client, instructor["access"], class_id)
    assert catalog["source"] == "live"
    assert [m["id"] for m in catalog["models"]] == SERVER_MODELS

    patch_class(client, instructor["access"], class_id, {"default_model": "my-team/coder-7b"})
    problem = create_open_problem(client, instructor["access"], class_id)
    fake.verdicts = openai_success_body(problem.item_id, model="my-team/coder-7b")
    participant = _submit(client, instructor, class_id, problem)

    assert run_scan(client)["count"] == 1

    scoring = fake.scoring_requests
    assert len(scoring) == 1
    assert scoring[0]["url"] == f"{SERVER_URL}/chat/completions"
    assert scoring[0]["headers"]["Authorization"] == "Bearer tok-secret-9876"
    assert scoring[0]["json"]["model"] == "my-team/coder-7b"
    assert "reasoning_effort" not in scoring[0]["json"]
    assert mine(client, participant["access"], class_id, problem.id)["submissions"][0]["status"] == "scored"


@pytest.mark.parametrize(
    ("server_url", "sentence"),
    [
        ("http://llm.example.com/v1", "https:// 로 시작하는 주소만 받습니다."),
        ("https://10.0.0.5/v1", "공인 주소로 열린 서버만 받습니다"),
        ("https://backend:8000/v1", "공인 주소로 열린 서버만 받습니다"),
    ],
)
def test_addresses_that_are_not_public_https_are_refused_with_their_sentence(client, db, server_url, sentence):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], key="sk-keep-1111")

    response = put_compatible_server(client, instructor["access"], class_id, server_url)

    assert response.status_code == 422
    assert response.json()["detail"].startswith(sentence)
    kept = get_class(client, instructor["access"], class_id)
    assert kept["scoring_connection_kind"] == "openai_key"
    assert kept["openai_key_masked"].endswith("1111")


@pytest.mark.parametrize(
    ("server", "sentence"),
    [
        ({"accepted_auth": "right-token"}, "서버가 인증 값을 거절했습니다"),
        ({"refuse": OutboundReason.UNREACHABLE}, "서버에 닿지 않습니다"),
        ({"refuse": OutboundReason.CERTIFICATE}, "서버 인증서를 확인하지 못했습니다"),
    ],
)
def test_a_server_that_fails_the_check_is_refused_with_its_sentence(
    client, db, monkeypatch, real_adapter, server, sentence
):
    FakeCompatibleServer(model_ids=SERVER_MODELS, **server).install(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=False)

    response = put_compatible_server(client, instructor["access"], class_id, SERVER_URL, "wrong-token")

    assert response.status_code == 422
    assert response.json()["detail"].startswith(sentence)
    assert get_class(client, instructor["access"], class_id)["has_openai_key"] is False


def test_a_server_without_a_model_list_takes_a_typed_model_name(client, db, monkeypatch, real_adapter):
    fake, instructor, class_id, _ = _class_with_compatible_server(client, monkeypatch, model_ids=None)

    catalog = _models(client, instructor["access"], class_id)
    assert catalog["source"] == "manual"
    assert catalog["models"] == []

    patch_class(client, instructor["access"], class_id, {"default_model": "local-coder"})
    problem = create_open_problem(client, instructor["access"], class_id)
    fake.verdicts = openai_success_body(problem.item_id, model="local-coder")
    _submit(client, instructor, class_id, problem)
    run_scan(client)

    scoring = fake.scoring_requests
    assert scoring[0]["json"]["model"] == "local-coder"
    # 인증 값을 비워 둔 서버에는 Authorization 을 싣지 않는다.
    assert "Authorization" not in scoring[0]["headers"]


def test_the_auth_value_never_appears_raw_in_responses_logs_or_error_events(
    client, db, monkeypatch, real_adapter, caplog
):
    token = f"tok-{secrets.token_hex(16)}"
    events: list[dict] = []

    class _CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            event = envelope.get_event()
            if event is not None:
                events.append(event)

    sentry_sdk.init(**{**sentry_init_options("http://public@glitchtip.invalid/1"), "transport": _CaptureTransport})
    caplog.set_level(logging.DEBUG)
    try:
        fake, instructor, class_id, saved = _class_with_compatible_server(
            client, monkeypatch, auth_value=token, model_ids=SERVER_MODELS, accepted_auth=token
        )
        problem = create_open_problem(client, instructor["access"], class_id)
        fake.error = RuntimeError("서버가 이상한 응답을 했다")
        _submit(client, instructor, class_id, problem)
        client.post(SCAN_URL, content_type="application/json", **internal_headers())
        bodies = [
            json.dumps(saved),
            get_class(client, instructor["access"], class_id).__repr__(),
            json.dumps(_models(client, instructor["access"], class_id)),
        ]
    finally:
        sentry_sdk.get_global_scope().set_client(None)

    assert fake.scoring_requests  # 채점 요청은 실제로 나갔다
    assert events  # 채점 실패가 오류 이벤트로 잡혔다 — 그 이벤트에도 값이 없어야 한다
    stored = Class.objects.get(id=class_id).openai_api_key_encrypted
    assert token not in stored and decrypt(stored) == token
    leaked_in_responses = any(token in body for body in bodies)
    leaked_in_logs = token in caplog.text
    leaked_in_events = any(token in json.dumps(e, ensure_ascii=False, default=str) for e in events)
    assert not leaked_in_responses
    assert not leaked_in_logs
    assert not leaked_in_events


def test_only_the_owner_saves_and_a_co_instructor_reads_kind_and_host(client, db, monkeypatch):
    fake = FakeCompatibleServer(model_ids=SERVER_MODELS).install(monkeypatch)
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    class_id = create_class(client, owner["access"], with_key=False)
    add_co_instructor(client, owner["access"], class_id, co["access"])

    refused = put_compatible_server(client, co["access"], class_id, SERVER_URL, "co-token")
    assert refused.status_code == 403
    assert fake.requests == []

    set_compatible_server(client, owner["access"], class_id, SERVER_URL, "owner-token-4321")
    seen = get_class(client, co["access"], class_id)
    assert seen["scoring_connection_kind"] == "compatible_server"
    assert seen["scoring_server_host"] == "llm.example.com"
    assert seen["scoring_server_url"] is None
    assert seen["scoring_auth_masked"] is None


def test_switching_between_an_openai_key_and_a_server_drops_the_previous_value(client, db, monkeypatch):
    FakeCompatibleServer(model_ids=SERVER_MODELS).install(monkeypatch)
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], key="sk-old-key-1111")

    set_compatible_server(client, instructor["access"], class_id, SERVER_URL)
    after_server = Class.objects.get(id=class_id)
    assert after_server.openai_api_key_encrypted == ""
    assert get_class(client, instructor["access"], class_id)["openai_key_masked"] is None

    set_key(client, instructor["access"], class_id, "sk-new-key-2222")
    back = get_class(client, instructor["access"], class_id)
    assert back["scoring_connection_kind"] == "openai_key"
    assert back["scoring_server_host"] is None
    assert back["openai_key_masked"].endswith("2222")
    assert Class.objects.get(id=class_id).scoring_server_url == ""


def test_handing_the_class_over_drops_the_server(client, db, monkeypatch):
    FakeCompatibleServer(model_ids=SERVER_MODELS).install(monkeypatch)
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    class_id = create_class(client, owner["access"], with_key=False)
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="받는 강사")
    set_compatible_server(client, owner["access"], class_id, SERVER_URL, "owner-token")

    transfer_ownership(client, owner["access"], class_id, co["access"], recipient_name="받는 강사")

    taken = get_class(client, co["access"], class_id)
    assert taken["has_openai_key"] is False
    assert taken["scoring_server_host"] is None


# --- 채점 연결은 따라가지 않는다(#605) ---------------------------------------------------


def _assert_no_connection(seen: dict) -> None:
    """「OpenAI 키·없음」 — 새 클래스가 아무 채점 연결 없이 시작한 모양."""

    assert seen["has_openai_key"] is False
    assert seen["scoring_connection_kind"] == "openai_key"
    assert seen["scoring_server_host"] is None
    assert seen["scoring_server_url"] is None
    assert seen["scoring_auth_masked"] is None


def test_a_copied_class_starts_without_the_server(client, db, monkeypatch):
    _, instructor, class_id, _ = _class_with_compatible_server(client, monkeypatch, auth_value="owner-token-4321")

    copied = client.post(f"{CLASSES_URL}/{class_id}/copy", **auth_header(instructor["access"]))
    assert copied.status_code == 201, copied.content

    _assert_no_connection(get_class(client, instructor["access"], copied.json()["id"]))
    assert Class.objects.get(id=copied.json()["id"]).scoring_server_url == ""


def test_a_class_imported_from_a_template_starts_without_the_server(client, db, monkeypatch):
    _, instructor, class_id, _ = _class_with_compatible_server(client, monkeypatch, auth_value="owner-token-4321")
    published = client.post(
        f"{CLASSES_URL}/{class_id}/publish-template",
        data={"publisher_display_name": "김강사"},
        content_type="application/json",
        **auth_header(instructor["access"]),
    )
    assert published.status_code in (200, 201), published.content
    other = login(client, uid="instructor-2")

    imported = client.post(
        f"/api/classroom/class-templates/{published.json()['share_code']}/import",
        data={"name": "가져온 클래스"},
        content_type="application/json",
        **auth_header(other["access"]),
    )
    assert imported.status_code == 201, imported.content

    _assert_no_connection(get_class(client, other["access"], imported.json()["id"]))


def test_a_connected_app_reads_only_kind_and_host_and_cannot_change_the_connection(client, db, monkeypatch):
    from tests.test_classroom_connected_apps import _connect, _rpc

    _, instructor, class_id, _ = _class_with_compatible_server(client, monkeypatch, auth_value="owner-token-4321")
    token = _connect(client, instructor["access"])["access_token"]

    read = _rpc(client, token, "tools/call", {"name": "get_class", "arguments": {"class_id": class_id}})
    seen = read.json()["result"]["structuredContent"]
    assert seen["has_openai_key"] is True
    assert seen["scoring_connection_kind"] == "compatible_server"
    assert seen["scoring_server_host"] == "llm.example.com"
    assert "scoring_server_url" not in seen
    assert "scoring_auth_masked" not in seen
    body = read.content.decode("utf-8")
    assert "/v1" not in body and "4321" not in body

    for arguments in (
        {"scoring_server_url": "https://other.example.com/v1"},
        {"scoring_connection_kind": "openai_key"},
        {"openai_api_key": "sk-new"},
    ):
        changed = _rpc(
            client, token, "tools/call", {"name": "update_class_settings", "arguments": {"class_id": class_id, **arguments}}
        )
        assert changed.json()["result"]["isError"] is True, arguments
    tool_names = {tool["name"] for tool in _rpc(client, token, "tools/list").json()["result"]["tools"]}
    assert not {name for name in tool_names if "key" in name or "server" in name or "connection" in name}
    assert Class.objects.get(id=class_id).scoring_server_url == SERVER_URL
