"""스토리지 어댑터가 버킷을 둘 다룬다 (#233, ADR-0032).

이 티켓은 새 HTTP 표면을 열지 않는다 — "어느 버킷에 쓰는가"를 호출 시점에 고를 수
있게 어댑터 계약을 넓히는 프리팩터이고, 실제 HTTP 노출은 #234(ContestImage)가
한다. 그래서 여기서는 이 저장소의 다른 파일들이 이미 그렇게 해 온 대로
(`FakeStorageAdapter().write_object(...)`를 직접 부르는 tests/test_scoring.py 등)
어댑터를 직접 호출해 계약을 확인한다 — 이 계약 자체에는 아직 걸어 다닐 HTTP
경로가 없다.

배포 부팅 가드(`STORAGE_IMAGES_BASE_URL`이 배포 환경에서 비면 거부)는
tests/test_deployment_config.py가 그 파일의 나머지 가드와 같은 방식(서브프로세스로
`manage.py check` 실행)으로 검증한다 — 이 파일이 다루는 것이 아니다.
"""

from __future__ import annotations

from datetime import timedelta

from storage.adapters.base import Bucket
from storage.adapters.fake import FakeStorageAdapter
from storage.public import compose_public_image_url


def test_bucket_defaults_to_private_and_matches_previous_behavior():
    """`bucket`을 생략하는 기존 호출부는 지금까지와 정확히 같은 URL을 받는다."""

    adapter = FakeStorageAdapter()
    presigned = adapter.presign_upload(
        "submission:1:2:source/abc", content_type="application/zip", expires_in=timedelta(minutes=15)
    )

    assert presigned.url.startswith(FakeStorageAdapter.base_url)
    assert presigned.method == "PUT"
    assert presigned.fields == {}


def test_public_images_bucket_uses_a_different_base_url():
    adapter = FakeStorageAdapter()
    presigned = adapter.presign_upload(
        "contest-image:1/abc",
        bucket=Bucket.PUBLIC_IMAGES,
        content_type="image/png",
        expires_in=timedelta(minutes=15),
        max_size_bytes=10 * 1024 * 1024,
    )

    assert presigned.url.startswith(FakeStorageAdapter.images_base_url)
    assert not presigned.url.startswith(FakeStorageAdapter.base_url + "/")


def test_presign_upload_with_max_size_bytes_issues_a_post_with_signed_constraints():
    """이미지처럼 크기 상한이 필요한 업로드는 PUT이 아니라 POST를 받고, 그 상한과
    content-type이 서명된 필드 안에 실제로 담긴다 — 브라우저가 아니라 스토리지가
    위반을 거절할 수 있어야 한다(ADR-0032)."""

    adapter = FakeStorageAdapter()
    presigned = adapter.presign_upload(
        "contest-image:1/abc",
        bucket=Bucket.PUBLIC_IMAGES,
        content_type="image/webp",
        expires_in=timedelta(minutes=15),
        max_size_bytes=10 * 1024 * 1024,
    )

    assert presigned.method == "POST"
    assert presigned.fields["X-Fake-Max-Size-Bytes"] == str(10 * 1024 * 1024)
    assert presigned.fields["Content-Type"] == "image/webp"


def test_write_and_read_object_are_scoped_per_bucket():
    """같은 object_key라도 버킷이 다르면 서로의 바이트를 보지 않는다."""

    adapter = FakeStorageAdapter()
    key = "contest-image:999/same-key"
    adapter.write_object(key, b"private bytes", bucket=Bucket.PRIVATE)
    adapter.write_object(key, b"public bytes", bucket=Bucket.PUBLIC_IMAGES)

    assert adapter.read_object(key, bucket=Bucket.PRIVATE) == b"private bytes"
    assert adapter.read_object(key, bucket=Bucket.PUBLIC_IMAGES) == b"public bytes"


def test_read_object_without_bucket_still_defaults_to_private():
    """기존 호출부(`FakeStorageAdapter().write_object(key, bytes)` 하나만 인자로
    받는 형태)가 여전히 통한다 — bucket 매개변수가 필수가 아니다."""

    adapter = FakeStorageAdapter()
    key = "submission:1:2:source/legacy"
    adapter.write_object(key, b"legacy bytes")

    assert adapter.read_object(key) == b"legacy bytes"


def test_compose_public_image_url_appends_object_key_to_the_configured_base(settings):
    settings.STORAGE_IMAGES_BASE_URL = "https://images.example.test/codemit-public-images"

    url = compose_public_image_url("contest-image:1/abc123")

    assert url == "https://images.example.test/codemit-public-images/contest-image:1/abc123"


# --- content-type (#238) ------------------------------------------------------


def test_write_object_records_the_given_content_type():
    """호출자가 형식을 아는 바이트를 쓸 때 넘긴 content_type이 그대로 기록된다."""

    adapter = FakeStorageAdapter()
    key = "contest-image:1/with-type"
    adapter.write_object(key, b"webp bytes", bucket=Bucket.PUBLIC_IMAGES, content_type="image/webp")

    assert adapter.written_content_type(key, bucket=Bucket.PUBLIC_IMAGES) == "image/webp"


# --- 삭제 (#262, ADR-0035) ----------------------------------------------------


def test_delete_object_removes_the_bytes():
    adapter = FakeStorageAdapter()
    key = "submission:1:2:demo-video/to-delete"
    adapter.write_object(key, b"video bytes")

    adapter.delete_object(key)

    assert adapter.read_object(key) is None


def test_delete_object_is_idempotent_for_an_already_missing_key():
    """파기 스캔의 멱등성 요구(#262) — 지운 다음 기록하기 전에 죽으면 다음 실행이
    같은 키를 한 번 더 지운다. 그 재시도가 예외를 만나면 스캔이 poison pill을
    만든다."""

    adapter = FakeStorageAdapter()
    key = "submission:1:2:demo-video/never-existed"

    adapter.delete_object(key)  # 예외 없이 조용히 끝난다.

    assert adapter.read_object(key) is None


def test_delete_object_is_scoped_per_bucket():
    adapter = FakeStorageAdapter()
    key = "contest-image:1/same-key"
    adapter.write_object(key, b"private bytes", bucket=Bucket.PRIVATE)
    adapter.write_object(key, b"public bytes", bucket=Bucket.PUBLIC_IMAGES)

    adapter.delete_object(key, bucket=Bucket.PRIVATE)

    assert adapter.read_object(key, bucket=Bucket.PRIVATE) is None
    assert adapter.read_object(key, bucket=Bucket.PUBLIC_IMAGES) == b"public bytes"


def test_write_object_without_content_type_falls_back_to_the_shared_default():
    """형식을 모르는 바이트는 어댑터 계약이 한 번 정한 기본값을 받는다 — 호출부가
    매번 그것을 다시 고르지 않는다."""

    from storage.adapters.base import DEFAULT_CONTENT_TYPE

    adapter = FakeStorageAdapter()
    key = "submission:1:2:source/no-type"
    adapter.write_object(key, b"legacy bytes")

    assert adapter.written_content_type(key) == DEFAULT_CONTENT_TYPE
    assert DEFAULT_CONTENT_TYPE == "application/octet-stream"
