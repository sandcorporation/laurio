"""DB 연결 사용률 경고 스캔 (#455, 부모 #453).

CLAUDE.md 「HTTP가 유일한 시임이다」— `POST /api/internal/scans/db-connection-usage`
하나로만 친다. 실제 pg_stat_activity 를 흔들지 않도록 `measure_connection_usage`를
몽키패치한다(`contests/search.py`의 `FakeContestSearchAdapter.search`를 몽키패치해
장애를 흉내내는 것과 같은 관용구) — 이 스캔 자체는 fake/real 어댑터가 없는, 지금 이
프로세스가 붙은 DB 에 대한 순수 관측이다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from core import db_connection_scan
from core.db_connection_scan import ConnectionUsage, DbConnectionUsageHigh

SCAN_URL = "/api/internal/scans/db-connection-usage"


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _mock_usage(monkeypatch, current: int, limit: int = 100) -> None:
    monkeypatch.setattr(
        db_connection_scan, "measure_connection_usage", lambda: ConnectionUsage(current, limit)
    )


def _captured(monkeypatch) -> list[BaseException]:
    captured: list[BaseException] = []
    monkeypatch.setattr(
        "core.observability.capture_handled_exception",
        lambda exc, **tags: captured.append(exc),
    )
    return captured


@pytest.mark.django_db
def test_scan_rejects_without_the_internal_token(client):
    response = client.post(SCAN_URL, content_type="application/json")

    assert response.status_code == 401


@pytest.mark.django_db
def test_below_threshold_sends_nothing(client, monkeypatch):
    _mock_usage(monkeypatch, current=79, limit=100)
    captured = _captured(monkeypatch)

    response = client.post(SCAN_URL, **_internal_headers())

    assert response.status_code == 200
    assert response.json()["count"] == 0
    assert captured == []


@pytest.mark.django_db
def test_at_or_above_threshold_sends_once(client, monkeypatch):
    _mock_usage(monkeypatch, current=80, limit=100)
    captured = _captured(monkeypatch)

    response = client.post(SCAN_URL, **_internal_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["rows"] == [{"current": 80, "limit": 100, "ratio": 0.8}]
    assert len(captured) == 1
    assert isinstance(captured[0], DbConnectionUsageHigh)


@pytest.mark.django_db
def test_repeated_breaches_within_the_interval_are_not_resent(client, monkeypatch):
    _mock_usage(monkeypatch, current=95, limit=100)
    captured = _captured(monkeypatch)

    first = client.post(SCAN_URL, **_internal_headers())
    second = client.post(SCAN_URL, **_internal_headers())

    assert first.json()["count"] == 1
    assert second.json()["count"] == 0
    assert len(captured) == 1


@pytest.mark.django_db
def test_it_sends_again_once_the_interval_has_passed(client, monkeypatch):
    from core.models import DbConnectionAlertState

    _mock_usage(monkeypatch, current=95, limit=100)
    captured = _captured(monkeypatch)

    first = client.post(SCAN_URL, **_internal_headers())
    assert first.json()["count"] == 1

    interval = timedelta(seconds=settings.DB_CONNECTION_ALERT_INTERVAL_SECONDS)
    DbConnectionAlertState.objects.filter(pk=1).update(
        last_alerted_at=timezone.now() - interval - timedelta(seconds=1)
    )

    second = client.post(SCAN_URL, **_internal_headers())

    assert second.json()["count"] == 1
    assert len(captured) == 2


@pytest.mark.django_db
def test_threshold_is_configurable_via_settings(client, monkeypatch, settings):
    settings.DB_CONNECTION_ALERT_THRESHOLD = 0.5
    _mock_usage(monkeypatch, current=51, limit=100)
    captured = _captured(monkeypatch)

    response = client.post(SCAN_URL, **_internal_headers())

    assert response.json()["count"] == 1
    assert len(captured) == 1


@pytest.mark.django_db
def test_interval_is_configurable_via_settings(client, monkeypatch, settings):
    settings.DB_CONNECTION_ALERT_INTERVAL_SECONDS = 0
    _mock_usage(monkeypatch, current=95, limit=100)
    captured = _captured(monkeypatch)

    first = client.post(SCAN_URL, **_internal_headers())
    second = client.post(SCAN_URL, **_internal_headers())

    assert first.json()["count"] == 1
    assert second.json()["count"] == 1
    assert len(captured) == 2


@pytest.mark.django_db
def test_scan_is_registered_and_reachable_via_tick(client, monkeypatch):
    """등록부에 있어 단건 호출뿐 아니라 `/api/internal/tick`으로도 닿는다(#137/#140).

    임계 아래로 두어 이 스캔의 결과가 `tick`이 도는 다른 스캔들의 count 를
    흔들지 않는다는 것도 함께 확인한다."""

    _mock_usage(monkeypatch, current=1, limit=100)

    response = client.post("/api/internal/tick", **_internal_headers())

    assert response.status_code == 200
    assert "db-connection-usage" in response.json()["scans"]
    assert response.json()["scans"]["db-connection-usage"]["count"] == 0
