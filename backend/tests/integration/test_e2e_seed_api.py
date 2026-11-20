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

    with override_settings(IS_DEPLOYED_ENVIRONMENT=True, CODEMIT_DEPLOYMENT_TARGET="production"):
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


@pytest.mark.django_db
def test_the_junk_prune_is_reachable_by_the_name_global_setup_uses(client):
    """`prune-junk` 가 이 이름으로 실제로 닿는다 (#183).

    `global-setup.ts` 가 이 키로 부른다. 등록부 키와 호출부 문자열이 어긋나거나 관리 명령이
    이름을 바꾸면 **백엔드 테스트는 전부 통과하고** 증상은 스위트 전체가 `globalSetup` 에서
    404 로 죽는 모양으로만 나타난다 — 그 실패는 「청소가 없다」가 아니라 「e2e 가 통째로
    깨졌다」로 보인다. 응답의 네 키까지 고정하는 것은 호출부가 그 모양을 읽기 때문이다.
    """

    resp = _post(client, "prune-junk")

    assert resp.status_code == 200, resp.content
    assert set(resp.json()) == {
        "categories_deleted",
        "deliverable_types_deleted",
        "skipped",
        "policy_reset",
    }


def test_two_callers_seeding_at_once_both_succeed(transactional_db):
    """**시드는 동시에 불려도 죽지 않는다**(2026-09-18, CI #242).

    Playwright 는 이 시드를 스펙 파일마다 `beforeAll` 에서 부르고
    `fullyParallel` 로 워커 여럿을 쓴다 — 스위트 시작 직후 여러 워커가 동시에
    첫 시드를 치는 창이 열린다. 그런데 `seed_e2e_contests` 는 「기존 e2e
    데이터를 지우고 다시 만든다」 구조라 순차로만 멱등했다: 둘이 같이 지우고
    같이 넣으면 한쪽이 유일 제약에 걸려 죽는다(`auth_user_username_key`,
    `Key (username)=(e2e-seed-sponsor)`).

    실측으로 동시 2번이면 3/3 로 한쪽이 500 이었다. CI #242 의 `frontend-e2e-
    public` 이 그렇게 빨갛게 났고, 그때 남은 오류는 `seed-http.ts` 의 400자
    자르기에 잘려 원인 줄이 유실됐다.

    **스레드로 치는 이유**: Django 는 연결을 스레드마다 연다 — 같은 스레드에서
    두 번 부르면 순차 호출이라 이 경쟁이 재현되지 않는다.
    """

    import threading

    from django.db import connections
    from django.test import Client

    results: list[int] = []
    lock = threading.Lock()

    def seed_once() -> None:
        try:
            response = _post(Client(), "contests")
            with lock:
                results.append(response.status_code)
        finally:
            # 스레드가 연 연결은 스레드가 닫는다 — 안 닫으면 테스트 DB 정리가
            # 「누가 접속 중이다」로 막힌다.
            connections.close_all()

    threads = [threading.Thread(target=seed_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert results == [200, 200], f"동시 시드가 죽었다: {results}"


@pytest.mark.django_db
def test_importable_contest_seed_is_listed_by_the_classroom_catalog(client):
    """강의실 가져오기 e2e(#876)가 심는 공모전이 실제로 「들여올 수 있는」 목록에 든다."""
    from core.contest_catalog import contest_catalog

    response = _post(client, "importable-contest", {"run_id": "t876"})
    assert response.status_code == 200, response.content
    seeded = response.json()
    assert seeded["contest_id"] in {c.contest_id for c in contest_catalog().list_importable()}
