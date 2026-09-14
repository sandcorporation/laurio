"""채점 키에 상태가 생기고, 저장할 때 벤더에게 실제로 한 번 확인한다 (#354,
ADR-0045).

핵심 대상: 저장 시점에 강의실 채점 어댑터(`CLASSROOM_SCORING_ADAPTER_MODE`)를
통해 이 키가 유효한지 묻는다. 벤더가 확실히 거절했을 때(401·403)만 저장을
막고 DB의 기존 키를 지킨다 — 그 밖의 실패(타임아웃·5xx·네트워크)는 저장은
허용하되 "미검증"으로 남긴다. fake 어댑터(dev·CI 기본값)는 항상 유효하다고
답해 가짜 키 저장 흐름이 그대로 돈다.

`test_classroom_openai_key.py`(#284)가 이미 덮는 마스킹·암호화 자체는 다시
검증하지 않는다 — 이 파일은 그 저장에 새로 끼어든 검증 한 번과 상태 값만
본다.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from classroom.models import Class

CLASSES_URL = "/api/classroom/classes"


def _login(client, uid="instructor-1", email=None):
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


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _key_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/openai-key"


def _set_key(client, access: str, class_id: int, key: str):
    return client.put(
        _key_url(class_id),
        data={"api_key": key},
        content_type="application/json",
        **_auth_header(access),
    )


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def json(self):
        return {}


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


def test_fake_adapter_always_answers_valid(client, db):
    """기본값(fake)으로 되돌리면 어떤 키를 저장해도 "확인함"이다 — dev·CI의
    가짜 키 저장 흐름이 그대로 돈다."""

    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="fake"):
        pair = _login(client)
        class_id = _create_class(client, pair["access"])

        response = _set_key(client, pair["access"], class_id, "sk-fake-anything")

        assert response.status_code == 200
        assert response.json()["openai_key_status"] == "verified"


def test_a_valid_key_is_saved_as_verified(client, db, monkeypatch):
    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(200))

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = _set_key(client, pair["access"], class_id, "sk-good-key")

    assert response.status_code == 200
    body = response.json()
    assert body["has_openai_key"] is True
    assert body["openai_key_status"] == "verified"


@pytest.mark.parametrize("status_code", [401, 403])
def test_a_rejected_key_is_refused_with_422(client, db, monkeypatch, status_code):
    monkeypatch.setattr(
        "core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(status_code)
    )

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = _set_key(client, pair["access"], class_id, "sk-bad-key")

    assert response.status_code == 422
    assert "sk-bad-key" not in response.content.decode()

    class_obj = Class.objects.get(id=class_id)
    assert class_obj.has_scoring_key() is False


def test_a_rejected_new_key_does_not_evict_the_working_old_key(client, db, monkeypatch):
    """오타로 친 새 키가 멀쩡한 옛 키를 밀어내지 않는다(AC)."""

    from core.crypto import decrypt

    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(200))
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    good = _set_key(client, pair["access"], class_id, "sk-good-old-key")
    assert good.status_code == 200

    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(401))
    bad = _set_key(client, pair["access"], class_id, "sk-typo-key")
    assert bad.status_code == 422

    class_obj = Class.objects.get(id=class_id)
    assert decrypt(class_obj.openai_api_key_encrypted) == "sk-good-old-key"
    assert class_obj.openai_api_key_status == Class.ScoringKeyStatus.VERIFIED


@pytest.mark.parametrize(
    "failure",
    [
        "network",
        "timeout",
        "server_error",
    ],
)
def test_unreachable_vendor_saves_as_unverified(client, db, monkeypatch, failure):
    """타임아웃·5xx·네트워크 오류는 저장을 막지 않는다 — 상태만 "미검증"으로
    남는다(AC)."""

    import requests

    def _raise_or_respond(*a, **k):
        if failure == "network":
            raise requests.ConnectionError("network unreachable")
        if failure == "timeout":
            raise requests.Timeout("timed out")
        return _FakeResponse(500)

    monkeypatch.setattr("core.llm_scoring.requests.get", _raise_or_respond)

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = _set_key(client, pair["access"], class_id, "sk-cant-verify")

    assert response.status_code == 200
    body = response.json()
    assert body["has_openai_key"] is True
    assert body["openai_key_status"] == "unverified"


def test_a_class_without_a_key_has_no_key_status(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["has_openai_key"] is False
    assert body["openai_key_status"] is None


def test_key_check_never_calls_the_scoring_endpoint(client, db, monkeypatch):
    """키 확인은 채점 요청(`/chat/completions`)이 아니라 모델 목록 조회처럼
    프롬프트·토큰이 필요 없는 값싼 확인이어야 한다."""

    called_post = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: called_post.append(1)
    )
    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(200))

    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    response = _set_key(client, pair["access"], class_id, "sk-good-key")

    assert response.status_code == 200
    assert not called_post
