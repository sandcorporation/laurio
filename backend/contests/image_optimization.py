"""ContestImage 최적화 — 썸네일·본문용 webp 파생본을 스캔이 만든다 (#235, ADR-0031/0032).

업로드 직후 큐잉하지 않는다(ADR-0032 「최적화는 스캔이 돈다」) — 이 저장소에는
이벤트로 큐잉되는 태스크 선례가 0건이고, 첫 `.delay()`를 여기서 도입하면 재시도·
시간 예산·행별 격리·수동 진입점을 전부 새로 만들게 된다. 대신 "아직 최적화되지
않은 ContestImage"를 찾는 스캔을 등록부(`core.scans`)에 올려 그 넷을 공짜로 받는다
— 뼈대는 `scoring.services.SUBMISSION_SCORING_SCAN`과 같다.

**이 스캔도 ADR-0031의 규율을 처음부터 받는다.** 실패가 `IMAGE_OPTIMIZATION_
FAILURE_LIMIT`회에 이르고 **동시에** `ContestImage.created_at` 이후
`IMAGE_OPTIMIZATION_FAILURE_GRACE`가 지나면, 그 이미지를 「최적화 불가」로
확정하고(`optimization_failed_at`) 후보에서 뺀다 — 막힌 이미지가 배치 앞자리를
영원히 차지해 새로 올린 이미지가 처리되지 못하는 굶주림을 막는다. 확정된 뒤에도
원본은 계속 보인다(`ContestImage.url`/`.thumbnail_url`이 원본으로 대신 답한다).

**두 종은 함께 성립한다.** 이미지 하나를 처리하는 동안 썸네일·본문용 webp를 둘 다
만들어 둘 다 스토리지에 쓴 뒤에만 `ContestImage`에 두 키를 **한 UPDATE**로 같이
채운다 — 어느 한쪽만 실패하면 이번 시도는 통째로 실패로 남고, 이미 성공한 다른
쪽의 오브젝트는 버려진다(다음 시도가 같은 결정적 키에 다시 써 덮어쓴다). 한 종만
성공한 중간 상태가 이 모델에 표현될 수 없다.
"""

from __future__ import annotations

import io
import logging
from datetime import timedelta

from django.db.models import Count, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce

from core.scans import ScanSpec
from storage.adapters import Bucket, get_storage_adapter

from .models import ContestImage, ContestImageOptimizationAttempt

logger = logging.getLogger(__name__)

# 목록(카드·그리드)용 — 실제 화면 폭보다 넉넉히 잡아 레티나 디스플레이에서도 흐리지
# 않게 한다. 참고 이미지는 시안이지 사진이 아니라 이 정도면 충분하다.
THUMBNAIL_MAX_DIMENSION = 480
# 상세(갤러리·라이트박스)용.
DETAIL_MAX_DIMENSION = 1600
_WEBP_QUALITY = 82

#: #235(ADR-0031): 실패 상한 — scoring의 SCORING_FAILURE_LIMIT과 같은 값을 그대로
#: 따른다(다른 값을 골라야 할 도메인상 이유가 없다).
IMAGE_OPTIMIZATION_FAILURE_LIMIT = 5

#: #235(ADR-0031): 유예. scoring은 6시간인데(심사기간에서 유래), 이미지에는 그런
#: 며칠짜리 기준이 없다 — 참가자가 화면에서 원본 대신 파생본을 보기까지 기다릴
#: 이유가 없으므로 훨씬 짧게 잡는다. 스캔 주기(60초)의 60배라 일시적인 스토리지
#: 장애가 그 안에서 낫는지 볼 여유는 충분하고, 정말 안 되는 것(이미지가 아닌
#: 바이트 등)은 1시간이면 확정된다.
IMAGE_OPTIMIZATION_FAILURE_GRACE = timedelta(hours=1)


