"""플랫폼 채점 벤더(#994) — 운영 설정 `LLM_SCORING_VENDOR` 로 OpenAI·Claude 를 고른다.

시임은 운영 설정 HTTP API(`/api/operator/runtime-settings`)와 플랫폼 채점의 어댑터 입구
`core.llm_scoring.get_adapter` 다. 값이 없으면 openai — 배포해도 운영 동작이 바뀌지 않는다.
방침 5·6항이 공모전 채점의 Anthropic 이전을 적기 전에는 anthropic 을 저장하지 않는다.
"""

from __future__ import annotations

from datetime import date

import pytest
from django.core.management import call_command
from django.test import Client

from core import llm_scoring_anthropic
from core.llm_scoring import FakeLLMScoringAdapter, LLMAdapterError, OpenAIScoringAdapter, get_adapter
from core.llm_scoring_anthropic import AnthropicScoringAdapter
from policies.models import RuntimeSetting
from policies.runtime_settings import SPECS

pytestmark = pytest.mark.django_db

ORIGIN = "http://testserver"
URL = "/api/operator/runtime-settings"
PW = "operator-pw-vendor-9941-zzz"
REAL_OPENAI = "core.llm_scoring.OpenAIScoringAdapter"
ANT_KEY = "sk-ant-db-key-1111111111111111abcd"  # leak-guard:allow — 가짜 키(흉내 연결 시험 모양)
OPEN = date(2000, 1, 1)
NOT_YET = date(2999, 1, 1)


@pytest.fixture(autouse=True)
def _env(monkeypatch, settings):
    monkeypatch.setenv("OPEN_AI_API_KEY", "sk-env-key-0000000000000000wxyz")
    for key in ("LLM_SCORING_VENDOR", "ANTHROPIC_API_KEY", "LLM_ANTHROPIC_MODEL"):
        monkeypatch.delenv(key, raising=False)
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = None


@pytest.fixture
def su():
    call_command("create_operator", "vendor_super", password=PW, superuser=True)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": "vendor_super", "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def save(su, django_capture_on_commit_callbacks):
    def _save(key: str, value: str):
        with django_capture_on_commit_callbacks(execute=True):
            return su.post(f"{URL}/{key}", data={"value": value}, content_type="application/json", HTTP_ORIGIN=ORIGIN)

    return _save


def _views(client):
    return {s["key"]: s for s in client.get(URL, HTTP_ORIGIN=ORIGIN).json()["settings"]}


# --- 기본값: 그 전과 같다 -------------------------------------------------------


def test_without_a_value_the_vendor_is_openai_and_get_adapter_is_unchanged(su, settings):
    view = _views(su)["LLM_SCORING_VENDOR"]
    assert (view["kind"], view["source"], view["default"], view["choices"]) == (
        "choice",
        "none",
        "openai",
        ["openai", "anthropic"],
    )
    settings.LLM_ADAPTER_MODE = REAL_OPENAI
    adapter = get_adapter(timeout=60)
    assert type(adapter) is OpenAIScoringAdapter
    assert adapter._timeout == 60


