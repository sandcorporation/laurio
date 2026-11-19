"""#986 보탬 4: 워커 안에서 도는 스캔은 한 번에 하나만 돈다 — 앞 실행이 도는 동안 온 실행은 건너뛴다."""

from __future__ import annotations

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
