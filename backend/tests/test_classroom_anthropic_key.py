"""강의실 채점 연결 「Claude(Anthropic) 키」 (#795, ADR-0066).

OpenAI 키(#284·#354·#681)와 같은 규율로 저장한다 — 소유자 전용, 암호화·끝 네 자리, 저장 전
`GET /v1/models` 로 한 번 확인. 채점은 네이티브 Messages API 의 구조화 출력으로 같은 판정을 받는다.

fake 스위치(기본, ADR-0043)에서는 저장 확인·모델 목록이 네트워크 없이 돈다. 실물 어댑터를 강제한
시험은 `requests` 를 몽키패치해 공식 문서 예시 모양의 녹화 응답을 준다 — 실제 Anthropic 을 부르지 않는다.
"""

from __future__ import annotations

import json

import pytest
import requests
from django.test import override_settings

from classroom.models import Class
from core.llm_scoring_anthropic import FAKE_MODELS_BODY
from tests.classroom_scenarios import (
    CLASSES_URL,
    REAL_SCORING_ADAPTER,
    add_co_instructor,
    auth_header,
    create_class,
    create_open_problem,
    get_class,
    join_class,
    login,
    mine,
    run_scan,
    set_anthropic_key,
    set_key,
    submit_repository,
    transfer_ownership,
)

ANTHROPIC = "https://api.anthropic.com/v1"


class _Response:
    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body

    def json(self):
        return self._body


def _messages_body(item_id: int, *, is_met: bool = True, usage: dict | None = None) -> dict:
    verdicts = [{"requirement_id": item_id, "is_met": is_met, "reasoning": "README 가 있다."}]
    return {
        "type": "message",
        "model": "claude-haiku-5-5",
        "content": [
            {"type": "thinking", "thinking": "", "signature": "sig"},
            {"type": "text", "text": json.dumps({"verdicts": verdicts}, ensure_ascii=False)},
        ],
        "stop_reason": "end_turn",
        "usage": usage or {"input_tokens": 900, "output_tokens": 100},
    }


def _anthropic_vendor(monkeypatch, *, models_status: int = 200, post=None) -> list:
    """Anthropic 로 나가는 GET(모델 목록·키 확인)·POST(채점)를 흉내 낸다. 나간 요청을 쌓아 돌려준다."""

    calls: list = []

    def get(url, **kwargs):
        calls.append(("GET", url, kwargs))
        assert url.startswith(ANTHROPIC), url
        return _Response(models_status, FAKE_MODELS_BODY if models_status == 200 else {"type": "error", "error": {"type": "authentication_error", "message": ""}})

    def do_post(url, **kwargs):
        calls.append(("POST", url, kwargs))
        assert url == f"{ANTHROPIC}/messages", url
        status, body = post(kwargs["json"])
        return _Response(status, body)

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests, "post", do_post)
    return calls


@pytest.fixture
def real_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE=REAL_SCORING_ADAPTER):
        yield


# --- 저장 -----------------------------------------------------------------------


def test_the_owner_saves_a_claude_key_and_sees_it_only_masked(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)

    response = set_anthropic_key(client, owner["access"], class_id, "sk-ant-api03-secretWXYZ")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["scoring_connection_kind"] == "anthropic_key"
    assert body["has_openai_key"] is True
    assert body["openai_key_masked"].endswith("WXYZ")
    assert "secret" not in json.dumps(body)
    assert body["openai_key_status"] == "verified"
    # OpenAI 모델은 Claude 키로 쓸 수 없다 — 기본 모델이 Haiku 로 옮겨 간다.
    assert body["default_model"] == "claude-haiku-5-5"
    assert body["default_model_is_reasoning"] is True
    stored = Class.objects.get(pk=class_id)
    assert "secret" not in stored.openai_api_key_encrypted


