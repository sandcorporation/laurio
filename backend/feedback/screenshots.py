"""제보 스크린샷 — 비공개 버킷 presigned 업로드/다운로드 (#1238).

`notifications.operator_notice_images` 꼴이다. 다른 학생의 이름·판정이 찍힐 수 있는 그림이라
공개 이미지 버킷은 쓰지 않고 `Bucket.PRIVATE` 에 올린다. 열람 주소는 제보자 본인과 운영자에게만,
열 때마다 짧게 발급한다(목록 응답에는 싣지 않는다).

키는 올린 사람으로 가른다(`feedback-screenshot:<user_id>/<hex>`) — 업로드가 제보 만들기보다 먼저라
제보 행으로 가를 수 없다. 제보를 만들 때 `attach_check` 가 (1) 그 사람이 올린 키인지 (2) 실제로
올라와 있는지 (3) 바이트가 png/jpeg/webp 인지 (4) 5MB 를 넘지 않는지 본다 — presigned POST 의
정책이 크기·형식을 이미 묶지만, 브라우저가 말한 content-type 만 믿지 않고 앞 바이트로 다시 본다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from ninja.errors import HttpError

from storage.adapters import Bucket, get_storage_adapter
from storage.adapters.base import PresignedDownload, PresignedUpload
from storage.sniffing import sniff_content_type

MAX_IMAGE_BYTES = 5 * 1024 * 1024

ALLOWED_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

KEY_PREFIX = "feedback-screenshot:"


def _owner_prefix(user_id: int) -> str:
    return f"{KEY_PREFIX}{user_id}/"


def request_upload_url(user_id: int, content_type: str) -> PresignedUpload:
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HttpError(422, "스크린샷은 png/jpeg/webp 형식만 올릴 수 있습니다.")

    adapter = get_storage_adapter()
    return adapter.presign_upload(
        f"{_owner_prefix(user_id)}{uuid4().hex}",
        bucket=Bucket.PRIVATE,
        content_type=content_type,
        expires_in=timedelta(seconds=settings.STORAGE_UPLOAD_URL_TTL_SECONDS),
        max_size_bytes=MAX_IMAGE_BYTES,
    )


def attach_check(object_key: str, user_id: int) -> None:
    """제보에 붙일 수 있는 키인지 — 아니면 422."""

    if not object_key.startswith(_owner_prefix(user_id)):
        raise HttpError(422, "스크린샷이 이 제보에 속하지 않습니다.")

    content = get_storage_adapter().read_object(
        object_key, bucket=Bucket.PRIVATE, max_bytes=MAX_IMAGE_BYTES + 1
    )
    if content is None:
        raise HttpError(422, "스크린샷이 아직 올라오지 않았습니다.")
    if len(content) > MAX_IMAGE_BYTES:
        raise HttpError(422, "스크린샷은 5MB 까지 올릴 수 있습니다.")
    if sniff_content_type(content) not in ALLOWED_CONTENT_TYPES:
        raise HttpError(422, "스크린샷은 png/jpeg/webp 형식만 올릴 수 있습니다.")


def request_download_url(object_key: str) -> PresignedDownload:
    """호출부가 열람 권한(제보자 본인·운영자)을 이미 확인한 뒤에만 부른다."""

    return get_storage_adapter().presign_download(
        object_key,
        bucket=Bucket.PRIVATE,
        filename="feedback-screenshot",
        expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
    )


def delete(object_key: str) -> None:
    get_storage_adapter().delete_object(object_key, bucket=Bucket.PRIVATE)
