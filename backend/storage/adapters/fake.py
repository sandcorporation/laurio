"""테스트용 인메모리 스토리지 더블.

CI와 로컬 테스트는 MinIO 없이 돈다(ADR-0007). 이 어댑터는 네트워크를 전혀 타지 않고
검사 가능한 고정 포맷의 URL을 생성한다. 상태를 저장하지 않으므로 여러 요청·여러
테스트에서 안전하게 재사용할 수 있다.

**#233부터 버킷이 둘이다(ADR-0032).** `bucket`을 생략하는 모든 기존 호출부는
지금까지와 같은 `base_url`(private 버킷)을 받는다 — `Bucket.PUBLIC_IMAGES`를
넘긴 호출만 `images_base_url`로 갈린다.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from django.conf import settings

from .base import Bucket, PresignedDownload, PresignedUpload, StorageAdapterError


class FakeStorageAdapter:
    base_url = "https://fake-storage.test/laurio-dev"
    # 실제 dev/staging/prod 버킷 이름(`config/settings.py` 기본값)의 명명 규칙을
    # 그대로 흉내낸다 — "public"과 "images"가 둘 다 들어간다(ADR-0032).
    images_base_url = "https://fake-storage.test/laurio-dev-public-images"

    # 클래스 레벨(인스턴스 아님) — get_storage_adapter()가 호출마다 새 인스턴스를
    # 만들기 때문에, 한 요청(업로드 시뮬레이션)에서 쓴 바이트가 다른 요청(채점 스캔)
    # 에서도 보이려면 인스턴스를 넘어 프로세스 수명 동안 유지되는 저장소가 필요하다.
    # 실제 업로드는 여전히 클라이언트가 presigned URL로 스토리지에 직접 하므로
    # (ADR-0005) 이 앱은 바이트를 중계하지 않는다 — `write_object`는 테스트가 "이미
    # 업로드되어 있다"는 전제 상태를 준비하기 위한 것으로 FakeStorageAdapter 전용이다.
    # 키가 (bucket, object_key) 튜플인 이유는 두 버킷이 같은 object_key를 각자
    # 독립적으로 가질 수 있어서다.
    _store: dict[tuple[Bucket, str], bytes] = {}

    def _base_url(self, bucket: Bucket) -> str:
        return self.images_base_url if bucket is Bucket.PUBLIC_IMAGES else self.base_url

    def presign_upload(
        self,
        object_key: str,
        *,
        bucket: Bucket = Bucket.PRIVATE,
        content_type: str | None = None,
        expires_in: timedelta,
        max_size_bytes: int | None = None,
    ) -> PresignedUpload:
        expires_at = datetime.now(timezone.utc) + expires_in
        base = self._base_url(bucket)

        if max_size_bytes is not None:
            # S3StorageAdapter가 실제로 발급하는 presigned POST와 대응시켜, 테스트가
            # "크기 상한·content-type이 서명된 정책에 실제로 담겼다"를 검증할 수
            # 있게 한다 — 필드 이름은 실물이 아니라 이 더블만의 것이지만(X-Fake-
            # 접두), 값 자체(상한·타입)는 그대로 노출한다.
            fields = {
                "key": object_key,
                "X-Fake-Policy": "post",
                "X-Fake-Max-Size-Bytes": str(max_size_bytes),
            }
            if content_type:
                fields["Content-Type"] = content_type
            return PresignedUpload(
                url=f"{base}/",
                method="POST",
                headers={},
                object_key=object_key,
                expires_at=expires_at,
                fields=fields,
            )

        url = (
            f"{base}/{object_key}"
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
        bucket: Bucket = Bucket.PRIVATE,
        expires_in: timedelta,
    ) -> PresignedDownload:
        expires_at = datetime.now(timezone.utc) + expires_in
        url = (
            f"{self._base_url(bucket)}/{object_key}"
            f"?X-Fake-Signature=download&X-Fake-Expires={int(expires_at.timestamp())}"
            # S3StorageAdapter가 ResponseContentDisposition=attachment 를 강제하는 것과
            # 대응시켜, 테스트가 "다운로드는 항상 첨부파일로 강제된다"를 검증할 수 있게 한다.
            "&X-Fake-Response-Content-Disposition=attachment"
        )
        return PresignedDownload(url=url, object_key=object_key, expires_at=expires_at)

    def read_object(self, object_key: str, *, bucket: Bucket = Bucket.PRIVATE) -> bytes | None:
        return self._store.get((bucket, object_key))

    def write_object(
        self, object_key: str, content: bytes, *, bucket: Bucket = Bucket.PRIVATE
    ) -> None:
        """실제 업로드(presigned PUT/POST)를 흉내내 미리 바이트를 채운다.

        #194 부터 `StorageAdapter` 계약의 일부다 — 「테스트 전용」이 아니라 「e2e 시드
        전용」이었고, #220부터는 저장소 박제(`scoring.services`)도 부른다. S3
        어댑터에도 같은 메서드가 있다 — 그 대칭이 있어야 시드·박제 둘 다 어느
        환경에서 돌든 자기 완결적이다.

        `settings.STORAGE_FAKE_WRITE_RAISING_TARGET_REFS`에 이 object_key가 속한
        target_ref(=`<target_ref>/<hex>`의 앞부분)가 있으면 `StorageAdapterError`를
        던진다 — 박제 저장 실패(#220)를 테스트가 재현하는 유일한 방법이다
        (`LLM_FAKE_RAISING_SUBMISSION_IDS`와 같은 원칙).
        """
        raising_target_refs = getattr(settings, "STORAGE_FAKE_WRITE_RAISING_TARGET_REFS", ())
        if any(object_key.startswith(f"{ref}/") for ref in raising_target_refs):
            raise StorageAdapterError(
                f"fake storage adapter가 write_object에 실패했다(강제된 실패 시나리오, "
                f"object_key={object_key!r})."
            )
        self._store[(bucket, object_key)] = content
