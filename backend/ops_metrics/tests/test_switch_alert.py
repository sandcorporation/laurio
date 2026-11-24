"""운영 스위치 경보(#1221) — 바뀐 채 오래 남은 스위치를 하루 한 번 알리고, 「이대로 둔다」로 멈춘다.

설정 저장·확인은 마운트된 API(`/api/operator/runtime-settings…`)로, 알림은 일 단위 태스크의 몸통(`check_daily`)으로 친다.
웹훅은 `ops_metrics.alerts.post_webhook` 을 갈아끼운다. 변경 시각은 이력 행을 직접 옮겨 사고 때 순서를 되돌린다."""

from datetime import datetime, timedelta, timezone

import pytest
from django.core.management import call_command
from django.test import Client

from ops_metrics import alerts
from ops_metrics.switch_alert import check_daily
from policies.models import RuntimeSetting, RuntimeSettingChange

pytestmark = pytest.mark.django_db

ORIGIN = "http://testserver"
URL = "/api/operator/runtime-settings"
PW = "operator-pw-switch-1221-zzz"
HOOK = "https://discord.invalid/api/webhooks/switch-test"
SCORING = "CONTEST_AI_SCORING"
REVIEW = "CONTEST_AI_QUALITY_REVIEW"
T0 = datetime(2026, 11, 19, 20, 39, tzinfo=timezone.utc)


def _client(username, *, superuser=True):
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
    return _client("sw_super")


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.delenv(SCORING, raising=False)
    monkeypatch.delenv(REVIEW, raising=False)


@pytest.fixture
def sent(monkeypatch, settings):
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = HOOK
    out: list[str] = []
    monkeypatch.setattr(alerts, "post_webhook", lambda url, content: out.append(content))
    return out


@pytest.fixture
def capture(django_capture_on_commit_callbacks):
    return django_capture_on_commit_callbacks


def _post(client, path, **body):
    return client.post(f"{URL}{path}", data=body, content_type="application/json", HTTP_ORIGIN=ORIGIN)


def _set(client, capture, key, value, at):
    """저장하고 그 변경을 `at` 으로 옮긴다."""

    with capture(execute=True):
        response = _post(client, f"/{key}", value=value)
    assert response.status_code == 200 and response.json()["changed"], response.content
    change = RuntimeSettingChange.objects.exclude(action="ack").filter(key=key).latest("id")
    change.changed_at = at
    change.save(update_fields=["changed_at"])
    RuntimeSetting.objects.filter(key=key).update(updated_at=at)


def _view(client, key):
    response = client.get(URL, HTTP_ORIGIN=ORIGIN)
    return next(s for s in response.json()["settings"] if s["key"] == key)


def test_differs_from_default_alerts_once_per_day_run_after_n_days(su, capture, sent):
    _set(su, capture, SCORING, "on", T0)

    assert check_daily(now=T0 + timedelta(days=1, hours=23)) == []
    assert sent == []

    assert check_daily(now=T0 + timedelta(days=2)) == [SCORING]
    assert len(sent) == 1
    # 키·라벨·지금 값/기본값·언제부터·운영자 계정 id — 이름·이메일·웹훅 주소는 없다.
    text = sent[0]
    assert SCORING in text and "공모전 AI 채점" in text and "on" in text and "기본 off" in text
    assert "2026-11-20 05:39" in text  # 서울 시각
    operator_id = RuntimeSettingChange.objects.get(key=SCORING).operator_id
    assert f"운영자 #{operator_id}" in text
    assert "sw_super" not in text and "discord" not in text

    # 하루 한 번 — 다음 날 실행이 다시 알린다.
    assert check_daily(now=T0 + timedelta(days=3)) == [SCORING]
    assert len(sent) == 2


def test_turned_off_after_on_alerts_though_off_equals_default(su, capture, sent):
    """사고 순서 — on 20:39 → off 20:59 → on 21:27 → off 21:46, N=2 일 뒤."""

    _set(su, capture, REVIEW, "on", T0)
    _set(su, capture, REVIEW, "off", T0 + timedelta(minutes=20))
    _set(su, capture, REVIEW, "on", T0 + timedelta(minutes=48))
    _set(su, capture, REVIEW, "off", T0 + timedelta(hours=1, minutes=7))
    assert _view(su, REVIEW)["value"] == "off"

    assert check_daily(now=T0 + timedelta(days=1, hours=23)) == []
    assert check_daily(now=T0 + timedelta(days=3)) == [REVIEW]
    assert len(sent) == 1 and REVIEW in sent[0] and "on → off" not in sent[0]


