"""카카오 프로필 조회가 닉네임을 읽어 저장한다 (#390, CONTEXT.md 「가입 링크」).

가입 링크의 이름 칸을 카카오 닉네임으로 미리 채우려면 그 값이 먼저
`SocialAccount`에 있어야 한다. `FakeSocialAdapter`는 access_token 문자열을
"<uid>:<email>"로만 파싱해 닉네임 자리가 없으므로(accounts/social.py), 여기서는
실제 `KakaoAdapter`가 타는 `urllib.request.urlopen`을 몽키패치해 벤더 응답을
흉내낸다 — `tests/test_github_api_adapter.py`가 `requests.get`에 쓰는 것과 같은
방식이다. `SOCIAL_AUTH_MODE=real`로 강제해야 이 어댑터가 실제로 선택된다.
"""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from accounts.models import SocialAccount

LOGIN_URL = "/api/auth/social/kakao/login"


class _FakeKakaoResponse:
    def __init__(self, body: dict):
        self._body = json.dumps(body).encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _fake_urlopen(body: dict):
    def _urlopen(request, timeout=5):
        assert request.full_url == "https://kapi.kakao.com/v2/user/me"
        return _FakeKakaoResponse(body)

    return _urlopen


def _kakao_response(uid: int, *, nickname: str | None, email: str = "person@example.com") -> dict:
    """`nickname=None`은 동의하지 않아 그 항목 자체가 응답에서 빠진 경우를
    흉내낸다 — 빈 문자열과 구분해 둔다(카카오는 미동의 항목을 아예 생략한다)."""

    profile: dict = {}
    if nickname is not None:
        profile["nickname"] = nickname
    return {"id": uid, "kakao_account": {"email": email, "profile": profile}}


@pytest.fixture(autouse=True)
def _force_real_kakao_adapter():
    with override_settings(SOCIAL_AUTH_MODE="real"):
        yield


@pytest.mark.django_db
def test_kakao_login_saves_the_nickname(client, monkeypatch):
    monkeypatch.setattr(
        "accounts.social.urllib.request.urlopen",
        _fake_urlopen(_kakao_response(101, nickname="말랑카우")),
    )

    response = client.post(LOGIN_URL, data={"access_token": "token"}, content_type="application/json")

    assert response.status_code == 200
    account = SocialAccount.objects.get(provider="kakao", provider_uid="101")
    assert account.nickname == "말랑카우"


@pytest.mark.django_db
def test_kakao_login_updates_the_nickname_on_the_next_login(client, monkeypatch):
    monkeypatch.setattr(
        "accounts.social.urllib.request.urlopen",
        _fake_urlopen(_kakao_response(202, nickname="옛날별명")),
    )
    client.post(LOGIN_URL, data={"access_token": "token"}, content_type="application/json")

    monkeypatch.setattr(
        "accounts.social.urllib.request.urlopen",
        _fake_urlopen(_kakao_response(202, nickname="새별명")),
    )
    response = client.post(LOGIN_URL, data={"access_token": "token"}, content_type="application/json")

    assert response.status_code == 200
    account = SocialAccount.objects.get(provider="kakao", provider_uid="202")
    assert account.nickname == "새별명"


@pytest.mark.django_db
def test_kakao_login_leaves_the_nickname_blank_when_not_provided(client, monkeypatch):
    monkeypatch.setattr(
        "accounts.social.urllib.request.urlopen",
        _fake_urlopen(_kakao_response(303, nickname=None)),
    )

    response = client.post(LOGIN_URL, data={"access_token": "token"}, content_type="application/json")

    assert response.status_code == 200
    account = SocialAccount.objects.get(provider="kakao", provider_uid="303")
    assert account.nickname == ""


@pytest.mark.django_db
def test_kakao_login_clears_a_previously_saved_nickname_when_consent_is_revoked(client, monkeypatch):
    monkeypatch.setattr(
        "accounts.social.urllib.request.urlopen",
        _fake_urlopen(_kakao_response(404, nickname="한때의별명")),
    )
    client.post(LOGIN_URL, data={"access_token": "token"}, content_type="application/json")

    monkeypatch.setattr(
        "accounts.social.urllib.request.urlopen",
        _fake_urlopen(_kakao_response(404, nickname=None)),
    )
    client.post(LOGIN_URL, data={"access_token": "token"}, content_type="application/json")

    account = SocialAccount.objects.get(provider="kakao", provider_uid="404")
    assert account.nickname == ""


@pytest.mark.django_db
def test_kakao_login_falls_back_to_properties_nickname(client, monkeypatch):
    """구버전 응답 모양이나 동의 범위가 다른 경우 `kakao_account.profile`이
    아니라 최상위 `properties.nickname`에 실려 올 수 있다."""

    body = {
        "id": 505,
        "kakao_account": {"email": "e@example.com", "profile": {}},
        "properties": {"nickname": "프로퍼티닉네임"},
    }
    monkeypatch.setattr("accounts.social.urllib.request.urlopen", _fake_urlopen(body))

    response = client.post(LOGIN_URL, data={"access_token": "token"}, content_type="application/json")

    assert response.status_code == 200
    account = SocialAccount.objects.get(provider="kakao", provider_uid="505")
    assert account.nickname == "프로퍼티닉네임"
