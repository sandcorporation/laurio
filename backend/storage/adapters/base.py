"""스토리지 어댑터 인터페이스 (ADR-0005, ADR-0007).

이 인터페이스는 의도적으로 업로드·다운로드 presigned URL 발급 두 가지만 제공한다.
객체를 public으로 바꾸거나, 버킷 정책을 고치거나, 다른 버킷으로 복사하는 메서드는
여기 없다 — 그런 코드 경로 자체를 인터페이스 레벨에서 존재할 수 없게 막는다.
공개 여부는 스토리지가 아니라 URL 발급 시점의 권한 판정(storage.policy)이 결정한다.

`read_object`(#12)는 예외다 — presigned URL이 아니라 백엔드 프로세스 자신의 자격증명
으로 직접 바이트를 읽는다. AI 채점(scoring 앱)이 제출된 소스코드를 LLM 입력으로
만들려면 실제 바이트가 있어야 하는데, presigned URL은 브라우저 같은 외부 클라이언트를
위한 것이라 서버 프로세스가 스스로에게 발급해 다시 내려받는 것은 낭비이고 우회다.
버킷이 계속 private으로 남고(ACL·정책을 건드리지 않는다), 이 앱만 자신의 자격증명으로
읽는다는 점에서 ADR-0005가 막는 "공개 전환"과는 다른 성격이다.
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

    def read_object(self, object_key: str) -> bytes | None:
        """object_key가 가리키는 바이트를 서버 프로세스 자신의 자격증명으로 직접 읽는다.

        존재하지 않으면 None을 돌려준다(예외를 던지지 않는다) — 아직 업로드가 완료되지
        않은 object_key를 채점 스캔이 만났을 때, 그건 장애가 아니라 "아직" 상태다.
        """
        ...
