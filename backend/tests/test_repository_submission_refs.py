"""저장소 제출이 브랜치·커밋 URL 을 받고, 브랜치는 첫 스캔이 커밋을 고정한다 (#777, ADR-0065).

- 받는 모양은 셋 — 저장소 · `/tree/<ref>`(뒤 전체가 브랜치 이름, 슬래시 포함) · `/commit/<sha>`
  (7~40자 16진수). 그 밖은 지금처럼 422. 낸 URL 은 그대로 되돌아온다(`value`).
- `SubmissionAsset.value` 는 저장소 URL 그대로이고 ref·고정 SHA 는 별도 컬럼이다 — 공개 여부
  확인·중복 제약이 그 키를 그대로 쓴다.
- 브랜치는 **처음 성공한 스캔(강의실은 첫 채점)** 이 그 HEAD 의 SHA 를 박고, 그 뒤 채점은 박힌
  SHA 만 본다. 짧은 커밋 SHA 는 첫 스캔이 전체 SHA 로 확정한다.
- ref 를 못 찾으면 비공개와 같은 줄의 새 상태(`repository_ref_found=False`)가 되고, 마감에도
  없으면 0% 판정에 「브랜치·커밋을 찾을 수 없었다」가 적힌다. 기본 브랜치로 대신 채점하지 않는다.

흉내 어댑터(`core.repository_adapters.FakeGitHubAdapter`)는 ref 이름에 "missing" 이 들어가면
찾을 수 없다고 답하고, 그 밖에는 URL+ref 에서 결정적으로 유도한 40자 SHA 를 돌려준다.
"""

from __future__ import annotations

import re
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from classroom.models import ClassroomScore
from contests.models import Category, DeliverableType
from repositories.models import RepositorySnapshot
from scoring.models import Score
from submissions.models import SubmissionAsset
from tests.classroom_scenarios import (
    auth_header,
    create_class,
    create_open_problem,
    instructor_submissions,
    join_class,
    login,
    mine,
    run_scan,
    submit_repository,
)
from tests.test_repository_reachability_recheck import _submit_repository_only
from tests.test_repository_scoring import _run_visibility_scan
from tests.test_source_readings import (
    _auth_header,
    _close_contest,
    _publish_contest,
    _run_scoring,
    _verified_user,
)

CLASSES_URL = "/api/classroom/classes"
FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


# --- 강의실 ---------------------------------------------------------------------------


def _classroom_problem(client) -> tuple[dict, dict, int, int]:
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id, submission_formats=["repository"])
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    return instructor, participant, class_id, problem.id


def _post_repository(client, access: str, class_id: int, problem_id: int, url: str):
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": url, "submission_format": "repository"},
        content_type="application/json",
        **auth_header(access),
    )


def test_classroom_accepts_branch_and_commit_urls_and_echoes_them(client, db):
    _instructor, participant, class_id, problem_id = _classroom_problem(client)

    branch = submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/kim/todo/tree/release/2024/"
    )
    commit = submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/kim/todo.git/commit/ABCDEF1"
    )

    assert branch["value"] == "https://github.com/kim/todo/tree/release/2024"
    assert branch["commit_sha"] is None
    assert commit["value"] == "https://github.com/kim/todo/commit/abcdef1"
    assert commit["commit_sha"] == "abcdef1"
    # 저장은 저장소 URL 그대로 + ref/sha 컬럼 — 공개 여부 확인·중복 제약이 그 키를 쓴다.
    rows = {
        a.repository_ref or a.repository_commit_sha: a
        for a in SubmissionAsset.objects.filter(kind=SubmissionAsset.Kind.REPOSITORY)
    }
    assert rows["release/2024"].value == "https://github.com/kim/todo"
    assert rows["abcdef1"].value == "https://github.com/kim/todo"
    # 참여자 목록·강사 목록도 낸 URL 그대로.
    listed = mine(client, participant["access"], class_id, problem_id)["submissions"]
    assert {s["value"] for s in listed} == {branch["value"], commit["value"]}
    instructor_rows = instructor_submissions(client, _instructor["access"], class_id, problem_id)
    assert {s["value"] for s in instructor_rows} == {branch["value"], commit["value"]}


def test_classroom_rejects_other_github_paths(client, db):
    _instructor, participant, class_id, problem_id = _classroom_problem(client)

    for url in [
        "https://github.com/kim/todo/blob/main/README.md",
        "https://github.com/kim/todo/pull/3",
        "https://github.com/kim/todo/tree/",
        "https://github.com/kim/todo/commit/abc",
        "https://github.com/kim/todo/commit/xyz1234",
    ]:
        response = _post_repository(client, participant["access"], class_id, problem_id, url)
        assert response.status_code == 422, url
        assert "/tree/" in response.json()["detail"] and "/commit/" in response.json()["detail"]


