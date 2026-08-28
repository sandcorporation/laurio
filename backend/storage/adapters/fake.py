"""테스트용 인메모리 스토리지 더블.

CI와 로컬 테스트는 MinIO 없이 돈다(ADR-0007). 이 어댑터는 네트워크를 전혀 타지 않고
검사 가능한 고정 포맷의 URL을 생성한다. 상태를 저장하지 않으므로 여러 요청·여러
테스트에서 안전하게 재사용할 수 있다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .base import PresignedDownload, PresignedUpload


class FakeStorageAdapter:
    base_url = "https://fake-storage.test/laurio-dev"

    def presign_upload(
        self,
        object_key: str,
        *,
        content_type: str | None = None,
        expires_in: timedelta,
    ) -> PresignedUpload:
        expires_at = datetime.now(timezone.utc) + expires_in
        url = (
            f"{self.base_url}/{object_key}"
            f"?X-Fake-Signature=upload&X-Fake-Expires={int(expires_at.timestamp())}"
        )
        headers = {"Content-Type": content_type} if content_type else {}
        return PresignedUpload(
            url=url,
            method="PUT",
            headers=headers,
            object_key=object_key,
            expires_at=expires_at,
        )

    def presign_download(
        self,
        object_key: str,
        *,
        expires_in: timedelta,
    ) -> PresignedDownload:
        expires_at = datetime.now(timezone.utc) + expires_in
        url = (
            f"{self.base_url}/{object_key}"
            f"?X-Fake-Signature=download&X-Fake-Expires={int(expires_at.timestamp())}"
        )
        return PresignedDownload(url=url, object_key=object_key, expires_at=expires_at)
