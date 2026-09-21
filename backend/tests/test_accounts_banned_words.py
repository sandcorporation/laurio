"""개최자 공개용 이름·개발자 표시 이름에 금칙어(사칭·욕설)가 있으면 거절된다
(spec #474, #478).

핵심 대상: `SponsorProfile.display_name`(공개 공모전 목록·상세에 뜬다)과
`DeveloperProfile.display_name`(공개 개발자 프로필·심사 비교 화면에 뜬다)이
`classroom.ClassMember.display_name`(#475)과 같은 규칙을 받는다 — 이름
필드라 사칭·욕설 두 목록이 모두 걸린다. 두 프로필 모두 `POST`가 생성과
수정을 겸하므로(get-or-create) 처음 정할 때와 나중에 바꿀 때가 같은
엔드포인트 하나이고, 이 파일의 테스트가 그 둘을 함께 고정한다. 거절
응답의 `detail`은 걸린 낱말이 아니라 종류만 말하는 문자열이다.

HTTP만 친다(이 저장소의 유일한 백엔드 시임) — `core.banned_words`의 판정
함수를 직접 부르지 않는다.
"""

from __future__ import annotations

import pytest

from accounts.models import DeveloperProfile, SponsorProfile

SPONSOR_URL = "/api/accounts/sponsor-profile"
DEVELOPER_URL = "/api/accounts/developer-profile"


def _login(client, uid="profile-owner", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _post_profile(client, access: str, url: str, display_name: str | None = None, bio: str | None = None):
    payload = {}
    if display_name is not None:
        payload["display_name"] = display_name
    if bio is not None:
        payload["bio"] = bio
    return client.post(url, data=payload, content_type="application/json", **_auth_header(access))


@pytest.mark.parametrize("url", [SPONSOR_URL, DEVELOPER_URL])
def test_impersonation_name_is_rejected(client, db, url):
    pair = _login(client)

    response = _post_profile(client, pair["access"], url, display_name="관리자")

    assert response.status_code == 422
    assert response.json()["detail"] == "이름에는 운영진을 뜻하는 말을 쓸 수 없습니다."
    # `get_or_create`가 행 자체는 먼저 만들지만(빈 값), 거절된 이름은 그 행에
    # 저장되지 않는다 — 이름이 빈 채로 남는다.
    for model in (SponsorProfile, DeveloperProfile):
        assert not model.objects.filter(display_name="관리자").exists()


@pytest.mark.parametrize("url", [SPONSOR_URL, DEVELOPER_URL])
def test_impersonation_name_is_rejected_regardless_of_case(client, db, url):
    pair = _login(client)

    response = _post_profile(client, pair["access"], url, display_name="Admin")

    assert response.status_code == 422
    assert response.json()["detail"] == "이름에는 운영진을 뜻하는 말을 쓸 수 없습니다."


@pytest.mark.parametrize("url", [SPONSOR_URL, DEVELOPER_URL])
def test_profanity_name_is_rejected(client, db, url):
    pair = _login(client)

    response = _post_profile(client, pair["access"], url, display_name="씨발")

    assert response.status_code == 422
    assert response.json()["detail"] == "이름에 욕설을 쓸 수 없습니다."


def test_renaming_an_existing_sponsor_profile_to_a_banned_name_is_also_rejected(client, db):
    """처음 만들 때만 막으면 나중에 사칭으로 바꾸면 그만이다(#475와 같은 이유) —
    `POST`가 생성·수정을 겸하므로 이 한 테스트가 그 두 경로를 함께 고정한다."""
    pair = _login(client)
    first = _post_profile(client, pair["access"], SPONSOR_URL, display_name="정상 이름")
    assert first.status_code == 200

    response = _post_profile(client, pair["access"], SPONSOR_URL, display_name="운영자")

    assert response.status_code == 422
    profile = SponsorProfile.objects.get(user__social_accounts__provider_uid="profile-owner")
    assert profile.display_name == "정상 이름"


def test_legitimate_names_pass(client, db):
    pair = _login(client)

    sponsor = _post_profile(client, pair["access"], SPONSOR_URL, display_name="코드밋 스폰서")
    developer = _post_profile(client, pair["access"], DEVELOPER_URL, display_name="김개발")

    assert sponsor.status_code == 200
    assert sponsor.json()["display_name"] == "코드밋 스폰서"
    assert developer.status_code == 200
    assert developer.json()["display_name"] == "김개발"


def test_not_sending_display_name_does_not_trigger_the_check(client, db):
    """`bio`만 보내는 부분 수정은 `display_name`을 건드리지 않으므로 검사도
    돌지 않는다 — None을 그대로 검사에 넣으면 죽는 회귀를 잡는다."""
    pair = _login(client)

    response = _post_profile(client, pair["access"], DEVELOPER_URL, bio="소개만 바꿉니다")

    assert response.status_code == 200


def test_rejection_detail_does_not_leak_the_banned_word(client, db):
    pair = _login(client)

    response = _post_profile(client, pair["access"], SPONSOR_URL, display_name="이 회사는 씨발 최고다")

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, str)
    assert "씨발" not in detail
