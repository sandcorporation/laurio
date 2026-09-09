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
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from ninja import Field, Router, Schema

from storage.adapters import get_storage_adapter
from storage.filenames import build_download_filename
from storage.policy import StorageAccessDenied, StorageAccessPolicy, get_content_type_resolver

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
    expires_at: str


class DownloadRequest(Schema):
    target_ref: str = Field(pattern=_TARGET_REF_PATTERN)
    object_key: str = Field(pattern=_OBJECT_KEY_PATTERN)


class DownloadResponse(Schema):
    download_url: str
    expires_at: str


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
    presigned = adapter.presign_upload(
        object_key,
        content_type=payload.content_type,
        expires_in=timedelta(seconds=settings.STORAGE_UPLOAD_URL_TTL_SECONDS),
    )
    return UploadResponse(
        object_key=presigned.object_key,
        upload_url=presigned.url,
        method=presigned.method,
        headers=presigned.headers,
        expires_at=presigned.expires_at.isoformat(),
    )


@router.post("/downloads", response=DownloadResponse)
def request_download(request, payload: DownloadRequest) -> DownloadResponse:
    # object_key가 target_ref 네임스페이스 밖의 것이면, target_ref에 대한 권한을
    # 얻었다고 해서 아무 object_key나 내려받을 수 있게 되지는 않는다.
    if not payload.object_key.startswith(f"{payload.target_ref}/"):
        raise StorageAccessDenied("object_key가 target_ref에 속하지 않는다")

    StorageAccessPolicy().authorize_download(request, payload.target_ref)

    content_type = get_content_type_resolver().resolve(payload.target_ref, payload.object_key)
    filename = build_download_filename(content_type)

    adapter = get_storage_adapter()
    presigned = adapter.presign_download(
        payload.object_key,
        filename=filename,
        expires_in=timedelta(seconds=settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS),
    )
    return DownloadResponse(
        download_url=presigned.url,
        expires_at=presigned.expires_at.isoformat(),
    )
