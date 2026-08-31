"""Operator 계정 관리 (#45, ADR-0018).

두 등급을 두는 이유는 무게가 다르기 때문이다 — 「돈을 움직일 수 있다」(`is_staff`)와
「돈을 움직일 권한을 나눠줄 수 있다」(`is_superuser`)는 같지 않다. 심판자 계정
하나가 뚫려도 공격자가 Operator 를 무한히 늘리지는 못해야 한다.

비활성화는 세션 회수까지 가야 완결된다. `is_active=False` 만 찍고 세션을 두면 이미
로그인해 있는 사람은 그대로 돈을 움직일 수 있다 — 「즉시 무효화」가 빈말이 된다.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from accounts.models import SocialAccount

ORIGIN = "http://testserver"
OPERATORS_URL = "/api/operator/operators"
ME_URL = "/api/operator/me"
PW = "operator-pw-9134-xyz"


def _client_for(username, *, superuser=False):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    assert (
        client.post(
            "/api/operator/login",
            data={"username": username, "password": PW},
            content_type="application/json",
            HTTP_ORIGIN=ORIGIN,
        ).status_code
        == 200
    )
    return client


def _create(client, username, *, superuser=False, password=PW):
    return client.post(
        OPERATORS_URL,
        data={"username": username, "password": password, "is_superuser": superuser},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )


def _deactivate(client, operator_id):
    return client.post(
        f"{OPERATORS_URL}/{operator_id}/deactivate", HTTP_ORIGIN=ORIGIN
    )


@pytest.mark.django_db
def test_a_superuser_operator_can_create_another_operator():
    root = _client_for("root", superuser=True)

    response = _create(root, "newbie")

    assert response.status_code == 201, response.content
    created = get_user_model().objects.get(username="newbie")
    assert created.is_staff is True
    assert created.is_superuser is False
    assert created.check_password(PW)


@pytest.mark.django_db
def test_an_ordinary_operator_cannot_create_operators():
    """심판자 계정 하나가 뚫려도 Operator 가 무한히 늘어나지는 않는다."""

    judge = _client_for("judge")

    response = _create(judge, "smuggled")

    assert response.status_code == 403, response.content
    assert not get_user_model().objects.filter(username="smuggled").exists()


@pytest.mark.django_db
def test_an_ordinary_operator_cannot_list_or_deactivate():
    root = _client_for("root", superuser=True)
    _create(root, "victim")
    victim_id = get_user_model().objects.get(username="victim").id

    judge = _client_for("judge")

    assert judge.get(OPERATORS_URL).status_code == 403
    assert _deactivate(judge, victim_id).status_code == 403
    assert get_user_model().objects.get(id=victim_id).is_active is True


@pytest.mark.django_db
def test_deactivating_an_operator_ends_their_sessions_immediately():
    """`is_active=False` 만으로는 부족하다 — 이미 로그인한 사람이 그대로 남는다."""

    root = _client_for("root", superuser=True)
    _create(root, "leaving")
    leaving_id = get_user_model().objects.get(username="leaving").id

    leaving = Client()
    assert (
        leaving.post(
            "/api/operator/login",
            data={"username": "leaving", "password": PW},
            content_type="application/json",
            HTTP_ORIGIN=ORIGIN,
        ).status_code
        == 200
    )
    assert leaving.get(ME_URL).status_code == 200

    assert _deactivate(root, leaving_id).status_code == 200

    # 다음 요청부터 막힌다 — 만료를 기다리지 않는다.
    assert leaving.get(ME_URL).status_code == 401
    assert get_user_model().objects.get(id=leaving_id).is_active is False


@pytest.mark.django_db
def test_a_deactivated_operator_cannot_log_back_in():
    root = _client_for("root", superuser=True)
    _create(root, "gone")
    gone_id = get_user_model().objects.get(username="gone").id
    _deactivate(root, gone_id)

    denied = Client().post(
        "/api/operator/login",
        data={"username": "gone", "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )

    assert denied.status_code == 401


@pytest.mark.django_db
def test_the_operator_list_never_exposes_credentials():
    root = _client_for("root", superuser=True)
    _create(root, "listed")

    response = root.get(OPERATORS_URL)

    assert response.status_code == 200
    body = response.json()
    usernames = {row["username"] for row in body}
    assert {"root", "listed"} <= usernames
    assert "password" not in str(body).lower()


@pytest.mark.django_db
def test_the_disjointness_invariant_holds_on_this_path_too(client):
    """부트스트랩 명령과 같은 규칙이 API 경로에서도 성립해야 한다(ADR-0018).

    한쪽만 막으면 다른 쪽으로 돌아 들어온다 — #42 가 명령과 소셜 로그인 양쪽에
    건 것과 같은 이유다.
    """

    assert (
        client.post(
            "/api/auth/social/kakao/login",
            data={"access_token": "participant-1:p@example.com"},
            content_type="application/json",
        ).status_code
        == 200
    )
    participant = SocialAccount.objects.get(provider_uid="participant-1").user

    root = _client_for("root", superuser=True)
    response = _create(root, participant.username)

    assert response.status_code == 422, response.content
    participant.refresh_from_db()
    assert participant.is_staff is False


@pytest.mark.django_db
def test_a_weak_password_is_refused_on_this_path_too():
    root = _client_for("root", superuser=True)

    response = _create(root, "weakling", password="1234")

    assert response.status_code == 422, response.content
    assert not get_user_model().objects.filter(username="weakling").exists()


@pytest.mark.django_db
def test_the_last_superuser_cannot_deactivate_themselves():
    """마지막 superuser 가 사라지면 아무도 Operator 를 만들 수 없는 상태가 된다.

    화면도 없고 계정을 되살릴 API 도 없으므로, 그 상태는 서버에 들어가 관리 명령을
    돌려야만 빠져나올 수 있다. 그 문을 막는다.
    """

    root = _client_for("root", superuser=True)
    root_id = get_user_model().objects.get(username="root").id

    response = _deactivate(root, root_id)

    assert response.status_code == 409, response.content
    assert get_user_model().objects.get(id=root_id).is_active is True
    assert root.get(ME_URL).status_code == 200


@pytest.mark.django_db
def test_a_superuser_can_be_deactivated_while_another_one_remains():
    first = _client_for("root", superuser=True)
    _create(first, "second-root", superuser=True)
    second_id = get_user_model().objects.get(username="second-root").id

    assert _deactivate(first, second_id).status_code == 200
    assert get_user_model().objects.get(id=second_id).is_active is False


@pytest.mark.django_db
def test_operator_management_requires_an_origin_like_every_other_mutation():
    root = _client_for("root", superuser=True)

    response = root.post(
        OPERATORS_URL,
        data={"username": "no-origin", "password": PW, "is_superuser": False},
        content_type="application/json",
    )

    assert response.status_code == 403
    assert not get_user_model().objects.filter(username="no-origin").exists()


@pytest.mark.django_db
def test_an_overlong_username_is_a_client_error_not_a_server_error():
    """4xx 여야 할 자리에서 500 이 나는 것은 이 저장소가 반복해 겪은 결함 모양이다."""

    root = _client_for("root", superuser=True)

    response = _create(root, "x" * 200)

    assert response.status_code == 422, response.content
    assert not get_user_model().objects.filter(username__startswith="x" * 50).exists()


@pytest.mark.django_db
def test_an_empty_username_is_refused():
    root = _client_for("root", superuser=True)

    assert _create(root, "").status_code == 422


@pytest.mark.django_db
def test_creating_the_same_operator_twice_is_a_conflict_not_a_crash():
    """사전 조회는 순차적으로만 막는다 — DB 의 unique 제약이 최후의 방어선이고,
    그것이 500 으로 새어나가면 안 된다."""

    root = _client_for("root", superuser=True)
    assert _create(root, "twice").status_code == 201

    second = _create(root, "twice")

    assert second.status_code in (409, 422), second.content
    assert get_user_model().objects.filter(username="twice").count() == 1


@pytest.mark.django_db
def test_the_list_says_who_is_active():
    """유일한 관리 표면이므로 "지금 누가 활성인가"에 답할 수 있어야 한다."""

    root = _client_for("root", superuser=True)
    _create(root, "retired")
    retired_id = get_user_model().objects.get(username="retired").id
    assert _deactivate(root, retired_id).status_code == 200

    rows = {row["username"]: row for row in root.get(OPERATORS_URL).json()}

    assert rows["root"]["is_active"] is True
    assert rows["retired"]["is_active"] is False
