"""content-type 백필 (#268 후속) — 옛 자료의 다운로드에 확장자를 되돌린다.

`SubmissionAsset.content_type` 은 #241 이 만든 필드라 그 전에 올라간 자료는 값이
비어 있고, 그러면 다운로드가 확장자 없는 `download` 로 떨어진다(이름이 `download`
인 것 자체는 설계다 — `storage.filenames` 참고, 확장자만 이 값에서 온다).
staging 실측(2026-09-10): 소스 37건·시연 영상 15건이 그 상태였고 과제 제출물은
전부 그랬다.

시임은 언제나 HTTP 다(CLAUDE.md). 백필은 관리 명령이라 `call_command` 로 부르지만,
**그 결과는 다운로드 응답으로 확인한다** — 고쳐야 할 것이 DB 의 문자열이 아니라
사용자가 받는 파일 이름이기 때문이다.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from django.core.management import call_command

from storage.adapters.fake import FakeStorageAdapter
from submissions.models import SubmissionAsset
from tests.test_submissions import (
    _auth_header,
    _publish_contest,
    _source_object_key,
    _submit,
    _verified_user,
)

DOWNLOADS_URL = "/api/storage/downloads"


# 기준데이터는 파일마다 자기 것을 만든다(`test_demo_video_retention.py` 와 같은
# 관용구) — 이름이 겹치면 병렬 워커끼리 유일성 제약에서 부딪친다.
@pytest.fixture
def category(db):
    from contests.models import Category

    return Category.objects.create(name="형식백필")


@pytest.fixture
def landing_type(db):
    from contests.models import DeliverableType

    return DeliverableType.objects.create(name="웹 서비스-형식백필", minimum_prize=500_000)


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app.py", "print('hello')\n")
    return buf.getvalue()


def _legacy_source(client, category, landing_type, *, uid: str, content: bytes | None):
    """content_type 이 비어 있는 옛 소스 자료 하나 — `content` 가 None 이면
    오브젝트도 없다(파기된 영상·바이트를 안 쓴 옛 시드와 같은 상태)."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, uid, f"{uid}-ci")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    if content is not None:
        FakeStorageAdapter().write_object(source_key, content)

    # content_type 을 아예 싣지 않는다 — #241 이전 클라이언트가 하던 그대로다.
    submit = _submit(
        client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]}
    )
    assert submit.status_code == 201, submit.content
    asset = SubmissionAsset.objects.get(submission_id=submit.json()["id"], kind="source")
    assert asset.content_type == ""
    return contest, dev, source_key, asset


def _download(client, dev, contest, source_key):
    response = client.post(
        DOWNLOADS_URL,
        data={
            "target_ref": f"submission:{contest['id']}:{dev['user_id']}:source",
            "object_key": source_key,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 200, response.content
    return response.json()["download_url"]


@pytest.mark.django_db
def test_backfill_gives_a_legacy_source_its_extension_back(client, category, landing_type):
    contest, dev, source_key, asset = _legacy_source(
        client, category, landing_type, uid="dev-backfill-1", content=_zip_bytes()
    )

    # 백필 전 — 확장자가 없다(#241 이 이 경우를 이미 그렇게 다룬다).
    assert 'filename="download"' in _download(client, dev, contest, source_key)

    call_command("backfill_asset_content_types")

    assert 'filename="download.zip"' in _download(client, dev, contest, source_key)
    asset.refresh_from_db()
    assert asset.content_type == "application/zip"


@pytest.mark.django_db
def test_backfill_is_idempotent(client, category, landing_type):
    """두 번 돌려도 같다 — 이미 채워진 행은 조회에서 빠진다."""

    contest, dev, source_key, asset = _legacy_source(
        client, category, landing_type, uid="dev-backfill-2", content=_zip_bytes()
    )
    call_command("backfill_asset_content_types")
    call_command("backfill_asset_content_types")

    asset.refresh_from_db()
    assert asset.content_type == "application/zip"
    assert 'filename="download.zip"' in _download(client, dev, contest, source_key)


@pytest.mark.django_db
def test_backfill_leaves_unrecognisable_bytes_alone(client, category, landing_type):
    """모르는 형식에 `application/octet-stream` 을 채우지 않는다 — 결과는 같은데
    DB 에만 거짓이 남는다(`build_download_filename` 이 그 값을 다시 "모른다"로
    해석한다)."""

    contest, dev, source_key, asset = _legacy_source(
        client, category, landing_type, uid="dev-backfill-3", content=b"not a known format at all"
    )
    call_command("backfill_asset_content_types")

    asset.refresh_from_db()
    assert asset.content_type == ""
    assert 'filename="download"' in _download(client, dev, contest, source_key)


@pytest.mark.django_db
def test_backfill_survives_an_asset_whose_object_is_gone(client, category, landing_type):
    """오브젝트가 없는 행은 실패가 아니다 — 파기된 시연 영상(ADR-0035)과 바이트를
    안 쓴 옛 시드가 그 상태다. 명령이 죽지 않고, 그 행도 그대로 남는다."""

    contest, dev, source_key, asset = _legacy_source(
        client, category, landing_type, uid="dev-backfill-4", content=None
    )
    call_command("backfill_asset_content_types")

    asset.refresh_from_db()
    assert asset.content_type == ""


@pytest.mark.django_db
def test_dry_run_changes_nothing(client, category, landing_type):
    contest, dev, source_key, asset = _legacy_source(
        client, category, landing_type, uid="dev-backfill-5", content=_zip_bytes()
    )
    call_command("backfill_asset_content_types", dry_run=True)

    asset.refresh_from_db()
    assert asset.content_type == ""
    assert 'filename="download"' in _download(client, dev, contest, source_key)
