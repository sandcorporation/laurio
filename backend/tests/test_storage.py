"""스토리지 어댑터 + presigned 업로드·다운로드 (ADR-0005, ADR-0007, ADR-0014).

이 API는 target_ref를 불투명한 문자열로 다룬다. Submission/Contest 모델은 이 앱이
모른다. 대상 상태 판정(소유자·공개 여부)은 STORAGE_TARGET_RESOLVER 훅으로 위임하고,
여기서는 tests.storage_fakes.FakeTargetStateResolver로 override_settings 해 그
훅이 실제로 호출·집행되는지를 검증한다.

인증은 실제 클라이언트와 같은 경로로 한다 — 소셜 로그인이 돌려주는 JWT를
`Authorization: Bearer` 헤더에 싣는다. Django 세션(`client.login`/`force_login`)은
이 플랫폼 어디에서도 만들어지지 않는다(어떤 로그인 경로도 `auth.login()`을 부르지
않는다) — 세션으로 통과하던 예전 테스트는 실제 클라이언트가 절대 밟을 수 없는
경로를 검증하고 있었다(#10 리뷰 지적). CSRF 검사도 세션 인증 특유의 보완책이었으므로
JWT 전환과 함께 사라진다 — 그 검사를 표적으로 한 테스트도 함께 걷어낸다.

앱은 절대 MinIO를 필요로 하지 않는다 — STORAGE_BACKEND 기본값이 "fake"라서
이 테스트 전체가 실제 스토리지 없이 돈다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from django.test import override_settings

FAKE_RESOLVER = "tests.storage_fakes.FakeTargetStateResolver"
FAKE_MAX_SIZE_RESOLVER = "tests.storage_fakes.FakeMaxUploadSizeResolver"


def _object_key(target_ref: str) -> str:
    """서버가 실제로 만드는 것과 같은 모양(32자리 소문자 16진수 접미어)."""
    return f"{target_ref}/{uuid4().hex}"


def _login(client, uid="dev-1", email=None):
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


def _login_and_get_id(client, uid="dev-1") -> tuple[str, int]:
    """실제 클라이언트처럼 소셜 로그인해 (access token, User pk) 를 돌려준다."""

    pair = _login(client, uid=uid)
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert me.status_code == 200
    return pair["access"], me.json()["id"]


# --- 업로드 ---------------------------------------------------------------


@pytest.mark.django_db
def test_upload_requires_authentication(client):
    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": "private:1:submission-42-source"},
        content_type="application/json",
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_authenticated_owner_can_request_upload_url(client):
    access, user_id = _login_and_get_id(client)
    target_ref = f"private:{user_id}:submission-42-source"

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": target_ref, "content_type": "application/zip"},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "PUT"
    assert body["object_key"].startswith(f"{target_ref}/")
    assert body["upload_url"]
    assert body["headers"] == {"Content-Type": "application/zip"}
    assert body["expires_at"]


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_authenticated_non_owner_cannot_request_upload_url(client):
    """로그인했다고 아무 target_ref에나 업로드할 수 있는 게 아니다 — 소유자만.

    이걸 확인하지 않으면 로그인한 누구나 다른 사람의 namespace에 파일을 심을 수
    있고, 마감 후 공개로 바뀌는 슬롯이라면 그 파일이 그대로 공개 다운로드된다
    (#10 리뷰 지적).
    """
    attacker_access, _attacker_id = _login_and_get_id(client, uid="attacker")
    _victim_access, victim_id = _login_and_get_id(client, uid="victim")

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": f"private:{victim_id}:submission-42-source"},
        content_type="application/json",
        **_auth_header(attacker_access),
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(
    STORAGE_TARGET_RESOLVER=FAKE_RESOLVER,
    STORAGE_MAX_UPLOAD_SIZE_RESOLVER=FAKE_MAX_SIZE_RESOLVER,
)
def test_upload_with_a_byte_cap_is_issued_as_presigned_post(client):
    """`STORAGE_MAX_UPLOAD_SIZE_RESOLVER`가 이 target_ref에 상한을 매기면
    presigned PUT이 아니라 POST가 나가고, 상한이 서명된 정책 필드(fake 어댑터의
    X-Fake-Max-Size-Bytes)에 실린다 — presigned PUT은 서명에 크기를 묶을
    수단이 없어 상한이 권고에 그친다(#261, ADR-0035)."""
    access, user_id = _login_and_get_id(client)
    target_ref = f"private:{user_id}:cap100"

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": target_ref},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "POST"
    assert body["fields"]["X-Fake-Max-Size-Bytes"] == "100"
    assert body["max_size_bytes"] == 100


@pytest.mark.django_db
@override_settings(
    STORAGE_TARGET_RESOLVER=FAKE_RESOLVER,
    STORAGE_MAX_UPLOAD_SIZE_RESOLVER=FAKE_MAX_SIZE_RESOLVER,
)
def test_upload_without_a_byte_cap_stays_presigned_put(client):
    """이 target_ref에 상한이 없으면(리졸버가 None을 돌려주면) 지금까지처럼
    presigned PUT이 나간다 — 상한 배선이 다른 모든 업로드를 바꾸지 않는다."""
    access, user_id = _login_and_get_id(client)
    target_ref = f"private:{user_id}:submission-42-source"

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": target_ref},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["method"] == "PUT"
    assert body["fields"] == {}
    assert body["max_size_bytes"] is None


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER="storage.policy.DenyUnknownTargetResolver")
def test_upload_falls_back_to_deny_by_default_without_a_real_resolver(client):
    """리졸버가 아무 도메인도 모르면(fail-closed 기본값), 로그인한 사용자라도
    업로드할 수 없다 — 누구도 owner로 확인되지 않는다."""

    access, user_id = _login_and_get_id(client)

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": f"private:{user_id}:submission-42-source"},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_upload_never_uses_a_real_network_call(client):
    """기본 STORAGE_BACKEND(=fake)로 MinIO 없이 URL이 발급되는지 확인한다."""
    access, user_id = _login_and_get_id(client)
    target_ref = f"private:{user_id}:submission-42-source"

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": target_ref},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 200
    assert response.json()["upload_url"].startswith("https://fake-storage.test/")


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_upload_url_expiry_reflects_configured_ttl(client):
    """만료가 실제로 설정값을 반영하는지 값 자체로 검증한다.

    문자열에 "expires=" 가 있다는 것만으로는 TTL 을 하드코딩해도 통과하므로
    (예전 버전의 버그), 실제 초 단위 차이를 계산해 검증한다.
    """
    access, user_id = _login_and_get_id(client)
    target_ref = f"private:{user_id}:submission-42-source"

    with override_settings(STORAGE_UPLOAD_URL_TTL_SECONDS=60):
        response = client.post(
            "/api/storage/uploads",
            data={"target_ref": target_ref},
            content_type="application/json",
            **_auth_header(access),
        )

    assert response.status_code == 200
    expires_at = datetime.fromisoformat(response.json()["expires_at"])
    delta = (expires_at - datetime.now(timezone.utc)).total_seconds()
    assert 55 <= delta <= 60


@pytest.mark.django_db
def test_invalid_target_ref_is_rejected(client):
    access, _user_id = _login_and_get_id(client)

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": "../../etc/passwd"},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 422


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
    access, user_id = _login_and_get_id(client)
    target_ref = f"private:{user_id}:submission-source"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
        **_auth_header(access),
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
    access, user_id = _login_and_get_id(client)
    target_ref = f"private:{user_id}:submission-source"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 200
    assert "attachment" in response.json()["download_url"]


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_non_owner_cannot_download_private_target(client):
    _owner_access, owner_id = _login_and_get_id(client, uid="owner")
    caller_access, _caller_id = _login_and_get_id(client, uid="someone-else")

    target_ref = f"private:{owner_id}:submission-source"
    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
        **_auth_header(caller_access),
    )

    assert response.status_code == 403


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER=FAKE_RESOLVER)
def test_public_target_is_downloadable_without_authentication(client):
    """ADR-0014: 마감 후 데모/영상은 로그인 없이도 전면 공개된다."""
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
    access, user_id = _login_and_get_id(client)
    own_target = f"private:{user_id}:submission-source"
    other_target = f"private:{user_id}:other-submission-source"

    response = client.post(
        "/api/storage/downloads",
        # target_ref로는 자기 소유를 대지만 object_key는 다른 target 아래 것을 요청한다.
        data={"target_ref": own_target, "object_key": _object_key(other_target)},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_object_key_with_path_traversal_is_rejected(client):
    """object_key는 서버가 만든 "<target_ref>/<32자리 hex>" 모양만 허용한다.
    ".."을 심어 접두어 밖으로 나가려는 시도는 패턴 검증에서 거부된다 — botocore가
    SigV4 서명 전에 dot-segment를 정규화해주지 않으므로 여기서 막아야 한다."""
    access, _user_id = _login_and_get_id(client)

    response = client.post(
        "/api/storage/downloads",
        data={
            "target_ref": "submission-42-source",
            "object_key": "submission-42-source/../../other-target/secret",
        },
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 422


@pytest.mark.django_db
@override_settings(STORAGE_TARGET_RESOLVER="storage.policy.DenyUnknownTargetResolver")
def test_download_falls_back_to_deny_by_default_without_a_real_resolver(client):
    """리졸버가 아무 도메인도 모르면(fail-closed 기본값) 로그인한 사용자라도
    다운로드가 막힌다."""
    access, _user_id = _login_and_get_id(client)
    target_ref = "submission-42-source"

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": target_ref, "object_key": _object_key(target_ref)},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 403
