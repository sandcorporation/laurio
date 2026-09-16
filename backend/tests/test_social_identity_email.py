"""이메일이 계정을 찾는 데 어떻게 쓰이는지(2026-09-16, ADR-0049).

식별 키는 여전히 소셜 계정 `(provider, provider_uid)` 다 — 이 파일이 고정하는 것은
그 위에 얹힌 이메일의 규칙 넷이다: 로그인마다 갱신, 비어 있지 않은 이메일은 유일,
**인증된** 이메일이 같을 때만 계정 연결, 탈퇴하면 파기.

HTTP 시임으로만 본다 — 로그인은 엔드포인트 하나이고, 규칙이 그 요청 안에서 돈다.
fake 어댑터는 토큰 `"<uid>:<이메일>"` 을 인증된 이메일로 보고, 끝에 `:unverified`
를 붙이면 인증되지 않은 것으로 본다.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.db.utils import IntegrityError

from accounts.models import AccountLink, SocialAccount

pytestmark = pytest.mark.django_db

LOGIN_URL = "/api/auth/social/{provider}/login"


def _login(client, provider: str, token: str):
    return client.post(
        LOGIN_URL.format(provider=provider),
        data={"access_token": token},
        content_type="application/json",
    )


def _user_of(provider: str, uid: str):
    return SocialAccount.objects.get(provider=provider, provider_uid=uid).user


def test_email_and_verification_are_refreshed_on_every_login(client):
    """예전에는 가입 시점 값이 영원히 남았다 — 카카오가 이메일을 주기 시작해도
    기존 계정은 빈 채였다(prod 에서 실제로 그랬다)."""

    assert _login(client, "kakao", "u1:").status_code == 200
    user = _user_of("kakao", "u1")
    assert user.email == ""
    assert SocialAccount.objects.get(user=user).email_verified is False

    assert _login(client, "kakao", "u1:someone@example.com").status_code == 200
    user.refresh_from_db()
    social = SocialAccount.objects.get(user=user)
    assert user.email == "someone@example.com"
    assert social.email == "someone@example.com"
    assert social.email_verified is True

    # 동의를 철회하면 다시 빈 값으로 돌아간다.
    assert _login(client, "kakao", "u1:").status_code == 200
    user.refresh_from_db()
    assert user.email == ""
    assert SocialAccount.objects.get(user=user).email_verified is False


def test_verified_same_email_links_two_providers_into_one_account(client):
    """인증된 이메일이 같으면 한 계정이다 — 소셜 계정 행이 둘, 계정은 하나."""

    assert _login(client, "kakao", "k1:same@example.com").status_code == 200
    assert _login(client, "google", "g1:same@example.com").status_code == 200

    kakao_user = _user_of("kakao", "k1")
    google_user = _user_of("google", "g1")
    assert kakao_user.pk == google_user.pk
    assert get_user_model().objects.filter(is_staff=False).count() == 1

    link = AccountLink.objects.get(user=kakao_user)
    assert link.social_account.provider == "google"
    assert link.matched_email == "same@example.com"
    assert link.linked_at is not None


def test_unverified_email_never_links_and_leaves_the_email_empty(client):
    """인증되지 않은 이메일로 묶으면 남의 이메일을 적어 그 계정에 들어갈 수 있다.
    그래서 묶지 않고, 유일 제약 때문에 새 계정의 이메일 칸은 비워 둔다 — 로그인은
    그대로 된다(사용자가 스스로 풀 수 없는 상태로 막지 않는다)."""

    assert _login(client, "kakao", "k2:shared@example.com").status_code == 200
    response = _login(client, "google", "g2:shared@example.com:unverified")
    assert response.status_code == 200

    kakao_user = _user_of("kakao", "k2")
    google_user = _user_of("google", "g2")
    assert kakao_user.pk != google_user.pk
    assert kakao_user.email == "shared@example.com"
    assert google_user.email == ""
    assert AccountLink.objects.count() == 0


def test_non_empty_account_email_is_unique(client):
    """부분 유일 인덱스가 실제로 걸려 있다 — 빈 이메일은 여럿 허용한다."""

    assert _login(client, "kakao", "k3:one@example.com").status_code == 200
    user = _user_of("kakao", "k3")

    other = get_user_model().objects.create_user(username="other", email="")
    other.email = "one@example.com"
    with pytest.raises(IntegrityError):
        other.save(update_fields=["email"])


def test_empty_emails_do_not_collide(client):
    """이메일을 주지 않는 계정이 여럿 있어도 로그인은 다 된다."""

    assert _login(client, "kakao", "k4:").status_code == 200
    assert _login(client, "google", "g4:").status_code == 200
    assert get_user_model().objects.filter(is_staff=False, email="").count() == 2


def test_withdrawal_erases_email_and_nickname(client):
    """탈퇴는 신원을 파기한다(ADR-0025) — 이메일·닉네임도 그 대상이다. 다만 소셜
    계정 행은 남아 같은 계정으로 다시 로그인하는 길을 계속 막는다."""

    tokens = _login(client, "kakao", "k5:gone@example.com").json()
    user = _user_of("kakao", "k5")
    social = SocialAccount.objects.get(user=user)
    social.nickname = "이름"
    social.save(update_fields=["nickname"])

    withdraw = client.post(
        "/api/accounts/withdrawal",
        content_type="application/json",
        **{"HTTP_AUTHORIZATION": f"Bearer {tokens['access']}"},
    )
    assert withdraw.status_code == 200, withdraw.content

    user.refresh_from_db()
    social.refresh_from_db()
    assert user.email == ""
    assert social.email == ""
    assert social.nickname == ""
    assert social.email_verified is False
    assert social.provider_uid == "k5"

    # 탈퇴한 계정으로는 다시 로그인할 수 없다 — 파기가 그 문을 열지 않는다.
    assert _login(client, "kakao", "k5:gone@example.com").status_code == 403
