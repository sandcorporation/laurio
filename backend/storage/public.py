"""서명 없는 공개 주소 조립 (#233, ADR-0032).

Contest 이미지처럼 이 저장소의 첫 공개 버킷(`storage.adapters.base.Bucket.
PUBLIC_IMAGES`)에 사는 오브젝트는 presigned URL이 필요 없다 — 버킷 자체가
익명 읽기이므로 기준 주소(`settings.STORAGE_IMAGES_BASE_URL`)에 object_key만
이어 붙이면 브라우저가 바로 읽는다. 서명이 없고 매 요청 URL이 항상 같으므로
CDN이 그대로 캐시한다(ADR-0032가 private 버킷의 presigned URL로는 못 하던 일).

이 함수는 대상이 실제로 `Bucket.PUBLIC_IMAGES`에 쓰였는지 확인하지 않는다 — 그
사실은 호출자(`contests.api`)가 이미 알고 있다(그 object_key를 만든 바로 그
호출이 `presign_upload(..., bucket=Bucket.PUBLIC_IMAGES)`를 썼다). 이 함수는
문자열 조립만 한다.
"""

from __future__ import annotations

from django.conf import settings


def compose_public_image_url(object_key: str) -> str:
    return f"{settings.STORAGE_IMAGES_BASE_URL}/{object_key}"
