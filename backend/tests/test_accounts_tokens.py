"""액세스 토큰 짧은 수명 + 리프레시 토큰 회전 + 로그아웃 블랙리스트 즉시 거부 (#5).

ADR-0012: 이 세 보완책 중 하나라도 빠지면 "JWT in localStorage" 결정 자체가 무효다.
"""

import pytest


def _login(client, token="uid-login:person@example.com"):
    response = client.post(
        "/api/auth/social/github/login",
        data={"access_token": token},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


@pytest.mark.django_db
def test_protected_endpoint_requires_token(client):
    response = client.get("/api/accounts/me")
    assert response.status_code == 401


@pytest.mark.django_db
def test_protected_endpoint_accepts_valid_access_token(client):
    pair = _login(client)

    response = client.get("/api/accounts/me", **_auth_header(pair["access"]))

    assert response.status_code == 200
    assert response.json()["has_sponsor_profile"] is False


@pytest.mark.django_db
def test_refresh_rotates_and_old_refresh_token_is_rejected(client):
    pair = _login(client)

    rotated = client.post(
        "/api/auth/refresh",
        data={"refresh": pair["refresh"]},
        content_type="application/json",
    )
    assert rotated.status_code == 200
    new_pair = rotated.json()
    assert new_pair["refresh"] != pair["refresh"]
    assert new_pair["access"] != pair["access"]

    reuse_attempt = client.post(
        "/api/auth/refresh",
        data={"refresh": pair["refresh"]},
        content_type="application/json",
    )
    assert reuse_attempt.status_code == 401

    still_works = client.post(
        "/api/auth/refresh",
        data={"refresh": new_pair["refresh"]},
        content_type="application/json",
    )
    assert still_works.status_code == 200


@pytest.mark.django_db
def test_logout_blacklists_access_token_immediately(client):
    pair = _login(client)

    before = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert before.status_code == 200

    logout = client.post(
        "/api/auth/logout",
        data={"refresh": pair["refresh"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert logout.status_code == 200

    after = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert after.status_code == 401


@pytest.mark.django_db
def test_logout_blacklists_refresh_token_too(client):
    pair = _login(client)

    client.post(
        "/api/auth/logout",
        data={"refresh": pair["refresh"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    refresh_attempt = client.post(
        "/api/auth/refresh",
        data={"refresh": pair["refresh"]},
        content_type="application/json",
    )
    assert refresh_attempt.status_code == 401


@pytest.mark.django_db
def test_access_token_ttl_is_short_lived_by_default():
    from django.conf import settings
    from datetime import timedelta

    assert settings.ACCESS_TOKEN_TTL <= timedelta(minutes=15)
    assert settings.REFRESH_TOKEN_TTL > settings.ACCESS_TOKEN_TTL
