"""가입 링크 발급과 재발급 (#279, CONTEXT.md 「강의실」).

핵심 대상: 강사가 클래스 상세에서 가입 코드를 보고, 다시 뽑으면 이전 코드는
더 이상 그 클래스를 가리키지 않는다. 이 티켓은 발급까지다 — 그 코드로
들어왔을 때 무슨 일이 일어나는지는 #280의 몫이다.
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


def test_class_is_issued_a_join_code_on_creation(client, db):
    pair = _login(client)

    response = client.post(
        CLASSES_URL,
        data={"name": "웹 스터디", "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 201
    body = response.json()
    assert isinstance(body["join_code"], str)
    assert len(body["join_code"]) >= 16


def test_join_codes_do_not_collide_across_classes(client, db):
    pair = _login(client)

    a = _create_class(client, pair["access"], name="A반")
    b = _create_class(client, pair["access"], name="B반")

    codes = {
        Class.objects.get(id=a).join_code,
        Class.objects.get(id=b).join_code,
    }
    assert len(codes) == 2


def test_instructor_regenerates_the_join_code(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    old_code = Class.objects.get(id=class_id).join_code

    response = client.post(
        f"{CLASSES_URL}/{class_id}/join-link/regenerate",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    new_code = response.json()["join_code"]
    assert new_code != old_code

    refreshed = Class.objects.get(id=class_id)
    assert refreshed.join_code == new_code


def test_regenerating_kills_the_old_code(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    old_code = Class.objects.get(id=class_id).join_code

    client.post(
        f"{CLASSES_URL}/{class_id}/join-link/regenerate",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    assert not Class.objects.filter(join_code=old_code).exists()


def test_another_instructor_cannot_regenerate_someone_elses_join_code(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    class_id = _create_class(client, a["access"], name="A의 클래스")
    old_code = Class.objects.get(id=class_id).join_code

    response = client.post(
        f"{CLASSES_URL}/{class_id}/join-link/regenerate",
        content_type="application/json",
        **_auth_header(b["access"]),
    )
    assert response.status_code == 404
    assert Class.objects.get(id=class_id).join_code == old_code


def test_class_detail_includes_join_code_for_the_owner(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"]))
    assert response.status_code == 200
    assert response.json()["join_code"] == Class.objects.get(id=class_id).join_code
