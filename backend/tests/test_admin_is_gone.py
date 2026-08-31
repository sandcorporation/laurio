"""Django admin 은 더 이상 존재하지 않는다 (#46, ADR-0019).

이 파일은 `test_admin.py`·`test_core_admin.py` 를 대체한다. 그 둘이 지키던 것은
"admin 이 뜬다"와 "배포 환경에서는 admin 으로 ClockOverride 를 못 건드린다"였다.
지킬 대상이 사라졌으므로 지키는 방식도 바뀐다 — 이제 확인할 것은 **도달 자체가
불가능하다**는 것이다.

**왜 없앴나.** admin 은 모델 행을 직접 편집할 수 있다. Appeal 과 AppealRuling 을
admin 에서 고칠 수 있는 한, #44 가 세운 감사 추적에는 우회로가 열린 채로 남는다 —
감사 추적을 만드는 작업이 스스로 그 문을 열어두는 꼴이다.

**요청해서 확인한다.** URL 설정을 읽어서 "없다"고 단언하지 않는다. 이 저장소는
`.dockerignore` 에서 「파일에 적혀 있다」를 증명으로 착각해 두 번 데었다.
"""

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from django.test import override_settings


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/admin/",
        "/admin/login/",
        "/admin/appeals/appeal/",
        "/admin/core/clockoverride/1/change/",
        "/admin/ledger/journalentry/",
    ],
)
def test_no_admin_path_responds(client, path):
    response = client.get(path)

    assert response.status_code == 404, f"{path} 가 아직 살아 있다: {response.status_code}"


@pytest.mark.django_db
def test_even_a_superuser_finds_nothing_there(client):
    """계정 등급으로 열리는 문이 아니다 — 아예 없다."""

    get_user_model().objects.create_superuser(
        username="root", email="root@example.invalid", password="operator-pw-9134-xyz"
    )
    assert client.login(username="root", password="operator-pw-9134-xyz")

    assert client.get("/admin/").status_code == 404


def test_the_admin_app_is_not_installed():
    assert not apps.is_installed("django.contrib.admin")


@pytest.mark.django_db
@override_settings(DEBUG=False)
def test_clock_override_has_no_screen_that_could_fill_it_in_production(client):
    """`ClockOverride` 가드가 지키던 위험이 사라졌다.

    이 행이 채워지면 `Clock.now()` 가 그 값에 멈추고 틱 전이·야간 판단·연기 큐가
    전부 멎는다. 예전에는 admin 이 그것을 채울 수 있어서 배포 환경에서 admin 편집을
    막는 가드가 필요했다. 이제 그 모델을 채울 화면이 아예 없다 — 남은 쓰기 경로는
    테스트가 부르는 `core.clock` 의 헬퍼뿐이다.
    """

    get_user_model().objects.create_superuser(
        username="root2", email="root2@example.invalid", password="operator-pw-9134-xyz"
    )
    assert client.login(username="root2", password="operator-pw-9134-xyz")

    assert client.get("/admin/core/clockoverride/1/change/").status_code == 404
    assert client.post("/admin/core/clockoverride/add/", data={}).status_code == 404


def test_no_app_registers_an_admin_module():
    """admin.py 가 하나라도 남으면 다음에 누군가 되살릴 때 아무도 못 알아챈다."""

    import pathlib

    backend = pathlib.Path(__file__).resolve().parent.parent
    leftovers = sorted(str(p.relative_to(backend)) for p in backend.glob("*/admin.py"))

    assert leftovers == [], f"admin 모듈이 남아 있다: {leftovers}"
