"""ClockOverride admin 가드 (코드리뷰 지적 #4).

ClockOverride 는 테스트 전용 시각 조작 스캐폴딩이다. 이걸 프로덕션에서 admin으로
채워버리면 Clock.now() 가 그 순간에 멈춰서, 틱 전이·야간 판단·연기 큐가 전부 멎는다.
DEBUG=False 인 배포 환경에서는 슈퍼유저조차 이 모델을 admin에서 조작할 수 없어야
한다.
"""

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from core.models import ClockOverride

CHANGE_URL = "/admin/core/clockoverride/1/change/"


def _login_superuser(client, username="clock-admin"):
    get_user_model().objects.create_superuser(
        username=username, email=f"{username}@example.com", password="operator-pw-1234"
    )
    assert client.login(username=username, password="operator-pw-1234")


@pytest.mark.django_db
def test_clock_override_admin_is_reachable_by_superuser_in_debug(client):
    # Django의 setup_test_environment()가 테스트 중에는 항상 settings.DEBUG 를
    # False 로 강제한다(운영과 비슷한 조건에서 테스트를 돌리기 위함). 그래서 "DEBUG일
    # 때" 시나리오는 명시적으로 override_settings(DEBUG=True) 로 재현해야 한다.
    ClockOverride.objects.create(pk=1)
    _login_superuser(client)

    with override_settings(DEBUG=True):
        response = client.get(CHANGE_URL)

    assert response.status_code == 200


@pytest.mark.django_db
def test_clock_override_admin_is_blocked_when_debug_is_off(client):
    ClockOverride.objects.create(pk=1)
    _login_superuser(client)

    # override_settings 없이도 pytest-django 테스트 환경은 이미 DEBUG=False 다 —
    # 명시적으로 다시 걸어 이 테스트의 전제를 코드로 드러낸다.
    with override_settings(DEBUG=False):
        response = client.get(CHANGE_URL)

    assert response.status_code == 403
