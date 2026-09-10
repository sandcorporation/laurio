"""시연 영상 파일 보존 기간 만료 스캔 (#262, ADR-0035).

**파기하는 것은 파일이지 자료가 아니다.** 그래서 이 파일이 확인하는 것은
`SubmissionAsset` 행이 아니라 그 행이 가리키는 스토리지 오브젝트가 사라지는가,
그리고 그 행·`Evidence`·다운로드 응답이 그 사건을 어떻게 겪는가다.

핵심 대상:

- 공모전은 이의 창의 끝(`judging_ends_at`) + 유예일수가 파기 시점이다.
- Assignment(ADR-0028)에는 심사기간이 없어 마감(`deadline_at`) + 같은 유예를 쓴다.
- 파기는 스토리지 오브젝트만 지운다 — 자료 행·라벨·Evidence는 남는다.
- 스캔은 멱등하다 — 이미 지워진 오브젝트를 다시 지워도 실패하지 않는다.
- 다운로드는 파기된 오브젝트에 대해 오류나 빈 응답이 아니라 "보존 기간이
  지났다"를 정상 응답(200, `expired=True`)으로 답한다.
- 소스는 이 스캔의 대상이 아니다 — 같은 제출의 소스 오브젝트는 그대로 남는다.

시임은 언제나 HTTP다(CLAUDE.md) — `_publish_contest`·`_close_contest` 같은
헬퍼로 기존 테스트가 이미 세운 관용구를 그대로 쓴다.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from contests.models import Contest, DeliverableType
from core.models import ClockOverride
from storage.adapters.fake import FakeStorageAdapter
from submissions.models import SubmissionAsset
from tests.submission_assets import assets_of
from tests.test_source_readings import _close_contest, _internal_headers
from tests.test_submissions import (
    _demo_video_object_key,
    _edit,
    _publish_contest,
    _source_object_key,
    _submit,
    _verified_user,
)

RETENTION_SCAN_URL = "/api/internal/scans/demo-video-retention-purge"
DOWNLOADS_URL = "/api/storage/downloads"

GRACE_DAYS = 30  # PlatformPolicy.demo_video_retention_grace_days 기본값(#263).


@pytest.fixture
def category(db):
    from contests.models import Category

    return Category.objects.create(name="시연영상보존")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스-영상보존", minimum_prize=500_000)


def _freeze(at) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _submit_with_demo_video(client, dev: dict, contest_id: int, *, requirement_id: int) -> dict:
    source_key = _source_object_key(contest_id, dev["user_id"])
    video_key = _demo_video_object_key(contest_id, dev["user_id"])
    FakeStorageAdapter().write_object(source_key, b"zip bytes")
    FakeStorageAdapter().write_object(video_key, b"video bytes")

    response = _submit(
        client,
        dev["access"],
        contest_id,
        {
            "assets": [
                {"kind": "source", "value": source_key},
                {"kind": "demo_video", "value": video_key, "label": "시연 영상"},
            ],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [],
                }
            ],
        },
    )
    assert response.status_code == 201, response.content
    body = response.json()
    video_asset_id = assets_of(body, "demo_video")[0]["id"]

    # 근거가 이 영상 자료를 가리킨다 — 파기 뒤에도 근거가 살아 있는지를 보려면
    # 먼저 근거가 실제로 이 자료를 가리켜야 한다.
    linked = _edit(
        client,
        dev["access"],
        contest_id,
        {
            "assets": [
                {"kind": "source", "value": source_key},
                {"kind": "demo_video", "value": video_key, "label": "시연 영상", "id": video_asset_id},
            ],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [
                        {"kind": "video_timestamp", "value": "00:01:23", "asset_id": video_asset_id}
                    ],
                }
            ],
        },
    )
    assert linked.status_code == 200, linked.content
    return {
        "submission": linked.json(),
        "video_key": video_key,
        "source_key": source_key,
        "video_asset_id": video_asset_id,
    }


def _run_retention_scan(client) -> dict:
    response = client.post(RETENTION_SCAN_URL, **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _get_submission(client, access: str, submission_id: int) -> dict:
    response = client.get(f"/api/submissions/{submission_id}", **{"HTTP_AUTHORIZATION": f"Bearer {access}"})
    assert response.status_code == 200, response.content
    return response.json()


# --- 공모전: 이의 창의 끝(judging_ends_at) + 유예일수 -------------------------------


@pytest.mark.django_db
def test_demo_video_file_survives_before_the_grace_period_elapses(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-retain-1", "dev-retain-ci-1")
    setup = _submit_with_demo_video(client, dev, contest["id"], requirement_id=requirement_id)

    _close_contest(client, contest, deadline=deadline)
    closed = Contest.objects.get(id=contest["id"])
    assert closed.judging_ends_at is not None

    # 이의 창이 닫히고 유예가 거의 다 됐지만 아직 하루가 남았다.
    _freeze(closed.judging_ends_at + timedelta(days=GRACE_DAYS - 1))
    result = _run_retention_scan(client)

    assert result["count"] == 0
    assert FakeStorageAdapter().read_object(setup["video_key"]) == b"video bytes"

    body = _get_submission(client, dev["access"], setup["submission"]["id"])
    video_asset = assets_of(body, "demo_video")[0]
    assert video_asset["demo_video_destroyed"] is False
    assert video_asset["demo_video_retention_deadline"] is not None


@pytest.mark.django_db
def test_demo_video_file_is_purged_after_the_appeal_window_plus_grace_elapses(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-retain-2", "dev-retain-ci-2")
    setup = _submit_with_demo_video(client, dev, contest["id"], requirement_id=requirement_id)

    _close_contest(client, contest, deadline=deadline)
    closed = Contest.objects.get(id=contest["id"])

    _freeze(closed.judging_ends_at + timedelta(days=GRACE_DAYS))
    result = _run_retention_scan(client)

    assert result["count"] == 1
    assert result["rows"][0]["submission_asset_id"] == setup["video_asset_id"]

    # 파일만 사라졌다 — 스토리지 오브젝트는 없다.
    assert FakeStorageAdapter().read_object(setup["video_key"]) is None

    # 소스는 이 스캔의 대상이 아니다 — 그대로 남는다("소스는 파기하지 않는다").
    assert FakeStorageAdapter().read_object(setup["source_key"]) == b"zip bytes"

    # 자료 행·라벨·Evidence는 그대로 남는다.
    asset = SubmissionAsset.objects.get(id=setup["video_asset_id"])
    assert asset.destroyed_at is not None
    assert asset.label == "시연 영상"
    assert asset.value == setup["video_key"]

    body = _get_submission(client, dev["access"], setup["submission"]["id"])
    video_asset = assets_of(body, "demo_video")[0]
    assert video_asset["demo_video_destroyed"] is True
    assert video_asset["id"] == setup["video_asset_id"]

    evidence = body["requirement_responses"][0]["evidence"][0]
    assert evidence["asset_id"] == setup["video_asset_id"]
    assert evidence["value"] == "00:01:23"


@pytest.mark.django_db
def test_retention_scan_is_idempotent_across_repeated_runs(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-retain-3", "dev-retain-ci-3")
    setup = _submit_with_demo_video(client, dev, contest["id"], requirement_id=requirement_id)

    _close_contest(client, contest, deadline=deadline)
    closed = Contest.objects.get(id=contest["id"])
    _freeze(closed.judging_ends_at + timedelta(days=GRACE_DAYS))

    first = _run_retention_scan(client)
    assert first["count"] == 1

    second = _run_retention_scan(client)
    assert second["count"] == 0
    assert second["failed"] == []


@pytest.mark.django_db
def test_retention_scan_recovers_when_the_file_was_already_deleted_but_not_yet_marked(
    client, category, landing_type
):
    """멱등성의 핵심 시나리오 — 지운 다음 기록하기 전에 죽은 상황을 흉내낸다.
    다음 실행이 이미 없는 키를 한 번 더 지우는 것으로 끝나야 한다(오류 없이)."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-retain-4", "dev-retain-ci-4")
    setup = _submit_with_demo_video(client, dev, contest["id"], requirement_id=requirement_id)

    _close_contest(client, contest, deadline=deadline)
    closed = Contest.objects.get(id=contest["id"])
    _freeze(closed.judging_ends_at + timedelta(days=GRACE_DAYS))

    # 파일만 먼저 지워진 상태(destroyed_at은 아직 비어 있다)를 흉내낸다.
    FakeStorageAdapter().delete_object(setup["video_key"])
    assert SubmissionAsset.objects.get(id=setup["video_asset_id"]).destroyed_at is None

    result = _run_retention_scan(client)

    assert result["count"] == 1
    assert result["failed"] == []
    asset = SubmissionAsset.objects.get(id=setup["video_asset_id"])
    assert asset.destroyed_at is not None


