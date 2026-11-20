"""ContestImage 최적화 스캔 — 썸네일·본문용 webp (#235, ADR-0031/0032).

시임은 HTTP다(CLAUDE.md) — 스캔은 `POST /api/internal/scans/contest-image-optimization`
으로 돌린다. 업로드 자체(presigned POST 발급·등록·순서·제거)는 `test_contest_images.py`
(#234)가 이미 고정하고 있으므로 여기서는 다시 단언하지 않는다.
"""

from __future__ import annotations

import io
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from contests.image_optimization import (
    IMAGE_OPTIMIZATION_FAILURE_GRACE,
    IMAGE_OPTIMIZATION_FAILURE_LIMIT,
)
from contests.models import Category, Contest, ContestImage, DeliverableType
from storage.adapters.base import Bucket
from storage.adapters.fake import FakeStorageAdapter

CONTESTS_URL = "/api/contests"
SCAN_URL = "/api/internal/scans/contest-image-optimization"


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _run_scan(client):
    response = client.post(SCAN_URL, **_internal_headers())
    assert response.status_code == 200, response.json()
    return response.json()


def _login(client, uid="sponsor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _verify(client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


@pytest.fixture
def category(db):
    return Category.objects.create(name="교육")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _create_draft(client, access, *, category, deliverable_type_ids, prize=2_000_000):
    response = client.post(
        CONTESTS_URL,
        data={
            "title": "이미지 최적화 대상",
            "category_id": category.id,
            "deliverable_type_ids": deliverable_type_ids,
            "description": "설명",
            "prize": prize,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    return response.json()


def _request_upload_url(client, access, contest_id, *, content_type="image/png"):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/images/upload-url",
        data={"content_type": content_type},
        content_type="application/json",
        **_auth_header(access),
    )


def _add_image(client, access, contest_id, object_key):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/images",
        data={"object_key": object_key},
        content_type="application/json",
        **_auth_header(access),
    )


def _real_png_bytes(size=(64, 48), color=(200, 40, 40)) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_and_register(client, access, contest_id, *, content=b"fake image bytes") -> dict:
    issued = _request_upload_url(client, access, contest_id)
    assert issued.status_code == 200, issued.json()
    object_key = issued.json()["object_key"]

    FakeStorageAdapter().write_object(object_key, content, bucket=Bucket.PUBLIC_IMAGES)

    created = _add_image(client, access, contest_id, object_key)
    assert created.status_code == 200, created.json()
    return created.json()


def _sponsor_and_draft(client, category, landing_type, *, ci):
    pair = _login(client, uid=ci)
    _verify(client, pair["access"], ci=ci)
    contest = _create_draft(
        client, pair["access"], category=category, deliverable_type_ids=[landing_type.id]
    )
    return pair, contest


# --- 최적화 전: 원본이 보인다 -------------------------------------------------


@pytest.mark.django_db
def test_before_the_scan_runs_both_urls_fall_back_to_the_original(
    client, category, landing_type
):
    pair, contest = _sponsor_and_draft(client, category, landing_type, ci="opt-1")
    created = _upload_and_register(client, pair["access"], contest["id"], content=_real_png_bytes())

    reread = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))
    image = reread.json()["images"][0]
    object_key = ContestImage.objects.get(id=created["id"]).object_key

    assert image["url"].endswith(f"/{object_key}")
    assert image["thumbnail_url"].endswith(f"/{object_key}")
    assert image["url"] == image["thumbnail_url"]


# --- 스캔 한 회차 뒤: 둘 다 있다 -----------------------------------------------