def test_new_settings_show_defaults_and_hide_the_key(su, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-env-0000000000000000wxyz")  # leak-guard:allow — 가짜 키
    views = _views(su)
    assert views["LLM_ANTHROPIC_MODEL"]["default"] == llm_scoring_anthropic.PLATFORM_DEFAULT_MODEL
    key = views["ANTHROPIC_API_KEY"]
    assert (key["kind"], key["value"], key["last4"], key["choices"]) == ("secret", None, "wxyz", None)
    assert SPECS["LLM_SCORING_VENDOR"].default == "openai"


# --- 저장 규칙 -----------------------------------------------------------------


def test_anthropic_can_be_saved_whatever_the_policy_date(save, settings, su):
    """대표 결정(2026-11-20): 방침 시행일과 상관없이 anthropic 을 저장한다 — 위험은 대표가 진다."""

    for when in (None, NOT_YET):
        settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = when
        assert save("LLM_SCORING_VENDOR", "anthropic").status_code == 200
        assert _views(su)["LLM_SCORING_VENDOR"]["value"] == "anthropic"


def test_values_outside_the_choices_are_refused_without_echo(save):
    response = save("LLM_SCORING_VENDOR", "gemini-x")
    assert (response.status_code, response.json()["code"]) == (422, "invalid_value")
    assert "gemini-x" not in response.content.decode()
    assert RuntimeSetting.objects.count() == 0


def test_openai_can_always_be_saved_and_is_normalized(save, su):
    assert save("LLM_SCORING_VENDOR", " OpenAI ").status_code == 200
    assert _views(su)["LLM_SCORING_VENDOR"]["value"] == "openai"


# --- get_adapter 가 벤더를 따른다 ------------------------------------------------


def test_anthropic_vendor_builds_the_claude_adapter_with_the_same_timeout_contract(save, settings):
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = OPEN
    settings.LLM_ADAPTER_MODE = REAL_OPENAI
    for key, value in (
        ("LLM_SCORING_VENDOR", "anthropic"),
        ("ANTHROPIC_API_KEY", ANT_KEY),
        ("LLM_ANTHROPIC_MODEL", "claude-haiku-5-5"),
    ):
        assert save(key, value).status_code == 200

    adapter = get_adapter(timeout=60)
    assert type(adapter) is AnthropicScoringAdapter
    assert (adapter._api_key, adapter._model, adapter._timeout) == (ANT_KEY, "claude-haiku-5-5", 60)
    assert (adapter._reasoning_effort, adapter._product) == ("low", "contest")
    assert get_adapter()._timeout == 20

    assert save("LLM_SCORING_VENDOR", "openai").status_code == 200
    assert type(get_adapter()) is OpenAIScoringAdapter


def test_model_falls_back_to_the_default(save, settings):
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = OPEN
    settings.LLM_ADAPTER_MODE = REAL_OPENAI
    save("LLM_SCORING_VENDOR", "anthropic")
    save("ANTHROPIC_API_KEY", ANT_KEY)
    assert get_adapter()._model == "claude-sonnet-5-5"


def test_missing_anthropic_key_fails_like_a_missing_openai_key(save, settings):
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = OPEN
    settings.LLM_ADAPTER_MODE = REAL_OPENAI
    save("LLM_SCORING_VENDOR", "anthropic")
    with pytest.raises(LLMAdapterError, match="ANTHROPIC_API_KEY"):
        get_adapter(timeout=60)


def test_env_vendor_sends_to_anthropic_whatever_the_policy_date(settings, monkeypatch):
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = None
    settings.LLM_ADAPTER_MODE = REAL_OPENAI
    monkeypatch.setenv("LLM_SCORING_VENDOR", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANT_KEY)
    assert type(get_adapter()).__name__ == "AnthropicScoringAdapter"


def test_fake_mode_stays_fake_whatever_the_vendor(settings, monkeypatch):
    settings.PRIVACY_POLICY_PLATFORM_ANTHROPIC_DATE = OPEN
    monkeypatch.setenv("LLM_SCORING_VENDOR", "anthropic")
    assert type(get_adapter()) is FakeLLMScoringAdapter


# --- 연결 시험 -----------------------------------------------------------------


def test_anthropic_key_probe_on_fake_adapter(su):
    def probe(value):
        return su.post(f"{URL}/ANTHROPIC_API_KEY/test", data={"value": value}, content_type="application/json", HTTP_ORIGIN=ORIGIN)

    assert probe(ANT_KEY).json() == {"result": "ok"}
    assert probe("sk-wrong-shape-000000000000").json() == {"result": "invalid_key"}
    assert RuntimeSetting.objects.count() == 0


def test_anthropic_key_probe_on_real_adapter_reports_rejection(su, settings, monkeypatch):
    settings.LLM_ADAPTER_MODE = REAL_OPENAI
    seen = {}

    class _Rejected:
        status_code = 401
        text = '{"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}'

        def json(self):
            return {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}}

    def fake_get(url, headers=None, **kwargs):
        seen["key"] = (headers or {}).get("x-api-key")
        seen["url"] = url
        return _Rejected()

    monkeypatch.setattr("core.llm_scoring_anthropic.requests.get", fake_get)
    response = su.post(
        f"{URL}/ANTHROPIC_API_KEY/test", data={"value": ANT_KEY}, content_type="application/json", HTTP_ORIGIN=ORIGIN
    )
    assert response.json() == {"result": "invalid_key"}
    assert seen == {"key": ANT_KEY, "url": "https://api.anthropic.com/v1/models"}
