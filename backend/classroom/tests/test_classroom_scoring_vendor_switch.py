"""강의실 클래스에 OpenAI·Claude 키를 둘 다 넣어 두고 채점 벤더를 스위치로 고른다 (#1269).

두 키는 따로 산다(`Class.openai_api_key_*`·`anthropic_api_key_*`) — 쉬는 쪽 키를 넣거나 바꿔도 스위치는 넘어가지
않고, `PUT …/scoring-vendor` 가 넘긴다. 키가 없거나 거부된 쪽으로는 넘어가지 않는다. 넘어가면 기본 모델·문제별
모델이 그 벤더 것으로 바뀌지만, 점수가 있는 제출은 다시 채점하지 않는다.

실물 어댑터를 강제한 시험은 `requests` 를 몽키패치해 OpenAI·Anthropic 응답을 흉내 낸다 — 실제 벤더를 부르지 않는다.
"""

from __future__ import annotations

import importlib
import json
import logging

import pytest
import requests
from django.apps import apps
from django.test import override_settings

from classroom import scoring_connection
from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt
from classroom.pending_scoring import SIZE_HOLD_ERROR_PREFIX
from classroom.tests.test_classroom_connected_apps import _connect
from classroom.tests.test_classroom_mcp_read_tools import _structured
from core.crypto import encrypt
from core.llm_scoring_anthropic import FAKE_MODELS_BODY
from tests.classroom_scenarios import (
    CLASSES_URL,
    REAL_SCORING_ADAPTER,
    FakeVendorResponse,
    add_co_instructor,
    auth_header,
    create_class,
    create_open_problem,
    get_class,
    join_class,
    login,
    mine,
    openai_verdicts_body,
    run_scan,
    set_anthropic_key,
    set_key,
    submit_repository,
    switch_scoring_vendor,
)

_migration = importlib.import_module("classroom.migrations.0042_class_anthropic_key")

OPENAI_KEY = "sk-openai-raw-SECRET1111"
CLAUDE_KEY = "sk-ant-raw-SECRET2222"
OPENAI = "https://api.openai.com/v1"
ANTHROPIC = "https://api.anthropic.com/v1"


@pytest.fixture
def real_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE=REAL_SCORING_ADAPTER):
        yield


def _models(client, access: str, class_id: int) -> list[str]:
    response = client.get(f"{CLASSES_URL}/{class_id}/scoring-models", **auth_header(access))
    assert response.status_code == 200, response.content
    return [m["id"] for m in response.json()["models"]]


def _two_keys(client, *, uid: str = "owner") -> tuple[dict, int]:
    owner = login(client, uid=uid)
    class_id = create_class(client, owner["access"], with_key=False)
    set_key(client, owner["access"], class_id, OPENAI_KEY)
    assert set_anthropic_key(client, owner["access"], class_id, CLAUDE_KEY).status_code == 200
    return owner, class_id


def _claude_body(item_id: int) -> dict:
    verdicts = [{"requirement_id": item_id, "is_met": True, "reasoning": "README 가 있다."}]
    return {
        "type": "message",
        "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": json.dumps({"verdicts": verdicts}, ensure_ascii=False)}],
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 900, "output_tokens": 100},
    }


def _vendors(monkeypatch, *, openai_post=None, anthropic_post=None) -> list:
    """OpenAI·Anthropic 로 나가는 요청을 함께 흉내 낸다 — 키 확인·모델 목록(GET)은 받고, 채점(POST)은 주어진
    응답을 준다. 나간 요청을 (벤더, 주소, 헤더, 본문)으로 쌓는다."""

    calls: list = []

    def get(url, **kwargs):
        vendor = "anthropic" if url.startswith(ANTHROPIC) else "openai"
        calls.append((vendor, "GET", url, kwargs.get("headers", {}), None))
        if vendor == "anthropic":
            return FakeVendorResponse(200, FAKE_MODELS_BODY)
        return FakeVendorResponse(200, {"object": "list", "data": [{"id": "gpt-4.1-mini", "object": "model"}]})

    def post(url, **kwargs):
        vendor = "anthropic" if url.startswith(ANTHROPIC) else "openai"
        calls.append((vendor, "POST", url, kwargs.get("headers", {}), kwargs.get("json")))
        handler = anthropic_post if vendor == "anthropic" else openai_post
        assert handler is not None, f"{vendor} 로 채점을 보내면 안 된다"
        status, body = handler(kwargs.get("json"))
        return FakeVendorResponse(status, body)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", post)
    return calls


def _posts(calls: list) -> list:
    return [c for c in calls if c[1] == "POST"]


