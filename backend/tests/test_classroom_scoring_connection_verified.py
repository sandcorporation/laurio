"""채점 연결의 확인 시각(#671, CONTEXT.md 「채점 연결」) — 연결이 마지막으로 실제로 닿은 때.

채워지는 때: 키 저장 때 벤더가 키를 받았을 때, 호환 서버를 저장할 때(저장 전 확인이 닿는다),
호환 서버 모델 선택의 시험 호출이 통과했을 때(#602), 실제 채점이 성공했을 때. 비워지는 때: 연결이
바뀌었는데 확인되지 않았을 때(벤더에 닿지 못한 키 저장)와 소유권 이전(#563). 준비와 확인은 마운트된
HTTP API 로 하고, 시각은 주입 가능한 시계(`core.clock.Clock`)로 옮긴다.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
import requests

from core.models import ClockOverride
from tests.classroom_scenarios import (
    FakeCompatibleServer,
    add_co_instructor,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    patch_class,
    raise_models_endpoint_network_error,
    respond_with_verdict,
    run_scan,
    set_compatible_server,
    set_key,
    submit_repository,
    transfer_ownership,
)

T0 = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
T1 = T0 + timedelta(days=3)
SERVER_URL = "https://verify.example.com/v1"


def _set_clock(at: datetime) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _verified_at(client, access: str, class_id: int) -> datetime | None:
    value = get_class(client, access, class_id)["scoring_connection_verified_at"]
    return None if value is None else datetime.fromisoformat(value.replace("Z", "+00:00"))


def test_a_class_without_a_connection_has_no_verified_time(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], with_key=False)

    assert _verified_at(client, owner["access"], class_id) is None


def test_a_key_the_vendor_accepts_is_verified_at_the_save(client, db):
    _set_clock(T0)
    owner = login(client, "owner")

    class_id = create_class(client, owner["access"])

    assert _verified_at(client, owner["access"], class_id) == T0


def test_a_key_saved_without_reaching_the_vendor_clears_the_verified_time(client, db, monkeypatch):
    _set_clock(T0)
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    with force_real_scoring_adapter():
        raise_models_endpoint_network_error(monkeypatch, requests.ConnectionError("network unreachable"))
        set_key(client, owner["access"], class_id, "sk-another-key-9999")

    assert _verified_at(client, owner["access"], class_id) is None


def test_a_compatible_server_is_verified_at_the_save_and_again_by_a_model_probe(client, db, monkeypatch):
    FakeCompatibleServer(model_ids=["coder-7b"]).install(monkeypatch)
    _set_clock(T0)
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], with_key=False)
    with force_real_scoring_adapter():
        set_compatible_server(client, owner["access"], class_id, SERVER_URL)
        assert _verified_at(client, owner["access"], class_id) == T0

        _set_clock(T1)
        patch_class(client, owner["access"], class_id, {"default_model": "coder-7b"})

    assert _verified_at(client, owner["access"], class_id) == T1


def test_a_scored_attempt_verifies_the_connection(client, db, monkeypatch):
    _set_clock(T0)
    owner = login(client, "owner")
    with force_real_scoring_adapter():
        raise_models_endpoint_network_error(monkeypatch, requests.ConnectionError("network unreachable"))
        class_id = create_class(client, owner["access"])
        assert _verified_at(client, owner["access"], class_id) is None
        problem = create_open_problem(client, owner["access"], class_id)
        learner = login(client, "learner")
        join_class(client, learner["access"], class_id, instructor_access=owner["access"])
        submit_repository(client, learner["access"], class_id, problem.id)
        _set_clock(T1)
        respond_with_verdict(monkeypatch, problem.item_id)
        assert run_scan(client)["count"] == 1

    assert _verified_at(client, owner["access"], class_id) == T1


def test_handing_over_ownership_clears_the_verified_time(client, db):
    _set_clock(T0)
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="공동 강사")

    transfer_ownership(client, owner["access"], class_id, co["access"])

    assert _verified_at(client, co["access"], class_id) is None


@pytest.mark.parametrize("reader", ["owner", "co"])
def test_every_instructor_reads_the_verified_time(client, db, reader):
    _set_clock(T0)
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="공동 강사")

    access = owner["access"] if reader == "owner" else co["access"]
    assert _verified_at(client, access, class_id) == T0
