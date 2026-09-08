"""ContestImage 업로드 상수 (#234, ADR-0032).

크기 상한·허용 content-type은 사업 판단(운영자가 배포 없이 조정하는 값)이 아니라
"presigned POST 정책에 무엇을 서명해 넣는가"라는 기술값이다 — 다른 상한
(`PlatformPolicy.max_contest_images`, 장수)과 자리가 다르다: 장수는 플랫폼
운영이고, 바이트 상한·MIME 허용목록은 이 코드가 스토리지에 무엇을 믿고
맡길지를 정하는 값이라 배포로 바꾼다.
"""

from __future__ import annotations

# 10MB — 참고 이미지는 시안·와이어프레임 스크린샷이지 원본 디자인 파일이 아니다.
MAX_CONTEST_IMAGE_BYTES = 10 * 1024 * 1024

ALLOWED_CONTEST_IMAGE_CONTENT_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)

# object_key의 target_ref 접두어 — "<CONTEST_IMAGE_TARGET_REF_PREFIX>{contest_id}/<hex>".
# storage.policy의 target_ref 리졸버 체계(submission:...)와는 별개다: 이미지의 읽기는
# 공개 버킷 자체가 답하므로(익명 읽기 정책) storage.api의 presigned download 경로를
# 거치지 않고, 업로드 인가도 `contests.api._get_owned_draft_contest`(소유자+DRAFT
# 게이트)가 이미 지므로 storage.policy.TargetStateResolver를 새로 꽂을 필요가 없다.
CONTEST_IMAGE_TARGET_REF_PREFIX = "contest-image:"


def contest_image_target_ref(contest_id: int) -> str:
    return f"{CONTEST_IMAGE_TARGET_REF_PREFIX}{contest_id}"
