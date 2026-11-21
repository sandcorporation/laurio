"""시험 CPU 한도의 실행기 배율 (#1163, `tests/cpu_speed.py`)."""

import pytest

from tests import cpu_speed


@pytest.mark.parametrize(
    ("ratio", "scale"),
    [
        (0.3, 1.0),  # 빠른 실행기(개발 머신) — 한도를 조이지 않는다
        (1.0, 1.0),
        (1.3, 1.3),  # 느린 무리 — 그만큼 늘려 준다
        (3.0, 1.5),  # 기준이 틀렸거나 튄 측정 — 1.5배까지만
    ],
)
def test_scale_follows_runner_slowness_within_bounds(ratio, scale):
    assert cpu_speed.scale_for(cpu_speed.REFERENCE_SECONDS * ratio) == pytest.approx(scale)


def test_measured_scale_stays_within_bounds():
    assert cpu_speed.MIN_SCALE <= cpu_speed.measured_scale() <= cpu_speed.MAX_SCALE