# --- 저장·스위치 -----------------------------------------------------------------------


def test_both_keys_are_kept_and_the_switch_moves_the_default_model_and_model_list(client, db):
    owner, class_id = _two_keys(client)

    body = get_class(client, owner["access"], class_id)
    # 쉬는 쪽 키(Claude)를 넣어도 스위치는 OpenAI 그대로다.
    assert body["scoring_connection_kind"] == "openai_key"
    assert body["openai_key"] == {"masked": "••••••••1111", "status": "verified", "switchable": True}
    assert body["anthropic_key"] == {"masked": "••••••••2222", "status": "verified", "switchable": True}
    assert body["openai_key_masked"].endswith("1111")
    assert "gpt-4.1-mini" in _models(client, owner["access"], class_id)

    switched = switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key")

    assert switched["scoring_connection_kind"] == "anthropic_key"
    assert switched["default_model"] == "claude-haiku-5-5"
    assert switched["openai_key_masked"].endswith("2222")
    assert switched["openai_key"]["masked"].endswith("1111")  # 쉬는 키는 그대로 남는다
    models = _models(client, owner["access"], class_id)
    assert models[0] == "claude-haiku-5-5"
    assert all(m.startswith("claude-") for m in models)

    back = switch_scoring_vendor(client, owner["access"], class_id, "openai_key")

    assert back["scoring_connection_kind"] == "openai_key"
    assert back["default_model"] == "gpt-4.1-mini"
    assert back["anthropic_key"]["masked"].endswith("2222")


def test_replacing_the_resting_key_does_not_flip_the_switch_or_reset_problem_models(client, db):
    owner, class_id = _two_keys(client)
    own = create_open_problem(client, owner["access"], class_id, model="gpt-4.1")

    assert set_anthropic_key(client, owner["access"], class_id, "sk-ant-rotated-3333").status_code == 200

    body = get_class(client, owner["access"], class_id)
    assert body["scoring_connection_kind"] == "openai_key"
    assert body["anthropic_key"]["masked"].endswith("3333")
    listed = client.get(f"{CLASSES_URL}/{class_id}/problems", **auth_header(owner["access"])).json()
    assert next(p for p in listed if p["id"] == own.id)["effective_model"] == "gpt-4.1"


def test_the_switch_returns_the_per_problem_models_of_the_other_vendor_to_the_class_default(client, db):
    owner, class_id = _two_keys(client)
    own = create_open_problem(client, owner["access"], class_id, model="gpt-4.1")

    switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key")

    listed = client.get(f"{CLASSES_URL}/{class_id}/problems", **auth_header(owner["access"])).json()
    assert next(p for p in listed if p["id"] == own.id)["effective_model"] == "claude-haiku-5-5"


