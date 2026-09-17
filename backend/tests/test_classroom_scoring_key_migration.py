"""공백뿐인 채점 키를 걷어내는 데이터 마이그레이션 (#435, spec #432).

핵심 대상: `classroom.migrations.0013_clear_whitespace_only_scoring_keys`가
`openai_api_key_encrypted`가 공백뿐인 클래스를 키 없는 클래스와 같은 상태로
되돌린다. 정상 경로(`PUT .../openai-key`)는 이런 값을 만들지 않으므로(422로
거절, `tests/test_classroom_openai_key.py`), 이 파일은 그 검증이 없던
시절의 데이터를 흉내 내 직접 ORM으로 만든다.
"""

from __future__ import annotations

import importlib

from django.apps import apps

from classroom.models import Class

# 마이그레이션 파일 이름이 숫자로 시작해(Django 관례) `from ... import`로
# 바로 부를 수 없다 — Django 자신도 마이그레이션을 이렇게 동적으로 읽는다.
_clear_whitespace_only_keys = importlib.import_module(
    "classroom.migrations.0013_clear_whitespace_only_scoring_keys"
)._clear_whitespace_only_keys


def _login(client, uid="instructor-1") -> str:
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()["access"]


def _create_class(client, access: str) -> int:
    response = client.post(
        "/api/classroom/classes",
        data={"name": "웹 스터디", "instructor_display_name": "강사"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == 201
    return response.json()["id"]


def test_whitespace_only_key_is_cleared_and_status_reset(client, db):
    access = _login(client)
    class_id = _create_class(client, access)
    Class.objects.filter(id=class_id).update(
        openai_api_key_encrypted="   ", openai_api_key_last4="abcd", openai_api_key_status="verified"
    )

    _clear_whitespace_only_keys(apps=apps, schema_editor=None)

    class_obj = Class.objects.get(id=class_id)
    assert class_obj.openai_api_key_encrypted == ""
    assert class_obj.openai_api_key_last4 == ""
    assert class_obj.openai_api_key_status == "unverified"
    assert class_obj.has_scoring_key() is False


def test_a_real_key_is_left_untouched(client, db):
    access = _login(client)
    class_id = _create_class(client, access)
    response = client.put(
        f"/api/classroom/classes/{class_id}/openai-key",
        data={"api_key": "sk-real-key-1234"},
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {access}",
    )
    assert response.status_code == 200
    before = Class.objects.get(id=class_id).openai_api_key_encrypted

    _clear_whitespace_only_keys(apps=apps, schema_editor=None)

    class_obj = Class.objects.get(id=class_id)
    assert class_obj.openai_api_key_encrypted == before
    assert class_obj.has_scoring_key() is True


def test_an_already_empty_key_is_left_untouched(client, db):
    access = _login(client)
    class_id = _create_class(client, access)

    _clear_whitespace_only_keys(apps=apps, schema_editor=None)

    class_obj = Class.objects.get(id=class_id)
    assert class_obj.openai_api_key_encrypted == ""
    assert class_obj.openai_api_key_status == "unverified"
