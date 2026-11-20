"""무료 공모전 개최 권한 — 운영자가 계정별로 켜고 끈다 (#414, ADR-0023/ADR-0048).

`contests.hosting_permission_services`는 여기서 직접 부르지 않는다 — 테스트의
유일한 시임은 HTTP다(CLAUDE.md). `tests/test_operator_deliverable_types.py`와
같은 등급·이력·Origin 검사 관용구를 따른다.

이 티켓은 권한을 "읽을 수 있는 판정"을 제공하는 데까지다 — 그 권한으로 실제
무료 공모전을 여는 것(#415)은 여기서 확인하지 않는다.
"""

import pytest
from django.core.management import call_command
from django.test import Client

from contests.models import HostingPermission, HostingPermissionChange

ORIGIN = "http://testserver"
PERMISSIONS_URL = "/api/operator/hosting-permissions"
SEARCH_URL = f"{PERMISSIONS_URL}/search"
CHANGES_URL = f"{PERMISSIONS_URL}/changes"
PW = "operator-pw-9942-xkcd-privacy"

pytestmark = pytest.mark.django_db


def _operator_client(username, *, superuser=False):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _set(client, user_id, *, granted, reason="테스트 사유", origin=ORIGIN):
    kwargs = {"content_type": "application/json"}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return client.post(
        f"{PERMISSIONS_URL}/{user_id}",
        data={"granted": granted, "reason": reason},
        **kwargs,
    )


def _developer_login(client, uid, *, email=None, nickname=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email=email)
    if nickname is not None:
        from accounts.models import SocialAccount

        SocialAccount.objects.filter(user=user).update(nickname=nickname)
    return user, response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


# --- 검색 -------------------------------------------------------------------


