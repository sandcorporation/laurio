"""ContestImage 업로드 상수 + 공유 로직 (#234/#236, ADR-0032).

크기 상한·허용 content-type은 사업 판단(운영자가 배포 없이 조정하는 값)이 아니라
"presigned POST 정책에 무엇을 서명해 넣는가"라는 기술값이다 — 다른 상한
(`PlatformPolicy.max_contest_images`, 장수)과 자리가 다르다: 장수는 플랫폼
운영이고, 바이트 상한·MIME 허용목록은 이 코드가 스토리지에 무엇을 믿고
맡길지를 정하는 값이라 배포로 바꾼다.

**업로드 발급·등록·순서변경·제거는 `contests.api`(공모전)와
`contests.assignment_api`(과제) 양쪽이 똑같이 쓴다**(#236, spec #225 "규칙을
가르면 화면마다 설명할 문장이 늘어난다"). 그래서 그 넷을 여기 함수로 한 번만
적는다 — 두 라우터는 자신의 게이트(`_get_owned_draft_contest` /
`_get_owned_editable_assignment`)로 이미 확인한 `Contest` 행을 넘기기만 한다.
「어느 Contest 가 이미지를 고칠 수 있는가」는 각 라우터의 게이트가 답하고,
「이미지를 어떻게 고치는가」는 이 모듈이 답한다 — 섞으면 두 표면이 검증 로직을
각자 베껴 언젠가 갈라진다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from ninja.errors import HttpError

from policies.scope import current_policy
from storage.adapters import Bucket, get_storage_adapter

from .models import Contest, ContestImage
from .schemas import (
    ContestImageCreateIn,
    ContestImageOut,
    ContestImageReorderIn,
    ContestImageUploadUrlIn,
    ContestImageUploadUrlOut,
)

# 10MB — 참고 이미지는 시안·와이어프레임 스크린샷이지 원본 디자인 파일이 아니다.
MAX_CONTEST_IMAGE_BYTES = 10 * 1024 * 1024

ALLOWED_CONTEST_IMAGE_CONTENT_TYPES = frozenset(
    {"image/png", "image/jpeg", "image/webp", "image/gif"}
)

# object_key의 target_ref 접두어 — "<CONTEST_IMAGE_TARGET_REF_PREFIX>{contest_id}/<hex>".
# storage.policy의 target_ref 리졸버 체계(submission:...)와는 별개다: 이미지의 읽기는
# 공개 버킷 자체가 답하므로(익명 읽기 정책) storage.api의 presigned download 경로를
# 거치지 않고, 업로드 인가도 각 라우터의 소유자 게이트가 이미 지므로
# storage.policy.TargetStateResolver를 새로 꽂을 필요가 없다. 접두어는 "contest-image:"
# 하나뿐이다 — 과제도 같은 `Contest` 행이고(ADR-0028) object_key 소속 확인은
# `contest.id`로 하지 종류(kind)로 가르지 않는다.
CONTEST_IMAGE_TARGET_REF_PREFIX = "contest-image:"


def contest_image_target_ref(contest_id: int) -> str:
    return f"{CONTEST_IMAGE_TARGET_REF_PREFIX}{contest_id}"


def serialize_contest_image(image: ContestImage) -> ContestImageOut:
    """**주소를 여기서 조립하지 않는다** — 모델의 `url`·`thumbnail_url`이 답한다(#235).

    그 둘이 최적화 전·실패 시에는 원본을, 끝난 뒤에는 파생본을 가리킨다. 화면이
    「파생본이 있는가」를 다시 판정하지 않게 하는 것이 #235 의 결정이고, 그 판정을
    이 함수가 한 번 더 적으면 두 곳이 어긋난다.
    """

    return ContestImageOut(
        id=image.id, url=image.url, thumbnail_url=image.thumbnail_url, order=image.order
    )


def request_upload_url(
    contest: Contest, payload: ContestImageUploadUrlIn
) -> ContestImageUploadUrlOut:
    """호출부가 이미 소유권·편집 가능 여부를 확인한 `contest`에 대해 presigned
    POST를 발급한다 — 게이트는 호출부(`request_contest_image_upload_url` /
    `request_assignment_image_upload_url`)의 몫이다."""

    if payload.content_type not in ALLOWED_CONTEST_IMAGE_CONTENT_TYPES:
        raise HttpError(422, "이미지는 png/jpeg/webp/gif 형식만 올릴 수 있습니다.")

    policy = current_policy()
    if contest.images.count() >= policy.max_contest_images:
        raise HttpError(
            422, f"이미지는 최대 {policy.max_contest_images}장까지 올릴 수 있습니다."
        )

    target_ref = contest_image_target_ref(contest.id)
    object_key = f"{target_ref}/{uuid4().hex}"

    adapter = get_storage_adapter()
    presigned = adapter.presign_upload(
        object_key,
        bucket=Bucket.PUBLIC_IMAGES,
        content_type=payload.content_type,
        expires_in=timedelta(seconds=settings.STORAGE_UPLOAD_URL_TTL_SECONDS),
        max_size_bytes=MAX_CONTEST_IMAGE_BYTES,
    )
    return ContestImageUploadUrlOut(
        object_key=presigned.object_key,
        upload_url=presigned.url,
        method=presigned.method,
        fields=presigned.fields,
        expires_at=presigned.expires_at.isoformat(),
    )


def create_image(contest: Contest, payload: ContestImageCreateIn) -> ContestImageOut:
    """presigned POST로 실제 바이트가 올라간 뒤, 그 object_key를 `contest`의
    이미지 목록에 등록한다. `object_key`가 이 Contest의 target_ref 아래인지
    확인한다 — 안 그러면 남의 upload-url 응답에서 얻은(또는 추측한) object_key를
    자기 Contest에 붙여 다른 Contest의 이미지를 여기 슬롯에 매다는 경로가
    열린다."""

    target_ref = contest_image_target_ref(contest.id)
    if not payload.object_key.startswith(f"{target_ref}/"):
        raise HttpError(422, "object_key가 이 대상에 속하지 않습니다.")

    policy = current_policy()
    if contest.images.count() >= policy.max_contest_images:
        raise HttpError(
            422, f"이미지는 최대 {policy.max_contest_images}장까지 올릴 수 있습니다."
        )

    next_order = contest.images.count()
    image = ContestImage.objects.create(
        contest=contest, object_key=payload.object_key, order=next_order
    )
    return serialize_contest_image(image)


def reorder_image(
    contest: Contest, image_id: int, payload: ContestImageReorderIn
) -> ContestImageOut:
    try:
        image = contest.images.get(id=image_id)
    except ContestImage.DoesNotExist as exc:
        raise HttpError(404, "이미지를 찾을 수 없습니다.") from exc

    image.order = payload.order
    image.save(update_fields=["order"])
    return serialize_contest_image(image)


def remove_image(contest: Contest, image_id: int) -> None:
    """이미지를 뺀다 — **이 행만 지운다.** object_key가 가리키는 오브젝트는
    그대로 남는다(어댑터에 삭제 메서드가 없다, ADR-0005/0032) — 재개최(#236)가
    같은 오브젝트를 가리키는 새 행을 만들 수 있기 때문이다."""

    try:
        image = contest.images.get(id=image_id)
    except ContestImage.DoesNotExist as exc:
        raise HttpError(404, "이미지를 찾을 수 없습니다.") from exc

    image.delete()
