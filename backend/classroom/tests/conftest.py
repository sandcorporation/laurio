"""강의실 시험이 나눠 쓰는 픽스처(#1087) — 여러 시험 파일에 같은 몸으로 있던 것을 모았다."""

import pytest
from django.core.cache import caches

from tests.classroom_scenarios import force_real_scoring_adapter


@pytest.fixture
def reset_rate_limits():
    """요청 한도 카운터를 시험 앞뒤로 비운다 — MCP·연결된 앱 시험은 한 시험에서 여러 번 부른다.
    파일마다 `pytestmark = pytest.mark.usefixtures("reset_rate_limits")` 로 켠다."""

    caches["rate_limits"].clear()
    yield
    caches["rate_limits"].clear()


@pytest.fixture
def real_scoring():
    # 통과를 만들려면 벤더 응답을 흉내 내야 한다 — 기본값(fake) 어댑터는 그 경로를 타지 않는다.
    with force_real_scoring_adapter():
        yield
