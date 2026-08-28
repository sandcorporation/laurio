"""S3 호환 API(dev=MinIO, staging/prod=S3·OCI) 스토리지 어댑터.

ADR-0005: 버킷은 영구히 private이다. 이 클래스는 put_object_acl·copy_object 같이
공개 전환에 쓰일 수 있는 호출을 의도적으로 두지 않는다. presigned PUT/GET URL
발급만 한다 — 앱은 파일 바이트를 절대 거치지 않는다.

`read_object`(#12)만 예외다 — get_object를 직접 호출해 바이트를 읽는다. ACL·정책을
전혀 건드리지 않으므로(버킷은 계속 private) "공개 전환"과는 다른 성격이며, AI 채점이
서버 프로세스 자신의 자격증명으로 소스코드를 읽는 유일한 경로다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import ClientError
from django.conf import settings

from .base import PresignedDownload, PresignedUpload


@lru_cache(maxsize=1)
def _build_client(
    endpoint_url: str, access_key: str, secret_key: str, region: str
) -> BaseClient:
    """presign은 순수 로컬 서명이라 네트워크를 타지 않지만, boto3 클라이언트
    생성 자체는 가볍지 않고 기본 세션이 동시 생성에 스레드 세이프하지도 않다.
    요청마다 새로 만들지 않고 프로세스당 한 번만 만든다. lru_cache가 락으로
    동시 호출을 직렬화해준다.

    access_key/secret_key가 비어 있으면 boto3 기본 자격증명 체인(IAM role 등)에
    맡긴다 — dev(MinIO)만 정적 키를 명시적으로 준다.
    """
    return boto3.client(
        "s3",
        endpoint_url=endpoint_url or None,
        aws_access_key_id=access_key or None,
        aws_secret_access_key=secret_key or None,
        region_name=region,
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


class S3StorageAdapter:
    def __init__(self) -> None:
        self._bucket = settings.STORAGE_BUCKET
        self._client = _build_client(
            settings.STORAGE_ENDPOINT_URL,
            settings.STORAGE_ACCESS_KEY,
            settings.STORAGE_SECRET_KEY,
            settings.STORAGE_REGION,
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
            Params={
                "Bucket": self._bucket,
                "Key": object_key,
                # 이 버킷은 Developer가 올린 신뢰할 수 없는 콘텐츠(소스·빌드)를 담는다.
                # 저장된 Content-Type과 무관하게 항상 첨부파일로 강제해, 브라우저가
                # text/html 같은 걸 스토리지 오리진에서 인라인으로 실행하지 못하게 막는다.
                "ResponseContentDisposition": "attachment",
            },
            ExpiresIn=int(expires_in.total_seconds()),
        )
        expires_at = datetime.now(timezone.utc) + expires_in
        return PresignedDownload(url=url, object_key=object_key, expires_at=expires_at)

    def read_object(self, object_key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=object_key)
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in {"NoSuchKey", "404"}:
                return None
            raise
        return response["Body"].read()