def test_a_co_instructor_cannot_save_it_and_reads_only_the_kind(client, db):
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    class_id = create_class(client, owner["access"], with_key=False)
    add_co_instructor(client, owner["access"], class_id, co["access"])
    assert set_anthropic_key(client, owner["access"], class_id).status_code == 200

    assert set_anthropic_key(client, co["access"], class_id).status_code == 403
    body = get_class(client, co["access"], class_id)
    assert body["scoring_connection_kind"] == "anthropic_key"
    assert body["has_openai_key"] is True


def test_a_key_anthropic_rejects_is_not_saved_and_the_old_key_stays(client, db, monkeypatch, real_adapter):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    calls = _anthropic_vendor(monkeypatch)
    assert set_anthropic_key(client, owner["access"], class_id, "sk-ant-good-1111").status_code == 200

    _anthropic_vendor(monkeypatch, models_status=401)
    response = set_anthropic_key(client, owner["access"], class_id, "sk-ant-typo-2222")

    assert response.status_code == 422
    assert get_class(client, owner["access"], class_id)["openai_key_masked"].endswith("1111")
    method, url, kwargs = calls[0]
    assert (method, url) == ("GET", f"{ANTHROPIC}/models")
    assert kwargs["headers"]["x-api-key"] == "sk-ant-good-1111"
    assert kwargs["headers"]["anthropic-version"] == "2023-06-01"


def test_a_key_saved_while_anthropic_is_unreachable_is_unverified(client, db, monkeypatch, real_adapter):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)

    def broken(url, **kwargs):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "get", broken)
    body = set_anthropic_key(client, owner["access"], class_id).json()

    assert body["openai_key_status"] == "unverified"
    assert body["scoring_connection_kind"] == "anthropic_key"


