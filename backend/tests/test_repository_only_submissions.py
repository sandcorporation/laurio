"""소스 없이 저장소만으로 제출하고, 닫혀 있으면 0%로 채점된다 (#218, ADR-0030).

ADR-0014는 소스 제출을 필수로 정했다 — 이유는 채점 품질이 아니라 Escrow 함정
(소스가 없으면 아무도 채점되지 않아 Distribution 대상이 0명이 되고, 참여자는 있어
환불도 막혀 상금이 갇힌다)이다. ADR-0030은 그 함정을 만드는 것이 "Score가 없는
것"이지 "소스가 없는 것"이 아니라는 것을 짚고, 소스 자료 또는 공개 저장소 중
최소 하나를 요구하는 것으로 완화한다 — 대신 마감 후 채점 시점에 그 저장소가
닫혀 있으면(private·404) 전체 미달(0%) Score를 만든다. 0%도 Score이므로
Distribution 판정은 그대로 진행되고 컷라인이 그 제출을 거른다.

핵심 대상:

- 소스 없이 공개 저장소만으로 제출·수정할 수 있고, 소스만으로도 여전히 낼 수
  있다. 둘 다 없으면 여전히 422다(기존 동작).
- 저장소만 낸 제출의 저장소가 채점 시점에 도달 불가능(private·404 — Fake
  어댑터는 이 둘을 구별하지 않는다, `repositories.adapters.FakeGitHubAdapter`의
  docstring 참고)이면 채점이 0% Score를 남긴다 — 영구 실패(Score 없음)가 아니다.
- 그 Score는 AI가 판정하지 않았음을 스스로 밝히고(`model_version`), 판정 근거가
  Requirement 항목마다 이유를 말한다.
- GitHub 장애로 공개 여부를 끝내 확인하지 못한 경우(is_public이 계속 null)는
  0%로 굳지 않는다 — 다음 스캔이 다시 시도한다.
- 소스가 있는 제출은 저장소가 닫혀도 나머지(소스)로 채점된다(기존 동작 유지) —
  `tests/test_repository_scoring.py`가 이미 고정한 사실이라 여기서는 반복하지
  않는다.

시임은 언제나 HTTP다(CLAUDE.md).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType
from scoring.models import Score, ScoringAttempt
from submissions.models import Submission, SubmissionAsset

from tests.test_source_readings import (
    _auth_header,
    _close_contest,
    _internal_headers,
    _publish_contest,
    _run_scoring,
    _verified_user,
)

CONTESTS_URL = "/api/contests"
VISIBILITY_SCAN_URL = "/api/internal/scans/repository-visibility"


# --- Assignment(ADR-0028)도 같은 규칙을 받는다(ADR-0030 "플랫폼 전체 규칙이고
# 개최자가 고르지 않는다 … Assignment에도 같이 적용한다") -------------------------


@pytest.mark.django_db
def test_assignment_submission_accepts_repository_only(client, landing_type):
    from tests.test_assignment_scoring import _create_and_open_assignment, _login

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="teacher-1", deadline_at=deadline
    )
    student = _login(client, "student-1")

    response = client.post(
        f"{CONTESTS_URL}/{assignment['id']}/submissions",
        data={
            "assets": [{"kind": "repository", "value": _repository_url("public-org")}],
            "requirement_responses": [
                {"requirement_id": assignment["requirement_id"], "is_met": True, "evidence": []}
            ],
            "invite_code": assignment["invite_code"],
        },
        content_type="application/json",
        **_auth_header(student["access"]),
    )

    assert response.status_code == 201, response.content
    assert response.json()["completion"]["repository_count"] == 1
    assert response.json()["completion"]["source_count"] == 0


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _repository_url(owner: str) -> str:
    return f"https://github.com/{owner}/repo-{uuid.uuid4().hex[:12]}"


def _run_visibility_scan(client) -> dict:
    response = client.post(VISIBILITY_SCAN_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _submit_repository_only(
    client, dev: dict, contest_id: int, *, requirement_id: int, repo_url: str
) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [{"kind": "repository", "value": repo_url}],
            "requirement_responses": [
                {"requirement_id": requirement_id, "is_met": True, "evidence": []}
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


# --- 제출 검증: 소스 또는 저장소 중 최소 하나 ------------------------------------


@pytest.mark.django_db
def test_repository_only_submission_is_accepted(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={"assets": [{"kind": "repository", "value": _repository_url("public-org")}]},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["completion"]["source_count"] == 0
    assert body["completion"]["repository_count"] == 1


@pytest.mark.django_db
def test_submission_with_neither_source_nor_repository_is_still_rejected(
    client, category, landing_type
):
    """#218이 완화한 것은 "소스 필수"이지 "채점 입력 필수"가 아니다 — 둘 다
    없으면 여전히 422다(그러지 않으면 ADR-0014가 막던 함정이 그대로 열린다)."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={"assets": []},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


