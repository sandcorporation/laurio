"""운영 설정 — 공모전 AI 키·모델 값을 Operator 화면에서 바꾸고 재시작 없이 반영 (#922, ADR-0075).

받아들임 기준을 마운트된 API(`/api/operator/runtime-settings…`)로 친다. 프로세스 캐시와 버전
무효화는 「다른 프로세스」를 흉내 내는 두 번째 읽기(`RuntimeSettingsReader`)로 본다 — pytest 에는
Redis 가 없어 같은 흉내 버전 저장소를 나눠 쥔다(`RUNTIME_SETTINGS_VERSION_STORE=memory`).
"""

from __future__ import annotations

import logging

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from contests.requirement_chat import OpenAIRequirementChatAdapter
from core.llm_scoring import OpenAIScoringAdapter, get_adapter
from core.observability import scrub_secrets
from policies.models import RuntimeSetting, RuntimeSettingChange
from policies.runtime_settings import (
    FALLBACK_TTL_SECONDS,
    MemoryVersionStore,
    RuntimeSettingsReader,
    setting_value,
    version_store,
)

pytestmark = pytest.mark.django_db

ORIGIN = "http://testserver"
URL = "/api/operator/runtime-settings"
PW = "operator-pw-runtime-9221-zzz"
ENV_KEY = "sk-env-key-0000000000000000wxyz"
DB_KEY = "sk-db-key-1111111111111111abcd"
NEW_KEY = "sk-db-key-2222222222222222efgh"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", ENV_KEY)
    monkeypatch.setenv("LLM_OPENAI_MODEL", "gpt-env-model")
    monkeypatch.delenv("LLM_OPENAI_TEMPERATURE", raising=False)
    monkeypatch.delenv("LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE", raising=False)


def _client_for(username, *, superuser=False):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    assert (
        client.post(
            "/api/operator/login",
            data={"username": username, "password": PW},
            content_type="application/json",
            HTTP_ORIGIN=ORIGIN,
        ).status_code
        == 200
    )
    return client


@pytest.fixture
def su():
    return _client_for("rs_super", superuser=True)


def _post(client, path, **body):
    return client.post(f"{URL}{path}", data=body, content_type="application/json", HTTP_ORIGIN=ORIGIN)


def _save(client, key, value, capture):
    with capture(execute=True):
        return _post(client, f"/{key}", value=value)


def _clear(client, key, capture):
    with capture(execute=True):
        return _post(client, f"/{key}/clear")


def _settings(client):
    response = client.get(URL, HTTP_ORIGIN=ORIGIN)
    assert response.status_code == 200
    return {s["key"]: s for s in response.json()["settings"]}


# --- 우선순위: DB 없음 → env, DB 있음 → DB, 지우기 → env -------------------------


def test_empty_table_keeps_env_values_for_contest_ai():
    assert RuntimeSetting.objects.count() == 0
    adapter = OpenAIScoringAdapter()
    assert adapter._api_key == ENV_KEY
    assert adapter._model == "gpt-env-model"
    assert adapter._temperature == 0
    chat = OpenAIRequirementChatAdapter()
    assert chat._api_key == ENV_KEY
    assert chat._temperature == 0.7


def test_db_value_wins_then_clear_falls_back_to_env(su, django_capture_on_commit_callbacks):
    assert _save(su, "OPEN_AI_API_KEY", DB_KEY, django_capture_on_commit_callbacks).status_code == 200
    assert _save(su, "LLM_OPENAI_MODEL", "gpt-db-model", django_capture_on_commit_callbacks).status_code == 200
    assert _save(su, "LLM_OPENAI_TEMPERATURE", "0.2", django_capture_on_commit_callbacks).status_code == 200
    assert (
        _save(su, "LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE", "0.4", django_capture_on_commit_callbacks).status_code
        == 200
    )

    adapter = OpenAIScoringAdapter()
    assert (adapter._api_key, adapter._model, adapter._temperature) == (DB_KEY, "gpt-db-model", 0.2)
    chat = OpenAIRequirementChatAdapter()
    assert (chat._api_key, chat._model, chat._temperature) == (DB_KEY, "gpt-db-model", 0.4)

    assert _clear(su, "OPEN_AI_API_KEY", django_capture_on_commit_callbacks).json()["changed"] is True
    assert OpenAIScoringAdapter()._api_key == ENV_KEY
    view = _settings(su)["OPEN_AI_API_KEY"]
    assert (view["source"], view["last4"]) == ("env", "wxyz")


def test_classroom_adapter_does_not_read_runtime_settings(su, django_capture_on_commit_callbacks):
    _save(su, "LLM_OPENAI_MODEL", "gpt-db-model", django_capture_on_commit_callbacks)
    adapter = OpenAIScoringAdapter(api_key="teacher-key", product="classroom")
    assert adapter._model == "gpt-env-model"


