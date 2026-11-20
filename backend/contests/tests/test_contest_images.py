"""ContestImage — 개최자가 이미지를 올리면 참가자가 본다 (#234, ADR-0032).

편집 게이트는 Requirement CRUD와 정확히 같다 — `_get_owned_draft_contest`가 소유자
(아니면 404)와 DRAFT 상태(아니면 409)를 함께 지킨다. 업로드는 presigned **POST**로
발급되고(크기 상한·content-type이 서명된 정책에 담긴다), 실제 행은 업로드가 끝난
뒤 `POST .../images`로 등록한다. 제거는 행만 지운다 — object_key가 가리키는
바이트는 FakeStorageAdapter의 인메모리 저장소에 그대로 남는 것으로 확인한다.
"""

from __future__ import annotations

import pytest

from contests.models import Category, Contest, ContestImage, DeliverableType
from storage.adapters.base import Bucket
from storage.adapters.fake import FakeStorageAdapter

CONTESTS_URL = "/api/contests"


def _login(client, uid="sponsor-1", email=None):
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


def _verify(client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


@pytest.fixture
def category(db):
    return Category.objects.create(name="교육")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _create_draft(client, access, *, category, deliverable_type_ids, prize=2_000_000):
    response = client.post(
        CONTESTS_URL,
        data={
            "title": "이미지 붙일 초안",
            "category_id": category.id,
            "deliverable_type_ids": deliverable_type_ids,
            "description": "설명",
            "prize": prize,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


def _request_upload_url(client, access, contest_id, *, content_type="image/png"):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/images/upload-url",
        data={"content_type": content_type},
        content_type="application/json",
        **_auth_header(access),
    )


def _add_image(client, access, contest_id, object_key):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/images",
        data={"object_key": object_key},
        content_type="application/json",
        **_auth_header(access),
    )


def _upload_and_register(client, access, contest_id, *, content_type="image/png") -> dict:
    """presigned POST를 받고, 실제 업로드를 흉내낸 뒤(FakeStorageAdapter에 바이트를
    미리 채운다) 행을 등록한다 — 실제 브라우저의 두 단계 흐름과 같다."""

    issued = _request_upload_url(client, access, contest_id, content_type=content_type)
    assert issued.status_code == 200, issued.json()
    object_key = issued.json()["object_key"]

    FakeStorageAdapter().write_object(object_key, b"fake image bytes", bucket=Bucket.PUBLIC_IMAGES)

    created = _add_image(client, access, contest_id, object_key)
    assert created.status_code == 200, created.json()
    return created.json()


# --- 업로드 URL 발급 --------------------------------------------------------


@pytest.mark.django_db
def test_owner_can_request_an_upload_url_with_size_and_content_type_bound(
    client, category, landing_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-1")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    response = _request_upload_url(client, pair["access"], contest["id"], content_type="image/webp")

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "POST"
    assert body["object_key"].startswith(f"contest-image:{contest['id']}/")
    # 크기 상한·content-type이 서명된 정책 필드 안에 실제로 담긴다(ADR-0032) —
    # 화면이 아니라 스토리지 자신이 위반을 거절할 수 있어야 한다.
    assert body["fields"]["Content-Type"] == "image/webp"
    assert "X-Fake-Max-Size-Bytes" in body["fields"]


@pytest.mark.django_db
def test_non_image_content_type_is_rejected(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-2")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    response = _request_upload_url(
        client, pair["access"], contest["id"], content_type="application/zip"
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_stranger_cannot_request_an_upload_url(client, category, landing_type):
    owner = _login(client, uid="owner")
    _verify(client, owner["access"], ci="owner-ci")
    contest = _create_draft(client, owner["access"], category=category, deliverable_type_ids=[landing_type.id])

    stranger = _login(client, uid="stranger")
    response = _request_upload_url(client, stranger["access"], contest["id"])

    assert response.status_code == 404


# --- 등록 --------------------------------------------------------------


@pytest.mark.django_db
def test_uploaded_image_is_registered_and_appears_in_order(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-3")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    first = _upload_and_register(client, pair["access"], contest["id"])
    second = _upload_and_register(client, pair["access"], contest["id"])

    assert first["order"] == 0
    assert second["order"] == 1

    reread = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))
    assert reread.status_code == 200
    images = reread.json()["images"]
    assert [img["id"] for img in images] == [first["id"], second["id"]]
    # url은 백엔드가 이미 조립한 서명 없는 공개 주소다.
    assert images[0]["url"].endswith(f"/{ContestImage.objects.get(id=first['id']).object_key}")


@pytest.mark.django_db
def test_object_key_from_another_contest_is_rejected(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-4")
    contest_a = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])
    contest_b = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    issued = _request_upload_url(client, pair["access"], contest_a["id"])
    object_key = issued.json()["object_key"]

    response = _add_image(client, pair["access"], contest_b["id"], object_key)

    assert response.status_code == 422


@pytest.mark.django_db
def test_image_count_cap_comes_from_platform_policy(client, category, landing_type):
    from policies.services import get_current_policy

    policy = get_current_policy()
    policy.max_contest_images = 1
    policy.save(update_fields=["max_contest_images"])

    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-5")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    _upload_and_register(client, pair["access"], contest["id"])

    # 상한(1장)에 도달했다 — 발급도, 등록도 둘 다 거절한다.
    second_issue = _request_upload_url(client, pair["access"], contest["id"])
    assert second_issue.status_code == 422
    assert "1" in second_issue.json()["detail"]


# --- 순서 변경 --------------------------------------------------------------


@pytest.mark.django_db
def test_owner_can_reorder_images(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-6")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    first = _upload_and_register(client, pair["access"], contest["id"])
    second = _upload_and_register(client, pair["access"], contest["id"])

    response = client.patch(
        f"{CONTESTS_URL}/{contest['id']}/images/{first['id']}",
        data={"order": 5},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["order"] == 5

    reread = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))
    images = reread.json()["images"]
    # 5로 옮긴 첫 번째 이미지가 이제 두 번째(order=1인 second) 뒤로 간다.
    assert [img["id"] for img in images] == [second["id"], first["id"]]


# --- 제거: 행만 지운다 -------------------------------------------------------


@pytest.mark.django_db
def test_removing_an_image_only_detaches_the_row_object_bytes_survive(
    client, category, landing_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-7")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    created = _upload_and_register(client, pair["access"], contest["id"])
    object_key = ContestImage.objects.get(id=created["id"]).object_key

    response = client.delete(
        f"{CONTESTS_URL}/{contest['id']}/images/{created['id']}",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert ContestImage.objects.filter(id=created["id"]).exists() is False

    # 오브젝트는 그대로 남아 있다 — 어댑터에 삭제 메서드가 없다(ADR-0005/0032).
    assert (
        FakeStorageAdapter().read_object(object_key, bucket=Bucket.PUBLIC_IMAGES)
        == b"fake image bytes"
    )

    reread = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))
    assert reread.json()["images"] == []


# --- 결제 뒤에는 잠긴다 -------------------------------------------------------


@pytest.mark.django_db
@pytest.mark.parametrize(
    "action",
    ["upload-url", "add", "reorder", "remove"],
)
def test_images_are_locked_once_the_contest_leaves_draft(client, category, landing_type, action):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-8")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    created = _upload_and_register(client, pair["access"], contest["id"])

    Contest.objects.filter(id=contest["id"]).update(status=Contest.Status.PUBLISHED)

    if action == "upload-url":
        response = _request_upload_url(client, pair["access"], contest["id"])
    elif action == "add":
        response = _add_image(client, pair["access"], contest["id"], f"contest-image:{contest['id']}/deadbeef")
    elif action == "reorder":
        response = client.patch(
            f"{CONTESTS_URL}/{contest['id']}/images/{created['id']}",
            data={"order": 3},
            content_type="application/json",
            **_auth_header(pair["access"]),
        )
    else:
        response = client.delete(
            f"{CONTESTS_URL}/{contest['id']}/images/{created['id']}",
            **_auth_header(pair["access"]),
        )

    assert response.status_code == 409


# --- 공개 상세: 로그인 없이도, JS 없이도 보인다 -------------------------------


@pytest.mark.django_db
def test_published_contests_public_detail_includes_images_without_authentication(
    client, category, landing_type
):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-9")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])
    created = _upload_and_register(client, pair["access"], contest["id"])

    Contest.objects.filter(id=contest["id"]).update(status=Contest.Status.PUBLISHED)

    # 인증 헤더 없이 — 공개 상세는 로그인하지 않은 방문자도 본다(spec #225 user story 11).
    response = client.get(f"{CONTESTS_URL}/{contest['id']}")

    assert response.status_code == 200
    images = response.json()["images"]
    assert len(images) == 1
    assert images[0]["id"] == created["id"]
    assert images[0]["url"].startswith("http")


@pytest.mark.django_db
def test_contest_without_images_has_an_empty_list_not_an_error(client, category, landing_type):
    pair = _login(client)
    _verify(client, pair["access"], ci="sponsor-ci-10")
    contest = _create_draft(client, pair["access"], category=category, deliverable_type_ids=[landing_type.id])

    response = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))

    assert response.status_code == 200
    assert response.json()["images"] == []
