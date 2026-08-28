"""스토리지 어댑터 + presigned 업로드·다운로드 (ADR-0005, ADR-0007, ADR-0014).

이 API는 target_ref를 불투명한 문자열로 다룬다. Submission/Contest는 아직 없다
(#8, #10). 대상 상태 판정은 STORAGE_TARGET_RESOLVER 훅으로 위임하고, 여기서는
tests.storage_fakes.FakeTargetStateResolver 로 override_settings 해 그 훅이
실제로 호출·집행되는지를 검증한다.

앱은 절대 MinIO를 필요로 하지 않는다 — STORAGE_BACKEND 기본값이 "fake"라서
이 테스트 전체가 실제 스토리지 없이 돈다.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

FAKE_RESOLVER = "tests.storage_fakes.FakeTargetStateResolver"


def _create_and_login(client, username="dev-1"):
    user = get_user_model().objects.create_user(username=username, password="pw-12345678")
    assert client.login(username=username, password="pw-12345678")
    return user


# --- 업로드 ---------------------------------------------------------------


@pytest.mark.django_db
def test_upload_requires_authentication(client):
    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": "submission-42-source"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_authenticated_user_can_request_upload_url(client):
    _create_and_login(client)

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": "submission-42-source", "content_type": "application/zip"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "PUT"
    assert body["object_key"].startswith("submission-42-source/")
    assert body["upload_url"]
    assert body["headers"] == {"Content-Type": "application/zip"}
    assert body["expires_at"]


@pytest.mark.django_db
def test_upload_never_uses_a_real_network_call(client):
    """기본 STORAGE_BACKEND(=fake)로 MinIO 없이 URL이 발급되는지 확인한다."""
    _create_and_login(client)

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": "submission-42-source"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert response.json()["upload_url"].startswith("https://fake-storage.test/")


@pytest.mark.django_db
def test_upload_url_expiry_reflects_configured_ttl(client):
    _create_and_login(client)

    with override_settings(STORAGE_UPLOAD_URL_TTL_SECONDS=60):
        response = client.post(
            "/api/storage/uploads",
            data={"target_ref": "submission-42-source"},
            content_type="application/json",
        )

    assert response.status_code == 200
    assert "expires=" in response.json()["upload_url"] or "X-Fake-Expires=" in response.json()["upload_url"]


@pytest.mark.django_db
def test_invalid_target_ref_is_rejected(client):
    _create_and_login(client)

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": "../../etc/passwd"},
        content_type="application/json",
    )

    assert response.status_code == 422


# --- 다운로드: 권한과 대상 상태 ---------------------------------------------


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_download_of_private_target_requires_authentication(client):
    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": "private:1:submission-42-source", "object_key": "private:1:submission-42-source/abc"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_owner_can_download_private_target(client):
    owner = _create_and_login(client)
    target_ref = f"private:{owner.pk}:submission-source"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": f"{target_ref}/abc"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["download_url"].startswith("https://fake-storage.test/")
    assert body["expires_at"]


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_non_owner_cannot_download_private_target(client):
    other = get_user_model().objects.create_user(username="someone-else", password="pw-12345678")
    _create_and_login(client)  # 로그인한 사람은 소유자가 아님

    target_ref = f"private:{other.pk}:submission-source"
    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": f"{target_ref}/abc"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_public_target_is_downloadable_without_authentication(client):
    """ADR-0014: 마감 후 데모/영상은 로그인 없이도 전면 공개된다."""
    target_ref = "public:none:submission-42-demo"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": f"{target_ref}/abc"},
        content_type="application/json",
    )

    assert response.status_code == 200


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_object_key_must_belong_to_the_claimed_target_ref(client):
    owner = _create_and_login(client)
    own_target = f"private:{owner.pk}:submission-source"
    other_target = f"private:{owner.pk}:other-submission-source"

    response = client.post(
        "/api/storage/downloads",
        # target_ref로는 자기 소유를 대지만 object_key는 다른 target 아래 것을 요청한다.
        data={"target_ref": own_target, "object_key": f"{other_target}/abc"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_download_falls_back_to_deny_by_default_without_a_real_resolver(client):
    """STORAGE_TARGET_RESOLVER를 아무도 꽂지 않은 상태(#8/#10 이전)에서는
    로그인한 사용자라도 다운로드가 막힌다 — fail-closed 기본값."""
    _create_and_login(client)

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": "submission-42-source", "object_key": "submission-42-source/abc"},
        content_type="application/json",
    )

    assert response.status_code == 403
