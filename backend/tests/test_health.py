"""헬스 엔드포인트.

이 프로젝트의 유일한 테스트 시임은 HTTP다. 테스트는 마운트된 django-ninja API를
전체 요청 스택(URLconf + 미들웨어 + 라우터)을 통해 호출한다. 라우터를 직접 부르는
방식은 미들웨어를 건너뛰므로 쓰지 않는다 — 이후 인증·CSRF·CSP가 그 층에 얹힌다.
"""

import pytest

from core import heartbeat

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def memory_store():
    store = heartbeat.store()
    store.reachable = True
    for role in heartbeat.ROLES:
        store.expire_now(heartbeat.KEY_PREFIX + role)
    yield store
    store.reachable = True


def test_health_returns_ok(client):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_redis_unreachable_is_503_naming_redis(client, memory_store):
    memory_store.reachable = False

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "failed": ["redis"]}


def test_db_unreachable_is_503_naming_db(client, monkeypatch):
    from django.db import connection

    def boom(*args, **kwargs):
        raise RuntimeError("host=secret.internal password=hunter2")

    monkeypatch.setattr(connection, "cursor", boom)

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "failed": ["db"]}
    assert "secret" not in response.content.decode()


def test_missing_worker_signals_are_503_naming_roles(client, settings, memory_store):
    settings.HEALTH_REQUIRED_WORKERS = ["celery", "grader"]
    heartbeat.beat("celery")

    response = client.get("/api/health")

    assert response.status_code == 503
    assert response.json() == {"status": "error", "failed": ["grader"]}


def test_all_signals_present_is_ok(client, settings):
    settings.HEALTH_REQUIRED_WORKERS = ["celery", "grader"]
    for role in ("celery", "grader"):
        heartbeat.beat(role)

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_signal_expiry_turns_health_503(client, settings, memory_store):
    settings.HEALTH_REQUIRED_WORKERS = ["grader"]
    heartbeat.beat("grader")
    assert client.get("/api/health").status_code == 200

    memory_store.expire_now(heartbeat.KEY_PREFIX + "grader")  # TTL 만료와 같은 상태

    assert client.get("/api/health").status_code == 503


def test_ready_scope_ignores_workers(client, settings):
    settings.HEALTH_REQUIRED_WORKERS = ["celery", "grader"]

    response = client.get("/api/health?scope=ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_scope_still_fails_when_redis_is_down(client, settings, memory_store):
    settings.HEALTH_REQUIRED_WORKERS = ["celery"]
    memory_store.reachable = False

    response = client.get("/api/health?scope=ready")

    assert response.status_code == 503
    assert response.json()["failed"] == ["redis"]


def test_beat_sets_key_with_ttl_and_touches_file(tmp_path, memory_store):
    f = tmp_path / "hb"

    heartbeat.beat("grader", path=f)

    assert f.exists()
    assert 0 < memory_store.ttl(heartbeat.KEY_PREFIX + "grader") <= heartbeat.TTL_SECONDS


def test_started_heartbeat_keeps_refreshing_key(memory_store, monkeypatch, tmp_path, request):
    monkeypatch.setattr(heartbeat, "HEARTBEAT_FILE", tmp_path / "hb")
    monkeypatch.setattr(heartbeat, "_started", {})
    monkeypatch.setattr(heartbeat, "_stops", {})
    key = heartbeat.KEY_PREFIX + "celery"
    # 0.05초마다 깨는 스레드를 남기지 않는다 — 같은 일꾼의 뒤 시험이 time.monotonic 을 갈아 끼우면 그 값을 먹는다(#1083)
    request.addfinalizer(lambda: heartbeat.stop_heartbeat("celery"))

    heartbeat.start_heartbeat("celery", interval=0.05)
    heartbeat.start_heartbeat("celery", interval=0.05)  # 중복 호출은 스레드를 늘리지 않는다
    assert len(heartbeat._started) == 1
    assert memory_store.exists(key)
    memory_store.expire_now(key)
    deadline = heartbeat.time.monotonic() + 2
    while not memory_store.exists(key) and heartbeat.time.monotonic() < deadline:
        heartbeat.time.sleep(0.02)  # wait-ok: 스레드의 다음 박동을 기다리는 폴링(사건 대기)

    assert memory_store.exists(key)
