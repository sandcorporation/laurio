"""e2e 시드를 서브프로세스가 아니라 HTTP 로 (#156).

시드 한 번이 `uv run python manage.py` 로 Django 를 새로 부팅해 **약 0.9초**를 썼다 —
심는 데이터 양과 무관한 순수 시동 비용이고, e2e 한 번에 백 번 넘게 치른다. 이미 떠 있는
프로세스가 답하면 그 비용이 사라진다.

**이름은 등록부에서만 온다** — `/internal/scans/{name}` 과 같은 규약이다. 관리 명령
이름을 요청에서 그대로 받아 실행하면 그건 원격 명령 실행 표면이지 시드 표면이 아니다.
옵션도 시드마다 허용 목록이 있다.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import override_settings

SEED_URL = "/api/internal/e2e/seed"


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _post(client, name: str, body: dict | None = None, *, token: bool = True):
    return client.post(
        f"{SEED_URL}/{name}",
        data=body or {},
        content_type="application/json",
        **(_internal_headers() if token else {}),
    )


@pytest.mark.django_db
def test_seeding_requires_the_internal_token(client):
    """토큰 없이는 심을 수 없다 — 이 표면은 실제 Contest·계정을 만든다."""

    resp = _post(client, "contests", token=False)
    assert resp.status_code in (401, 403), resp.content


@pytest.mark.django_db
def test_unknown_seed_name_is_404_not_a_command_runner(client):
    """등록부에 없는 이름은 404 다 (#156).

    이름을 그대로 관리 명령으로 넘기면 내부 토큰 하나로 아무 명령이나 돌릴 수 있는
    표면이 된다 — `/internal/scans/{name}` 이 등록부에서만 이름을 받는 것과 같은 이유다.
    """

    resp = _post(client, "createsuperuser")
    assert resp.status_code == 404, resp.content


@pytest.mark.django_db
def test_unknown_option_is_rejected_rather_than_forwarded(client):
    """시드마다 옵션 허용 목록이 있다 — 목록에 없는 이름은 명령으로 넘어가기 전에 막힌다.

    명령의 인자 표면이 나중에 늘어났을 때 그 새 인자가 자동으로 HTTP 로도 열리는 것을
    막는다. 열려 있는 것(`username`·`password`·`superuser`)은 e2e 가 실제로 쓴다.
    """

    resp = _post(client, "operator", {"bulk": 5})
    assert resp.status_code == 422, resp.content
    assert "bulk" in resp.json()["detail"]


@pytest.mark.django_db
def test_deployed_environment_refuses_to_seed(client):
    """배포 환경에서는 심지 않는다 (#156).

    관리 명령 중 둘은 스스로 거부하지만 `seed_e2e_contests` 는 그 가드가 없다 —
    HTTP 로 열면서 그 구멍이 표면이 되므로 입구에서도 막는다.
    """

    with override_settings(IS_DEPLOYED_ENVIRONMENT=True, LAURIO_DEPLOYMENT_TARGET="staging"):
        resp = _post(client, "contests")
    assert resp.status_code == 403, resp.content


@pytest.mark.django_db
def test_seeding_an_operator_returns_what_the_command_returns(client):
    """명령이 내던 JSON 을 그대로 돌려준다 — 호출부(e2e 헬퍼)가 읽는 모양이 같아야 한다."""

    resp = _post(client, "operator", {"username": "e2e-op-http-1"})

    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["username"] == "e2e-op-http-1"
    # 비밀번호는 돌려주지 않는다 — 호출부가 고정 상수로 안다(seed-operator.ts).
    assert set(body) == {"id", "username", "is_superuser"}


@pytest.mark.django_db
def test_operator_queue_seed_honours_the_run_id_from_the_request(client):
    """run id 를 본문으로 받는다 (#156).

    명령은 그 값을 프로세스 환경변수에서 읽었다 — 서브프로세스를 띄우던 시절의 규약이다.
    HTTP 로 부르면 부르는 쪽의 환경변수가 백엔드 프로세스에 있을 리 없으므로, 그 값이
    요청에 실려야 한다. 이 값이 무시되면 「이번 실행이 심은 것」과 「이전 실행이 남긴 것」을
    가르는 유일한 기준이 사라진다.
    """

    from contests.models import Contest

    resp = _post(client, "operator-queues", {"only": "identity", "run_id": "runhttp1"})

    assert resp.status_code == 200, resp.content
    assert Contest.objects.filter(title__contains="[runhttp1]").exists(), (
        "요청으로 준 run id 가 심은 Contest 의 접두어에 반영되지 않았다"
    )


@pytest.mark.django_db
def test_operator_queue_seed_requires_a_run_id(client):
    """`run_id` 를 안 주면 심지 않는다 (#156, 코드리뷰).

    명령은 환경변수도 없으면 프로세스 수명 내내 고정된 폴백 토큰을 쓴다 — 호출마다 새로
    뜨던 서브프로세스에서는 그것이 곧 「이번 호출」이었지만, 긴 수명의 서버에서는 그 판정이
    **서버 부팅 시점**을 기준으로 서고, 그 시드가 다른 경로로 방금 심은 Contest 를 남의
    것으로 보고 지운다. 기본값이 없는 편이 낫다.
    """

    resp = _post(client, "operator-queues", {"only": "identity"})

    assert resp.status_code == 422, resp.content
    assert "run_id" in resp.json()["detail"]


@pytest.mark.django_db
def test_reseeding_an_operator_does_not_log_out_live_sessions(client):
    """같은 계정을 다시 심어도 이미 로그인한 세션이 죽지 않는다 (#157).

    이 명령은 「멱등하다」고 적혀 있지만 실제로는 매번 `set_password` 를 다시 불렀고,
    Django 는 비밀번호가 바뀌면 세션 인증 해시로 그 계정의 **살아 있는 세션을 전부**
    무효화한다. 직렬 실행에서는 프로세스당 한 번만 심어 드러나지 않았는데, e2e 를
    워커 여럿으로 돌리면 옆 워커가 같은 공용 계정을 심는 순간 이쪽 세션이 죽는다 —
    화면은 그저 로그인으로 튕기고, 원인은 이 명령이다.
    """

    from django.test import Client

    username = "e2e-op-reseed-1"
    password = "e2e-operator-pw-9134-xyz"
    assert _post(client, "operator", {"username": username, "password": password}).status_code == 200

    logged_in = Client()
    login = logged_in.post(
        "/api/operator/login",
        data={"username": username, "password": password},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert login.status_code == 200, login.content

    # 옆 워커가 같은 계정을 다시 심는다.
    assert _post(client, "operator", {"username": username, "password": password}).status_code == 200

    still_alive = logged_in.get("/api/operator/me")
    assert still_alive.status_code == 200, (
        "다시 심었더니 이미 로그인한 세션이 죽었다 — 비밀번호를 바꿀 이유가 없는데 바꿨다"
    )