def _to_webp_bytes(image, max_dimension: int) -> bytes:
    """리사이즈해 webp 바이트로 인코딩한다. `image`는 호출자가 이미 연 프레임의
    복사본이어야 한다 — `Image.thumbnail`이 제자리에서 리사이즈하므로, 같은 프레임을
    두 크기로 두 번 쓰려면(썸네일·본문) 매번 새 복사본이 필요하다."""

    from PIL import Image

    frame = image
    if frame.mode == "P":
        # 팔레트 모드는 투명도가 인덱스에 숨어 있어 그대로 리사이즈하면 깨진다.
        frame = frame.convert("RGBA")
    elif frame.mode not in ("RGB", "RGBA", "L"):
        frame = frame.convert("RGB")

    frame.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
    buffer = io.BytesIO()
    frame.save(buffer, format="WEBP", quality=_WEBP_QUALITY)
    return buffer.getvalue()


def generate_derivatives(original_bytes: bytes) -> tuple[bytes, bytes]:
    """원본 바이트에서 (썸네일, 본문용) webp 바이트 쌍을 만든다.

    `original_bytes`가 이미지가 아니거나 손상됐으면 Pillow가 그대로 예외를 던진다
    (`PIL.UnidentifiedImageError` 등) — 이 함수는 그 예외를 흡수하지 않는다.
    호출자(`_optimize_one`)가 "이번 시도는 실패"로 기록한다. `im.load()`로 디코딩을
    여기서 강제한다 — 안 그러면 잘린 파일이 지연 디코드 때문에 이 함수를 통과한 뒤
    다른 곳에서야 터진다.
    """

    from PIL import Image

    with Image.open(io.BytesIO(original_bytes)) as opened:
        opened.load()
        thumbnail = _to_webp_bytes(opened.copy(), THUMBNAIL_MAX_DIMENSION)
        detail = _to_webp_bytes(opened.copy(), DETAIL_MAX_DIMENSION)
    return thumbnail, detail


def _derivative_keys(object_key: str) -> tuple[str, str]:
    """원본 object_key에서 결정적으로 파생시킨다 — 재시도가 매번 같은 자리를
    덮어써, 실패한 시도가 스토리지에 고아 오브젝트를 남기지 않는다."""

    return f"{object_key}-thumbnail.webp", f"{object_key}-detail.webp"


def _cap_reached(attempt_count: int, created_at, as_of) -> bool:
    """실패 상한(#235, ADR-0031)에 이르렀는가 — `scoring.services._scoring_cap_reached`
    와 같은 모양이다. 카운트만으로는 부족하고, `created_at` 이후 유예도 지나야 한다."""

    if attempt_count < IMAGE_OPTIMIZATION_FAILURE_LIMIT:
        return False
    return as_of >= created_at + IMAGE_OPTIMIZATION_FAILURE_GRACE


def _pending_contest_images(as_of, ctx):
    """아직 최적화되지 않았고(썸네일·본문 중 하나라도 비어 있고) 「최적화 불가」로
    확정되지도 않은 ContestImage.

    **정렬은 시도 횟수 오름차순이다**(#235, ADR-0031 — `scoring._pending_submissions`
    와 같은 이유). `id` 오름차순만 쓰면 막힌 오래된 이미지가 항상 배치 앞자리를
    차지해, 그 수가 배치 상한을 넘으면 새로 올린 이미지가 한 번도 시도되지 못한다.
    """

    attempt_count = (
        ContestImageOptimizationAttempt.objects.filter(contest_image=OuterRef("pk"))
        .order_by()
        .values("contest_image")
        .annotate(count=Count("id"))
        .values("count")
    )

    return (
        ContestImage.objects.filter(optimization_failed_at__isnull=True)
        .filter(Q(thumbnail_key="") | Q(detail_key=""))
        .annotate(attempt_count=Coalesce(Subquery(attempt_count), 0))
    )