def test_first_off_that_was_never_on_is_not_a_target(su, capture, sent):
    _set(su, capture, REVIEW, "off", T0)

    assert check_daily(now=T0 + timedelta(days=30)) == []
    assert sent == []


def test_confirm_silences_until_next_change(su, capture, sent):
    _set(su, capture, SCORING, "on", T0)
    assert _view(su, SCORING)["needs_confirm"] is True

    response = _post(su, f"/{SCORING}/confirm")
    assert response.status_code == 200 and response.json()["changed"] is True
    view = _view(su, SCORING)
    assert view["needs_confirm"] is False
    assert view["confirmed_by"] == "sw_super" and view["confirmed_at"]
    assert view["changed_at"].startswith("2026-11-19")
    ack = RuntimeSettingChange.objects.get(action="ack")
    assert (ack.key, ack.before, ack.after) == (SCORING, "on", "on")

    assert check_daily(now=T0 + timedelta(days=5)) == []
    assert sent == []
    # 이미 확인한 것을 또 확인해도 기록이 늘지 않는다.
    assert _post(su, f"/{SCORING}/confirm").json()["changed"] is False
    assert RuntimeSettingChange.objects.filter(action="ack").count() == 1

    # 다음 변경(off → on 다시)이 오면 확인은 효력을 잃고 다시 대상이 된다.
    _set(su, capture, SCORING, "off", T0 + timedelta(days=6))
    _set(su, capture, SCORING, "on", T0 + timedelta(days=6, hours=1))
    assert _view(su, SCORING)["needs_confirm"] is True
    assert check_daily(now=T0 + timedelta(days=9)) == [SCORING]


def test_confirm_needs_a_target_switch_and_superuser(su, capture, sent):
    assert _post(su, f"/{SCORING}/confirm").json()["changed"] is False  # 대상 아님
    assert _post(su, "/LLM_OPENAI_MODEL/confirm").status_code == 422
    assert _post(su, "/NOPE/confirm").status_code == 404
    plain = _client("sw_plain", superuser=False)
    assert _post(plain, f"/{SCORING}/confirm").status_code in (401, 403)
    assert RuntimeSettingChange.objects.count() == 0


def test_after_days_comes_from_runtime_setting(su, capture, sent):
    _set(su, capture, SCORING, "on", T0)
    _set(su, capture, "SWITCH_ALERT_AFTER_DAYS", "5", T0)

    assert check_daily(now=T0 + timedelta(days=4)) == []
    assert check_daily(now=T0 + timedelta(days=5)) == [SCORING]


def test_blank_webhook_stays_silent_and_failure_does_not_raise(su, capture, monkeypatch, settings):
    _set(su, capture, SCORING, "on", T0)
    now = T0 + timedelta(days=3)
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = ""
    assert check_daily(now=now) == [SCORING]

    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = HOOK

    def boom(url, content):
        raise RuntimeError(url)

    monkeypatch.setattr(alerts, "post_webhook", boom)
    assert check_daily(now=now) == [SCORING]


def test_confirmation_shows_in_change_history(su, capture):
    _set(su, capture, SCORING, "on", T0)
    _post(su, f"/{SCORING}/confirm")
    rows = su.get(f"{URL}/changes", HTTP_ORIGIN=ORIGIN).json()
    assert rows[0]["action"] == "ack" and rows[0]["operator_username"] == "sw_super"


def test_second_destination_gets_the_switch_alert_and_its_failure_is_harmless(su, capture, monkeypatch, settings):
    _set(su, capture, SCORING, "on", T0)
    now = T0 + timedelta(days=3)
    settings.OPS_ALERT_DISCORD_WEBHOOK_URL = HOOK
    settings.OPS_ALERT_NOTICE_WEBHOOK_URL = "https://notice.invalid/hook/x"
    out: dict[str, list[str]] = {}
    monkeypatch.setattr(alerts, "post_webhook", lambda url, content: out.setdefault(url, []).append(content))
    assert check_daily(now=now) == [SCORING]
    assert out[HOOK] == out["https://notice.invalid/hook/x"] and len(out[HOOK]) == 1

    def boom(url, content):
        raise RuntimeError(url)

    monkeypatch.setattr(alerts, "post_webhook", boom)
    assert check_daily(now=now) == [SCORING]
