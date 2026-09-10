"""S3 호환 API(dev=MinIO, staging/prod=S3·OCI) 스토리지 어댑터.

ADR-0005: 소스가 사는 버킷은 영구히 private이다. 이 클래스는 put_object_acl·
copy_object 같이 공개 전환에 쓰일 수 있는 호출을 의도적으로 두지 않는다.
presigned PUT/POST/GET URL 발급만 한다 — 앱은 파일 바이트를 절대 거치지 않는다.

`read_object`(#12)만 예외다 — get_object를 직접 호출해 바이트를 읽는다. ACL·정책을
전혀 건드리지 않으므로(버킷은 계속 private) "공개 전환"과는 다른 성격이며, AI 채점이
서버 프로세스 자신의 자격증명으로 소스코드를 읽는 유일한 경로다.

**#233부터 버킷이 둘이다(ADR-0032).** `bucket` 매개변수가 어느 버킷 이름으로
풀리는지는 `_bucket_name`이 결정한다 — `Bucket.PRIVATE`은 지금까지의
`settings.STORAGE_BUCKET`, `Bucket.PUBLIC_IMAGES`는 새 `settings.STORAGE_IMAGES_BUCKET`
이다. 이 클래스는 두 버킷 다 같은 자격증명·같은 엔드포인트로 다룬다 — 가르는 것은
버킷이지 스토리지 서버가 아니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from functools import lru_cache

import boto3
from botocore.client import BaseClient, Config
from botocore.exceptions import ClientError
from django.conf import settings

from .base import DEFAULT_CONTENT_TYPE, Bucket, PresignedDownload, PresignedUpload


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
        self._client = _build_client(
            settings.STORAGE_ENDPOINT_URL,
            settings.STORAGE_ACCESS_KEY,
            settings.STORAGE_SECRET_KEY,
            settings.STORAGE_REGION,
        )
        # presign_upload/presign_download는 브라우저가 직접 여는 URL을 만든다 —
        # 서버 프로세스 자신이 스토리지에 붙는 self._client와 호스트가 다를 수
        # 있다(FE-09, #34: dev 컨테이너 내부 DNS "minio:9000"은 브라우저가 못
        # 푼다). STORAGE_PUBLIC_ENDPOINT_URL이 STORAGE_ENDPOINT_URL과 같으면
        # (staging/prod처럼) lru_cache가 같은 인스턴스를 돌려준다.
        self._public_client = _build_client(
            settings.STORAGE_PUBLIC_ENDPOINT_URL,
            settings.STORAGE_ACCESS_KEY,
            settings.STORAGE_SECRET_KEY,
            settings.STORAGE_REGION,
        )

    def _bucket_name(self, bucket: Bucket) -> str:
        if bucket is Bucket.PUBLIC_IMAGES:
            return settings.STORAGE_IMAGES_BUCKET
        return settings.STORAGE_BUCKET

    def presign_upload(
        self,
        object_key: str,
        *,
        bucket: Bucket = Bucket.PRIVATE,
        content_type: str | None = None,
        expires_in: timedelta,
        max_size_bytes: int | None = None,
    ) -> PresignedUpload:
        bucket_name = self._bucket_name(bucket)
        expires_at = datetime.now(timezone.utc) + expires_in

        if max_size_bytes is not None:
            # presigned POST(#234, ADR-0032) — 크기 상한·content-type을 서명된
            # 정책 조건에 담는다. presigned PUT은 서명에 크기를 묶을 수단이
            # 없어(POST policy가 그 수단이다) 이미지처럼 상한이 필요한 업로드에는
            # 쓰지 않는다.
            conditions: list = [["content-length-range", 0, max_size_bytes]]
            post_fields: dict[str, str] = {}
            if content_type:
                conditions.append({"Content-Type": content_type})
                post_fields["Content-Type"] = content_type

            presigned_post = self._public_client.generate_presigned_post(
                Bucket=bucket_name,
                Key=object_key,
                Fields=post_fields,
                Conditions=conditions,
                ExpiresIn=int(expires_in.total_seconds()),
            )
            return PresignedUpload(
                url=presigned_post["url"],
                method="POST",
                headers={},
                object_key=object_key,
                expires_at=expires_at,
                fields=presigned_post["fields"],
            )

        params: dict[str, str] = {"Bucket": bucket_name, "Key": object_key}
        if content_type:
            params["ContentType"] = content_type

        url = self._public_client.generate_presigned_url(
            "put_object",
            Params=params,
            ExpiresIn=int(expires_in.total_seconds()),
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
        bucket: Bucket = Bucket.PRIVATE,
        expires_in: timedelta,
        filename: str,
    ) -> PresignedDownload:
        url = self._public_client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": self._bucket_name(bucket),
                "Key": object_key,
                # 이 버킷은 Developer가 올린 신뢰할 수 없는 콘텐츠(소스·빌드)를 담는다.
                # 저장된 Content-Type과 무관하게 항상 첨부파일로 강제해, 브라우저가
                # text/html 같은 걸 스토리지 오리진에서 인라인으로 실행하지 못하게 막는다.
                # `filename`은 플랫폼이 만든 값이다(#241) — 사용자 입력이 아니라서
                # 그대로 붙여도 RFC 5987 이스케이프가 필요 없다(storage.adapters.base
                # 참고).
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
            },
            ExpiresIn=int(expires_in.total_seconds()),
        )
        expires_at = datetime.now(timezone.utc) + expires_in
        return PresignedDownload(url=url, object_key=object_key, expires_at=expires_at)

    def read_object(
        self,
        object_key: str,
        *,
        bucket: Bucket = Bucket.PRIVATE,
        max_bytes: int | None = None,
    ) -> bytes | None:
        # `max_bytes`는 Range 헤더로 내려보낸다 — 바이트를 받아 자르는 것이 아니라
        # **애초에 그만큼만 받는다**(계약 참고). Range 는 끝을 포함하므로 -1 이다.
        extra = {"Range": f"bytes=0-{max_bytes - 1}"} if max_bytes else {}
        try:
            response = self._client.get_object(
                Bucket=self._bucket_name(bucket), Key=object_key, **extra
            )
        except ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in {"NoSuchKey", "404"}:
                return None
            # 오브젝트가 요청한 범위보다 짧으면 S3는 416 을 낼 수 있다 — 그건
            # "없다"도 "장애"도 아니라 "더 짧다"이므로, 범위 없이 다시 읽는다.
            if max_bytes and error_code in {"InvalidRange", "416"}:
                return self.read_object(object_key, bucket=bucket)
            raise
        return response["Body"].read()

    def write_object(
        self,
        object_key: str,
        content: bytes,
        *,
        bucket: Bucket = Bucket.PRIVATE,
        content_type: str | None = None,
    ) -> None:
        # `self._client`(서버가 붙는 호스트)를 쓴다 — `self._public_client` 는
        # 브라우저가 여는 URL 을 만들기 위한 것이라 컨테이너 안에서는 풀리지 않을
        # 수 있다(FE-09/#34 의 minio:9000 대 127.0.0.1:19000).
        #
        # ContentType을 명시적으로 채운다(#238) — 생략하면 boto3/S3가 임의로
        # `binary/octet-stream`을 붙이는데, 그 사실이 코드에 안 보여 호출부가
        # 매번 "이래도 되나"를 다시 판단하게 된다. `DEFAULT_CONTENT_TYPE`을 여기
        # 한 곳에서만 적용해 그 판단을 없앤다.
        self._client.put_object(
            Bucket=self._bucket_name(bucket),
            Key=object_key,
            Body=content,
            ContentType=content_type or DEFAULT_CONTENT_TYPE,
        )

    def delete_object(self, object_key: str, *, bucket: Bucket = Bucket.PRIVATE) -> None:
        # S3 호환 DeleteObject는 없는 키를 지워도 204를 낸다 — 재시도가 예외를
        # 만나지 않는다(#262의 멱등성 요구). `self._client`(서버가 붙는 호스트)를
        # 쓴다 — `write_object`·`read_object`와 같은 이유다.
        self._client.delete_object(Bucket=self._bucket_name(bucket), Key=object_key)
