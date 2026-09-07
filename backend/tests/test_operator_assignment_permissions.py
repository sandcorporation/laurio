"""Assignment 02 — 운영자가 Sponsor에게 과제 개최 자격을 주고 거둔다 (#206, ADR-0028/0029).

`GET /api/operator/assignment-permissions`(자격 보유자 목록, 일반 등급도 가능)·
`POST /api/operator/assignment-permissions/grant`(부여, 상위 등급만)·
`POST /api/operator/assignment-permissions/{id}/revoke`(회수, 상위 등급만)·
`GET /api/operator/assignment-permissions/changes`(이력)를 마운트된 django-ninja
API로 친다(CLAUDE.md — HTTP가 유일한 시임).

선행 사례: `test_operator_deliverable_types.py`(같은 등급 구분·이력·오류 모양),
`test_operator_policy.py`.

과제(Assignment) status 자체는 이 티켓 범위 밖이다(#207) — 여기서 고정하는 것은
자격이라는 상태 하나와 그 변경 이력이지 "이미 열린 과제가 계속 도는가"가 아니다
(그 사실은 Contest.Status에 ASSIGNMENT_OPEN/CLOSED가 생기는 #207에서 코드로
증명된다. #206의 서비스 계층(`accounts.assignment_permission_services.
revoke_assignment_permission`)이 Contest를 전혀 건드리지 않는다는 사실 자체가
그 약속의 근거다).
"""

import pytest
from django.core.management import call_command
from django.test import Client

from accounts.models import AssignmentPermissionChange, SponsorProfile

ORIGIN = "http://testserver"
HOLDERS_URL = "/api/operator/assignment-permissions"
GRANT_URL = "/api/operator/assignment-permissions/grant"
CHANGES_URL = "/api/operator/assignment-permissions/changes"
PW = "operator-pw-asgnperm-9931-xyz"


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


def _grant(client, *, username, reason="수업 개설 승인", origin=ORIGIN):
    kwargs = {"content_type": "application/json"}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return client.post(GRANT_URL, data={"username": username, "reason": reason}, **kwargs)


def _revoke(client, sponsor_profile_id, *, reason="남용 신고 접수", origin=ORIGIN):
    kwargs = {"content_type": "application/json"}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return client.post(
        f"{HOLDERS_URL}/{sponsor_profile_id}/revoke", data={"reason": reason}, **kwargs
    )


def _sponsor_login(client, uid, email):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _sponsor_username(client, access: str) -> str:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()["username"]


# --- 조회: 일반 등급도 되고, 보유자만 나온다 --------------------------------