def test_the_switch_refuses_a_vendor_without_a_key(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    set_key(client, owner["access"], class_id, OPENAI_KEY)

    switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key", expect=422)

    body = get_class(client, owner["access"], class_id)
    assert body["scoring_connection_kind"] == "openai_key"
    assert body["anthropic_key"] is None


def test_the_switch_refuses_a_key_the_vendor_rejected_while_scoring(client, db, monkeypatch, real_adapter):
    _vendors(monkeypatch)
    owner = login(client, uid="owner")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"], with_key=False)
    assert set_anthropic_key(client, owner["access"], class_id, CLAUDE_KEY).status_code == 200
    problem = create_open_problem(client, owner["access"], class_id, syntax_check_enabled=False)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    _vendors(monkeypatch, anthropic_post=lambda body: (401, {"type": "error", "error": {"type": "authentication_error"}}))
    run_scan(client)
    # Claude 키가 거부됐으니 OpenAI 키를 넣으면 그쪽으로 넘어간다(지금 연결로는 채점할 수 없다).
    _vendors(monkeypatch)
    set_key(client, owner["access"], class_id, OPENAI_KEY)
    body = get_class(client, owner["access"], class_id)
    assert body["scoring_connection_kind"] == "openai_key"
    assert body["anthropic_key"] == {"masked": "••••••••2222", "status": "rejected", "switchable": False}

    switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key", expect=422)

    assert get_class(client, owner["access"], class_id)["scoring_connection_kind"] == "openai_key"


def test_only_the_owner_can_switch(client, db):
    owner, class_id = _two_keys(client)
    co = login(client, uid="co")
    add_co_instructor(client, owner["access"], class_id, co["access"])

    switch_scoring_vendor(client, co["access"], class_id, "anthropic_key", expect=403)

    assert get_class(client, owner["access"], class_id)["scoring_connection_kind"] == "openai_key"


def test_deleting_the_resting_key_keeps_scoring_and_deleting_the_active_one_leaves_no_key(client, db):
    owner, class_id = _two_keys(client)

    resting = client.delete(f"{CLASSES_URL}/{class_id}/anthropic-key", **auth_header(owner["access"]))
    assert resting.status_code == 200, resting.content
    assert resting.json()["anthropic_key"] is None
    assert resting.json()["has_openai_key"] is True

    active = client.delete(f"{CLASSES_URL}/{class_id}/openai-key", **auth_header(owner["access"]))
    assert active.status_code == 200, active.content
    assert active.json()["has_openai_key"] is False
    assert active.json()["openai_key"] is None


# --- 채점 -------------------------------------------------------------------------------


def _scoring_setup(client):
    owner, class_id = _two_keys(client)
    participant = login(client, uid="participant")
    problem = create_open_problem(client, owner["access"], class_id, syntax_check_enabled=False)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    return owner, participant, class_id, problem


def test_scoring_goes_to_the_vendor_the_switch_picks_with_that_vendors_key(client, db, monkeypatch, real_adapter):
    _vendors(monkeypatch)
    owner, participant, class_id, problem = _scoring_setup(client)
    submit_repository(client, participant["access"], class_id, problem.id)
    verdict = [{"requirement_id": problem.item_id, "is_met": True, "reasoning": "ok"}]
    calls = _vendors(
        monkeypatch,
        openai_post=lambda body: (200, openai_verdicts_body(verdict)),
        anthropic_post=lambda body: (200, _claude_body(problem.item_id)),
    )

    run_scan(client)

    [(vendor, _, url, headers, sent)] = _posts(calls)
    assert (vendor, url, sent["model"]) == ("openai", f"{OPENAI}/chat/completions", "gpt-4.1-mini")
    assert headers["Authorization"] == f"Bearer {OPENAI_KEY}"

    switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key")
    submit_repository(client, participant["access"], class_id, problem.id)
    calls.clear()

    run_scan(client)

    [(vendor, _, url, headers, sent)] = _posts(calls)
    assert (vendor, url, sent["model"]) == ("anthropic", f"{ANTHROPIC}/messages", "claude-haiku-5-5")
    assert headers["x-api-key"] == CLAUDE_KEY


def test_switching_rescores_nothing_that_has_a_score_and_picks_up_only_the_size_held(
    client, db, monkeypatch, real_adapter
):
    """스위치로 채점 모델이 바뀌면 다시 집히는 것은 점수 없는 제출뿐이다 — 「크기 초과」 보류(#989)는 그 모델일
    때만 빠지므로 새 벤더 모델로 다시 시도한다. 점수가 있는 제출은 벤더를 다시 부르지 않는다(강사 돈)."""

    _vendors(monkeypatch)
    owner, participant, class_id, problem = _scoring_setup(client)
    scored_id = submit_repository(client, participant["access"], class_id, problem.id)["id"]
    verdict = [{"requirement_id": problem.item_id, "is_met": True, "reasoning": "ok"}]
    _vendors(monkeypatch, openai_post=lambda body: (200, openai_verdicts_body(verdict)))
    run_scan(client)
    held_id = submit_repository(client, participant["access"], class_id, problem.id)["id"]
    too_long = {"error": {"message": "too long", "type": "invalid_request_error", "code": "context_length_exceeded"}}
    _vendors(monkeypatch, openai_post=lambda body: (400, too_long))
    run_scan(client)
    assert ClassroomScore.objects.filter(submission_id=scored_id).exists()
    assert ClassroomScoringAttempt.objects.filter(
        submission_id=held_id, error__startswith=SIZE_HOLD_ERROR_PREFIX
    ).exists()
    scored_attempts = ClassroomScoringAttempt.objects.filter(submission_id=scored_id).count()

    switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key")
    calls = _vendors(monkeypatch, anthropic_post=lambda body: (200, _claude_body(problem.item_id)))
    run_scan(client)
    run_scan(client)

    assert len(_posts(calls)) == 1, "점수 있는 제출을 다시 채점했거나 보류를 두 번 불렀다"
    assert ClassroomScore.objects.filter(submission_id=held_id).exists()
    assert ClassroomScoringAttempt.objects.filter(submission_id=scored_id).count() == scored_attempts
    statuses = [s["status"] for s in mine(client, participant["access"], class_id, problem.id)["submissions"]]
    assert statuses == ["scored", "scored"]


# --- 기존 값 옮기기 ------------------------------------------------------------------------


def test_the_migration_moves_a_claude_connection_key_into_the_claude_columns_and_back(client, db, monkeypatch, real_adapter):
    owner = login(client, uid="owner")
    claude_class_id = create_class(client, owner["access"], with_key=False)
    openai_class_id = create_class(client, owner["access"], with_key=False)
    # 옛 모양(#795): Claude 키 연결이 OpenAI 키 칸을 같이 썼다.
    Class.objects.filter(pk=claude_class_id).update(
        scoring_connection_kind=Class.ScoringConnectionKind.ANTHROPIC_KEY,
        default_model="claude-haiku-5-5",
        openai_api_key_encrypted=encrypt(CLAUDE_KEY),
        openai_api_key_last4="2222",
        openai_api_key_status=Class.ScoringKeyStatus.VERIFIED,
    )
    Class.objects.filter(pk=openai_class_id).update(
        openai_api_key_encrypted=encrypt(OPENAI_KEY),
        openai_api_key_last4="1111",
        openai_api_key_status=Class.ScoringKeyStatus.VERIFIED,
    )

    _migration._move_claude_keys(apps, None)

    moved = Class.objects.get(pk=claude_class_id)
    assert (moved.openai_api_key_encrypted, moved.openai_api_key_last4) == ("", "")
    assert (moved.anthropic_api_key_last4, moved.anthropic_api_key_status) == ("2222", "verified")
    connection = scoring_connection.connection_for(moved)
    assert connection is not None
    assert (connection.kind, connection.base_url, connection.auth_value()) == ("anthropic_key", ANTHROPIC, CLAUDE_KEY)
    untouched = Class.objects.get(pk=openai_class_id)
    assert untouched.openai_api_key_last4 == "1111" and untouched.anthropic_api_key_encrypted == ""
    body = get_class(client, owner["access"], claude_class_id)
    assert body["anthropic_key"]["masked"].endswith("2222") and body["openai_key"] is None

    _migration._move_claude_keys_back(apps, None)

    restored = Class.objects.get(pk=claude_class_id)
    assert restored.openai_api_key_last4 == "2222"
    assert scoring_connection.ScoringConnection(
        kind="anthropic_key", base_url=ANTHROPIC, _encrypted_auth=restored.openai_api_key_encrypted
    ).auth_value() == CLAUDE_KEY


def test_a_migrated_claude_class_is_scored_by_claude_with_the_same_key(client, db, monkeypatch, real_adapter):
    _vendors(monkeypatch)
    owner = login(client, uid="owner")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"], with_key=False)
    problem = create_open_problem(client, owner["access"], class_id, syntax_check_enabled=False)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    Class.objects.filter(pk=class_id).update(
        scoring_connection_kind=Class.ScoringConnectionKind.ANTHROPIC_KEY,
        default_model="claude-haiku-5-5",
        openai_api_key_encrypted=encrypt(CLAUDE_KEY),
        openai_api_key_last4="2222",
        openai_api_key_status=Class.ScoringKeyStatus.VERIFIED,
    )
    _migration._move_claude_keys(apps, None)
    calls = _vendors(monkeypatch, anthropic_post=lambda body: (200, _claude_body(problem.item_id)))

    run_scan(client)

    [(vendor, _, _, headers, _)] = _posts(calls)
    assert vendor == "anthropic" and headers["x-api-key"] == CLAUDE_KEY


# --- 키 값이 나가지 않는다 -------------------------------------------------------------------


def test_no_key_value_reaches_responses_logs_or_the_connected_app(client, db, caplog):
    caplog.set_level(logging.DEBUG)
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    saved = [
        client.put(
            f"{CLASSES_URL}/{class_id}/openai-key",
            data={"api_key": OPENAI_KEY},
            content_type="application/json",
            **auth_header(owner["access"]),
        ),
        set_anthropic_key(client, owner["access"], class_id, CLAUDE_KEY),
    ]
    switched = switch_scoring_vendor(client, owner["access"], class_id, "anthropic_key")
    token = _connect(client, owner["access"])["access_token"]
    tool_class = _structured(client, token, "get_class", class_id=class_id)

    texts = [r.content.decode("utf-8") for r in saved] + [
        json.dumps(switched, ensure_ascii=False),
        json.dumps(get_class(client, owner["access"], class_id), ensure_ascii=False),
        json.dumps(tool_class, ensure_ascii=False),
        caplog.text,
    ]
    for text in texts:
        assert "SECRET" not in text
    # 연결된 앱은 끝 네 자리 마스킹도 받지 않는다(#605).
    assert "openai_key" not in tool_class and "anthropic_key" not in tool_class
    assert tool_class["scoring_connection_kind"] == "anthropic_key"
