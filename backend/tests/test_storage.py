"""스토리지 어댑터 + presigned 업로드·다운로드 (ADR-0005, ADR-0007, ADR-0014).

이 API는 target_ref를 불투명한 문자열로 다룬다. Submission/Contest는 아직 없다
(#8, #10). 대상 상태 판정은 STORAGE_TARGET_RESOLVER 훅으로 위임하고, 여기서는
tests.storage_fakes.FakeTargetStateResolver 로 override_settings 해 그 훅이
실제로 호출·집행되는지를 검증한다.

앱은 절대 MinIO를 필요로 하지 않는다 — STORAGE_BACKEND 기본값이 "fake"라서
이 테스트 전체가 실제 스토리지 없이 돈다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.middleware.csrf import get_token
from django.test import Client, RequestFactory, override_settings

FAKE_RESOLVER = "tests.storage_fakes.FakeTargetStateResolver"


def _object_key(target_ref: str) -> str:
    """서버가 실제로 만드는 것과 같은 모양(32자리 소문자 16진수 접미어)."""
    return f"{target_ref}/{uuid4().hex}"


def _create_and_login(client, username="dev-1"):
    user = get_user_model().objects.create_user(username=username, password="pw-12345678")
    assert client.login(username=username, password="pw-12345678")
    return user


def _csrf_token_and_cookie() -> tuple[str, str]:
    """실제 로그인 뷰 없이도 유효한 CSRF 토큰/쿠키 쌍을 만든다.

    get_token()이 request.META["CSRF_COOKIE"]에 채우는 비밀값이 쿠키가 되고,
    반환값(마스킹된 토큰)이 X-CSRFToken 헤더가 된다. 같은 비밀에서 나온 토큰이라
    Django의 CsrfViewMiddleware가 정상으로 검증한다.
    """
    request = RequestFactory().get("/")
    token = get_token(request)
    secret = request.META["CSRF_COOKIE"]
    return token, secret


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
    """만료가 실제로 설정값을 반영하는지 값 자체로 검증한다.

    문자열에 "expires=" 가 있다는 것만으로는 TTL 을 하드코딩해도 통과하므로
    (예전 버전의 버그), 실제 초 단위 차이를 계산해 검증한다.
    """
    _create_and_login(client)

    with override_settings(STORAGE_UPLOAD_URL_TTL_SECONDS=60):
        response = client.post(
            "/api/storage/uploads",
            data={"target_ref": "submission-42-source"},
            content_type="application/json",
        )

    assert response.status_code == 200
    expires_at = datetime.fromisoformat(response.json()["expires_at"])
    delta = (expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 55 <= delta <= 60


@pytest.mark.django_db
def test_invalid_target_ref_is_rejected(client):
    _create_and_login(client)

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": "../../etc/passwd"},
        content_type="application/json",
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_upload_without_csrf_token_is_rejected_even_with_valid_session():
    """세션 쿠키만으로는 부족하다 — 폼 전송으로 위조 가능하므로 CSRF 토큰도 요구한다."""
    strict_client = Client(enforce_csrf_checks=True)
    _create_and_login(strict_client)

    response = strict_client.post(
        "/api/storage/uploads",
        data={"target_ref": "submission-42-source"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_upload_with_valid_session_and_csrf_token_succeeds():
    strict_client = Client(enforce_csrf_checks=True)
    _create_and_login(strict_client)
    token, secret = _csrf_token_and_cookie()
    strict_client.cookies["csrftoken"] = secret

    response = strict_client.post(
        "/api/storage/uploads",
        data={"target_ref": "submission-42-source"},
        content_type="application/json",
        HTTP_X_CSRFTOKEN=token,
    )

    assert response.status_code == 200


# --- 다운로드: 권한과 대상 상태 ---------------------------------------------


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_download_of_private_target_requires_authentication(client):
    target_ref = "private:1:submission-42-source"
    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
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
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["download_url"].startswith("https://fake-storage.test/")
    assert body["expires_at"]


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_download_url_forces_attachment_disposition(client):
    """소스·빌드는 신뢰할 수 없는 콘텐츠다. 저장 시 Content-Type이 무엇이었든
    다운로드는 항상 첨부파일로 강제해야 브라우저가 스토리지 오리진에서
    text/html 등을 인라인으로 실행하지 못한다."""
    owner = _create_and_login(client)
    target_ref = f"private:{owner.pk}:submission-source"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert "attachment" in response.json()["download_url"]


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_non_owner_cannot_download_private_target(client):
    other = get_user_model().objects.create_user(username="someone-else", password="pw-12345678")
    _create_and_login(client)  # 로그인한 사람은 소유자가 아님

    target_ref = f"private:{other.pk}:submission-source"
    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_download_owner_without_csrf_token_is_rejected():
    strict_client = Client(enforce_csrf_checks=True)
    owner = _create_and_login(strict_client)
    target_ref = f"private:{owner.pk}:submission-source"

    response = strict_client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_public_target_is_downloadable_without_authentication(client):
    """ADR-0014: 마감 후 데모/영상은 로그인 없이도 전면 공개된다. 쿠키로 신원을
    주장하지 않는 요청이므로 CSRF 토큰도 필요 없다."""
    target_ref = "public:none:submission-42-demo"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
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
        data={"target_ref": own_target, "object_key": _object_key(other_target)},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_object_key_with_path_traversal_is_rejected(client):
    """object_key는 서버가 만든 "<target_ref>/<32자리 hex>" 모양만 허용한다.
    ".."을 심어 접두어 밖으로 나가려는 시도는 패턴 검증에서 거부된다 — botocore가
    SigV4 서명 전에 dot-segment를 정규화해주지 않으므로 여기서 막아야 한다."""
    _create_and_login(client)

    response = client.post(
        "/api/storage/downloads",
        data={
            "target_ref": "submission-42-source",
            "object_key": "submission-42-source/../../other-target/secret",
        },
        content_type="application/json",
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_download_falls_back_to_deny_by_default_without_a_real_resolver(client):
    """STORAGE_TARGET_RESOLVER를 아무도 꽂지 않은 상태(#8/#10 이전)에서는
    로그인한 사용자라도 다운로드가 막힌다 — fail-closed 기본값."""
    _create_and_login(client)
    target_ref = "submission-42-source"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
    )

    assert response.status_code == 403
