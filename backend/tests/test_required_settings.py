"""운영 필수 설정 확인(#1124) — `manage.py check_required_settings --service <이름>`.

시임은 명령이다 — 배포 뒤 확인(`scripts/ci/post-deploy-check.sh`)이 서비스 컨테이너마다 이것을 부른다. 출력은 키
이름과 「비어 있음」뿐이어야 한다(값·길이·해시 없음). 운영 설정(DB)이 env 보다 앞서는 키는 그 규칙대로 본다.
"""

from __future__ import annotations

import re
from io import StringIO

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from ops_metrics import required_settings
from policies import runtime_settings

pytestmark = pytest.mark.django_db

REAL_LLM = "scoring.adapters.OpenAIScoringAdapter"
ALIGO = "notifications.adapters_aligo.Aligo{}Adapter"
VALUE = "filled-value-7f3a"  # 출력에 새면 안 되는 값


@pytest.fixture(autouse=True)
def _prod_like(settings, monkeypatch):
    """운영처럼 다 채운 상태 — 시험마다 하나를 비운다."""

    settings.PUBLIC_SUPPORT_EMAIL = "help@example.com"
    settings.ALIGO_API_KEY = VALUE
    settings.ALIGO_USER_ID = VALUE
    settings.ALIGO_SENDER_PHONE_NUMBER = VALUE
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = VALUE
    settings.NOTIFICATION_ALIMTALK_ADAPTER = ALIGO.format("Alimtalk")
    settings.NOTIFICATION_SMS_ADAPTER = ALIGO.format("Sms")
    settings.NOTIFICATION_LMS_ADAPTER = ALIGO.format("Lms")
    settings.LLM_ADAPTER_MODE = REAL_LLM
    monkeypatch.setenv("CONTEST_AI_SCORING", "on")
    monkeypatch.setenv("OPEN_AI_API_KEY", VALUE)
    for key in ("LLM_SCORING_VENDOR", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    runtime_settings.reset_for_tests()
    yield
    runtime_settings.reset_for_tests()


def run(service: str) -> tuple[bool, str]:
    out = StringIO()
    try:
        call_command("check_required_settings", service=service, stdout=out)
    except CommandError as exc:
        assert exc.returncode == 1
        return False, out.getvalue()
    return True, out.getvalue()


@pytest.mark.parametrize("service", ["backend", "celery-worker"])
def test_filled_prod_settings_pass(service):
    ok, out = run(service)
    assert ok, out
    assert out.strip() == f"{service}: 필수 설정 통과"


def test_empty_support_email_names_the_key_in_every_service_that_reads_it(settings):
    settings.PUBLIC_SUPPORT_EMAIL = "  "
    for service in ("backend", "celery-worker"):
        ok, out = run(service)
        assert not ok
        assert out.splitlines() == [f"{service} SUPPORT_EMAIL: 비어 있음"]


def test_output_carries_names_only_never_values(settings, monkeypatch):
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = ""
    settings.ALIGO_USER_ID = ""
    monkeypatch.setenv("OPEN_AI_API_KEY", "")
    ok, out = run("celery-worker")
    assert not ok
    assert VALUE not in out
    assert not re.search(r"\d+자|len|sha|hash", out, re.IGNORECASE)
    assert out.splitlines() == [
        "celery-worker ALIGO_USER_ID: 비어 있음",
        "celery-worker OPS_ALERT_DISCORD_WEBHOOK_URL: 비어 있음",
        "celery-worker OPEN_AI_API_KEY: 비어 있음",
    ]


def test_aligo_keys_are_required_only_when_an_aligo_adapter_is_bound(settings):
    settings.ALIGO_API_KEY = settings.ALIGO_USER_ID = settings.ALIGO_SENDER_PHONE_NUMBER = ""
    ok, out = run("backend")
    assert not ok and out.count("ALIGO_") == 3

    settings.NOTIFICATION_ALIMTALK_ADAPTER = "notifications.adapters.FakeAlimtalkAdapter"
    settings.NOTIFICATION_SMS_ADAPTER = "notifications.adapters.FakeSmsAdapter"
    settings.NOTIFICATION_LMS_ADAPTER = ALIGO.format("Lms")
    assert not run("backend")[0]  # 하나라도 알리고면 필요하다

    settings.NOTIFICATION_LMS_ADAPTER = "notifications.adapters.FakeLmsAdapter"
    assert run("backend")[0]


def test_vendor_key_is_checked_only_where_the_scan_runs(monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", "")
    assert run("backend")[0]
    ok, out = run("celery-worker")
    assert not ok and out.splitlines() == ["celery-worker OPEN_AI_API_KEY: 비어 있음"]


@pytest.mark.parametrize(
    ("switch", "mode"),
    [("off", REAL_LLM), ("", REAL_LLM), ("on", "fake")],
)
def test_vendor_key_is_not_required_when_contest_scoring_does_not_call_a_vendor(settings, monkeypatch, switch, mode):
    monkeypatch.setenv("OPEN_AI_API_KEY", "")
    monkeypatch.setenv("CONTEST_AI_SCORING", switch)
    settings.LLM_ADAPTER_MODE = mode
    assert run("celery-worker")[0]


def test_anthropic_vendor_requires_the_anthropic_key_not_the_openai_key(monkeypatch):
    monkeypatch.setenv("LLM_SCORING_VENDOR", "anthropic")
    monkeypatch.setenv("OPEN_AI_API_KEY", "")
    ok, out = run("celery-worker")
    assert not ok and out.splitlines() == ["celery-worker ANTHROPIC_API_KEY: 비어 있음"]

    monkeypatch.setenv("ANTHROPIC_API_KEY", VALUE)
    assert run("celery-worker")[0]


def test_runtime_setting_in_db_wins_over_empty_env(monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", "")
    call_command("create_operator", "required_settings_su", password="required-pw-1124-zzzz", superuser=True)
    operator = get_user_model().objects.get(username="required_settings_su")
    runtime_settings.save_setting(  # leak-guard:allow — 가짜 키
        "OPEN_AI_API_KEY", "sk-db-key-1124-000000000000", operator=operator,
    )
    runtime_settings.reset_for_tests()
    assert run("celery-worker")[0]


def test_unknown_service_is_refused():
    with pytest.raises(CommandError, match="표에 없는 서비스"):
        call_command("check_required_settings", service="frontend", stdout=StringIO())


def test_services_listing_matches_the_check_script():
    out = StringIO()
    call_command("check_required_settings", services=True, stdout=out)
    assert out.getvalue().split() == required_settings.services() == ["backend", "celery-worker"]

    script = (settings.BASE_DIR.parent / "scripts" / "ci" / "post-deploy-check.sh").read_text(encoding="utf-8")
    listed = re.search(r'^REQUIRED_SETTINGS_SERVICES="([^"]*)"', script, re.MULTILINE)
    assert listed is not None
    assert listed.group(1).split() == required_settings.services()
