"""Operator 로그인과 세션 (#43, ADR-0016/0018).

세션은 실제 Redis 에 산다. 세션 레코드를 지우는 것이 곧 즉시 무효화이므로 별도의
토큰 블랙리스트를 두지 않는다 — 돈을 움직이는 권한은 즉시 빼앗을 수 있어야 한다.

`Origin` 검증은 ADR-0016 의 **성립 조건**이다. 쿠키는 브라우저가 자동으로 실어
보내므로, 변경 요청의 Origin 을 검증하지 않으면 이 구조는 토큰을 JS 에 노출하는
것보다 나쁘다. 헤더가 아예 없는 요청도 거부한다(fail-closed).
"""

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import override_settings

OPERATOR_PW = "operator-pw-9134-xyz"
LOGIN_URL = "/api/operator/login"
LOGOUT_URL = "/api/operator/logout"
ME_URL = "/api/operator/me"

# Django 테스트 클라이언트가 보내는 기본 호스트. Origin 검증이 비교하는 값이다.
SAME_ORIGIN = "http://testserver"


def _make_operator(username="alice", *, superuser=False, active=True):
    call_command("create_operator", username, password=OPERATOR_PW, superuser=superuser)
    operator = get_user_model().objects.get(username=username)
    if not active:
        operator.is_active = False
        operator.save(update_fields=["is_active"])
    return operator


def _login(client, username="alice", password=OPERATOR_PW, origin=SAME_ORIGIN):
    headers = {"HTTP_ORIGIN": origin} if origin is not None else {}
    return client.post(
        LOGIN_URL,
        data={"username": username, "password": password},
        content_type="application/json",
        **headers,
    )


@pytest.mark.django_db
def test_operator_logs_in_and_sees_their_own_identity(client):
    _make_operator()

    assert _login(client).status_code == 200

    me = client.get(ME_URL)
    assert me.status_code == 200
    body = me.json()
    assert body["username"] == "alice"
    assert body["is_superuser"] is False
    # 비밀번호와 관련된 어떤 것도 나오면 안 된다.
    assert "password" not in str(body).lower()


@pytest.mark.django_db
def test_the_session_credential_is_not_readable_by_browser_javascript(client):
    _make_operator()
    _login(client)

    cookie = client.cookies[settings.SESSION_COOKIE_NAME]
    assert cookie["httponly"], "세션 쿠키가 HttpOnly 가 아니다"


@pytest.mark.django_db
def test_logging_out_blocks_the_very_next_request(client):
    """만료를 기다리지 않는다 — 그 자리에서 막혀야 한다."""

    _make_operator()
    _login(client)
    assert client.get(ME_URL).status_code == 200

    assert client.post(LOGOUT_URL, HTTP_ORIGIN=SAME_ORIGIN).status_code == 200

    assert client.get(ME_URL).status_code == 401


@pytest.mark.django_db
def test_a_wrong_password_does_not_reveal_whether_the_account_exists(client):
    _make_operator("known")

    missing = _login(client, username="nobody", password="whatever-9134-xyz")
    wrong = _login(client, username="known", password="wrong-9134-xyz")

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json() == wrong.json(), "응답이 계정 존재 여부를 드러낸다"


@pytest.mark.django_db
def test_a_deactivated_operator_cannot_log_in(client):
    _make_operator("gone", active=False)

    assert _login(client, username="gone").status_code == 401


@pytest.mark.django_db
def test_operator_paths_are_closed_by_default(client):
    """라우터 기본값으로 막힌다 — 엔드포인트마다 붙이면 다음에 추가되는 것이 열린 채 태어난다."""

    assert client.get(ME_URL).status_code == 401


@pytest.mark.django_db
def test_being_logged_in_is_not_the_same_as_being_an_operator(client):
    """staff 가 아닌 계정의 세션으로는 운영자 경로에 닿을 수 없다."""

    participant = get_user_model().objects.create_user(username="participant")
    client.force_login(participant)

    assert client.get(ME_URL).status_code == 403


@pytest.mark.django_db
def test_a_mutating_request_from_another_origin_is_rejected(client):
    _make_operator()
    _login(client)

    response = client.post(LOGOUT_URL, HTTP_ORIGIN="https://evil.example")

    assert response.status_code == 403
    # 거부됐으니 세션은 살아 있어야 한다.
    assert client.get(ME_URL).status_code == 200


@pytest.mark.django_db
def test_a_mutating_request_with_no_origin_at_all_is_rejected(client):
    """fail-closed — 최신 브라우저는 상태를 바꾸는 요청에 항상 Origin 을 싣는다."""

    _make_operator()
    _login(client)

    assert client.post(LOGOUT_URL).status_code == 403
    assert client.get(ME_URL).status_code == 200


@pytest.mark.django_db
def test_reading_is_not_subject_to_origin_checks(client):
    """CSRF 는 상태를 바꾸는 요청에만 성립한다."""

    _make_operator()
    _login(client)

    assert client.get(ME_URL, HTTP_ORIGIN="https://evil.example").status_code == 200


@pytest.mark.django_db
def test_the_internal_shared_secret_cannot_reach_operator_paths(client):
    """#24 가 지목한 그 시크릿이 다른 문으로 돌아 들어오면 안 된다."""

    _make_operator()

    response = client.get(ME_URL, HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN)

    assert response.status_code == 401


@pytest.mark.django_db
def test_login_itself_is_a_mutating_request_and_checks_origin(client):
    _make_operator()

    assert _login(client, origin="https://evil.example").status_code == 403
    assert _login(client, origin=None).status_code == 403


@pytest.mark.django_db
def test_the_session_survives_being_read_back_from_redis(client):
    """세션이 프로세스 메모리가 아니라 실제 저장소에 있다는 것을 확인한다.

    새 클라이언트에 같은 쿠키를 실어 보내면 서버가 저장소에서 세션을 다시 읽어
    같은 신원으로 응답해야 한다. locmem 으로 돌면 이 테스트도 통과하므로 이것만으로
    Redis 를 증명하지는 못한다 — 저장소가 무엇인지는 배포 설정 검증이 따로 본다.
    """

    from django.test import Client

    _make_operator()
    _login(client)
    sessionid = client.cookies[settings.SESSION_COOKIE_NAME].value

    other = Client()
    other.cookies[settings.SESSION_COOKIE_NAME] = sessionid

    assert other.get(ME_URL).status_code == 200


@pytest.mark.django_db
def test_deleting_the_session_record_revokes_access_immediately(client):
    """별도 블랙리스트를 두지 않는 근거 — 세션을 지우는 것이 곧 회수다."""

    from django.contrib.sessions.backends.cache import SessionStore

    _make_operator()
    _login(client)
    sessionid = client.cookies[settings.SESSION_COOKIE_NAME].value
    assert client.get(ME_URL).status_code == 200

    SessionStore(session_key=sessionid).delete()

    assert client.get(ME_URL).status_code == 401


@pytest.mark.django_db
@override_settings(SESSION_COOKIE_SECURE=True)
def test_the_session_cookie_is_secure_when_the_deployment_says_so(client):
    _make_operator()
    _login(client)

    assert client.cookies[settings.SESSION_COOKIE_NAME]["secure"]