@pytest.mark.django_db
def test_ordinary_operator_can_view_holders_and_only_current_holders_appear():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-view-1", "perm-view-1@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-view", superuser=True)
    granted = _grant(root, username=username)
    assert granted.status_code == 200, granted.content

    judge = _operator_client("judge-perm-view")
    response = judge.get(HOLDERS_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    usernames = [row["username"] for row in response.json()]
    assert username in usernames


@pytest.mark.django_db
def test_holders_list_is_empty_by_default():
    judge = _operator_client("judge-perm-empty")

    response = judge.get(HOLDERS_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    assert response.json() == []


# --- 부여: 상위 등급만, 이유가 필요하고, SponsorProfile을 지연 생성한다 -----


@pytest.mark.django_db
def test_superuser_can_grant_permission_to_a_user_without_a_sponsor_profile_yet():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-grant-1", "perm-grant-1@example.com")
    username = _sponsor_username(client, pair["access"])

    # 이 시점에는 아직 SponsorProfile을 만들 만한 행동(과제 개최·콘테스트 개최)을
    # 한 적이 없다 — 소셜 로그인만 마친 상태다.
    assert not SponsorProfile.objects.filter(user__username=username).exists()

    root = _operator_client("root-perm-grant", superuser=True)
    response = _grant(root, username=username)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["username"] == username
    assert body["can_open_assignments"] is True

    profile = SponsorProfile.objects.get(user__username=username)
    assert profile.can_open_assignments is True

    change = AssignmentPermissionChange.objects.get(sponsor_profile=profile)
    assert change.operator.username == "root-perm-grant"
    assert change.action == AssignmentPermissionChange.Action.GRANTED
    assert change.reason == "수업 개설 승인"
    assert change.before == {"can_open_assignments": False}
    assert change.after == {"can_open_assignments": True}


@pytest.mark.django_db
def test_ordinary_operator_cannot_grant():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-grant-403", "perm-grant-403@example.com")
    username = _sponsor_username(client, pair["access"])

    judge = _operator_client("judge-perm-grant")
    response = _grant(judge, username=username)

    assert response.status_code == 403, response.content
    assert not SponsorProfile.objects.filter(
        user__username=username, can_open_assignments=True
    ).exists()


@pytest.mark.django_db
def test_grant_without_reason_is_rejected():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-noreason", "perm-noreason@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-noreason", superuser=True)
    response = _grant(root, username=username, reason="")

    assert response.status_code == 422, response.content


@pytest.mark.django_db
def test_grant_to_unknown_username_is_404_not_500():
    root = _operator_client("root-perm-missing-user", superuser=True)

    response = _grant(root, username="no-such-user-perm-9999")

    assert response.status_code == 404, response.content


@pytest.mark.django_db
def test_granting_twice_is_409_not_500():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-dup", "perm-dup@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-dup", superuser=True)
    first = _grant(root, username=username)
    assert first.status_code == 200, first.content

    second = _grant(root, username=username)

    assert second.status_code == 409, second.content
    assert AssignmentPermissionChange.objects.filter(
        sponsor_profile__user__username=username
    ).count() == 1


@pytest.mark.django_db
def test_grant_to_an_operator_account_is_rejected():
    """ADR-0018의 서로소 불변식 — Operator에게 Sponsor 권한을 주지 않는다."""

    call_command("create_operator", "operator-perm-target", password="irrelevant-pw-123")
    root = _operator_client("root-perm-vs-operator", superuser=True)

    response = _grant(root, username="operator-perm-target")

    assert response.status_code == 422, response.content


@pytest.mark.django_db
def test_grant_without_origin_is_403():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-noorigin", "perm-noorigin@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-noorigin", superuser=True)
    response = _grant(root, username=username, origin=None)

    assert response.status_code == 403, response.content


# --- 회수: 상위 등급만, 목록에서 빠지지만 SponsorProfile은 남는다 ----------


@pytest.mark.django_db
def test_superuser_can_revoke_and_holder_disappears_from_list():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-revoke-1", "perm-revoke-1@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-revoke", superuser=True)
    granted = _grant(root, username=username)
    profile_id = granted.json()["sponsor_profile_id"]

    response = _revoke(root, profile_id)

    assert response.status_code == 200, response.content
    assert response.json()["can_open_assignments"] is False

    holders = root.get(HOLDERS_URL, HTTP_ORIGIN=ORIGIN).json()
    assert username not in [row["username"] for row in holders]

    # SponsorProfile 자체는 지워지지 않는다 — 자격만 내려간다.
    profile = SponsorProfile.objects.get(id=profile_id)
    assert profile.can_open_assignments is False

    change = AssignmentPermissionChange.objects.get(
        sponsor_profile_id=profile_id, action=AssignmentPermissionChange.Action.REVOKED
    )
    assert change.operator.username == "root-perm-revoke"
    assert change.reason == "남용 신고 접수"
    assert change.before == {"can_open_assignments": True}
    assert change.after == {"can_open_assignments": False}


@pytest.mark.django_db
def test_ordinary_operator_cannot_revoke():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-revoke-403", "perm-revoke-403@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-revoke-403-setup", superuser=True)
    profile_id = _grant(root, username=username).json()["sponsor_profile_id"]

    judge = _operator_client("judge-perm-revoke")
    response = _revoke(judge, profile_id)

    assert response.status_code == 403, response.content
    assert SponsorProfile.objects.get(id=profile_id).can_open_assignments is True


@pytest.mark.django_db
def test_revoke_without_reason_is_rejected():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-revoke-noreason", "perm-rev-noreason@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-revoke-noreason", superuser=True)
    profile_id = _grant(root, username=username).json()["sponsor_profile_id"]

    response = _revoke(root, profile_id, reason="")

    assert response.status_code == 422, response.content
    assert SponsorProfile.objects.get(id=profile_id).can_open_assignments is True


@pytest.mark.django_db
def test_revoking_a_missing_sponsor_profile_is_404():
    root = _operator_client("root-perm-revoke-missing", superuser=True)

    response = _revoke(root, 999_999)

    assert response.status_code == 404, response.content


@pytest.mark.django_db
def test_revoking_a_profile_without_permission_is_409_not_500():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-revoke-noperm", "perm-rev-noperm@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-revoke-noperm", superuser=True)
    granted = _grant(root, username=username)
    profile_id = granted.json()["sponsor_profile_id"]
    first_revoke = _revoke(root, profile_id)
    assert first_revoke.status_code == 200, first_revoke.content

    second_revoke = _revoke(root, profile_id)

    assert second_revoke.status_code == 409, second_revoke.content


# --- 이력: 일반 등급도 보고, 회수된 뒤에도 이름이 남는다 --------------------


@pytest.mark.django_db
def test_history_is_visible_to_ordinary_operators_and_survives_revocation():
    client = Client()
    pair = _sponsor_login(client, "sponsor-perm-history", "perm-history@example.com")
    username = _sponsor_username(client, pair["access"])

    root = _operator_client("root-perm-history", superuser=True)
    granted = _grant(root, username=username, reason="이력 부여 사유")
    profile_id = granted.json()["sponsor_profile_id"]
    revoked = _revoke(root, profile_id, reason="이력 회수 사유")
    assert revoked.status_code == 200, revoked.content

    judge = _operator_client("judge-perm-history")
    response = judge.get(CHANGES_URL, HTTP_ORIGIN=ORIGIN)

    assert response.status_code == 200, response.content
    entries = response.json()
    by_action = {entry["action"]: entry for entry in entries if entry["username"] == username}
    assert by_action["granted"]["reason"] == "이력 부여 사유"
    assert by_action["revoked"]["reason"] == "이력 회수 사유"
    # 회수 뒤 보유자 목록에서는 빠졌지만, 이력 행은 여전히 이 Sponsor의
    # username을 들고 있다 — DeliverableTypeChangeOut과 달리 별도 목록과의
    # 조인 없이 이 행 하나로 "누구의 이력인가"에 답한다.
    assert by_action["granted"]["username"] == username
    assert by_action["revoked"]["username"] == username
