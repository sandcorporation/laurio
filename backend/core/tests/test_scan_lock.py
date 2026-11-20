"""#986 보탬 4: 워커 안에서 도는 스캔은 한 번에 하나만 돈다 — 앞 실행이 도는 동안 온 실행은 건너뛴다."""

from __future__ import annotations

import threading
import time

import pytest

from core import scan_lock, scans
from core.scans import ScanSpec


def _spec(handled: list[int], *, worker_time_limit_seconds: float | None = 30.0) -> ScanSpec:
    return ScanSpec(
        name="lock-probe",
        candidates=lambda as_of, ctx: [1],
        handle_row=lambda row, as_of, ctx: handled.append(row) or {"row": row},
        worker_time_limit_seconds=worker_time_limit_seconds,
    )


@pytest.fixture
def probe(monkeypatch):
    handled: list[int] = []
    monkeypatch.setitem(scans.SCAN_REGISTRY, "lock-probe", _spec(handled))
    return handled


def test_a_run_while_another_holds_the_lock_is_skipped(probe):
    with scan_lock.hold("lock-probe", 30) as acquired:
        assert acquired
        result = scans.run_scan("lock-probe")

    assert result["skipped"] == "running"
    assert result["rows"] == [] and result["failed"] == []
    assert probe == []


@pytest.mark.django_db
def test_the_lock_is_released_after_a_run(probe):
    scans.run_scan("lock-probe")
    scans.run_scan("lock-probe")

    assert probe == [1, 1]


def test_the_lock_is_released_when_a_run_raises(monkeypatch):
    def boom(as_of, ctx):
        raise RuntimeError("후보 쿼리 실패")

    monkeypatch.setitem(
        scans.SCAN_REGISTRY,
        "lock-probe",
        ScanSpec(name="lock-probe", candidates=boom, handle_row=lambda *a: None, worker_time_limit_seconds=30.0),
    )
    with pytest.raises(RuntimeError):
        scans.run_scan("lock-probe")

    with scan_lock.hold("lock-probe", 30) as acquired:
        assert acquired


def test_an_expired_lock_does_not_block_and_is_not_released_by_its_old_holder():
    store = scan_lock.MemoryLockStore()
    with scan_lock.hold("x", 30, client=store) as first:
        assert first
        store._values[f"{scan_lock.KEY_PREFIX}x"] = ("someone-else", float("inf"))  # 만료 뒤 남이 잡았다
    assert store.get(f"{scan_lock.KEY_PREFIX}x") == "someone-else"


@pytest.mark.django_db
def test_http_scans_take_no_lock(monkeypatch):
    handled: list[int] = []
    monkeypatch.setitem(scans.SCAN_REGISTRY, "lock-probe", _spec(handled, worker_time_limit_seconds=None))

    with scan_lock.hold("lock-probe", 30):
        scans.run_scan("lock-probe")

    assert handled == [1]


class _RecordingStore(scan_lock.MemoryLockStore):
    def __init__(self) -> None:
        super().__init__()
        self.ttls: list[int] = []
        self.renewed = threading.Event()

    def set(self, name, value, *, nx, ex):
        self.ttls.append(ex)
        if not nx:
            self.renewed.set()
        return super().set(name, value, nx=nx, ex=ex)


def test_a_long_scan_holds_a_short_lease_and_renews_it_while_alive():
    """#1699 — 상한 840초를 통째로 잡지 않는다. 워커가 죽으면 늘리던 스레드도 죽어 임대(60초) 안에 풀린다."""

    store = _RecordingStore()
    with scan_lock.hold("x", 840, client=store, renew_every=0.01) as acquired:
        assert acquired
        assert store.renewed.wait(5)
    assert set(store.ttls) == {scan_lock.LEASE_SECONDS}
    renewals = len(store.ttls)
    assert store.get(f"{scan_lock.KEY_PREFIX}x") is None
    time.sleep(0.05)
    assert len(store.ttls) == renewals  # 풀고 난 뒤로는 늘리지 않는다


def test_the_renewer_does_not_extend_a_lock_someone_else_now_holds():
    store = _RecordingStore()
    key = f"{scan_lock.KEY_PREFIX}x"
    with scan_lock.hold("x", 840, client=store, renew_every=0.01):
        store.delete(key)
        store.set(key, "other", nx=True, ex=60)
        store.renewed.clear()
        assert not store.renewed.wait(0.1)
    assert store.get(key) == "other"
