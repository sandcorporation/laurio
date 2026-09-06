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
def test_social_login_with_same_email_across_two_providers_creates_separate_accounts(client):
    """같은 사람이 두 제공자로 로그인하면 계정을 연결하지 않고 따로 만든다(#189).

    (provider, provider_uid)만이 신원의 근거다 — 이메일이 같다고 계정을 합치지
    않는다. 이유는 셋:

    1. **카카오는 이메일을 아예 안 줄 수 있다**(#189 유저스토리 12, 허용된
       공백). 이메일 매칭을 신원 병합의 기준으로 쓰면 그 공백이 있는 계정은
       애초에 병합 후보가 될 수 없어 규칙이 제공자마다 다르게 동작한다.
    2. **이메일 검증 수준이 제공자마다 다르다.** GitHub는 미검증 이메일을
       프로필에 노출할 수 있고, 구글은 검증된 이메일만 준다 — "이메일이
       같으면 같은 사람"이라는 전제 자체가 제공자에 따라 신뢰도가 다르다.
       그 전제를 API 계약에 넣는 순간, 미검증 제공자 쪽 이메일을 공격자가
       피해자의 것으로 채워 로그인하면 계정을 가로챌 길이 열린다.
    3. **자동 병합은 되돌릴 수 없는 결합이다.** 사람이 실수로 다른 이메일이
       달린 두 제공자로 가입한 뒤 나중에 병합을 원하면, 그건 명시적인 동의를
       받는 별도 기능(계정 연결 화면)의 몫이지 로그인 경로가 조용히 결정할
       일이 아니다 — 지금은 그 기능 자체가 없다(ADR-0013 참고).

    그래서 지금은 두 로그인이 서로 다른 User·SocialAccount로 남고, 둘 다
    독립적으로 계속 로그인된다 — 사람 입장에서는 "같은 사람인데 계정이
    둘"이지만, 그 상태가 "신원을 잘못 병합했다"보다 안전하다.
    """
    same_email = "same-person@example.com"

    kakao_login = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"kakao-uid-1:{same_email}"},
        content_type="application/json",
    )
    google_login = client.post(
        "/api/auth/social/google/login",
        data={"access_token": f"google-uid-1:{same_email}"},
        content_type="application/json",
    )

    assert kakao_login.status_code == 200
    assert google_login.status_code == 200

    accounts = SocialAccount.objects.filter(email=same_email)
    assert accounts.count() == 2
    users = {account.user_id for account in accounts}
    assert len(users) == 2, "같은 이메일이라도 두 제공자 로그인은 서로 다른 User로 남아야 한다"

    # 두 토큰 쌍이 서로 다른 사용자를 가리킨다 — 병합됐다면 둘 다 같은
    # user.id로 issue_token_pair가 불렸을 것이다.
    assert kakao_login.json()["access"] != google_login.json()["access"]
