"""AssignmentImage — 과제에도 공모전과 같은 참고 이미지 규칙이 붙는다 (#236, ADR-0032).

`contests.images`가 발급·등록·순서변경·제거를 `contests.api`(공모전)와
`contests.assignment_api`(과제) 양쪽에 그대로 빌려준다 — 그래서 이 파일은
`tests/test_contest_images.py`와 같은 결의 테스트를 과제 표면(URL이
`/api/assignments/{id}/images/...`)에 대고 반복한다. 다른 것은 편집 게이트
하나뿐이다: 공모전은 결제가 문을 닫고, 과제는 **첫 제출**이 문을 닫는다
(`_get_owned_editable_assignment`, #209가 이미 정의한 잠금 — 새로 만들지
않는다). DRAFT뿐 아니라 제출 0건인 ASSIGNMENT_OPEN 과제도 고칠 수 있다는
점까지 그 게이트가 그대로 답한다.

InviteCode로 들어온 학생이 로그인 없이도 이미지를 보는지(spec #225 user story
24 "과제에 이미지가 있는지 안다")는 `GET /assignments/invite/{code}`(auth=None)
가 이미지 목록을 싣는지로 확인한다.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.management import call_command
from django.test import Client

from contests.models import ContestImage, DeliverableType
from storage.adapters.base import Bucket
from storage.adapters.fake import FakeStorageAdapter

ASSIGNMENTS_URL = "/api/assignments"
CONTESTS_URL = "/api/contests"
GRANT_URL = "/api/operator/assignment-permissions/grant"
OPERATOR_PW = "operator-pw-asgnimg-9931-xyz"
OPERATOR_ORIGIN = "http://testserver"


def _operator_client(username="root-asgnimg"):
    call_command("create_operator", username, password=OPERATOR_PW, superuser=True)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": OPERATOR_PW},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _login(client, uid, email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _username(client, access: str) -> str:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()["username"]


def _user_id(client, access: str) -> int:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()["id"]


def _grant_permission(operator_client, *, username, reason="수업 개설 승인"):
    response = operator_client.post(
        GRANT_URL,
        data={"username": username, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content


def _sponsor_with_permission(client, root, uid):
    pair = _login(client, uid)
    username = _username(client, pair["access"])
    _grant_permission(root, username=username)
    return pair


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _create_assignment(client, access, *, deliverable_type_ids, title="파이썬 기초 과제"):
    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": title,
            "deliverable_type_ids": deliverable_type_ids,
            "description": "1주차 과제",
            "deadline_at": "2030-01-01T00:00:00Z",
            "requirements": [{"text": "함수를 정의한다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201, created.content
    return created.json()["id"]


def _open_assignment(client, access, assignment_id: int) -> str:
    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200, opened.content
    return opened.json()["invite_code"]


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, access: str, contest_id: int, invite_code: str, student_user_id: int):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [
                {"kind": "source", "value": _source_object_key(contest_id, student_user_id)}
            ],
            "invite_code": invite_code,
        },
        content_type="application/json",
        **_auth_header(access),
    )


def _request_upload_url(client, access, assignment_id, *, content_type="image/png"):
    return client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/images/upload-url",
        data={"content_type": content_type},
        content_type="application/json",
        **_auth_header(access),
    )


def _add_image(client, access, assignment_id, object_key):
    return client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/images",
        data={"object_key": object_key},
        content_type="application/json",
        **_auth_header(access),
    )


def _upload_and_register(client, access, assignment_id, *, content_type="image/png") -> dict:
    issued = _request_upload_url(client, access, assignment_id, content_type=content_type)
    assert issued.status_code == 200, issued.json()
    object_key = issued.json()["object_key"]

    FakeStorageAdapter().write_object(object_key, b"fake image bytes", bucket=Bucket.PUBLIC_IMAGES)

    created = _add_image(client, access, assignment_id, object_key)
    assert created.status_code == 200, created.json()
    return created.json()


# --- 업로드 발급·등록 -----------------------------------------------------------


@pytest.mark.django_db
def test_owner_can_upload_an_image_to_a_draft_assignment(client, landing_type):
    root = _operator_client("root-img-1")
    pair = _sponsor_with_permission(client, root, "img-sponsor-1")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])

    response = _request_upload_url(client, pair["access"], assignment_id, content_type="image/webp")

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["object_key"].startswith(f"contest-image:{assignment_id}/")
    assert body["fields"]["Content-Type"] == "image/webp"


@pytest.mark.django_db
def test_uploaded_image_is_registered_and_appears_on_the_assignment(client, landing_type):
    root = _operator_client("root-img-2")
    pair = _sponsor_with_permission(client, root, "img-sponsor-2")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])

    first = _upload_and_register(client, pair["access"], assignment_id)
    second = _upload_and_register(client, pair["access"], assignment_id)

    assert first["order"] == 0
    assert second["order"] == 1

    detail = client.get(f"{ASSIGNMENTS_URL}/{assignment_id}", **_auth_header(pair["access"]))
    assert detail.status_code == 200
    images = detail.json()["images"]
    assert [img["id"] for img in images] == [first["id"], second["id"]]


@pytest.mark.django_db
def test_stranger_cannot_request_an_upload_url(client, landing_type):
    root = _operator_client("root-img-3")
    owner = _sponsor_with_permission(client, root, "img-sponsor-3")
    assignment_id = _create_assignment(client, owner["access"], deliverable_type_ids=[landing_type.id])

    stranger = _login(client, "img-stranger-3")
    response = _request_upload_url(client, stranger["access"], assignment_id)

    assert response.status_code == 404


@pytest.mark.django_db
def test_object_key_from_another_assignment_is_rejected(client, landing_type):
    root = _operator_client("root-img-4")
    pair = _sponsor_with_permission(client, root, "img-sponsor-4")
    assignment_a = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    assignment_b = _create_assignment(
        client, pair["access"], deliverable_type_ids=[landing_type.id], title="다른 과제"
    )

    issued = _request_upload_url(client, pair["access"], assignment_a)
    object_key = issued.json()["object_key"]

    response = _add_image(client, pair["access"], assignment_b, object_key)

    assert response.status_code == 422


@pytest.mark.django_db
def test_image_count_cap_comes_from_platform_policy(client, landing_type):
    from policies.services import get_current_policy

    policy = get_current_policy()
    policy.max_contest_images = 1
    policy.save(update_fields=["max_contest_images"])

    root = _operator_client("root-img-5")
    pair = _sponsor_with_permission(client, root, "img-sponsor-5")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])

    _upload_and_register(client, pair["access"], assignment_id)

    second_issue = _request_upload_url(client, pair["access"], assignment_id)
    assert second_issue.status_code == 422
    assert "1" in second_issue.json()["detail"]


# --- 열려 있고 제출이 없는 동안은 계속 고칠 수 있다 ------------------------------


@pytest.mark.django_db
def test_owner_can_add_reorder_and_remove_images_while_open_before_any_submission(
    client, landing_type
):
    root = _operator_client("root-img-6")
    pair = _sponsor_with_permission(client, root, "img-sponsor-6")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    _open_assignment(client, pair["access"], assignment_id)

    first = _upload_and_register(client, pair["access"], assignment_id)
    second = _upload_and_register(client, pair["access"], assignment_id)

    reordered = client.patch(
        f"{ASSIGNMENTS_URL}/{assignment_id}/images/{first['id']}",
        data={"order": 5},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert reordered.status_code == 200, reordered.content
    assert reordered.json()["order"] == 5

    removed = client.delete(
        f"{ASSIGNMENTS_URL}/{assignment_id}/images/{second['id']}",
        **_auth_header(pair["access"]),
    )
    assert removed.status_code == 200, removed.content
    assert ContestImage.objects.filter(id=second["id"]).exists() is False

    # 뺀 오브젝트는 그대로 남는다 — 공모전과 같은 이유(ADR-0005/0032).
    removed_object_key = ContestImage.objects.get(id=first["id"]).object_key
    assert removed_object_key  # sanity: 위에서 순서만 바꾼 first는 아직 존재한다


# --- 첫 제출이 문을 닫는다 ------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize("action", ["upload-url", "add", "reorder", "remove"])
def test_images_are_locked_once_a_submission_exists(client, landing_type, action):
    root = _operator_client("root-img-7")
    pair = _sponsor_with_permission(client, root, "img-sponsor-7")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    invite_code = _open_assignment(client, pair["access"], assignment_id)

    created = _upload_and_register(client, pair["access"], assignment_id)

    student = _login(client, "img-student-7")
    student_user_id = _user_id(client, student["access"])
    submitted = _submit(client, student["access"], assignment_id, invite_code, student_user_id)
    assert submitted.status_code == 201, submitted.content

    if action == "upload-url":
        response = _request_upload_url(client, pair["access"], assignment_id)
    elif action == "add":
        response = _add_image(
            client, pair["access"], assignment_id, f"contest-image:{assignment_id}/deadbeef"
        )
    elif action == "reorder":
        response = client.patch(
            f"{ASSIGNMENTS_URL}/{assignment_id}/images/{created['id']}",
            data={"order": 3},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )
    else:
        response = client.delete(
            f"{ASSIGNMENTS_URL}/{assignment_id}/images/{created['id']}",
            **_auth_header(pair["access"]),
        )

    assert response.status_code == 409
    # 이미지도 「첫 제출이 문을 닫는다」의 같은 문구를 받는다 — 새 잠금 규칙이
    # 아니라 #209의 게이트를 그대로 재사용했다는 뜻이다.
    assert "제출" in response.json()["detail"]


@pytest.mark.django_db
def test_still_open_but_zero_submissions_stays_editable(client, landing_type):
    """제출이 하나도 없으면 ASSIGNMENT_OPEN 이어도 계속 고칠 수 있다 — 마감(문을
    닫는 사건은 첫 제출이지 「열림」 자체가 아니다)."""

    root = _operator_client("root-img-8")
    pair = _sponsor_with_permission(client, root, "img-sponsor-8")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    _open_assignment(client, pair["access"], assignment_id)

    response = _upload_and_register(client, pair["access"], assignment_id)
    assert response["order"] == 0


# --- InviteCode로 들어온 학생이 로그인 없이도 본다 -------------------------------


@pytest.mark.django_db
def test_invited_student_sees_images_without_authentication(client, landing_type):
    root = _operator_client("root-img-9")
    pair = _sponsor_with_permission(client, root, "img-sponsor-9")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])
    invite_code = _open_assignment(client, pair["access"], assignment_id)

    uploaded = _upload_and_register(client, pair["access"], assignment_id)

    anonymous = Client()
    response = anonymous.get(f"{ASSIGNMENTS_URL}/invite/{invite_code}")
    assert response.status_code == 200, response.content
    images = response.json()["images"]
    assert [img["id"] for img in images] == [uploaded["id"]]
    assert images[0]["url"].endswith(
        f"/{ContestImage.objects.get(id=uploaded['id']).object_key}"
    )


@pytest.mark.django_db
def test_assignment_without_images_has_an_empty_list_not_an_error(client, landing_type):
    root = _operator_client("root-img-10")
    pair = _sponsor_with_permission(client, root, "img-sponsor-10")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])

    detail = client.get(f"{ASSIGNMENTS_URL}/{assignment_id}", **_auth_header(pair["access"]))
    assert detail.status_code == 200
    assert detail.json()["images"] == []


@pytest.mark.django_db
def test_assignment_images_do_not_leak_into_contests_and_vice_versa(client, landing_type):
    """공모전과 과제는 같은 `Contest` 모델을 공유하지만(ADR-0028), 이미지 표면이
    서로의 id를 대신 받아주면 안 된다 — 공모전 라우터의 게이트
    (`_get_owned_draft_contest`)는 `is_assignment`를 명시적으로 거부한다."""

    root = _operator_client("root-img-11")
    pair = _sponsor_with_permission(client, root, "img-sponsor-11")
    assignment_id = _create_assignment(client, pair["access"], deliverable_type_ids=[landing_type.id])

    # `/api/contests/{assignment_id}/images/upload-url`로 과제 id를 공모전
    # 라우터에 들이밀면 소유자여도 막힌다(409 — DRAFT는 맞지만 is_assignment다).
    cross_response = client.post(
        f"{CONTESTS_URL}/{assignment_id}/images/upload-url",
        data={"content_type": "image/png"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert cross_response.status_code == 409
