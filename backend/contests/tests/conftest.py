"""공모전 시험이 나눠 쓰는 픽스처(#1087) — 목록·검색 시험 세 파일에 같은 몸으로 있던 분류·결과물 종류."""

import pytest

from contests.models import Category, DeliverableType


@pytest.fixture
def games(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def web(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=2_000_000)


@pytest.fixture
def mobile(db):
    return DeliverableType.objects.create(name="모바일 앱", minimum_prize=1_500_000)
