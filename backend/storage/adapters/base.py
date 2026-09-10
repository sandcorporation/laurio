"""스토리지 어댑터 인터페이스 (ADR-0005, ADR-0007, ADR-0032, ADR-0035).

이 인터페이스는 의도적으로 업로드·다운로드 presigned URL 발급, 읽기, 쓰기,
그리고 **삭제**(ADR-0035) 다섯 메서드만 제공한다. 객체를 public으로 바꾸거나,
버킷 정책을 고치거나, 다른 버킷으로 복사하는 메서드는 여전히 없다 — 그런 코드
경로 자체를 인터페이스 레벨에서 존재할 수 없게 막는다. 공개 여부는 스토리지가
아니라 URL 발급 시점의 권한 판정(storage.policy)이 결정하거나(private 버킷),
버킷 자체가 애초에 공개 읽기다(ADR-0032의 이미지 버킷).

**`delete_object`(#262)만 연 이유는 파기와 무관하다** — 공개 전환·복사를 뺀
것은 마감 시각에 수백 개 파일의 공개 여부가 뒤집힐 때 옮기다 부분 실패하면
공모전이 반쯤 공개된 채 멈추는 실패 모양을 표현 불가능하게 만들려던 것이었다.
삭제는 그 모양을 만들지 않는다 — 도중에 실패해도 남는 상태는 "아직 안 지워진
파일"이고, 그건 다음 스캔이 정상적으로 다시 집는 상태다.

`read_object`(#12)는 예외다 — presigned URL이 아니라 백엔드 프로세스 자신의 자격증명
으로 직접 바이트를 읽는다. AI 채점(scoring 앱)이 제출된 소스코드를 LLM 입력으로
만들려면 실제 바이트가 있어야 하는데, presigned URL은 브라우저 같은 외부 클라이언트를
위한 것이라 서버 프로세스가 스스로에게 발급해 다시 내려받는 것은 낭비이고 우회다.
버킷이 계속 private으로 남고(ACL·정책을 건드리지 않는다), 이 앱만 자신의 자격증명으로
읽는다는 점에서 ADR-0005가 막는 "공개 전환"과는 다른 성격이다.

**#233부터 네 메서드 전부가 `bucket` 을 받는다(ADR-0032).** 지금까지는 설정의 버킷
이름 하나를 생성자가 잡고 모든 호출이 그것을 썼다 — Contest 이미지가 살 두 번째
(공개) 버킷을 다루려면 어느 버킷인지가 호출 시점에 정해져야 한다. 기존 호출부는
전부 `bucket` 을 생략한다 — 기본값 `Bucket.PRIVATE` 이 지금까지의 동작과 그대로
같다. 이 매개변수가 여는 것은 "어느 버킷에 쓰는가" 하나뿐이고, 공개 전환·복사·삭제
메서드는 여전히 없다.

**#238부터 `write_object`가 `content_type`을 받는다.** 새 능력이 아니라 이미 쓰고 있는
바이트에 대한 메타데이터다 — 서버가 직접 쓰는 두 경로(ContestImage 파생본, 저장소
박제본)가 자기 형식을 밝힐 자리가 계약에 없어 둘 다 `binary/octet-stream`으로 나갔다
(staging 실측). 호출자가 형식을 아는 바이트(webp 파생본·zip 박제본)를 쓸 때는 그 MIME을
넘기고, 모르면 생략한다 — 그러면 `DEFAULT_CONTENT_TYPE`이 쓰인다. 기본값이 어댑터
계약에 한 번만 정해져 있으므로 호출부마다 그것을 다시 고르지 않는다. `presign_upload`는
손대지 않는다 — 브라우저가 올리는 바이트의 content-type은 이미 서명된 정책이 정한다.

**#241부터 `presign_download`가 `filename`을 받는다(필수 키워드 인자).** 지금까지는
`ResponseContentDisposition`이 `"attachment"`뿐이라 파일명이 없었다 — 브라우저가
URL의 마지막 조각(서버가 만든 32자리 hex object_key)을 파일명으로 대신 써 확장자
없는 이름이 떨어졌다. 호출자는 `storage.filenames.build_download_filename`으로
항상 채워진 이름을 만들어 넘긴다(원본 파일명은 쓰지 않는다 — 사용자 입력을 헤더에
실으면 RFC 5987 이스케이프가 필요해진다는 것이 #241의 결정이다).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Protocol

#: `write_object`가 `content_type`을 받지 않았을 때 쓰는 기본값 (#238). 형식을 모르는
#: 바이트에 어떤 content-type을 실을지를 어댑터 계약에 한 번만 정해 두어, 호출부마다
#: 매번 다시 고르지 않게 한다.
DEFAULT_CONTENT_TYPE = "application/octet-stream"


class StorageAdapterError(Exception):
    """`write_object`·`read_object`가 서버 자신의 자격증명으로 스토리지에 직접
    붙는 도중 실패했다(네트워크 오류·권한 거부 등) — GitHub 어댑터의
    `GitHubAdapterError`와 같은 자리다. 호출자(#220의 저장소 박제 경로)는 이
    실패를 "그 시도만 못했다"로 다루고, `Score`를 만들지 않은 채 다음 스캔이
    다시 시도하게 한다.
    """


class Bucket(str, Enum):
    """어느 버킷에 쓰는가 (#233, ADR-0032).

    `PRIVATE`가 기본값이다 — 소스·시연 영상·빌드 자산·저장소 박제본이 지금까지
    그대로 사는 곳이고, `bucket`을 생략하는 모든 기존 호출부가 계속 이 값을 받는다.
    `PUBLIC_IMAGES`는 이 저장소의 첫 공개 오브젝트인 Contest 이미지 전용 버킷이다
    (ADR-0032) — 이 값으로 쓴 오브젝트는 서명 없이도 누구나 읽을 수 있다.
    """

    PRIVATE = "private"
    PUBLIC_IMAGES = "public_images"


@dataclass(frozen=True)
class PresignedUpload:
    """업로드용 presigned URL. 앱은 바이트를 중계하지 않고 이 정보만 클라이언트에 준다.

    `method`가 "PUT"이면 `headers`를 그대로 요청 헤더에 실어 파일 바이트를 그
    URL에 직접 PUT한다(지금까지의 모든 업로드). `method`가 "POST"면(#234,
    presign_upload에 `max_size_bytes`를 준 호출) `fields`가 multipart/form-data
    본문에 실을 서명된 정책 필드(키·정책·서명 등)를 담고, 파일은 그 뒤에 "file"
    필드로 이어 붙여 그 URL에 POST한다 — 크기 상한·content-type이 이 필드들 안의
    서명된 정책에 묶여 있으므로 위반하면 스토리지 자신이 거절한다(presigned PUT은
    서명에 크기를 묶을 수단이 없어 이미지 업로드에는 쓰지 않는다).
    """

    url: str
    method: str
    headers: dict[str, str]
    object_key: str
    expires_at: datetime
    fields: dict[str, str] = field(default_factory=dict)


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
        bucket: Bucket = Bucket.PRIVATE,
        content_type: str | None,
        expires_in: timedelta,
        max_size_bytes: int | None = None,
    ) -> PresignedUpload:
        """`max_size_bytes`를 주면(#234) presigned POST를 발급해 크기 상한과
        `content_type`을 서명된 정책 조건에 담는다 — 브라우저를 믿지 않고 바이트가
        애초에 들어오지 않게 한다. 생략하면 지금까지처럼 presigned PUT이다."""
        ...

    def presign_download(
        self,
        object_key: str,
        *,
        bucket: Bucket = Bucket.PRIVATE,
        expires_in: timedelta,
        filename: str,
    ) -> PresignedDownload:
        """`filename`이 응답의 `Content-Disposition`에 실린다(#241).

        브라우저는 `attachment`에 파일명이 없으면 URL의 마지막 조각(서버가 만든
        32자리 hex object_key)을 파일명으로 쓴다 — 확장자 없는 이름이 떨어지는
        원인이 그것이다. `filename`은 항상 채워야 한다(`storage.filenames.
        build_download_filename`가 content-type을 몰라도 확장자 없는 이름을
        낸다) — 이름이 없는 것보다는 확장자가 없는 이름이 낫다."""
        ...

    def read_object(self, object_key: str, *, bucket: Bucket = Bucket.PRIVATE) -> bytes | None:
        """object_key가 가리키는 바이트를 서버 프로세스 자신의 자격증명으로 직접 읽는다.

        존재하지 않으면 None을 돌려준다(예외를 던지지 않는다) — 아직 업로드가 완료되지
        않은 object_key를 채점 스캔이 만났을 때, 그건 장애가 아니라 "아직" 상태다.
        """
        ...

    def write_object(
        self,
        object_key: str,
        content: bytes,
        *,
        bucket: Bucket = Bucket.PRIVATE,
        content_type: str | None = None,
    ) -> None:
        """바이트를 서버 프로세스 자신의 자격증명으로 직접 쓴다 (#194).

        실제 업로드는 대부분 브라우저가 `presign_upload` 로 받은 URL 에 직접
        PUT/POST 한다(ADR-0005, ADR-0032) — 서버는 보통 오브젝트를 옮기지도
        쓰지도 않는다. 오랫동안 유일한 호출자는 **e2e 시드**였다: 제출물 소스를
        미리 채운 뒤 같은 프로세스에서 채점 스캔을 돌려 Score 를 만드는 시드들
        (`seed_e2e_operator_queues`)이 그것이고, 그 시드들은
        `IS_DEPLOYED_ENVIRONMENT` 에서 스스로 거부한다.

        **#220부터 정상 운영에도 이 경로를 쓰는 코드가 생겼다.** 소스 없이
        저장소만 낸 제출을 채점할 때, 이미 clone 해 손에 쥔 zip 바이트를
        버리지 않고 이 메서드로 그대로 저장한다(`scoring.services`의 박제
        경로) — 추가 GitHub 호출 없이 Handover 가 넘길 소스를 만든다.

        **`read_object` 와 같은 성격이라 계약에 둔다.** 그쪽도 서버 프로세스가 자기
        자격증명으로 오브젝트에 직접 붙는 경로다 — 읽기만 계약에 있고 쓰기는
        fake 에만 있으면, 그 비대칭이 「시드는 fake 스토리지에서만 돈다」는
        제약이 되어 e2e 러너에 파이썬 툴체인과 DB 포트 노출을 남긴다(#194 가 그 사슬을
        적는다).

        같은 object_key 에 두 번 쓰면 덮어쓴다. 실패(네트워크 오류 등)하면
        `StorageAdapterError`를 던진다 — 호출자(#220 의 박제 경로)는 이 실패를
        "Score 를 만들지 않고 다음 스캔에서 재시도"로 다룬다.

        **`content_type`은 새 능력이 아니라 지금 쓰는 바이트의 메타데이터다 (#238).**
        호출자가 형식을 아는 바이트(ContestImage의 webp 파생본·저장소 박제 zip)를 쓸 때
        넘긴다 — 생략하면 `DEFAULT_CONTENT_TYPE`이 쓰인다. 이 오브젝트에는 presigned
        업로드가 없으므로(서버가 직접 쓴다) 여기가 유일하게 content-type을 실을 자리다.
        """
        ...

    def delete_object(self, object_key: str, *, bucket: Bucket = Bucket.PRIVATE) -> None:
        """오브젝트 하나를 서버 프로세스 자신의 자격증명으로 직접 지운다 (#262, ADR-0035).

        보존 기간이 지난 시연 영상의 **파일**만 지우는 스캔(`submissions.retention`)
        이 유일한 호출자다 — 자료 행(`SubmissionAsset`)이나 그것을 가리키는
        `Evidence`는 이 메서드가 모른다(스토리지 어댑터는 도메인 모델을 모른다).

        **이미 없는 object_key를 지워도 조용히 성공한다.** 파기 스캔이 오브젝트를
        지운 뒤 그 사실을 기록하기 전에 죽으면, 다음 실행이 같은 object_key를
        다시 지운다 — 그 재시도가 예외를 던지면 멱등성이 깨진다. S3 호환
        `DeleteObject`가 이미 이 semantics(없는 키를 지워도 204)를 갖고 있으므로
        실물 어댑터는 별도 방어가 필요 없다.
        """
        ...
