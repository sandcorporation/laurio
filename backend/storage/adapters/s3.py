"""S3 호환 API(dev=MinIO, staging/prod=S3·OCI) 스토리지 어댑터.

ADR-0005: 버킷은 영구히 private이다. 이 클래스는 put_object_acl·copy_object 같이
공개 전환에 쓰일 수 있는 호출을 의도적으로 두지 않는다. presigned PUT/GET URL
발급만 한다 — 앱은 파일 바이트를 절대 거치지 않는다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import boto3
from botocore.client import Config
from django.conf import settings

from .base import PresignedDownload, PresignedUpload


class S3StorageAdapter:
    def __init__(self) -> None:
        self._bucket = settings.STORAGE_BUCKET
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.STORAGE_ENDPOINT_URL or None,
            aws_access_key_id=settings.STORAGE_ACCESS_KEY,
            aws_secret_access_key=settings.STORAGE_SECRET_KEY,
            region_name=settings.STORAGE_REGION,
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )

    def presign_upload(
        self,
        object_key: str,
        *,
        content_type: str | None = None,
        expires_in: timedelta,
    ) -> PresignedUpload:
        params: dict[str, str] = {"Bucket": self._bucket, "Key": object_key}
        if content_type:
            params["ContentType"] = content_type

        url = self._client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=int(expires_in.total_seconds()),
        )
        expires_at = datetime.now(timezone.utc) + expires_in
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
        url = self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": object_key},
            ExpiresIn=int(expires_in.total_seconds()),
        )
        expires_at = datetime.now(timezone.utc) + expires_in
        return PresignedDownload(url=url, object_key=object_key, expires_at=expires_at)
