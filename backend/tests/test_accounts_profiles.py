"""Sponsor·Developer 프로필 지연 생성 + 자유 서식 sanitize (#5).

하나의 User가 어떤 Contest에서는 Sponsor, 다른 Contest에서는 Developer일 수 있다
(CONTEXT.md). 두 프로필 모두 필요해질 때만 생긴다.
"""

import pytest

from accounts.models import DeveloperProfile, SponsorProfile


def _login(client):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": "profile-owner:owner@example.com"},
        content_type="application/json",
    )
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


@pytest.mark.django_db
def test_no_profiles_exist_right_after_social_login(client):
    pair = _login(client)

    me = client.get("/api/accounts/me", **_auth_header(pair["access"])).json()

    assert me["has_sponsor_profile"] is False
    assert me["has_developer_profile"] is False


@pytest.mark.django_db
def test_sponsor_profile_is_created_lazily(client):
    pair = _login(client)

    response = client.post(
        "/api/accounts/sponsor-profile",
        data={"display_name": "라우리오 스폰서", "bio": "우리는 상금을 겁니다"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert SponsorProfile.objects.filter(user__social_accounts__provider_uid="profile-owner").exists()

    me = client.get("/api/accounts/me", **_auth_header(pair["access"])).json()
    assert me["has_sponsor_profile"] is True
    assert me["has_developer_profile"] is False


@pytest.mark.django_db
def test_one_user_can_hold_both_profiles(client):
    pair = _login(client)

    client.post(
        "/api/accounts/sponsor-profile",
        data={},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    client.post(
        "/api/accounts/developer-profile",
        data={},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    me = client.get("/api/accounts/me", **_auth_header(pair["access"])).json()
    assert me["has_sponsor_profile"] is True
    assert me["has_developer_profile"] is True


@pytest.mark.django_db
def test_free_text_bio_is_sanitized(client):
    pair = _login(client)

    response = client.post(
        "/api/accounts/developer-profile",
        data={
            "display_name": "개발자",
            "bio": "<script>alert('xss')</script>안녕하세요",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 200
    body = response.json()
    assert "<script>" not in body["bio"]
    assert "안녕하세요" in body["bio"]

    stored = DeveloperProfile.objects.get(user__social_accounts__provider_uid="profile-owner")
    assert "<script>" not in stored.bio