def _record_failure(image: ContestImage, as_of, message: str) -> dict:
    """실패 이력을 남기고, 상한에 이르렀으면 「최적화 불가」로 확정한다.

    `scoring.services._score_one`과 같은 이유로 뼈대(`core.scans.run_scan`)의
    행별 예외 격리에만 맡기지 않는다 — 실패를 `ContestImageOptimizationAttempt`
    로 **남겨야** 상한 판정의 근거가 쌓인다."""

    ContestImageOptimizationAttempt.objects.create(
        contest_image=image, error=message[:2000]
    )
    attempt_count = image.optimization_attempts.count()

    if _cap_reached(attempt_count, image.created_at, as_of):
        # `optimization_failed_at__isnull=True` 조건을 그대로 걸어 둔다 — 이미 다른
        # 실행이 먼저 확정했다면(동시 실행) 조용히 아무 일도 하지 않는다.
        ContestImage.objects.filter(pk=image.pk, optimization_failed_at__isnull=True).update(
            optimization_failed_at=as_of, optimization_error=message[:2000]
        )
        return {"contest_image_id": image.id, "status": "capped", "error": message}

    ContestImage.objects.filter(pk=image.pk).update(optimization_error=message[:2000])
    return {"contest_image_id": image.id, "status": "failed", "error": message}


def _optimize_one(image: ContestImage, as_of, ctx) -> dict:
    """ContestImage 하나를 최적화한다 — `score_submission_once`와 같은 규율로
    이 함수는 절대 예외를 밖으로 던지지 않는다. 모든 실패는
    `ContestImageOptimizationAttempt`에 남고 "failed"·"capped"·"source_not_found"
    로 돌아온다.
    """

    adapter = get_storage_adapter()

    try:
        original_bytes = adapter.read_object(image.object_key, bucket=Bucket.PUBLIC_IMAGES)
        if original_bytes is None:
            # 행이 등록되는 시점(`contests.api.add_contest_image`)은 이미 업로드가
            # 끝난 뒤라 정상적으로는 일어나지 않는다 — 그래도 일어난다면 원본이
            # 영원히 나타나지 않을 수 있는 이상 상태이므로, 다른 실패와 똑같이
            # 상한을 적용한다(예외로 남겨 두면 이 행이 후보 맨 앞을 영원히
            # 차지하는 poison pill이 된다).
            raise FileNotFoundError(
                f"공개 이미지 버킷에서 원본을 찾을 수 없다(object_key={image.object_key!r})."
            )

        thumbnail_bytes, detail_bytes = generate_derivatives(original_bytes)
        thumbnail_key, detail_key = _derivative_keys(image.object_key)
        # content_type을 명시한다(#238) — 이 파생본은 항상 webp로 인코딩하므로
        # (`_to_webp_bytes`) 형식을 모르는 바이트가 아니다. 이걸 생략하면 CDN
        # 앞단이 "모르는 바이트"로 보고 압축·캐시 최적화를 걸지 않는다(스토리지
        # 어댑터 계약이 이 문제를 만났던 지점, staging 실측).
        adapter.write_object(
            thumbnail_key, thumbnail_bytes, bucket=Bucket.PUBLIC_IMAGES, content_type="image/webp"
        )
        adapter.write_object(
            detail_key, detail_bytes, bucket=Bucket.PUBLIC_IMAGES, content_type="image/webp"
        )
    except Exception as exc:  # noqa: BLE001 - 한 행의 실패가 배치를 막으면 안 된다.
        logger.exception(
            "ContestImage(pk=%s) 최적화 중 예외, 다음 건으로 계속", image.id
        )
        return _record_failure(image, as_of, f"{type(exc).__name__}: {exc}")

    # 둘 다 성공했을 때만 한 UPDATE로 같이 채운다 — 한 종만 성공한 상태를 남기지
    # 않는다(모듈 docstring).
    ContestImage.objects.filter(pk=image.pk).update(
        thumbnail_key=thumbnail_key, detail_key=detail_key
    )
    return {"contest_image_id": image.id, "status": "optimized"}


# order_by는 뼈대 기본값(`id` 오름차순)의 예외다(#235, ADR-0031) — `_pending_
# contest_images`가 annotate하는 `attempt_count`가 먼저고 `id`가 동률을 가른다.
CONTEST_IMAGE_OPTIMIZATION_SCAN = ScanSpec(
    name="contest-image-optimization",
    candidates=_pending_contest_images,
    handle_row=_optimize_one,
    order_by=("attempt_count", "id"),
)