def test_classroom_first_grading_pins_the_branch_head_and_regrading_keeps_it(client, db):
    _instructor, participant, class_id, problem_id = _classroom_problem(client)
    submitted = submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/kim/todo/tree/feature"
    )

    run_scan(client)

    asset = SubmissionAsset.objects.get(submission_id=submitted["id"])
    assert ClassroomScore.objects.filter(submission_id=submitted["id"]).exists()
    assert FULL_SHA.match(asset.repository_commit_sha)
    assert asset.repository_ref == "feature"
    pinned = asset.repository_commit_sha
    listed = mine(client, participant["access"], class_id, problem_id)["submissions"][0]
    assert listed["value"] == "https://github.com/kim/todo/tree/feature"
    assert listed["commit_sha"] == pinned

    # 다시 채점해도(같은 자산을 다시 clone 해도) 박힌 SHA 가 그대로다.
    from core.repository_adapters import get_github_adapter
    from submissions.repository_pins import clone_repository_asset

    cloned = clone_repository_asset(asset, get_github_adapter())
    assert cloned.commit_sha == pinned
    assert SubmissionAsset.objects.get(pk=asset.pk).repository_commit_sha == pinned


# --- 공모전 ---------------------------------------------------------------------------


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _contest_with_repository(client, category, landing_type, *, repo_url: str):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"], repo_url=repo_url
    )
    return contest, deadline, dev, submission


def _repository_asset_out(client, dev: dict, submission_id: int) -> dict:
    detail = client.get(f"/api/submissions/{submission_id}", **_auth_header(dev["access"]))
    assert detail.status_code == 200, detail.content
    return next(a for a in detail.json()["assets"] if a["kind"] == "repository")


@pytest.mark.django_db
def test_contest_branch_url_is_pinned_by_the_first_scan_and_scored_at_that_commit(
    client, category, landing_type
):
    contest, deadline, dev, submission = _contest_with_repository(
        client, category, landing_type, repo_url="https://github.com/acme/widgets/tree/release/2024"
    )

    before = _repository_asset_out(client, dev, submission["id"])
    assert before["value"] == "https://github.com/acme/widgets/tree/release/2024"
    assert before["commit_sha"] is None
    assert before["repository_ref_found"] is None

    _run_visibility_scan(client)

    after = _repository_asset_out(client, dev, submission["id"])
    assert after["is_public"] is True
    assert after["repository_ref_found"] is True
    assert FULL_SHA.match(after["commit_sha"])
    assert after["value"] == before["value"]

    _close_contest(client, contest, deadline=deadline)
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    snapshot = RepositorySnapshot.objects.get(asset__submission_id=submission["id"])
    assert snapshot.commit_sha == after["commit_sha"]


@pytest.mark.django_db
def test_contest_short_commit_sha_is_expanded_by_the_first_scan(client, category, landing_type):
    _contest, _deadline, dev, submission = _contest_with_repository(
        client, category, landing_type, repo_url="https://github.com/acme/widgets/commit/abcdef1"
    )

    _run_visibility_scan(client)

    asset = _repository_asset_out(client, dev, submission["id"])
    assert FULL_SHA.match(asset["commit_sha"]) and asset["commit_sha"].startswith("abcdef1")
    assert asset["value"] == f"https://github.com/acme/widgets/commit/{asset['commit_sha']}"
    assert asset["repository_ref_found"] is True


@pytest.mark.django_db
def test_contest_repository_url_without_ref_is_not_pinned(client, category, landing_type):
    _contest, _deadline, dev, submission = _contest_with_repository(
        client, category, landing_type, repo_url="https://github.com/acme/widgets"
    )

    _run_visibility_scan(client)

    asset = _repository_asset_out(client, dev, submission["id"])
    assert asset["is_public"] is True
    assert asset["commit_sha"] is None
    assert asset["repository_ref_found"] is None


@pytest.mark.django_db
def test_contest_missing_branch_is_flagged_and_scores_zero_with_the_reason(
    client, category, landing_type
):
    contest, deadline, dev, submission = _contest_with_repository(
        client, category, landing_type, repo_url="https://github.com/acme/widgets/tree/missing-branch"
    )

    _run_visibility_scan(client)

    asset = _repository_asset_out(client, dev, submission["id"])
    assert asset["is_public"] is True
    assert asset["repository_ref_found"] is False
    assert asset["commit_sha"] is None

    _close_contest(client, contest, deadline=deadline)
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("0.00")
    assert not RepositorySnapshot.objects.filter(asset__submission_id=submission["id"]).exists()
    for item in score.reasoning:
        assert item["is_met"] is False
        assert "입력이 없었다" in item["reasoning"]
        assert "브랜치·커밋을 찾을 수 없었다" in item["reasoning"]


@pytest.mark.django_db
def test_contest_rejects_other_github_paths_naming_the_three_shapes(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = client.post(
        f"/api/contests/{contest['id']}/submissions",
        data={
            "assets": [{"kind": "repository", "value": "https://github.com/acme/widgets/blob/main/a.py"}],
            "requirement_responses": [],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 422, response.content
    assert "/tree/" in response.json()["detail"] and "/commit/" in response.json()["detail"]
