"""S3 호환 스토리지 어댑터가 내보내는 요청 모양 (OCI Object Storage 호환성).

벤더 경계 코드다 — `tests/test_payments_toss_adapter.py` 가 적어 둔 층위와 같다. 네트워크는
타지 않는다: botocore 의 `before-send` 이벤트에서 요청을 가로채 가짜 응답을 돌려준다.

**왜 이 파일이 있는가.** boto3 는 최근 판(1.36~)부터 업로드에 요청 체크섬을 기본으로 붙이고
그 바디를 aws-chunked 로 보낸다. OCI Object Storage 의 S3 호환 API 는 그것을
`NotImplemented: AWS chunked encoding not supported` 로 거절한다 — 실험 버킷에서 실측했다
(2026-09-14, boto3 1.43.82). MinIO 는 받아 줘서 dev·staging 에서는 보이지 않는다.
"""

from __future__ import annotations

from botocore.awsrequest import AWSResponse

from storage.adapters import s3 as s3_module
from storage.adapters.s3 import S3StorageAdapter


class _Raw:
    def __init__(self, body: bytes = b"") -> None:
        self._body = body

    def stream(self, **_kwargs):
        yield self._body


def _capture(adapter: S3StorageAdapter) -> list:
    sent: list = []

    def _before_send(request, **_kwargs):
        sent.append(request)
        return AWSResponse(request.url, 200, {}, _Raw())

    adapter._client.meta.events.register("before-send.s3", _before_send)
    return sent


def test_uploads_do_not_use_aws_chunked_encoding_or_default_checksums(settings):
    settings.STORAGE_ENDPOINT_URL = "https://objectstorage.example.test"
    settings.STORAGE_PUBLIC_ENDPOINT_URL = "https://objectstorage.example.test"
    settings.STORAGE_ACCESS_KEY = "test-access"
    settings.STORAGE_SECRET_KEY = "test-secret"
    settings.STORAGE_REGION = "ap-chuncheon-1"
    s3_module._build_client.cache_clear()
    adapter = S3StorageAdapter()
    sent = _capture(adapter)

    adapter.write_object("probe/server.txt", b"hello", content_type="text/plain")

    headers = {k.lower(): v for k, v in sent[0].headers.items()}
    assert "aws-chunked" not in str(headers.get("content-encoding", ""))
    assert not str(headers.get("x-amz-content-sha256", "")).startswith("STREAMING-")
    assert not any(k.startswith("x-amz-checksum-") for k in headers)
    assert "x-amz-sdk-checksum-algorithm" not in headers
