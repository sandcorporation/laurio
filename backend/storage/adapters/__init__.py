"""어댑터 바인딩 (ADR-0007): 환경별로 STORAGE_BACKEND 설정 하나로 갈아끼운다.

기본값은 "fake"다. dev compose가 backend 컨테이너에 STORAGE_BACKEND=s3 를
주입해 MinIO로 바인딩한다(docker/compose.dev.yaml). 테스트는 아무것도 설정하지
않아도 fake로 떨어지므로 MinIO 없이 돈다.
"""

from __future__ import annotations

from django.conf import settings
from django.utils.module_loading import import_string

from .base import (
    DEFAULT_CONTENT_TYPE,
    Bucket,
    PresignedDownload,
    PresignedUpload,
    StorageAdapter,
    StorageAdapterError,
)

_BACKENDS = {
    "fake": "storage.adapters.fake.FakeStorageAdapter",
    "s3": "storage.adapters.s3.S3StorageAdapter",
}

__all__ = [
    "DEFAULT_CONTENT_TYPE",
    "Bucket",
    "PresignedDownload",
    "PresignedUpload",
    "StorageAdapter",
    "StorageAdapterError",
    "get_storage_adapter",
]


def get_storage_adapter() -> StorageAdapter:
    backend = getattr(settings, "STORAGE_BACKEND", "") or "fake"
    # 등록된 별칭이 아니면 dotted path 로도 받아준다(테스트에서 커스텀 더블을 꽂을 때 쓴다).
    path = _BACKENDS.get(backend, backend)
    adapter_cls = import_string(path)
    return adapter_cls()
