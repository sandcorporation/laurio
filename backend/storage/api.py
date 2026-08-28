"""presigned 업로드·다운로드 엔드포인트 (ADR-0005).

앱은 바이트를 중계하지 않는다. 이 두 엔드포인트는 스토리지 어댑터가 만든
presigned URL을 그대로 돌려줄 뿐이고, 실제 파일은 클라이언트가 스토리지와
직접 주고받는다.

`target_ref`는 이 앱 입장에서 불투명한 문자열이다 — 어떤 Submission의 어떤
슬롯(소스/빌드/영상)을 가리키는지는 이 티켓이 알 필요가 없다. 호출자 권한과
대상 상태 판정은 전부 `storage.policy`로 위임한다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from ninja import Field, Router, Schema

from storage.adapters import get_storage_adapter
from storage.policy import StorageAccessDenied, StorageAccessPolicy

router = Router(tags=["storage"])

# target_ref는 나중에 object_key의 접두어로도 쓰인다. 경로 구분자·상위 디렉터리
# 탈출에 쓰일 수 있는 문자를 애초에 배제한다.
_TARGET_REF_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9:_-]{0,199}$"


class UploadRequest(Schema):
    target_ref: str = Field(pattern=_TARGET_REF_PATTERN)
    content_type: str | None = None


class UploadResponse(Schema):
    object_key: str
    upload_url: str
    method: str
    headers: dict[str, str]
    expires_at: str


class DownloadRequest(Schema):
    target_ref: str = Field(pattern=_TARGET_REF_PATTERN)
    object_key: str


class DownloadResponse(Schema):
    download_url: str
    expires_at: str


def _new_object_key(target_ref: str) -> str:
    return f"{target_ref}/{uuid4().hex}"


@router.post("/uploads", response=UploadResponse)
def request_upload(request, payload: UploadRequest) -> UploadResponse:
    StorageAccessPolicy().authorize_upload(request, payload.target_ref)

    adapter = get_storage_adapter()
    object_key = _new_object_key(payload.target_ref)
    presigned = adapter.presign_upload(
        object_key,
        content_type=payload.content_type,
        expires_in=timedelta(seconds=settings.STORAGE_UPLOAD_URL_TTL_SECONDS),
    )
    return UploadResponse(
        object_key=presigned.object_key,
        upload_url=presigned.url,
        method=presigned.method,
        headers=presigned.headers,
        expires_at=presigned.expires_at.isoformat(),
    )


@router.post("/downloads", response=DownloadResponse)
def request_download(request, payload: DownloadRequest) -> DownloadResponse:
    # object_key가 target_ref 네임스페이스 밖의 것이면, target_ref에 대한 권한을
    # 얻었다고 해서 아무 object_key나 내려받을 수 있게 되지는 않는다.
    if not payload.object_key.startswith(f"{payload.target_ref}/"):
        raise StorageAccessDenied("object_key가 target_ref에 속하지 않는다")

    StorageAccessPolicy().authorize_download(request, payload.target_ref)

    adapter = get_storage_adapter()
    presigned = adapter.presign_download(
        payload.object_key,
        expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
    )
    return DownloadResponse(
        download_url=presigned.url,
        expires_at=presigned.expires_at.isoformat(),
    )
