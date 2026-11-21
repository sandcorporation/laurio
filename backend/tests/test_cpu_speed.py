"""CPU 한도 배율 — 앞서 돈 시험들이 기준보다 얼마나 느렸나 (#1211)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _pytest.junitxml import mangle_test_address

from tests.cpu_speed import (
    MAX_SCALE,
    MIN_SAMPLES,
    REFERENCE,
    RunnerPace,
    junit_key,
    load_reference,
    reference_from_junit,
)


@pytest.mark.parametrize(
    "nodeid",
    [
        "tests/test_x.py::test_a",
        "payouts/tests/test_payouts.py::test_b[AligoSmsAdapter-NOTIFICATION_LMS_ADAPTER]",
        "tests/integration/test_y.py::TestGroup::test_c[a/b::c]",
    ],
)
def test_key_is_what_junit_writes(nodeid):
    names = mangle_test_address(nodeid)
    assert junit_key(nodeid) == ".".join(names[:-1]) + "::" + names[-1]


def _pace(ratio: float, count: int) -> RunnerPace:
    reference = {f"t::{i}": 0.5 for i in range(count)}
    pace = RunnerPace(reference)
    for key in reference:
        pace.record(key, 0.5 * ratio)
    pace.record("not-in-reference::x", 9.0)
    return pace


def test_a_slow_runner_raises_the_scale_by_how_much_slower_the_earlier_tests_ran():
    assert _pace(1.3, MIN_SAMPLES).scale() == pytest.approx(1.3)


def test_the_scale_stays_between_one_and_the_cap():
    assert _pace(0.6, MIN_SAMPLES).scale() == 1.0
    assert _pace(3.0, MIN_SAMPLES).scale() == MAX_SCALE


def test_too_few_earlier_tests_give_no_allowance():
    pace = _pace(1.4, MIN_SAMPLES - 1)
    assert pace.samples == MIN_SAMPLES - 1
    assert pace.scale() == 1.0


def test_reference_is_the_median_over_runs_of_heavy_enough_tests(tmp_path: Path):
    def junit(name: str, rows: dict[str, float]) -> Path:
        cases = "".join(
            f'<testcase classname="tests.test_x" name="{n}"><properties>'
            f'<property name="cpu_seconds" value="{c}"/></properties></testcase>'
            for n, c in rows.items()
        )
        path = tmp_path / name
        path.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>")
        return path

    paths = [
        junit("1.xml", {"heavy": 0.9, "light": 0.05, "rare": 1.0}),
        junit("2.xml", {"heavy": 1.2, "light": 0.05, "rare": 1.0}),
        junit("3.xml", {"heavy": 1.0, "light": 0.06}),
    ]
    assert reference_from_junit(paths) == {"tests.test_x::heavy": 1.0}


def test_the_committed_reference_names_test_files_that_exist():
    """기준이 비거나 열쇠 모양이 junit 과 어긋나면 배율은 늘 1.0 이 된다 — 그것을 막는다."""
    reference = load_reference(REFERENCE)
    assert len(reference) >= 200
    backend = REFERENCE.parent.parent

    def has_file(key: str) -> bool:
        parts = key.split("::", 1)[0].split(".")
        return any((backend / Path(*parts[:n])).with_suffix(".py").exists() for n in range(len(parts), 0, -1))

    found = sum(has_file(k) for k in reference)
    assert found >= 0.9 * len(reference), f"기준 {len(reference)}개 중 파일이 있는 것 {found}개 — 다시 쓴다"
