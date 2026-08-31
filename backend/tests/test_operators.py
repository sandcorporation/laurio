"""Operator 계정과 서로소 불변식 (#42, ADR-0018).

Operator 는 Sponsor·Developer 와 **서로소**다. 소셜 계정을 가진 계정은 Operator 가
될 수 없고, Operator 계정으로는 소셜 로그인이 되지 않는다. 양방향 모두에서 막혀야
한다 — 한쪽만 막으면 다른 쪽으로 돌아 들어와 한 계정이 두 신뢰 경계를 걸친다.

시임에 대하여 — 소셜 로그인 거부는 HTTP 로 친다(CLAUDE.md 의 규율 그대로). 반면
부트스트랩 명령은 `call_command` 로 부른다. `test_deployment_config.py` 가 세운
서브프로세스 관용구는 **부팅 시점처럼 DB 가 없는 경우**의 것이다 — DB 를 만드는
명령을 서브프로세스로 돌리면 pytest 가 만든 테스트 DB 가 아니라 개발 DB 를 친다.
`call_command` 는 그 명령의 공개 인터페이스이기도 하다.
"""

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError

from accounts.models import DeveloperProfile, SocialAccount


def _social_login(client, uid="dev-1", email="dev@example.com"):
    return client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )


@pytest.mark.django_db
def test_bootstrap_command_creates_an_operator():
    call_command("create_operator", "alice", password="operator-pw-9134-xyz")

    operator = get_user_model().objects.get(username="alice")
    assert operator.is_staff is True
    assert operator.is_superuser is False
    assert operator.check_password("operator-pw-9134-xyz")


@pytest.mark.django_db
def test_bootstrap_command_can_create_the_first_superuser():
    """계정 관리 화면이 없으므로 부트스트랩 경로가 코드에 있어야 한다.

    이후 Operator 는 `is_superuser` 가 운영자 API 로 만든다(#45).
    """

    call_command("create_operator", "root", password="operator-pw-9134-xyz", superuser=True)

    operator = get_user_model().objects.get(username="root")
    assert operator.is_staff is True
    assert operator.is_superuser is True


@pytest.mark.django_db
def test_bootstrap_command_refuses_an_account_that_has_a_social_login(client):
    """서로소 불변식 — 참가자 쪽에서 운영자 쪽으로 넘어오는 방향."""

    assert _social_login(client, uid="participant-1").status_code == 200
    participant = SocialAccount.objects.get(provider_uid="participant-1").user

    with pytest.raises(CommandError) as exc:
        call_command("create_operator", participant.username, password="operator-pw-9134-xyz")

    assert "소셜" in str(exc.value), str(exc.value)
    participant.refresh_from_db()
    assert participant.is_staff is False


@pytest.mark.django_db
def test_bootstrap_command_refuses_a_weak_password():
    with pytest.raises(CommandError):
        call_command("create_operator", "bob", password="1234")

    assert not get_user_model().objects.filter(username="bob").exists()


@pytest.mark.django_db
def test_social_login_is_refused_for_an_operator_account(client):
    """서로소 불변식 — 운영자 쪽에서 참가자 쪽으로 넘어가는 방향.

    이쪽이 반대 방향이다. 명령만 막으면, 이미 Operator 인 계정에 소셜 계정을 붙여
    돌아 들어올 수 있다.
    """

    call_command("create_operator", "carol", password="operator-pw-9134-xyz")
    operator = get_user_model().objects.get(username="carol")
    SocialAccount.objects.create(
        user=operator, provider=SocialAccount.Provider.KAKAO, provider_uid="carol-social"
    )

    response = _social_login(client, uid="carol-social")

    assert response.status_code == 403, response.content
    assert SocialAccount.objects.filter(provider_uid="carol-social").exists()


@pytest.mark.django_db
def test_an_operator_cannot_reach_the_developer_profile_path(client):
    """Operator 는 `DeveloperProfile` 을 가질 수 없다 — 규칙이 아니라 구조가 막는다.

    `DeveloperProfile` 은 JWT 인증이 필요한 경로에서만 만들어지고, JWT 는 소셜
    로그인으로만 나온다. Operator 는 소셜 로그인이 거부되므로 토큰을 얻을 수 없고,
    따라서 그 경로에 애초에 닿지 못한다. 이 사슬이 끊기면 자기 사건 심판이 다시
    가능해지므로, 사슬 자체를 테스트로 고정한다.
    """

    call_command("create_operator", "dave", password="operator-pw-9134-xyz")
    operator = get_user_model().objects.get(username="dave")
    SocialAccount.objects.create(
        user=operator, provider=SocialAccount.Provider.KAKAO, provider_uid="dave-social"
    )

    # 토큰을 얻는 유일한 문이 닫혀 있다.
    assert _social_login(client, uid="dave-social").status_code == 403

    # 그래서 프로필도 생기지 않는다.
    assert not DeveloperProfile.objects.filter(user=operator).exists()


@pytest.mark.django_db
def test_participants_can_still_log_in(client):
    """불변식을 세우면서 원래 되던 것을 막으면 안 된다."""

    response = _social_login(client, uid="ordinary-1")

    assert response.status_code == 200
    user = SocialAccount.objects.get(provider_uid="ordinary-1").user
    assert user.is_staff is False
