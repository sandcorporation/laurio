"""Django admin.

운영자는 이의제기 심판·정산 감사·부정행위 조사를 admin에서 처리한다(ADR-0002).
그 화면이 실제로 뜨고 로그인이 걸려 있는지를 HTTP로 확인한다.
"""

import pytest
from django.contrib.auth import get_user_model


@pytest.mark.django_db
def test_admin_requires_login(client):
    response = client.get("/admin/")

    assert response.status_code == 302
    assert "/admin/login/" in response["Location"]


@pytest.mark.django_db
def test_operator_can_log_in_to_admin(client):
    get_user_model().objects.create_superuser(
        username="operator", email="operator@example.com", password="operator-pw-1234"
    )

    logged_in = client.login(username="operator", password="operator-pw-1234")
    assert logged_in

    response = client.get("/admin/")
    assert response.status_code == 200
