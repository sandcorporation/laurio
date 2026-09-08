"""저장소만 낸 제출을 채점 때 박제해 우승자에게 넘긴다 (#220, ADR-0030).

`#218`이 소스 없이 저장소만으로 제출할 수 있게 열었다. 그 저장소가 우승한 뒤
비공개로 바뀌거나 지워지면, ADR-0014가 정의한 Handover("Sponsor에게 접근
권한을 여는 것")가 열어 줄 것이 없다 — 상금을 낸 Sponsor가 빈손이 된다. 그래서
소스 자료가 하나도 없는 제출에 한해, 채점이 이미 clone해 손에 쥔 zip을 그대로
`kind=source` 자료로 보관한다("박제"). 별도 모델이 아니라 기존 `SubmissionAsset`
(kind=source)로 두는 것이 이 티켓의 핵심 설계다 — Handover·소스 열람 기록·
스토리지 인가 전부 이미 그 종류를 안다.

핵심 대상:

- 소스 없이 공개 저장소만 낸 제출은 채점 시점에 그 코드가 보관되고, 보관을 위해
  저장소를 다시 받지 않는다(이미 clone된 zip을 그대로 쓴다).
- 소스를 올린 제출은 저장소가 있어도 보관하지 않는다.
- 보관본은 플랫폼이 만든 것으로 표시되고(`created_by_platform`), 참가자는
  지우거나 고칠 수 없다.
- Award 후 Sponsor가 그 보관본을 실제로 내려받을 수 있다 — 인가·열람 기록이
  참가자가 올린 소스와 똑같이 동작한다(별도 코드를 새로 만들지 않는다는 것 자체가
  이 설계가 맞다는 증거다).
- Award 전에는 Sponsor가 볼 수 없다(ADR-0014의 은닉이 그대로 성립한다).
- 보관 저장이 실패하면 Score가 생기지 않고 다음 스캔이 다시 시도한다.
- 과제에서 강사의 "소스 펼치기"가 보관본을 연다.

시임은 언제나 HTTP다(CLAUDE.md).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, DeliverableType
from scoring.models import Score, ScoringAttempt
from storage.adapters.fake import FakeStorageAdapter
from submissions.models import Submission, SubmissionAsset
from submissions.target_refs import source_target_ref

from tests.test_assignment_source_readings import (
    _create_and_open_assignment,
    _reveal as _reveal_assignment_source,
)
from tests.test_handover import _award
from tests.test_source_readings import (
    _auth_header,
    _close_contest,
    _internal_headers,
    _publish_contest,
    _run_scoring,
    _verified_user,
)

CONTESTS_URL = "/api/contests"
SUBMISSIONS_URL = "/api/submissions"
STORAGE_URL = "/api/storage"
VISIBILITY_SCAN_URL = "/api/internal/scans/repository-visibility"


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _repository_url(owner: str) -> str:
    return f"https://github.com/{owner}/repo-{uuid.uuid4().hex[:12]}"


def _submit_repository_only(
    client, dev: dict, contest_id: int, *, repo_url: str, requirement_id: int | None = None
) -> dict:
    requirement_responses = (
        [{"requirement_id": requirement_id, "is_met": True, "evidence": []}]
        if requirement_id is not None
        else []
    )
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [{"kind": "repository", "value": repo_url, "label": "메인 저장소"}],
            "requirement_responses": requirement_responses,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _run_visibility_scan(client) -> dict:
    response = client.post(VISIBILITY_SCAN_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _archived_asset(submission_id: int) -> SubmissionAsset:
    return Submission.objects.get(id=submission_id).assets.get(
        kind=SubmissionAsset.Kind.SOURCE, created_by_platform=True
    )


# --- 박제: 언제 일어나는가 -----------------------------------------------------


@pytest.mark.django_db
def test_repository_only_submission_is_archived_as_source_at_scoring_time(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    repo_url = _repository_url("public-org")
    repo_marker = f"REPO_MARKER_{uuid.uuid4().hex}"

    with override_settings(GITHUB_FAKE_REPO_FILES={repo_url: {"main.py": f"# {repo_marker}\n"}}):
        submission = _submit_repository_only(client, dev, contest["id"], repo_url=repo_url)

        _run_visibility_scan(client)
        _close_contest(client, contest, deadline=deadline)
        result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("100.00")

    archived = _archived_asset(submission["id"])
    assert archived.created_by_platform is True
    assert "commit" in archived.label

    # 추가 GitHub 호출 없이, 채점이 이미 손에 쥔 zip 그대로다 — 저장된 바이트
    # 안에 저장소 clone 마커가 그대로 있다.
    stored = FakeStorageAdapter().read_object(archived.value)
    assert stored is not None
    assert repo_marker.encode("utf-8") in stored

    # 참가자에게도 이 자료가 보이고, 출처가 플랫폼임이 드러난다.
    detail = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}", **_auth_header(dev["access"])
    )
    assert detail.status_code == 200
    source_assets = [a for a in detail.json()["assets"] if a["kind"] == "source"]
    assert len(source_assets) == 1
    assert source_assets[0]["created_by_platform"] is True


@pytest.mark.django_db
def test_submission_with_uploaded_source_is_not_archived(client, category, landing_type):
    """소스를 올린 제출은 저장소가 함께 있어도 박제하지 않는다 — Handover에 이미
    넘길 것이 있다."""

    from tests.test_repository_scoring import _submit_with_repository

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    repo_url = _repository_url("public-org")
    submission = _submit_with_repository(
        client,
        dev,
        contest["id"],
        requirement_id=requirement_id,
        repo_url=repo_url,
        source_marker="SRC_MARKER",
    )

    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    source_assets = SubmissionAsset.objects.filter(
        submission_id=submission["id"], kind=SubmissionAsset.Kind.SOURCE
    )
    assert source_assets.count() == 1
    assert source_assets.first().created_by_platform is False


# --- 참가자는 지우거나 고칠 수 없다 ---------------------------------------------


@pytest.mark.django_db
def test_developer_cannot_remove_the_archived_source_by_editing(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    repo_url = _repository_url("public-org")
    submission = _submit_repository_only(client, dev, contest["id"], repo_url=repo_url)

    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    archived = _archived_asset(submission["id"])

    # 마감이 지나면 Contest가 더 이상 SUBMITTABLE이 아니라 이 API 자체가 404다
    # (`_get_published_contest_or_404`) — 박제 자료를 굳이 참조하지 않아도 이미
    # 막힌다. 그래도 그 자료가 그대로 남아 있는지 확인한다.
    put_resp = client.put(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me",
        data={"assets": [], "requirement_responses": []},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert put_resp.status_code == 404

    archived.refresh_from_db()
    assert SubmissionAsset.objects.filter(pk=archived.pk).exists()


# --- Award 전후 가시성 (ADR-0014) -----------------------------------------------


@pytest.mark.django_db
def test_award_opens_the_archived_source_to_sponsor_and_it_downloads(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    repo_url = _repository_url("public-org")
    submission = _submit_repository_only(client, dev, contest["id"], repo_url=repo_url)

    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    archived = _archived_asset(submission["id"])

    _award(client, sponsor, contest["id"], submission["id"])

    detail = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}", **_auth_header(sponsor["access"])
    )
    assert detail.status_code == 200
    source_assets = [a for a in detail.json()["assets"] if a["kind"] == "source"]
    assert len(source_assets) == 1
    assert source_assets[0]["value"] == archived.value

    download_resp = client.post(
        f"{STORAGE_URL}/downloads",
        data={
            "target_ref": source_target_ref(contest["id"], dev["user_id"]),
            "object_key": archived.value,
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert download_resp.status_code == 200, download_resp.content
    assert "download_url" in download_resp.json()


@pytest.mark.django_db
def test_sponsor_cannot_see_the_archived_source_before_award(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    repo_url = _repository_url("public-org")
    submission = _submit_repository_only(client, dev, contest["id"], repo_url=repo_url)

    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    archived = _archived_asset(submission["id"])

    detail = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}", **_auth_header(sponsor["access"])
    )
    assert detail.status_code == 200
    assert [a for a in detail.json()["assets"] if a["kind"] == "source"] == []

    download_resp = client.post(
        f"{STORAGE_URL}/downloads",
        data={
            "target_ref": source_target_ref(contest["id"], dev["user_id"]),
            "object_key": archived.value,
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert download_resp.status_code == 403


# --- 보관 저장 실패는 재시도한다 -------------------------------------------------


@pytest.mark.django_db
def test_archiving_failure_defers_scoring_and_retries_on_the_next_scan(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    repo_url = _repository_url("public-org")
    submission = _submit_repository_only(client, dev, contest["id"], repo_url=repo_url)

    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)

    target_ref = source_target_ref(contest["id"], dev["user_id"])
    with override_settings(STORAGE_FAKE_WRITE_RAISING_TARGET_REFS=[target_ref]):
        result = _run_scoring(client)

    assert result["rows"][0]["status"] == "archive_failed"
    assert not Score.objects.filter(submission_id=submission["id"]).exists()
    assert ScoringAttempt.objects.filter(
        submission_id=submission["id"], permanent=False
    ).exists()
    assert not SubmissionAsset.objects.filter(
        submission_id=submission["id"], created_by_platform=True
    ).exists()

    # 스토리지가 회복되면 다음 스캔이 처음부터(LLM 재호출 포함) 다시 시도해
    # 성공한다.
    result2 = _run_scoring(client)
    assert result2["rows"][0]["status"] == "scored"
    assert Score.objects.filter(submission_id=submission["id"]).exists()
    assert SubmissionAsset.objects.filter(
        submission_id=submission["id"], created_by_platform=True
    ).exists()


# --- Assignment: 강사의 "소스 펼치기"가 보관본을 연다 ---------------------------


@pytest.mark.django_db
def test_assignment_instructor_reveal_opens_the_archived_source(client, landing_type):
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="archive-sponsor-1"
    )

    from tests.test_assignment_source_readings import _auth_header as _asrc_auth_header
    from tests.test_assignment_source_readings import _login as _asrc_login

    student_pair = _asrc_login(client, "archive-student-1")
    repo_url = _repository_url("public-org")
    repo_marker = f"REPO_MARKER_{uuid.uuid4().hex}"

    with override_settings(GITHUB_FAKE_REPO_FILES={repo_url: {"main.py": f"# {repo_marker}\n"}}):
        response = client.post(
            f"{CONTESTS_URL}/{assignment['id']}/submissions",
            data={
                "assets": [{"kind": "repository", "value": repo_url}],
                "invite_code": assignment["invite_code"],
            },
            content_type="application/json",
            **_asrc_auth_header(student_pair["access"]),
        )
        assert response.status_code == 201, response.content
        submission = response.json()

        _run_visibility_scan(client)

        from core.models import ClockOverride

        ClockOverride.objects.update_or_create(
            pk=1, defaults={"overridden_at": timezone.now() + timedelta(days=8)}
        )
        close_resp = client.post(
            "/api/internal/scans/assignment-close", **_internal_headers()
        )
        assert close_resp.status_code == 200, close_resp.content
        score_resp = _run_scoring(client)

    assert score_resp["rows"][0]["status"] == "scored"

    reveal = _reveal_assignment_source(
        client, assignment["sponsor_access"], assignment["id"], submission["id"]
    )
    assert reveal.status_code == 200, reveal.content
    body = reveal.json()
    kinds = {a["kind"] for a in body["assets"]}
    assert kinds == {"source", "repository"}
    source_entry = next(a for a in body["assets"] if a["kind"] == "source")
    assert source_entry["url"]  # presigned 다운로드 URL — 박제본을 가리킨다.
