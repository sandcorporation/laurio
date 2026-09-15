"""운영팀 알림 이미지 — 비공개 버킷 presigned 업로드/다운로드 (#419).

공모전 이미지(`contests.images`, ADR-0032)의 업로드 방식을 그대로 따르되
버킷만 다르다: 기프티콘 바코드처럼 주소만으로 새면 안 되는 값이라 **공개
이미지 버킷은 쓰지 않는다** — `Bucket.PRIVATE`(기본값, 제출물 소스와 같은
버킷)에 올린다.

`target_ref`는 업로드 시점의 **보낸 운영자**로 가른다(`operator-notice-image:
<sender_id>`) — 업로드가 실제 발송(어느 Notification 에 붙을지)보다 먼저
일어나므로(작성 화면이 이미지부터 받고 나중에 「보내기」를 누른다) `contest-
image:<contest_id>`처럼 대상 행으로 가를 수 없다. 대신 `send_operator_notice`
가 이 접두어로 소유권을(그 요청을 보낸 운영자가 실제로 올린 키인지) 확인한다
— 남의 업로드 응답에서 얻은(또는 추측한) 키를 자기 알림에 붙이는 경로를 막는다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from ninja.errors import HttpError

from storage.adapters import Bucket, get_storage_adapter

# 5MB — 기프티콘 이미지 한 장이면 충분하다. 공모전 참고 이미지(10MB)보다
# 작게 잡는다 — 이건 시안이 아니라 캡처 이미지 한 장이다.
MAX_IMAGE_BYTES = 5 * 1024 * 1024

ALLOWED_CONTENT_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})

IMAGE_TARGET_REF_PREFIX = "operator-notice-image:"


def image_target_ref(sender_id: int) -> str:
    return f"{IMAGE_TARGET_REF_PREFIX}{sender_id}"


def request_upload_url(sender_id: int, content_type: str):
    """받는 사람·제목이 아직 정해지지 않은 시점에도 부를 수 있다 — 작성
    화면이 이미지부터 올리고 나중에 받는 사람과 함께 보내기 때문이다."""

    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HttpError(422, "이미지는 png/jpeg/webp 형식만 올릴 수 있습니다.")

    target_ref = image_target_ref(sender_id)
    object_key = f"{target_ref}/{uuid4().hex}"

    adapter = get_storage_adapter()
    return adapter.presign_upload(
        object_key,
        bucket=Bucket.PRIVATE,
        content_type=content_type,
        expires_in=timedelta(seconds=settings.STORAGE_UPLOAD_URL_TTL_SECONDS),
        max_size_bytes=MAX_IMAGE_BYTES,
    )


def assert_owned_by(object_key: str, sender_id: int) -> None:
    target_ref = image_target_ref(sender_id)
    if not object_key.startswith(f"{target_ref}/"):
        raise HttpError(422, "이미지가 이 요청에 속하지 않습니다.")


def request_download_url(object_key: str):
    """받는 사람·보낸 운영자에게만 열 때마다 짧게(분 단위) 발급한다 — 호출부
    (`notifications.api`·`notifications.operator_api`)가 그 권한을 이미
    확인한 뒤에만 부른다."""

    adapter = get_storage_adapter()
    return adapter.presign_download(
        object_key,
        bucket=Bucket.PRIVATE,
        filename="operator-notice-image",
        expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
    )
