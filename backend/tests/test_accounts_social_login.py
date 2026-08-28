"""소셜 로그인 — 비밀번호 없이 카카오·GitHub·구글로 로그인해 JWT를 받는다 (#5).

dev/test는 Fake 소셜 어댑터로 바인딩된다(ADR-0007) — access_token 문자열이 곧
"<provider_uid>:<email>" 형식이며 실제 제공자 네트워크를 타지 않는다.
"""

import pytest

from accounts.models import SocialAccount


@pytest.mark.django_db
@pytest.mark.parametrize("provider", ["kakao", "github", "google"])
def test_social_login_issues_token_pair(client, provider):
    response = client.post(
        f"/api/auth/social/{provider}/login",
        data={"access_token": "uid-1:person@example.com"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["access"]
    assert body["refresh"]
    assert body["token_type"] == "bearer"


@pytest.mark.django_db
def test_social_login_creates_user_with_no_usable_password(client):
    response = client.post(
        "/api/auth/social/github/login",
        data={"access_token": "gh-42:dev@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200

    account = SocialAccount.objects.get(provider="github", provider_uid="gh-42")
    assert account.user.has_usable_password() is False


@pytest.mark.django_db
def test_social_login_is_idempotent_per_provider_identity(client):
    payload = {"access_token": "uid-9:same@example.com"}

    first = client.post(
        "/api/auth/social/google/login", data=payload, content_type="application/json"
    )
    second = client.post(
        "/api/auth/social/google/login", data=payload, content_type="application/json"
    )

    assert first.status_code == 200 and second.status_code == 200
    assert SocialAccount.objects.filter(provider="google", provider_uid="uid-9").count() == 1


@pytest.mark.django_db
def test_social_login_rejects_malformed_token(client):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": "not-a-valid-fake-token"},
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_social_login_rejects_unsupported_provider(client):
    response = client.post(
        "/api/auth/social/facebook/login",
        data={"access_token": "uid-1:a@example.com"},
        content_type="application/json",
    )

    assert response.status_code == 401