def test_switching_back_to_an_openai_key_moves_the_default_model_back(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    set_anthropic_key(client, owner["access"], class_id)

    set_key(client, owner["access"], class_id, "sk-openai-key")

    body = get_class(client, owner["access"], class_id)
    assert body["scoring_connection_kind"] == "openai_key"
    assert body["default_model"] == "gpt-4.1-mini"


def test_handing_the_class_over_drops_the_givers_claude_key(client, db):
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    class_id = create_class(client, owner["access"], with_key=False)
    add_co_instructor(client, owner["access"], class_id, co["access"])
    set_anthropic_key(client, owner["access"], class_id)

    transfer_ownership(client, owner["access"], class_id, co["access"])

    body = get_class(client, co["access"], class_id)
    assert body["has_openai_key"] is False
    assert body["scoring_connection_kind"] == "openai_key"


# --- 모델 목록·비용 ------------------------------------------------------------------


def _models(client, access: str, class_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/scoring-models", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


def test_the_model_list_shows_haiku_first_then_sonnet_without_opus(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    set_anthropic_key(client, owner["access"], class_id)

    catalog = _models(client, owner["access"], class_id)

    assert catalog["source"] == "live"
    assert [(m["id"], m["label"]) for m in catalog["models"]] == [
        ("claude-haiku-5-5", "Claude Haiku 5.5"),
        ("claude-sonnet-5-5", "Claude Sonnet 5.5"),
        ("claude-sonnet-5", "Claude Sonnet 5"),
    ]
    assert all(m["is_reasoning_model"] for m in catalog["models"])


def test_when_the_list_cannot_be_read_the_small_claude_list_stands_in(client, db, monkeypatch, real_adapter):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    _anthropic_vendor(monkeypatch)
    set_anthropic_key(client, owner["access"], class_id)

    def broken(url, **kwargs):
        raise requests.ConnectionError()

    monkeypatch.setattr(requests, "get", broken)
    from django.core.cache import cache

    cache.clear()
    catalog = _models(client, owner["access"], class_id)

    assert catalog["source"] == "fallback"
    assert [m["id"] for m in catalog["models"]] == ["claude-haiku-5-5", "claude-sonnet-5-5"]


def test_the_owner_can_pick_sonnet_but_not_an_openai_model(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    set_anthropic_key(client, owner["access"], class_id)

    ok = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "claude-sonnet-5-5"},
        content_type="application/json",
        **auth_header(owner["access"]),
    )
    bad = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4.1-mini"},
        content_type="application/json",
        **auth_header(owner["access"]),
    )

    assert ok.status_code == 200 and ok.json()["default_model"] == "claude-sonnet-5-5"
    assert bad.status_code == 422


def test_the_cost_estimate_prices_claude_models_in_won(client, db):
    owner = login(client, uid="owner")
    class_id = create_class(client, owner["access"], with_key=False)
    set_anthropic_key(client, owner["access"], class_id)

    response = client.get(f"{CLASSES_URL}/{class_id}/scoring-cost", **auth_header(owner["access"]))

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["unit"] == "krw"
    rows = {(r["model_id"], r["reasoning_effort"]): r for r in body["rows"]}
    assert {("claude-haiku-5-5", effort) for effort in ("low", "medium", "high")} <= rows.keys()
    assert all(r["priced"] for r in body["rows"])
    haiku, sonnet = rows[("claude-haiku-5-5", "low")], rows[("claude-sonnet-5-5", "low")]
    assert haiku["by_source_size"][0]["krw"] < sonnet["by_source_size"][0]["krw"]


# --- 채점 ----------------------------------------------------------------------------


def _scoring_setup(client):
    owner = login(client, uid="owner")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"], with_key=False)
    assert set_anthropic_key(client, owner["access"], class_id).status_code == 200
    problem = create_open_problem(client, owner["access"], class_id, syntax_check_enabled=False)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    submit_repository(client, participant["access"], class_id, problem.id)
    return owner, participant, class_id, problem


def test_an_attempt_is_scored_by_claude_with_the_verdict_schema_and_usage_counted(client, db, monkeypatch, real_adapter):
    _anthropic_vendor(monkeypatch)
    owner, participant, class_id, problem = _scoring_setup(client)
    calls = _anthropic_vendor(
        monkeypatch,
        post=lambda body: (200, _messages_body(problem.item_id, usage={"input_tokens": 900, "output_tokens": 100})),
    )

    run_scan(client)

    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert attempt["status"] != "pending"
    [(method, url, kwargs)] = [c for c in calls if c[0] == "POST"]
    sent = kwargs["json"]
    assert sent["model"] == "claude-haiku-5-5"
    assert sent["output_config"]["format"]["type"] == "json_schema"
    # 클래스의 추론 강도(기본 「낮음」)가 effort 로 실린다.
    assert sent["output_config"]["effort"] == "low"
    assert kwargs["headers"]["x-api-key"] == "sk-ant-test-instructor-key"
    assert get_class(client, owner["access"], class_id)["token_usage_total"] == 1000


def test_an_exhausted_credit_balance_pauses_the_class_instead_of_failing_the_attempt(
    client, db, monkeypatch, real_adapter
):
    _anthropic_vendor(monkeypatch)
    owner, participant, class_id, problem = _scoring_setup(client)
    error = {
        "type": "error",
        "error": {"type": "invalid_request_error", "message": "Your credit balance is too low to access the Anthropic API."},
    }
    _anthropic_vendor(monkeypatch, post=lambda body: (400, error))

    run_scan(client)

    [attempt] = mine(client, participant["access"], class_id, problem.id)["submissions"]
    assert attempt["status"] == "pending"
    assert attempt["pending_reason"] == "no_api_key"
    assert Class.objects.get(pk=class_id).scoring_quota_exhausted_at is not None


def test_a_key_anthropic_rejects_while_scoring_marks_the_key_rejected(client, db, monkeypatch, real_adapter):
    _anthropic_vendor(monkeypatch)
    owner, participant, class_id, problem = _scoring_setup(client)
    _anthropic_vendor(
        monkeypatch, post=lambda body: (401, {"type": "error", "error": {"type": "authentication_error", "message": ""}})
    )

    run_scan(client)

    assert get_class(client, owner["access"], class_id)["openai_key_status"] == "rejected"