# --- Assignment: 심사기간이 없어 마감(deadline_at) + 같은 유예를 쓴다 ------------------


_OPERATOR_PASSWORD = "zzzz-unrelated-passphrase-8841"


def _operator_client(username: str):
    call_command("create_operator", username, password=_OPERATOR_PASSWORD, superuser=True)
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": _OPERATOR_PASSWORD},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert response.status_code == 200, response.content
    return operator


def _create_and_open_assignment(client, *, deliverable_type_ids, sponsor_uid, deadline_at):
    from tests.test_submissions import _login, _auth_header

    root = _operator_client(f"root-{sponsor_uid}")
    pair = _login(client, sponsor_uid)
    username = client.get(
        "/api/accounts/me", **_auth_header(pair["access"])
    ).json()["username"]
    grant = root.post(
        "/api/operator/assignment-permissions/grant",
        data={"username": username, "reason": "수업 개설 승인"},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert grant.status_code == 200, grant.content

    created = client.post(
        "/api/assignments",
        data={
            "title": f"{sponsor_uid}의 과제",
            "deliverable_type_ids": deliverable_type_ids,
            "description": "과제 설명",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [{"text": "함수를 정의한다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]
    requirement_id = created.json()["requirements"][0]["id"]

    opened = client.post(
        f"/api/assignments/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert opened.status_code == 200, opened.content
    return {
        "id": assignment_id,
        "invite_code": opened.json()["invite_code"],
        "requirement_id": requirement_id,
    }


@pytest.mark.django_db
def test_assignment_demo_video_uses_deadline_plus_grace_since_it_has_no_judging_ends_at(
    client, landing_type
):
    from tests.test_submissions import _auth_header, _login

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client,
        deliverable_type_ids=[landing_type.id],
        sponsor_uid="retain-teacher-1",
        deadline_at=deadline,
    )

    student_pair = _login(client, "retain-student-1")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]

    source_key = f"submission:{assignment['id']}:{student_id}:source/{uuid.uuid4().hex}"
    video_key = f"submission:{assignment['id']}:{student_id}:demo-video/{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(source_key, b"zip bytes")
    FakeStorageAdapter().write_object(video_key, b"video bytes")

    submitted = client.post(
        f"/api/contests/{assignment['id']}/submissions",
        data={
            "assets": [
                {"kind": "source", "value": source_key},
                {"kind": "demo_video", "value": video_key},
            ],
            "requirement_responses": [
                {"requirement_id": assignment["requirement_id"], "is_met": True, "evidence": []}
            ],
            "invite_code": assignment["invite_code"],
        },
        content_type="application/json",
        **_auth_header(student_pair["access"]),
    )
    assert submitted.status_code == 201, submitted.content
    video_asset_id = assets_of(submitted.json(), "demo_video")[0]["id"]

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )
    close_resp = client.post("/api/internal/scans/assignment-close", **_internal_headers())
    assert close_resp.status_code == 200
    closed = Contest.objects.get(id=assignment["id"])
    assert closed.status == Contest.Status.ASSIGNMENT_CLOSED
    assert closed.judging_ends_at is None  # ADR-0028 — Assignment에는 심사기간이 없다.

    # 마감 + 유예 - 1일: 아직이다.
    _freeze(deadline + timedelta(days=GRACE_DAYS - 1))
    too_early = _run_retention_scan(client)
    assert too_early["count"] == 0
    assert FakeStorageAdapter().read_object(video_key) == b"video bytes"

    # 마감 + 유예: 파기된다.
    _freeze(deadline + timedelta(days=GRACE_DAYS))
    on_time = _run_retention_scan(client)
    assert on_time["count"] == 1
    assert FakeStorageAdapter().read_object(video_key) is None

    asset = SubmissionAsset.objects.get(id=video_asset_id)
    assert asset.destroyed_at is not None


# --- 다운로드: 파기된 오브젝트는 오류나 빈 응답이 아니라 "만료" 응답이다 ---------------


@pytest.mark.django_db
def test_download_of_a_purged_demo_video_reports_expired_without_error(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-retain-5", "dev-retain-ci-5")
    setup = _submit_with_demo_video(client, dev, contest["id"], requirement_id=requirement_id)

    _close_contest(client, contest, deadline=deadline)
    closed = Contest.objects.get(id=contest["id"])

    # 파기 전 — 정상적으로 다운로드 URL이 발급된다.
    target_ref = f"submission:{contest['id']}:{dev['user_id']}:demo-video"
    before = client.post(
        DOWNLOADS_URL,
        data={"target_ref": target_ref, "object_key": setup["video_key"]},
        content_type="application/json",
        **{"HTTP_AUTHORIZATION": f"Bearer {dev['access']}"},
    )
    assert before.status_code == 200, before.content
    assert before.json()["expired"] is False
    assert before.json()["download_url"]

    _freeze(closed.judging_ends_at + timedelta(days=GRACE_DAYS))
    _run_retention_scan(client)

    after = client.post(
        DOWNLOADS_URL,
        data={"target_ref": target_ref, "object_key": setup["video_key"]},
        content_type="application/json",
        **{"HTTP_AUTHORIZATION": f"Bearer {dev['access']}"},
    )
    assert after.status_code == 200, after.content
    body = after.json()
    assert body["expired"] is True
    assert body["download_url"] is None
    assert body["expires_at"] is None
