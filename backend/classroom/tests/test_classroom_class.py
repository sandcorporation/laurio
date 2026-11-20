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
        data={"name": "2026 하반기 웹 스터디", "instructor_display_name": "김강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "2026 하반기 웹 스터디"
    assert body["instructor_display_name"] == "김강사"
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
        data={"name": "A의 클래스", "instructor_display_name": "강사"},
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
        data={"name": "A의 클래스", "instructor_display_name": "강사"},
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


def test_creating_a_class_without_instructor_display_name_is_rejected(client, db):
    pair = _login(client, uid="instructor-1")

    response = client.post(
        CLASSES_URL,
        data={"name": "이름 없는 강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_creating_a_class_with_a_blank_instructor_display_name_is_rejected(client, db):
    pair = _login(client, uid="instructor-1")

    response = client.post(
        CLASSES_URL,
        data={"name": "빈 이름", "instructor_display_name": ""},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_existing_classes_have_a_blank_instructor_display_name(db):
    """마이그레이션이 아무 값도 지어내지 않는다(#299 AC) — 이 필드가 생기기 전에
    ORM으로 바로 만든 행(API 검증을 거치지 않는 경로)은 빈 문자열로 남는다."""

    instructor = get_user_model().objects.create_user(username="instructor-x", email="x@example.com")
    class_obj = Class.objects.create(instructor=instructor, name="예전 클래스")
    assert class_obj.instructor_display_name == ""


def test_instructor_updates_the_instructor_display_name_in_class_settings(client, db):
    pair = _login(client, uid="instructor-1")
    created = client.post(
        CLASSES_URL,
        data={"name": "웹 스터디", "instructor_display_name": "첫이름"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    ).json()

    response = client.patch(
        f"{CLASSES_URL}/{created['id']}",
        data={"instructor_display_name": "새이름"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["instructor_display_name"] == "새이름"
