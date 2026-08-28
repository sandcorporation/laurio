"""스토리지 어댑터 인터페이스 (ADR-0005, ADR-0007).

이 인터페이스는 의도적으로 업로드·다운로드 presigned URL 발급 두 가지만 제공한다.
객체를 public으로 바꾸거나, 버킷 정책을 고치거나, 다른 버킷으로 복사하는 메서드는
여기 없다 — 그런 코드 경로 자체를 인터페이스 레벨에서 존재할 수 없게 막는다.
공개 여부는 스토리지가 아니라 URL 발급 시점의 권한 판정(storage.policy)이 결정한다.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol


@dataclass(frozen=True)
class PresignedUpload:
    """업로드용 presigned URL. 앱은 바이트를 중계하지 않고 이 정보만 클라이언트에 준다."""

    url: str
    method: str
    headers: dict[str, str]
    object_key: str
    expires_at: datetime


@dataclass(frozen=True)
class PresignedDownload:
    """다운로드용 presigned URL."""

    url: str
    object_key: str
    expires_at: datetime


class StorageAdapter(Protocol):
    """dev는 MinIO(S3StorageAdapter), 테스트는 FakeStorageAdapter로 바인딩한다."""

    def presign_upload(
        self,
        object_key: str,
        *,
        content_type: str | None,
        expires_in: timedelta,
    ) -> PresignedUpload: ...

    def presign_download(
        self,
        object_key: str,
        *,
        expires_in: timedelta,
    ) -> PresignedDownload: ...
