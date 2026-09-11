"""참여자가 자기 클래스로 돌아갈 길 — 「내가 들어간 클래스」 목록 (#328,
CONTEXT.md 「강의실」, ADR-0037).

핵심 대상: 참여자로 가입한 클래스가 `GET /classroom/classes/joined`에
나온다. 본인이 강사인 클래스는 여기 겹쳐 나오지 않는다 — 그 클래스는 이미
`GET /classroom/classes`가 보여준다. 남의 클래스에 참여자로 들어간 적이
없으면 목록은 비고, 내보내진 클래스도 사라지지 않되 그 사실이 신호로
남는다.
"""

from __future__ import annotations

CLASSES_URL = "/api/classroom/classes"
JOINED_URL = f"{CLASSES_URL}/joined"


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


def _create_class(
    client, access: str, name: str = "웹 스터디", instructor_display_name: str = "강사"
) -> dict:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": instructor_display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()


def _join(client, access: str, join_code: str, display_name: str) -> dict:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


def test_participant_sees_the_class_they_joined(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(
        client, instructor["access"], name="웹 스터디", instructor_display_name="김강사"
    )
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자닉네임")

    response = client.get(JOINED_URL, **_auth_header(participant["access"]))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["id"] == created["id"]
    assert body[0]["name"] == "웹 스터디"
    assert body[0]["instructor_display_name"] == "김강사"
    assert body[0]["archived"] is False
    assert body[0]["expelled"] is False


def test_a_class_the_user_only_teaches_does_not_appear_in_joined(client, db):
    instructor = _login(client, uid="instructor-1")
    _create_class(client, instructor["access"])

    response = client.get(JOINED_URL, **_auth_header(instructor["access"]))
    assert response.status_code == 200
    assert response.json() == []


def test_instructor_who_also_joined_their_own_class_does_not_see_it_twice(client, db):
    """강사 본인도 참여자로 들어올 수 있다(models.py `ClassMember`
    docstring) — 그때도 `joined` 목록에는 나오지 않는다. `GET
    /classroom/classes`가 이미 그 클래스를 보여주므로 여기 더하면 첫 화면에
    같은 클래스가 두 번 나온다."""

    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    _join(client, instructor["access"], created["join_code"], "강사닉네임")

    response = client.get(JOINED_URL, **_auth_header(instructor["access"]))
    assert response.status_code == 200
    assert response.json() == []


def test_a_class_the_user_never_joined_does_not_appear(client, db):
    participant = _login(client, uid="participant-1")

    response = client.get(JOINED_URL, **_auth_header(participant["access"]))
    assert response.status_code == 200
    assert response.json() == []


def test_archived_class_still_appears_as_joined(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자닉네임")

    archive = client.post(
        f"{CLASSES_URL}/{created['id']}/archive",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert archive.status_code == 200

    response = client.get(JOINED_URL, **_auth_header(participant["access"]))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["archived"] is True


def test_expelled_membership_still_appears_but_marked_expelled(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자닉네임")

    members = client.get(
        f"{CLASSES_URL}/{created['id']}/members", **_auth_header(instructor["access"])
    )
    member_id = members.json()[0]["id"]
    expel = client.post(
        f"{CLASSES_URL}/{created['id']}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert expel.status_code == 200

    response = client.get(JOINED_URL, **_auth_header(participant["access"]))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["expelled"] is True


def test_joined_response_never_leaks_the_instructors_join_code_or_openai_key(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자닉네임")

    response = client.get(JOINED_URL, **_auth_header(participant["access"]))
    body = response.json()
    assert "join_code" not in body[0]
    assert created["join_code"] not in response.content.decode()
    assert "has_openai_key" not in body[0]
    assert "token_budget" not in body[0]
