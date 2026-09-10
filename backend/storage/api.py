"""presigned 업로드·다운로드 엔드포인트 (ADR-0005).

앱은 바이트를 중계하지 않는다. 이 두 엔드포인트는 스토리지 어댑터가 만든
presigned URL을 그대로 돌려줄 뿐이고, 실제 파일은 클라이언트가 스토리지와
직접 주고받는다.

`target_ref`는 이 앱 입장에서 불투명한 문자열이다 — 어떤 Submission의 어떤
슬롯(소스/빌드/영상)을 가리키는지는 이 티켓이 알 필요가 없다. 호출자 권한과
대상 상태 판정은 전부 `storage.policy`로 위임한다.

**다운로드 파일명(#241)도 같은 방식으로 위임한다.** 이 오브젝트에 어떤
content-type이 저장돼 있는지는 storage 앱이 모른다 — 업로드 시점에 받은
content-type을 `SubmissionAsset`·`handovers.BuildAsset`에 남기는 것은 도메인
쪽 책임이다(#241 결정). `STORAGE_CONTENT_TYPE_RESOLVER`가 그 값을 돌려주면
`storage.filenames.build_download_filename`이 파일명을 만든다 — content-type을
몰라도(리졸버가 None을 돌려줘도) 이름 자체는 항상 만든다.

**업로드 바이트 상한(#261)도 같은 방식으로 위임한다.** 이 슬롯에 몇 바이트까지
허용하는지는 storage 앱이 모른다 — `STORAGE_MAX_UPLOAD_SIZE_RESOLVER`가 그 값을
돌려주면 그대로 `adapter.presign_upload`의 `max_size_bytes`에 실어, 상한이 있는
슬롯은 presigned PUT 대신 POST로 발급된다(ADR-0032/ADR-0035 — PUT은 서명에
크기를 묶을 수단이 없다). 리졸버가 None을 돌려주면(기본값) 지금까지처럼 PUT이다.

**파기 여부(#262)도 같은 방식으로 위임한다.** 보존 기간이 지나 파일만 지워진
오브젝트인지는 `STORAGE_DESTRUCTION_RESOLVER`가 답한다 — 그러면 `request_download`는
presigned URL을 발급하지 않고 `expired=True`를 낸다. 오류(4xx)가 아니라 200이다:
권한도 있고 자료도 있지만 내려줄 바이트만 없다는 사실이 오류가 아니라서다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from ninja import Field, Router, Schema

from storage.adapters import get_storage_adapter
from storage.filenames import build_download_filename
from storage.policy import (
    StorageAccessDenied,
    StorageAccessPolicy,
    get_content_type_resolver,
    get_destruction_resolver,
    get_download_ttl_resolver,
    get_max_upload_size_resolver,
)

router = Router(tags=["storage"])

# target_ref는 나중에 object_key의 접두어로도 쓰인다. 경로 구분자·상위 디렉터리
# 탈출에 쓰일 수 있는 문자를 애초에 배제한다("." 도 빠져 있다 — ".." 조합 자체가
# 안 만들어진다).
_TARGET_REF_FRAGMENT = r"[A-Za-z0-9][A-Za-z0-9:_-]{0,199}"
_TARGET_REF_PATTERN = rf"^{_TARGET_REF_FRAGMENT}$"

# object_key는 서버가 new_object_key()로만 만든다 — 항상 "<target_ref>/<32자리
# 소문자 16진수>" 모양이다. 클라이언트가 다운로드 요청에 이 값을 그대로 되돌려
# 보내므로, 우리가 실제로 만드는 모양 그대로를 화이트리스트로 강제한다. object_key
# 쪽 문자 집합에 "."과 추가 "/"가 아예 없으므로 botocore가 SigV4 서명 전에
# dot-segment를 정규화하지 않아도(하지 않는다) 접두어 밖으로 나가는 키는 애초에
# 패턴을 통과하지 못한다.
_OBJECT_KEY_PATTERN = rf"^{_TARGET_REF_FRAGMENT}/[0-9a-f]{{32}}$"


class UploadRequest(Schema):
    target_ref: str = Field(pattern=_TARGET_REF_PATTERN)
    content_type: str | None = None


class UploadResponse(Schema):
    object_key: str
    upload_url: str
    method: str
    headers: dict[str, str]
    # 상한이 있는 업로드(#261)의 presigned POST가 실어야 하는 서명된 정책
    # 필드 — multipart/form-data 본문에 "file"보다 먼저 실어야 한다. 상한이
    # 없는(지금까지의) PUT 업로드는 빈 dict로 내려간다.
    fields: dict[str, str] = Field(default_factory=dict)
    expires_at: str
    # 이 슬롯에 실제로 적용된 바이트 상한(#261) — 없으면 None. 서명 조건에
    # 이미 실린 값을 그대로 다시 알려줘, 브라우저가 실제 바이트를 보내기 전에
    # (요청 자체는 이미 끝난 뒤) 파일 크기를 먼저 재보고 넘으면 업로드를 걸지
    # 않을 수 있게 한다 — 몇 GB를 다 올린 뒤 거절당하는 것보다 낫다(ADR-0035).
    max_size_bytes: int | None = None


class DownloadRequest(Schema):
    target_ref: str = Field(pattern=_TARGET_REF_PATTERN)
    object_key: str = Field(pattern=_OBJECT_KEY_PATTERN)


class DownloadResponse(Schema):
    # 보존 기간이 지나 파일이 파기된 오브젝트(#262, ADR-0035)는 `expired=True`고
    # 나머지 둘은 null이다 — 자료 행·근거는 그대로 있지만 내려줄 파일이 없다는
    # 뜻이라, 이 요청 자체는 정상(200)으로 끝난다. 오류도 빈 응답도 아니다.
    download_url: str | None = None
    expires_at: str | None = None
    expired: bool = False


def new_object_key(target_ref: str) -> str:
    """업로드 하나가 받는 object_key. **이 형식을 아는 곳은 여기뿐이어야 한다.**

    공개 이름인 이유는 데모 시드(#253)가 같은 규칙을 써야 하기 때문이다 — 시드가
    값을 손으로 조립하던 동안 그 값은 `_OBJECT_KEY_PATTERN`(다운로드)과
    `target_ref_for_asset_kind`(쓰기 검증) 둘 다에 걸렸고, 아무도 눌러 보기
    전까지 아무도 몰랐다.
    """

    return f"{target_ref}/{uuid4().hex}"


@router.post("/uploads", response=UploadResponse)
def request_upload(request, payload: UploadRequest) -> UploadResponse:
    StorageAccessPolicy().authorize_upload(request, payload.target_ref)

    adapter = get_storage_adapter()
    object_key = new_object_key(payload.target_ref)
    max_size_bytes = get_max_upload_size_resolver().resolve(payload.target_ref)
    presigned = adapter.presign_upload(
        object_key,
        content_type=payload.content_type,
        expires_in=timedelta(seconds=settings.STORAGE_UPLOAD_URL_TTL_SECONDS),
        max_size_bytes=max_size_bytes,
    )
    return UploadResponse(
        object_key=presigned.object_key,
        upload_url=presigned.url,
        method=presigned.method,
        headers=presigned.headers,
        fields=presigned.fields,
        expires_at=presigned.expires_at.isoformat(),
        max_size_bytes=max_size_bytes,
    )


@router.post("/downloads", response=DownloadResponse)
def request_download(request, payload: DownloadRequest) -> DownloadResponse:
    # object_key가 target_ref 네임스페이스 밖의 것이면, target_ref에 대한 권한을
    # 얻었다고 해서 아무 object_key나 내려받을 수 있게 되지는 않는다.
    if not payload.object_key.startswith(f"{payload.target_ref}/"):
        raise StorageAccessDenied("object_key가 target_ref에 속하지 않는다")

    StorageAccessPolicy().authorize_download(request, payload.target_ref)

    if get_destruction_resolver().resolve(payload.object_key):
        # 보존 기간이 지나 파일만 파기됐다(#262) — 권한은 있었지만 내려줄
        # 바이트가 없다. presigned URL을 발급해도 스토리지가 404를 낼 뿐이니
        # 발급 자체를 건너뛴다.
        return DownloadResponse(expired=True)

    content_type = get_content_type_resolver().resolve(payload.target_ref, payload.object_key)
    filename = build_download_filename(content_type)

    ttl_seconds = get_download_ttl_resolver().resolve(payload.target_ref)
    adapter = get_storage_adapter()
    presigned = adapter.presign_download(
        payload.object_key,
        filename=filename,
        expires_in=timedelta(seconds=ttl_seconds),
    )
    return DownloadResponse(
        download_url=presigned.url,
        expires_at=presigned.expires_at.isoformat(),
    )
