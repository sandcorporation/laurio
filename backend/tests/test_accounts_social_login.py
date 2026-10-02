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


@pytest.mark.django_db
def test_social_login_with_unverified_email_across_two_providers_creates_separate_accounts(client):
    """**인증되지 않은** 이메일이 같아도 계정을 합치지 않는다(#189 → ADR-0049).

    2026-09-16 에 규칙이 갈렸다: 제공자가 **인증했다고 말한** 이메일이 같으면 한
    계정으로 묶는다(그 경로는 `tests/test_social_identity_email.py` 가 고정한다).
    그러나 인증 여부를 모르거나 인증되지 않은 이메일은 여전히 근거가 되지 못한다 —
    미검증 이메일을 피해자의 것으로 채워 로그인하면 계정을 가로챌 길이 열리기
    때문이고, 이 테스트가 그 문이 닫혀 있음을 지킨다. fake 어댑터는 토큰 끝의
    `:unverified` 로 그 상태를 흉내 낸다.

    합치지 않은 두 계정 중 나중 것은 이메일 칸이 비어 남는다 — 비어 있지 않은 계정
    이메일은 유일하고(부분 유일 인덱스), 그렇다고 로그인을 막지는 않는다.
    """
    same_email = "same-person@example.com"

    kakao_login = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"kakao-uid-1:{same_email}:unverified"},
        content_type="application/json",
    )
    google_login = client.post(
        "/api/auth/social/google/login",
        data={"access_token": f"google-uid-1:{same_email}:unverified"},
        content_type="application/json",
    )

    assert kakao_login.status_code == 200
    assert google_login.status_code == 200

    accounts = SocialAccount.objects.filter(
        provider_uid__in=["kakao-uid-1", "google-uid-1"]
    )
    assert accounts.count() == 2
    users = {account.user_id for account in accounts}
    assert len(users) == 2, "인증되지 않은 이메일이 같아도 두 로그인은 서로 다른 User 로 남아야 한다"
    assert not accounts.filter(email_verified=True).exists()

    # 두 토큰 쌍이 서로 다른 사용자를 가리킨다 — 병합됐다면 둘 다 같은
    # user.id로 issue_token_pair가 불렸을 것이다.
    assert kakao_login.json()["access"] != google_login.json()["access"]


@pytest.mark.django_db(transaction=True)
def test_two_simultaneous_first_logins_of_the_same_person_both_succeed(monkeypatch):
    """같은 사람이 동시에 두 번 처음 로그인하면(버튼을 빠르게 두 번, 두 탭) 둘 다
    「계정이 없다」를 보고 같은 사용자를 만들려 한다 — 늦은 쪽이 유일 제약에 걸려
    500 을 받았다(#500). 둘 다 같은 계정으로 로그인해야 한다.

    경쟁은 결정적으로 만든다: 두 요청이 각자 「소셜 계정이 없다」를 확인한 뒤
    (`find_linkable_user` 는 그때만 불린다) 서로를 기다렸다가 함께 계정을 만든다.
    스레드마다 자기 DB 연결·트랜잭션이라 실제 동시 요청과 같다.
    """

    import threading

    from django.contrib.auth import get_user_model
    from django.db import connection
    from django.test import Client

    import accounts.api as accounts_api

    real_find = accounts_api.find_linkable_user
    both_looked = threading.Barrier(2, timeout=10)

    def wait_for_the_other(profile):
        both_looked.wait()
        return real_find(profile)

    monkeypatch.setattr(accounts_api, "find_linkable_user", wait_for_the_other)

    results: list = []

    def log_in():
        try:
            response = Client(raise_request_exception=False).post(
                "/api/auth/social/kakao/login",
                data={"access_token": "race-1:race@example.com"},
                content_type="application/json",
            )
            results.append(response.status_code)
        finally:
            connection.close()

    threads = [threading.Thread(target=log_in) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert results == [200, 200]
    assert SocialAccount.objects.filter(provider="kakao", provider_uid="race-1").count() == 1
    assert get_user_model().objects.filter(username="kakao:race-1").count() == 1
