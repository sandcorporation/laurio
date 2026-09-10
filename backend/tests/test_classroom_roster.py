"""참여자 명단과 내보내기 — 행을 지우지 않고 표시한다 (#281,
CONTEXT.md 「강의실」, ADR-0037).

핵심 대상: 강사가 클래스에서 불릴 이름으로 명단을 보고, 내보내도 행이
지워지지 않고 "내보냄"으로 표시된다. 강사 본인이 참여자로 들어와 있으면
명단에서 구별된다. 남의 명단은 강사가 아닌 누구도 볼 수 없다.

"내보낸 사람은 새 제출을 낼 수 없다"(#281 AC)는 여기서 직접 검증하지 않는다
— 강의실은 아직 문제 제출 자체가 없다(#286이 그 엔드포인트를 짓는다). 이
티켓은 그 티켓이 검사할 신호(`ClassMember.expelled_at`)를 남기는 데까지다.
"""

from __future__ import annotations

from classroom.models import ClassMember

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


def _create_class(client, access: str, name: str = "웹 스터디") -> dict:
    response = client.post(
        CLASSES_URL,
        data={"name": name},
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


def _members_url(class_id: int) -> str:
    return f"{CLASSES_URL}/{class_id}/members"


def test_instructor_sees_participants_by_their_class_specific_name(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자닉네임")

    response = client.get(_members_url(created["id"]), **_auth_header(instructor["access"]))
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["display_name"] == "참여자닉네임"
    assert body[0]["expelled"] is False
    assert body[0]["is_instructor"] is False


def test_roster_distinguishes_the_instructor_when_they_join_their_own_class(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    _join(client, instructor["access"], created["join_code"], "강사 본인")

    response = client.get(_members_url(created["id"]), **_auth_header(instructor["access"]))
    body = response.json()
    assert len(body) == 1
    assert body[0]["is_instructor"] is True


def test_instructor_expels_a_participant(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자")

    member_id = ClassMember.objects.get(classroom_id=created["id"]).id
    response = client.post(
        f"{_members_url(created['id'])}/{member_id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert response.status_code == 200
    assert response.json()["expelled"] is True

    roster = client.get(_members_url(created["id"]), **_auth_header(instructor["access"]))
    assert roster.json()[0]["expelled"] is True


def test_expelling_does_not_delete_the_membership_row(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자")

    member = ClassMember.objects.get(classroom_id=created["id"])
    client.post(
        f"{_members_url(created['id'])}/{member.id}/expel",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )

    assert ClassMember.objects.filter(id=member.id).exists()
    refreshed = ClassMember.objects.get(id=member.id)
    assert refreshed.display_name == "참여자"
    assert refreshed.expelled_at is not None


def test_expelling_twice_stays_expelled_without_error(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자")
    member_id = ClassMember.objects.get(classroom_id=created["id"]).id
    expel_url = f"{_members_url(created['id'])}/{member_id}/expel"

    first = client.post(expel_url, content_type="application/json", **_auth_header(instructor["access"]))
    second = client.post(expel_url, content_type="application/json", **_auth_header(instructor["access"]))

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["expelled"] is True
    assert ClassMember.objects.filter(id=member_id).count() == 1


def test_another_instructors_roster_is_not_found(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    created = _create_class(client, a["access"], name="A의 클래스")

    response = client.get(_members_url(created["id"]), **_auth_header(b["access"]))
    assert response.status_code == 404


def test_another_instructor_cannot_expel_someone_elses_participant(client, db):
    a = _login(client, uid="instructor-a")
    b = _login(client, uid="instructor-b")
    created = _create_class(client, a["access"], name="A의 클래스")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자")
    member_id = ClassMember.objects.get(classroom_id=created["id"]).id

    response = client.post(
        f"{_members_url(created['id'])}/{member_id}/expel",
        content_type="application/json",
        **_auth_header(b["access"]),
    )
    assert response.status_code == 404
    assert ClassMember.objects.get(id=member_id).expelled_at is None


def test_a_participant_cannot_view_the_roster(client, db):
    instructor = _login(client, uid="instructor-1")
    created = _create_class(client, instructor["access"])
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], created["join_code"], "참여자")

    response = client.get(_members_url(created["id"]), **_auth_header(participant["access"]))
    assert response.status_code == 404


def test_roster_requires_authentication(client, db):
    instructor = _login(client)
    created = _create_class(client, instructor["access"])

    response = client.get(_members_url(created["id"]))
    assert response.status_code == 401