def test_get_adapter_is_rebuilt_with_the_new_key(su, settings, django_capture_on_commit_callbacks):
    settings.LLM_ADAPTER_MODE = "core.llm_scoring.OpenAIScoringAdapter"
    _save(su, "OPEN_AI_API_KEY", DB_KEY, django_capture_on_commit_callbacks)
    assert get_adapter()._api_key == DB_KEY
    _save(su, "OPEN_AI_API_KEY", NEW_KEY, django_capture_on_commit_callbacks)
    assert get_adapter()._api_key == NEW_KEY


# --- 캐시: 버전 무효화와 Redis 장애 --------------------------------------------


def test_other_process_sees_new_value_only_after_version_bump(su, django_capture_on_commit_callbacks):
    other = RuntimeSettingsReader(version_store())
    assert setting_value("LLM_OPENAI_MODEL", reader=other) == "gpt-env-model"

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert _post(su, "/LLM_OPENAI_MODEL", value="gpt-db-model").status_code == 200
    # 커밋 전(버전이 오르기 전) — 캐시를 쥔 프로세스는 옛 값.
    assert setting_value("LLM_OPENAI_MODEL", reader=other) == "gpt-env-model"
    # 메모리가 빈 프로세스는 처음 읽을 때 DB 를 본다.
    fresh = RuntimeSettingsReader(version_store())
    assert setting_value("LLM_OPENAI_MODEL", reader=fresh) == "gpt-db-model"

    for callback in callbacks:
        callback()
    assert setting_value("LLM_OPENAI_MODEL", reader=other) == "gpt-db-model"


def test_version_store_outage_falls_back_to_short_ttl(su, django_capture_on_commit_callbacks, caplog):
    now = [1000.0]
    store = version_store()
    assert isinstance(store, MemoryVersionStore)
    reader = RuntimeSettingsReader(store, clock=lambda: now[0])
    assert setting_value("LLM_OPENAI_MODEL", reader=reader) == "gpt-env-model"

    store.fail = True
    response = _save(su, "LLM_OPENAI_MODEL", "gpt-db-model", django_capture_on_commit_callbacks)
    assert response.status_code == 200  # 버전을 못 올려도 저장은 끝난다
    now[0] += 1
    assert setting_value("LLM_OPENAI_MODEL", reader=reader) == "gpt-env-model"
    now[0] += FALLBACK_TTL_SECONDS
    assert setting_value("LLM_OPENAI_MODEL", reader=reader) == "gpt-db-model"


def test_database_failure_falls_back_to_env():
    def broken():
        raise RuntimeError("relation does not exist")

    reader = RuntimeSettingsReader(MemoryVersionStore(), loader=broken)
    assert setting_value("OPEN_AI_API_KEY", reader=reader) == ENV_KEY


# --- 응답·이력·로그·DB 에 비밀 원문 없음 ----------------------------------------


def test_secret_never_leaves_in_response_history_logs_or_db(su, django_capture_on_commit_callbacks, caplog):
    caplog.set_level(logging.DEBUG)
    saved = _save(su, "OPEN_AI_API_KEY", DB_KEY, django_capture_on_commit_callbacks)
    replaced = _save(su, "OPEN_AI_API_KEY", NEW_KEY, django_capture_on_commit_callbacks)
    listing = su.get(URL, HTTP_ORIGIN=ORIGIN)
    changes = su.get(f"{URL}/changes", HTTP_ORIGIN=ORIGIN)
    probed = _post(su, "/OPEN_AI_API_KEY/test", value=NEW_KEY)

    for response in (saved, replaced, listing, changes, probed):
        for raw in (DB_KEY, NEW_KEY, ENV_KEY):
            assert raw not in response.content.decode()
    for raw in (DB_KEY, NEW_KEY):
        assert raw not in caplog.text
        assert not RuntimeSetting.objects.filter(stored__contains=raw).exists()

    view = _settings(su)["OPEN_AI_API_KEY"]
    assert view["configured"] is True and view["value"] is None
    assert (view["source"], view["last4"], view["updated_by"]) == ("db", "efgh", "rs_super")
    history = changes.json()
    assert [(c["action"], c["before"], c["after"]) for c in history] == [
        ("set", "••••abcd", "••••efgh"),
        ("set", "", "••••abcd"),
    ]


def test_env_key_shows_only_last4(su):
    view = _settings(su)["OPEN_AI_API_KEY"]
    assert (view["source"], view["configured"], view["value"], view["last4"]) == ("env", True, None, "wxyz")


