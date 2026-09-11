"""강사가 자기 OpenAI 키를 넣는다 — 저장 뒤에는 다시 못 본다 (#284,
CONTEXT.md 「강의실」).

핵심 대상: 채점은 강사 본인의 키로 돈다. 키는 저장 뒤 마스킹된 형태로만
보이고, 평문은 API 응답·로그·오류 메시지 어디에도 나오지 않는다. `core.crypto`
로 암호화해 저장하고(#269가 공유층으로 옮긴 그 헬퍼), 복호화는 채점 요청을
보낼 때만 한다 — 그래서 마스킹은 복호화가 아니라 저장 시점에 함께 남긴
마지막 네 자리로 만든다.
"""

from __future__ import annotations

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


def test_a_new_class_has_no_openai_key(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"]))
    assert response.status_code == 200
    body = response.json()
    assert body["has_openai_key"] is False
    assert body["openai_key_masked"] is None


def test_instructor_sets_a_key_and_only_sees_it_masked(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.put(
        _key_url(class_id),
        data={"api_key": "sk-test-abcd1234wxyz"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["has_openai_key"] is True
    assert body["openai_key_masked"] is not None
    assert body["openai_key_masked"].endswith("wxyz")
    assert "sk-test-abcd1234wxyz" not in response.content.decode()


def test_the_raw_key_is_not_stored_in_plaintext(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    client.put(
        _key_url(class_id),
        data={"api_key": "sk-test-abcd1234wxyz"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    class_obj = Class.objects.get(id=class_id)
    assert class_obj.openai_api_key_encrypted != "sk-test-abcd1234wxyz"
    assert "sk-test-abcd1234wxyz" not in class_obj.openai_api_key_encrypted


def test_setting_a_new_key_replaces_the_previous_one(client, db):
    from core.crypto import decrypt

    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    client.put(
        _key_url(class_id),
        data={"api_key": "sk-old-key-1111"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    response = client.put(
        _key_url(class_id),
        data={"api_key": "sk-new-key-2222"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["openai_key_masked"].endswith("2222")

    class_obj = Class.objects.get(id=class_id)
    assert decrypt(class_obj.openai_api_key_encrypted) == "sk-new-key-2222"


def test_an_empty_key_is_rejected(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.put(
        _key_url(class_id),
        data={"api_key": "  "},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_a_non_instructor_cannot_set_another_classs_key(client, db):
    owner = _login(client, uid="owner")
    class_id = _create_class(client, owner["access"])

    intruder = _login(client, uid="intruder")
    response = client.put(
        _key_url(class_id),
        data={"api_key": "sk-stolen-0000"},
        content_type="application/json",
        **_auth_header(intruder["access"]),
    )
    assert response.status_code == 404
