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


@pytest.mark.django_db
def test_operator_revoked_refresh_token_stops_working_immediately(client):
    """운영자가 admin에서 RefreshToken.revoked_at을 기입하면 그 즉시 회전이 막혀야
    한다 — 블랙리스트에 없어도(로그아웃을 거치지 않았어도) 마찬가지다(ADR-0012).
    """
    from django.utils import timezone

    from accounts.models import RefreshToken

    pair = _login(client)

    # 운영자가 admin에서 이 리프레시 토큰을 직접 회수했다고 가정한다.
    RefreshToken.objects.all().update(revoked_at=timezone.now())

    response = client.post(
        "/api/auth/refresh",
        data={"refresh": pair["refresh"]},
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_logout_fails_loudly_when_refresh_token_is_invalid(client):
    """예전엔 블랙리스트 기록 실패를 조용히 삼켜 200을 돌려줬다 — 지금은 그대로
    드러난다. 200을 돌려주면서 토큰이 여전히 유효한 상태로 남는 건 ADR-0012가 금지하는
    상황이다.
    """
    pair = _login(client)

    response = client.post(
        "/api/auth/logout",
        data={"refresh": "not-a-real-jwt"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 401
    assert response.json() != {"status": "ok"}


@pytest.mark.django_db
def test_logout_blacklists_an_already_expired_refresh_token_without_crashing(client):
    """서명은 유효하지만 exp가 지난 리프레시 토큰도 블랙리스트 기록 자체는 성공해야
    한다. `blacklist_token`이 만료를 이유로 예외를 던지면, 로그아웃이 실패를 더 이상
    삼키지 않는 지금(로그아웃 fail-loud 수정) 이 흔한 시나리오가 그대로 500으로 샌다.
    """
    from datetime import datetime, timedelta, timezone as dt_timezone
    from unittest.mock import patch

    issue_time = datetime.now(dt_timezone.utc) - timedelta(days=20)
    with patch("django.utils.timezone.now", return_value=issue_time):
        stale_pair = _login(client, token="stale-refresh-owner:x@example.com")

    # 리프레시 TTL(14일)까지 지난 뒤 같은 사용자로 다시 로그인해, "지금" 유효한
    # 액세스 토큰을 새로 받는다(같은 SocialAccount → 같은 User).
    fresh_pair = _login(client, token="stale-refresh-owner:x@example.com")

    response = client.post(
        "/api/auth/logout",
        data={"refresh": stale_pair["refresh"]},
        content_type="application/json",
        **_auth_header(fresh_pair["access"]),
    )

    assert response.status_code == 200