def test_missing_everywhere_is_source_none(su, monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY")
    view = _settings(su)["OPEN_AI_API_KEY"]
    assert (view["source"], view["configured"], view["last4"]) == ("none", False, None)


def test_defaults_shown_match_adapter_constants(su, monkeypatch):
    from contests import requirement_chat
    from core import llm_scoring

    monkeypatch.delenv("LLM_OPENAI_MODEL")
    views = _settings(su)
    assert views["LLM_OPENAI_MODEL"]["default"] == llm_scoring._OPENAI_DEFAULT_MODEL
    assert float(views["LLM_OPENAI_TEMPERATURE"]["default"]) == llm_scoring._OPENAI_DEFAULT_TEMPERATURE
    assert (
        float(views["LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE"]["default"])
        == requirement_chat._OPENAI_DEFAULT_TEMPERATURE
    )
    assert views["LLM_OPENAI_MODEL"]["source"] == "none"
    assert views["OPEN_AI_API_KEY"]["default"] is None


def test_sentry_event_for_this_path_carries_no_body():
    event = {"request": {"url": f"{URL}/OPEN_AI_API_KEY", "data": {"value": DB_KEY}}}
    assert DB_KEY not in repr(scrub_secrets(event))


# --- 저장 규칙 -----------------------------------------------------------------


def test_blank_save_keeps_existing_value(su, django_capture_on_commit_callbacks):
    _save(su, "OPEN_AI_API_KEY", DB_KEY, django_capture_on_commit_callbacks)
    response = _save(su, "OPEN_AI_API_KEY", "   ", django_capture_on_commit_callbacks)
    assert response.status_code == 200 and response.json()["changed"] is False
    assert OpenAIScoringAdapter()._api_key == DB_KEY
    assert RuntimeSettingChange.objects.count() == 1


@pytest.mark.parametrize(
    ("key", "value", "code"),
    [
        ("LLM_OPENAI_TEMPERATURE", "2.5", "out_of_range"),
        ("LLM_OPENAI_TEMPERATURE", "nan", "out_of_range"),
        ("LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE", "hot", "invalid_value"),
        ("LLM_OPENAI_MODEL", "gpt 4o", "invalid_value"),
        ("OPEN_AI_API_KEY", "sk-has space-zzzzzzzzzz", "invalid_value"),
    ],
)
def test_invalid_values_are_refused_without_echo(su, key, value, code):
    response = _post(su, f"/{key}", value=value)
    assert response.status_code == 422
    assert response.json()["code"] == code
    assert value not in response.content.decode()
    assert RuntimeSetting.objects.count() == 0


def test_unknown_setting_is_404(su):
    assert _post(su, "/SECRET_KEY", value="x").status_code == 404


# --- 권한 ----------------------------------------------------------------------


def test_plain_operator_reads_but_cannot_write(django_capture_on_commit_callbacks):
    plain = _client_for("rs_plain")
    assert plain.get(URL, HTTP_ORIGIN=ORIGIN).status_code == 200
    assert plain.get(f"{URL}/changes", HTTP_ORIGIN=ORIGIN).status_code == 200
    assert _post(plain, "/LLM_OPENAI_MODEL", value="gpt-x").status_code == 403
    assert _post(plain, "/LLM_OPENAI_MODEL/clear").status_code == 403
    assert _post(plain, "/OPEN_AI_API_KEY/test", value=DB_KEY).status_code == 403
    assert RuntimeSetting.objects.count() == 0


def test_non_operator_is_refused():
    user = get_user_model().objects.create_user(username="rs_member", password=PW)
    client = Client()
    client.force_login(user)
    assert client.get(URL, HTTP_ORIGIN=ORIGIN).status_code == 403
    assert _post(client, "/LLM_OPENAI_MODEL", value="gpt-x").status_code == 403
    assert Client().get(URL, HTTP_ORIGIN=ORIGIN).status_code == 401


# --- 연결 시험 -----------------------------------------------------------------


def test_probe_with_input_and_with_stored_value_on_fake_adapter(su, django_capture_on_commit_callbacks):
    assert _post(su, "/OPEN_AI_API_KEY/test", value=NEW_KEY).json() == {"result": "ok"}
    assert _post(su, "/OPEN_AI_API_KEY/test", value="wrong-shape").json() == {"result": "invalid_key"}
    # 입력이 비면 지금 쓰이는 값(env)으로.
    assert _post(su, "/OPEN_AI_API_KEY/test").json() == {"result": "ok"}
    assert RuntimeSetting.objects.count() == 0  # 시험은 저장하지 않는다


def test_probe_on_real_adapter_reports_rejection_without_detail(su, settings, monkeypatch):
    settings.LLM_ADAPTER_MODE = "core.llm_scoring.OpenAIScoringAdapter"
    seen = {}

    class _Rejected:
        status_code = 401
        text = '{"error": {"message": "Incorrect API key provided: sk-db-***efgh"}}'

        def json(self):
            return {"error": {"message": self.text}}

    def fake_get(url, headers=None, **kwargs):
        seen["auth"] = (headers or {}).get("Authorization")
        return _Rejected()

    monkeypatch.setattr("core.llm_scoring.requests.get", fake_get)
    response = _post(su, "/OPEN_AI_API_KEY/test", value=NEW_KEY)
    assert response.json() == {"result": "invalid_key"}
    assert seen["auth"] == f"Bearer {NEW_KEY}"


def test_probe_without_any_key_is_422(su, monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY")
    response = _post(su, "/OPEN_AI_API_KEY/test")
    assert (response.status_code, response.json()["code"]) == (422, "not_configured")


def test_probe_is_only_for_the_key(su):
    response = _post(su, "/LLM_OPENAI_MODEL/test", value="gpt-x")
    assert (response.status_code, response.json()["code"]) == (422, "not_probeable")
