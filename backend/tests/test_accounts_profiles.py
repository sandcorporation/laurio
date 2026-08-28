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


@pytest.mark.django_db
def test_sanitize_preserves_plain_punctuation_without_entity_corruption(client):
    """`bleach.clean`은 안전한 HTML을 만드는 게 목적이라 `& < >` 를 실체 참조로
    인코딩한다. 태그를 하나도 허용하지 않으면 그 인코딩은 더 이상 안전을 위해 필요
    없다 — 오히려 "Rock & Roll" 같은 평범한 글을 저장·재저장할 때마다
    "Rock &amp;amp; Roll" 처럼 중첩 오염시킨다. 문장부호가 원형 그대로 왕복하는지
    확인한다.
    """
    pair = _login(client)
    plain_text = "Rock & Roll <3 forever"

    first = client.post(
        "/api/accounts/developer-profile",
        data={"bio": plain_text},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert first.status_code == 200
    assert first.json()["bio"] == plain_text

    # 같은 값을 다시 저장해도(재-sanitize) 중첩 오염되지 않는다.
    second = client.post(
        "/api/accounts/developer-profile",
        data={"bio": first.json()["bio"]},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert second.json()["bio"] == plain_text

    stored = DeveloperProfile.objects.get(user__social_accounts__provider_uid="profile-owner")
    assert stored.bio == plain_text


@pytest.mark.django_db
def test_overlong_display_name_is_rejected_with_422_not_500(client):
    """DB의 `CharField(max_length=100)`에 그대로 부딪히면 422가 아니라 500이 난다."""
    pair = _login(client)

    response = client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "가" * 101},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_partial_update_does_not_wipe_the_other_field(client):
    """`display_name`만 보내면 기존 `bio`가 조용히 ""로 지워지던 버그.

    "안 보냄"(None)과 "명시적으로 비움"("")을 구분해야, 부분 업데이트가 다른 필드를
    건드리지 않으면서도 "둘 다 명시적으로 지우기"는 여전히 가능해야 한다.
    """
    pair = _login(client)

    client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "원래이름", "bio": "원래 소개"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    only_bio = client.post(
        "/api/accounts/developer-profile",
        data={"bio": "새 소개"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert only_bio.status_code == 200
    body = only_bio.json()
    assert body["display_name"] == "원래이름"
    assert body["bio"] == "새 소개"

    stored = DeveloperProfile.objects.get(user__social_accounts__provider_uid="profile-owner")
    assert stored.display_name == "원래이름"
    assert stored.bio == "새 소개"

    # 명시적으로 두 필드를 비우는 것은 여전히 가능해야 한다.
    cleared = client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "", "bio": ""},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert cleared.status_code == 200
    assert cleared.json() == {"display_name": "", "bio": ""}