def test_search_finds_account_by_email_substring():
    user, _ = _developer_login(Client(), "host-search-email", email="unique-search-1@example.com")
    judge = _operator_client("judge-hosting-search-email")

    response = judge.get(SEARCH_URL, {"q": "unique-search-1"}, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    assert any(row["user_id"] == user.id for row in response.json())


def test_search_finds_account_by_nickname_substring():
    user, _ = _developer_login(
        Client(), "host-search-nick", email="host-search-nick@example.com", nickname="검색용별명"
    )
    judge = _operator_client("judge-hosting-search-nick")

    response = judge.get(SEARCH_URL, {"q": "검색용별명"}, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    assert any(row["user_id"] == user.id for row in response.json())


def test_search_with_empty_query_finds_nothing():
    _developer_login(Client(), "host-search-empty", email="host-search-empty@example.com")
    judge = _operator_client("judge-hosting-search-empty")

    response = judge.get(SEARCH_URL, {"q": ""}, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    assert response.json() == []


def test_search_result_reflects_current_grant_state():
    user, _ = _developer_login(Client(), "host-search-state", email="host-search-state@example.com")
    root = _operator_client("root-hosting-search-state", superuser=True)

    before = root.get(SEARCH_URL, {"q": "host-search-state"}, HTTP_ORIGIN=ORIGIN).json()
    assert before[0]["is_granted"] is False

    _set(root, user.id, granted=True)

    after = root.get(SEARCH_URL, {"q": "host-search-state"}, HTTP_ORIGIN=ORIGIN).json()
    assert after[0]["is_granted"] is True


# --- 켜기/끄기: 상위 등급만, 이유가 필요하다 ----------------------------------


def test_superuser_can_grant_and_it_appears_in_granted_list():
    user, _ = _developer_login(Client(), "host-grant-1", email="host-grant-1@example.com")
    root = _operator_client("root-hosting-grant", superuser=True)

    response = _set(root, user.id, granted=True, reason="베타 테스터로 지정")

    assert response.status_code == 200, response.content
    assert response.json()["is_granted"] is True

    listed = root.get(PERMISSIONS_URL, HTTP_ORIGIN=ORIGIN)
    assert listed.status_code == 200
    assert any(row["user_id"] == user.id for row in listed.json())


def test_granting_twice_is_409_not_500():
    user, _ = _developer_login(Client(), "host-grant-dup", email="host-grant-dup@example.com")
    root = _operator_client("root-hosting-grant-dup", superuser=True)
    _set(root, user.id, granted=True)

    response = _set(root, user.id, granted=True)

    assert response.status_code == 409, response.content


def test_superuser_can_revoke_and_it_leaves_the_granted_list():
    user, _ = _developer_login(Client(), "host-revoke-1", email="host-revoke-1@example.com")
    root = _operator_client("root-hosting-revoke", superuser=True)
    _set(root, user.id, granted=True, reason="부여")

    response = _set(root, user.id, granted=False, reason="더 이상 필요 없음")

    assert response.status_code == 200, response.content
    assert response.json()["is_granted"] is False

    listed = root.get(PERMISSIONS_URL, HTTP_ORIGIN=ORIGIN)
    assert not any(row["user_id"] == user.id for row in listed.json())


def test_ordinary_operator_cannot_grant():
    user, _ = _developer_login(Client(), "host-grant-ord", email="host-grant-ord@example.com")
    judge = _operator_client("judge-hosting-grant")

    response = _set(judge, user.id, granted=True)

    assert response.status_code == 403, response.content
    assert not HostingPermission.objects.filter(user=user, is_granted=True).exists()


def test_grant_without_reason_is_rejected():
    user, _ = _developer_login(Client(), "host-grant-noreason", email="host-grant-noreason@example.com")
    root = _operator_client("root-hosting-noreason", superuser=True)

    response = _set(root, user.id, granted=True, reason="")

    assert response.status_code == 422, response.content
    assert not HostingPermission.objects.filter(user=user, is_granted=True).exists()


def test_grant_without_origin_is_403():
    user, _ = _developer_login(Client(), "host-grant-noorigin", email="host-grant-noorigin@example.com")
    root = _operator_client("root-hosting-noorigin", superuser=True)

    response = _set(root, user.id, granted=True, origin=None)

    assert response.status_code == 403, response.content
    assert not HostingPermission.objects.filter(user=user, is_granted=True).exists()


def test_granting_a_missing_account_is_404():
    root = _operator_client("root-hosting-missing", superuser=True)

    response = _set(root, 9_999_999, granted=True)

    assert response.status_code == 404, response.content


def test_non_operator_request_is_rejected():
    user, pair = _developer_login(Client(), "host-not-operator", email="host-not-operator@example.com")
    client = Client()

    response = client.post(
        f"{PERMISSIONS_URL}/{user.id}",
        data={"granted": True, "reason": "시도"},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
        **_auth_header(pair["access"]),
    )

    assert response.status_code in (401, 403), response.content


# --- 이력: append-only, 사유·시각·운영자·부여/회수가 남는다 --------------------


def test_history_records_operator_reason_and_action_for_grant_and_revoke():
    user, _ = _developer_login(Client(), "host-history-1", email="host-history-1@example.com")
    root = _operator_client("root-hosting-history", superuser=True)

    _set(root, user.id, granted=True, reason="첫 지정")
    _set(root, user.id, granted=False, reason="지정 취소")

    response = root.get(CHANGES_URL, HTTP_ORIGIN=ORIGIN)
    assert response.status_code == 200, response.content
    rows = [row for row in response.json() if row["user_id"] == user.id]
    assert len(rows) == 2
    # 최신순 — 회수가 먼저 나온다.
    assert rows[0]["action"] == "revoked"
    assert rows[0]["reason"] == "지정 취소"
    assert rows[0]["operator_username"] == "root-hosting-history"
    assert rows[1]["action"] == "granted"
    assert rows[1]["reason"] == "첫 지정"

    assert HostingPermissionChange.objects.filter(user=user).count() == 2


def test_history_is_visible_to_ordinary_operators():
    user, _ = _developer_login(Client(), "host-history-view", email="host-history-view@example.com")
    root = _operator_client("root-hosting-history-view", superuser=True)
    _set(root, user.id, granted=True, reason="지정")

    judge = _operator_client("judge-hosting-history-view")
    response = judge.get(CHANGES_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    assert any(row["user_id"] == user.id for row in response.json())


def test_history_has_no_update_or_delete_route():
    """append-only — 이력 행을 고치거나 지우는 엔드포인트 자체가 없다.

    직접 지울 방법이 없다는 것을 코드 수준에서 보장하는 것이 이 티켓의 계약이다
    (DeliverableTypeChange·CategoryChange와 같은 append-only 규율, ADR-0023).
    """

    user, _ = _developer_login(Client(), "host-history-immutable", email="host-history-immutable@example.com")
    root = _operator_client("root-hosting-history-immutable", superuser=True)
    _set(root, user.id, granted=True, reason="지정")

    change = HostingPermissionChange.objects.get(user=user)

    delete_response = root.delete(f"{CHANGES_URL}/{change.id}", HTTP_ORIGIN=ORIGIN)
    assert delete_response.status_code == 404

    patch_response = root.patch(
        f"{CHANGES_URL}/{change.id}",
        data={"reason": "고치기 시도"},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert patch_response.status_code == 404