@pytest.mark.django_db
def test_scan_creates_both_derivatives_after_one_run(client, category, landing_type):
    pair, contest = _sponsor_and_draft(client, category, landing_type, ci="opt-2")
    created = _upload_and_register(client, pair["access"], contest["id"], content=_real_png_bytes())

    result = _run_scan(client)
    row = next(r for r in result["rows"] if r["contest_image_id"] == created["id"])
    assert row["status"] == "optimized"

    image = ContestImage.objects.get(id=created["id"])
    assert image.thumbnail_key
    assert image.detail_key
    assert image.is_optimized is True

    # 파생본이 실제로 스토리지에 쓰였고, 다시 디코드할 수 있는 webp다.
    from PIL import Image

    adapter = FakeStorageAdapter()
    thumb_bytes = adapter.read_object(image.thumbnail_key, bucket=Bucket.PUBLIC_IMAGES)
    detail_bytes = adapter.read_object(image.detail_key, bucket=Bucket.PUBLIC_IMAGES)
    assert thumb_bytes is not None and detail_bytes is not None
    with Image.open(io.BytesIO(thumb_bytes)) as im:
        assert im.format == "WEBP"
    with Image.open(io.BytesIO(detail_bytes)) as im:
        assert im.format == "WEBP"

    # 목록은 작은 것을, 상세는 큰 것을 받는다 — 화면은 어느 쪽인지 판정하지
    # 않고 백엔드가 이미 갈라 준 URL을 그대로 쓴다(spec #225 AC).
    reread = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))
    image_out = reread.json()["images"][0]
    assert image_out["thumbnail_url"].endswith(f"/{image.thumbnail_key}")
    assert image_out["url"].endswith(f"/{image.detail_key}")
    assert image_out["thumbnail_url"] != image_out["url"]

    # 파생본은 자기 형식을 밝힌다 — 이걸 빠뜨리면 CDN 이 "모르는 바이트"로 보고
    # 압축·캐시 최적화를 걸지 않는다(#238, staging 실측: 예전엔 binary/octet-stream).
    assert adapter.written_content_type(image.thumbnail_key, bucket=Bucket.PUBLIC_IMAGES) == "image/webp"
    assert adapter.written_content_type(image.detail_key, bucket=Bucket.PUBLIC_IMAGES) == "image/webp"

    # 원본은 지워지지 않는다.
    assert adapter.read_object(image.object_key, bucket=Bucket.PUBLIC_IMAGES) is not None

    # 공개 목록(GET /contests)도 같은 두 URL을 그대로 낸다 — 목록 카드가 큰 원본을
    # 받아 나가지 않는다. list_contests는 (`_serialize_contest`를 거치는 상세와
    # 달리) Contest 쿼리셋을 그대로 스키마에 태우므로, 이 값들이 모델 프로퍼티가
    # 아니라 스키마 필드 이름과 다르게 계산됐다면 여기서만 드러난다.
    Contest.objects.filter(id=contest["id"]).update(status=Contest.Status.PUBLISHED)
    listed = client.get(CONTESTS_URL)
    assert listed.status_code == 200
    listed_contest = next(c for c in listed.json()["items"] if c["id"] == contest["id"])
    listed_image = listed_contest["images"][0]
    assert listed_image["thumbnail_url"].endswith(f"/{image.thumbnail_key}")
    assert listed_image["url"].endswith(f"/{image.detail_key}")


@pytest.mark.django_db
def test_optimizing_again_does_not_reprocess_an_already_optimized_image(
    client, category, landing_type
):
    """이미 둘 다 있는 이미지는 다음 회차의 후보에서 빠진다 — 계속 재처리하지
    않는다."""

    pair, contest = _sponsor_and_draft(client, category, landing_type, ci="opt-3")
    created = _upload_and_register(client, pair["access"], contest["id"], content=_real_png_bytes())

    first = _run_scan(client)
    assert any(r["contest_image_id"] == created["id"] for r in first["rows"])

    second = _run_scan(client)
    assert not any(r["contest_image_id"] == created["id"] for r in second["rows"])


# --- 이미지가 아닌 바이트: 그 한 건만 실패하고 배치는 계속된다 ------------------


