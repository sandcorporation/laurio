"""아래 앱이 위 앱을 import 하지 않고 부르는 자리가 실제로 올라 있고, 앱 사이 순환이 없다 — #1086.

`core.ops_ports` 의 셋과, 탈퇴·휴면 때 연결된 앱 허락을 끊는 시그널 연결(`accounts.apps`)이 Django 가 뜬 뒤에
제자리에 있어야 한다. 비면 운영 지표가 빠지거나 스캔이 정책 스코프 없이 돌거나 허락이 남는다.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from accounts.signals import user_became_dormant, user_withdrawn
from core.connected_app_signals import revoke_on_dormancy, revoke_on_withdrawal
from core.ops_ports import OPS_RECORDER, REQUEST_RECORDER, SCAN_SCOPE
from ops_metrics import recorder, request_buffer
from policies.scope import policy_scope


def test_the_upper_apps_fill_the_shared_layer_slots():
    assert OPS_RECORDER.get() is recorder
    assert REQUEST_RECORDER.get() is request_buffer
    assert SCAN_SCOPE.get() is policy_scope


def _receivers(signal) -> list:
    return [entry[1]() for entry in signal.receivers]


def test_withdrawal_and_dormancy_still_revoke_connected_apps():
    assert revoke_on_withdrawal in _receivers(user_withdrawn)
    assert revoke_on_dormancy in _receivers(user_became_dormant)


def _cycles_script():
    path = Path(__file__).resolve().parents[2] / "scripts" / "app_import_cycles.py"
    spec = importlib.util.spec_from_file_location("app_import_cycles", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def tangled_graph():
    """저장소 전체를 AST 로 읽는 일은 픽스처에서 한 번 — 시험 본문의 CPU 한도 밖이다(#1086, 본문에서 2.03초)."""

    cycles = _cycles_script()
    deps, sites = cycles.graph(everything=True)
    return [comp for comp in cycles.strongly_connected(deps) if len(comp) > 1], sites


def test_no_app_is_in_a_cycle_even_counting_function_imports_and_model_strings(tangled_graph):
    tangled, sites = tangled_graph
    assert tangled == [], [
        f"{src} → {dst}: {where}" for comp in tangled for (src, dst), where in sites.items() if {src, dst} <= set(comp)
    ]


def test_the_contest_family_slots_are_filled_by_the_apps_above():
    from awards.ports import OPEN_HANDOVER
    from contests import ports

    for slot in (
        ports.SIZE_HELD_FILTER,
        ports.POINTS_BY_REQUIREMENT,
        ports.AWARD_SUBMISSION,
        ports.SPONSORED_CONTEST_QUERYSET,
        ports.PAYOUT_ACTION,
        OPEN_HANDOVER,
    ):
        assert callable(slot.get()), slot.name