# --- 채점: 닫혀 있으면 0%, AI를 부르지 않는다 ------------------------------------


@pytest.mark.django_db
def test_repository_only_submission_scores_zero_when_repository_is_private(
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
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    repo_url = _repository_url("private-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )

    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("0.00")
    # AI가 판정하지 않았음을 스스로 밝힌다(ADR-0030) — 실제 LLM 모델 식별자
    # 형식과 겹치지 않는 사람이 읽을 수 있는 값이다.
    assert "fake-llm" not in score.model_version
    assert "claude" not in score.model_version.lower()
    assert score.reasoning, "판정 근거가 비어 있다"
    for item in score.reasoning:
        assert item["is_met"] is False
        assert "입력이 없었다" in item["reasoning"]

    # 이의 화면(OwnScoreOut)도 같은 사실을 보여준다.
    own_score = client.get(
        f"/api/submissions/{submission['id']}/score", **_auth_header(dev["access"])
    )
    assert own_score.status_code == 200
    assert own_score.json()["percentage"] == "0.00"


@pytest.mark.django_db
def test_repository_only_submission_scores_zero_when_repository_is_unreachable(
    client, category, landing_type
):
    """404(삭제·이름 변경)도 private과 같은 취급이다 — Fake 어댑터는 이 둘을
    구별하지 않는다(`check_public`이 GitHub 자신도 그런다는 이유로 이미 그렇게
    설계됐다, `repositories.adapters.GitHubRepositoryNotFoundError`의 docstring).
    """

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

    # Fake 어댑터에서 "private" 마커가 실질적으로 404·비공개를 함께 흉내낸다.
    repo_url = _repository_url("deleted-private-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )

    _run_visibility_scan(client)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("0.00")


@pytest.mark.django_db
def test_repository_only_submission_does_not_settle_to_zero_while_github_is_down(
    client, category, landing_type
):
    """GitHub 장애·rate limit·네트워크 오류는 불이익으로 치지 않는다(ADR-0030) —
    `is_public`이 계속 null인 동안은 0%로 굳지 않고 다음 스캔이 다시 시도한다.
    """

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

    # "checkerror"는 404가 아닌 실패(네트워크 순단 등)를 흉내낸다 — is_public이
    # 계속 null로 남는다.
    repo_url = _repository_url("checkerror-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )

    # 가시성 스캔을 아예 성공시키지 않은 채(is_public은 계속 null) 유예 기간을
    # 훌쩍 넘긴 시각으로 시계를 옮긴다 — "GitHub이 끝내 확인해 주지 않는다"를
    # 재현한다.
    _close_contest(client, contest, deadline=deadline)
    from core.models import ClockOverride

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(hours=3)}
    )

    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "repository_unresolved"
    assert not Score.objects.filter(submission_id=submission["id"]).exists()
    assert ScoringAttempt.objects.filter(
        submission_id=submission["id"], permanent=False
    ).exists()
    # 결정적 실패로 확정하지 않는다 — 다음 스캔이 여전히 이 Submission을 본다.
    assert not ScoringAttempt.objects.filter(
        submission_id=submission["id"], permanent=True
    ).exists()


@pytest.mark.django_db
def test_repository_only_submission_scores_normally_once_repository_becomes_public(
    client, category, landing_type
):
    """공개로 확인되면 저장소만으로도 정상 채점된다 — 0% 자동 미달이 아니라
    저장소 clone 내용이 실제 채점 근거가 된다."""

    from django.test import override_settings

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
    repo_marker = f"REPO_MARKER_{uuid.uuid4().hex}"

    with override_settings(GITHUB_FAKE_REPO_FILES={repo_url: {"main.py": f"# {repo_marker}\n"}}):
        response = client.post(
            f"{CONTESTS_URL}/{contest['id']}/submissions",
            data={
                "assets": [{"kind": "repository", "value": repo_url}],
                "requirement_responses": [
                    {
                        "requirement_id": requirement_id,
                        "is_met": True,
                        "evidence": [{"kind": "source_location", "value": repo_marker}],
                    }
                ],
            },
            content_type="application/json",
            **_auth_header(dev["access"]),
        )
        assert response.status_code == 201, response.content
        submission = response.json()

        _run_visibility_scan(client)
        _close_contest(client, contest, deadline=deadline)
        result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("100.00")
    assert repo_marker in score.prompt

    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    assert any(e["asset_id"] == repository_asset.id for e in score.scored_assets)