@pytest.mark.django_db
def test_a_non_image_object_fails_alone_and_does_not_block_the_rest_of_the_batch(
    client, category, landing_type
):
    pair, contest = _sponsor_and_draft(client, category, landing_type, ci="opt-4")

    broken = _upload_and_register(client, pair["access"], contest["id"], content=b"not an image at all")
    healthy = _upload_and_register(client, pair["access"], contest["id"], content=_real_png_bytes())

    result = _run_scan(client)

    broken_row = next(r for r in result["rows"] if r["contest_image_id"] == broken["id"])
    healthy_row = next(r for r in result["rows"] if r["contest_image_id"] == healthy["id"])

    assert broken_row["status"] == "failed"
    assert healthy_row["status"] == "optimized"

    broken_image = ContestImage.objects.get(id=broken["id"])
    assert broken_image.is_optimized is False
    assert broken_image.optimization_attempts.count() == 1
    assert broken_image.optimization_error

    # 실패한 쪽도 원본은 계속 보인다 — 빈자리가 생기지 않는다.
    reread = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))
    broken_out = next(i for i in reread.json()["images"] if i["id"] == broken["id"])
    assert broken_out["url"].endswith(f"/{broken_image.object_key}")


# --- 실패 상한: 반드시 끝난다(ADR-0031) ---------------------------------------


@pytest.mark.django_db
def test_repeated_failures_are_confirmed_unoptimizable_after_the_cap(
    client, category, landing_type
):
    """실패가 상한(5회)에 이르고 **동시에** 유예(1시간)가 지나야 확정된다 — 둘 중
    하나만으로는 확정되지 않는다."""

    pair, contest = _sponsor_and_draft(client, category, landing_type, ci="opt-5")
    broken = _upload_and_register(client, pair["access"], contest["id"], content=b"garbage")
    image_id = broken["id"]

    # 아직 created_at 이후 유예가 지나지 않았다 — 횟수만으로는 확정되지 않는다.
    for _ in range(IMAGE_OPTIMIZATION_FAILURE_LIMIT):
        _run_scan(client)

    image = ContestImage.objects.get(id=image_id)
    assert image.optimization_attempts.count() == IMAGE_OPTIMIZATION_FAILURE_LIMIT
    assert image.optimization_failed_at is None

    # created_at을 유예 너머로 되돌린다(다른 스펙들의 관용구와 같다 —
    # Contest.objects.filter(...).update(status=...)).
    ContestImage.objects.filter(id=image_id).update(
        created_at=timezone.now() - IMAGE_OPTIMIZATION_FAILURE_GRACE - timedelta(minutes=1)
    )

    result = _run_scan(client)
    row = next(r for r in result["rows"] if r["contest_image_id"] == image_id)
    assert row["status"] == "capped"

    image.refresh_from_db()
    assert image.optimization_failed_at is not None
    assert image.optimization_error

    # 확정된 뒤에도 원본은 계속 보인다.
    reread = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(pair["access"]))
    out = next(i for i in reread.json()["images"] if i["id"] == image_id)
    assert out["url"].endswith(f"/{image.object_key}")

    # 그리고 후보에서 빠진다 — 새로 올린 이미지가 같은 회차에 처리되도록.
    attempts_before = image.optimization_attempts.count()
    again = _run_scan(client)
    assert not any(r["contest_image_id"] == image_id for r in again["rows"])
    assert image.optimization_attempts.count() == attempts_before


# --- 함께 성립: 스토리지 쓰기가 실패하면 한 종도 채워지지 않는다 ----------------


@pytest.mark.django_db
def test_a_storage_write_failure_leaves_neither_derivative_populated(
    client, category, landing_type, settings
):
    pair, contest = _sponsor_and_draft(client, category, landing_type, ci="opt-6")
    created = _upload_and_register(client, pair["access"], contest["id"], content=_real_png_bytes())
    object_key = ContestImage.objects.get(id=created["id"]).object_key
    target_ref = object_key.rsplit("/", 1)[0]

    settings.STORAGE_FAKE_WRITE_RAISING_TARGET_REFS = [target_ref]
    result = _run_scan(client)

    row = next(r for r in result["rows"] if r["contest_image_id"] == created["id"])
    assert row["status"] == "failed"

    image = ContestImage.objects.get(id=created["id"])
    assert image.thumbnail_key == ""
    assert image.detail_key == ""
    assert image.is_optimized is False
