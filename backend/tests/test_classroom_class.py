"""Class — 강사가 클래스를 만들고 목록에서 본다 (#278, CONTEXT.md 「강의실」, ADR-0037).

핵심 대상: 강사가 「내 클래스」에서 자기 것만 보고, 남의 클래스는 목록에도
상세에도 나오지 않는다. Class는 역할 프로필이 아니라 User를 직접 가리킨다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

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


def test_instructor_creates_a_class_and_sees_it_in_my_classes(client, db):
    pair = _login(client, uid="instructor-1")

    response = client.post(
        CLASSES_URL,
        data={"name": "2026 하반기 웹 스터디"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "2026 하반기 웹 스터디"
    assert "created_at" in body

    listing = client.get(CLASSES_URL, **_auth_header(pair["access"]))
    assert listing.status_code == 200
    names = [row["name"] for row in listing.json()]
    assert names == ["2026 하반기 웹 스터디"]


def test_another_instructors_class_does_not_appear_in_my_classes(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")

    client.post(
        CLASSES_URL,
        data={"name": "A의 클래스"},
        content_type="application/json",
        **_auth_header(a["access"]),
    )

    listing = client.get(CLASSES_URL, **_auth_header(b["access"]))
    assert listing.status_code == 200
    assert listing.json() == []


def test_another_instructors_class_detail_is_not_found(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")

    created = client.post(
        CLASSES_URL,
        data={"name": "A의 클래스"},
        content_type="application/json",
        **_auth_header(a["access"]),
    )
    class_id = created.json()["id"]

    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(b["access"]))
    assert detail.status_code == 404


def test_class_requires_authentication(client, db):
    response = client.get(CLASSES_URL)
    assert response.status_code == 401


def test_class_points_directly_to_user_not_a_role_profile():
    field = Class._meta.get_field("instructor")
    assert field.related_model is get_user_model()
