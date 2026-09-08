"""채점 직전에 저장소 도달 가능성을 다시 확인하고, 그 판정을 기록으로 남긴다
(#219, ADR-0030).

`#218`이 세운 "닫혀 있으면 0%" 판정의 근거는 최대 1시간 낡을 수 있는 주기 스캔
(`repository-visibility`)의 값이다. "채점 당시 닫혀 있었다"는 판정의 근거로
한 시간 전의 사실을 쓰는 것은 정직하지 않다 — 그래서 채점이 그 제출의 저장소
도달 가능성을 채점 시점에 직접 재확인하고, 스캔이 남긴 값보다 그 결과를
우선한다.

핵심 대상:

- 마지막 스캔 이후 공개로 되돌린 저장소는 0%가 되지 않는다(재확인이 살린다).
- 마지막 스캔 이후 비공개로 바꾼 저장소는 0%가 된다(재확인이 잡아낸다).
- 재확인이 장애로 실패하면 마지막으로 알던 값으로 진행하고, 채점이 멈추거나
  실패하지 않는다.
- 판정의 시각·결과·사유가 `Score.repository_reachability_check`에 남고,
  이후 스캔이 그 기록을 덮어쓰지 않는다.
- 참가자가 자기 제출에서 그 판정 사유를 본다(`OwnScoreOut`).
- 저장소가 없는 제출과 소스가 함께 있는 제출의 채점 동작은 바뀌지 않는다 —
  재확인 자체가 일어나지 않는다(`tests/test_repository_scoring.py`가 그 사실을
  고정한다).

스캔이 남긴 `is_public`을 "낡은 값"으로 미리 세팅해 두는 데는 ORM을 직접
쓴다 — 실제 스캔을 돌려 그 값을 만들면 Fake 어댑터가 URL 텍스트로만 판정을
결정하는 특성상(`repositories.adapters.FakeGitHubAdapter`) "그때는 그랬는데
지금은 다르다"는 시차를 재현할 수 없다. HTTP가 유일한 시임이라는 원칙은
**채점 스캔 자체**(재확인의 대상)에는 그대로 적용된다 — ORM 조작은 그 앞의
전제(낡은 값)를 세우는 데만 쓴다.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, DeliverableType
from repositories.models import RepositorySnapshot
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


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _repository_url(owner: str) -> str:
    return f"https://github.com/{owner}/repo-{uuid.uuid4().hex[:12]}"


def _submit_repository_only(
    client, dev: dict, contest_id: int, *, requirement_id: int, repo_url: str, evidence_value=None
) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [{"kind": "repository", "value": repo_url}],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": (
                        [{"kind": "source_location", "value": evidence_value}]
                        if evidence_value
                        else []
                    ),
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _mark_stale_scan_result(submission_id: int, *, is_public: bool | None) -> None:
    """스캔이 예전에 이 값을 남겼던 것처럼 DB를 직접 세팅한다 — 채점 직전
    재확인이 그것을 덮어쓰는지가 이 파일의 핵심이다."""

    SubmissionAsset.objects.filter(
        submission_id=submission_id, kind=SubmissionAsset.Kind.REPOSITORY
    ).update(is_public=is_public, is_public_checked_at=timezone.now() - timedelta(hours=1))


@pytest.mark.django_db
def test_recheck_revives_a_repository_that_was_made_public_again_since_the_last_scan(
    client, category, landing_type
):
    """스캔은 예전에 비공개로 남겼지만(낡은 값), 채점 시점에 실제로는 공개다 —
    재확인이 이것을 살려 정상 채점(AI)으로 이어져야 한다. 0%로 굳지 않는다."""

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
        submission = _submit_repository_only(
            client,
            dev,
            contest["id"],
            requirement_id=requirement_id,
            repo_url=repo_url,
            evidence_value=repo_marker,
        )
        # 스캔이 한 시간 전에 "비공개"로 남겼다 — 그 사이 참가자가 공개로
        # 되돌려 놨다는 것을 이 테스트가 아는 사실이다. URL 자체는 항상
        # 공개였다(Fake 어댑터는 URL 텍스트로만 판정하므로 "그때는 진짜
        # 비공개였다"를 재현할 수 없다 — 파일 docstring 참고).
        _mark_stale_scan_result(submission["id"], is_public=False)

        _close_contest(client, contest, deadline=deadline)
        result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("100.00")
    assert repo_marker in score.prompt
    assert score.model_version != "platform-auto (채점 입력 없음)"

    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    # 재확인이 실제로 clone까지 이어졌다 — 스냅샷이 그 증거다.
    assert RepositorySnapshot.objects.filter(asset=repository_asset).exists()

    check = score.repository_reachability_check
    assert len(check) == 1
    assert check[0]["asset_id"] == repository_asset.id
    assert check[0]["is_public"] is True
    assert check[0]["source"] == "live_check"


@pytest.mark.django_db
def test_recheck_catches_a_repository_that_was_made_private_since_the_last_scan(
    client, category, landing_type
):
    """스캔은 예전에 공개로 남겼지만(낡은 값), 채점 시점에 실제로는 닫혀 있다 —
    재확인이 이것을 잡아 0%로 채점해야 한다."""

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

    # "private"는 check_public()을 False로, "cloneerror"는 clone()을 실패로
    # 만든다(FakeGitHubAdapter) — 낡은 "공개" 값 아래에서 시도되는 최초 clone도
    # 실패해야 재확인 분기까지 도달한다.
    repo_url = _repository_url("private-cloneerror-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )
    # 스캔이 한 시간 전에 "공개"로 남겼다.
    _mark_stale_scan_result(submission["id"], is_public=True)

    _close_contest(client, contest, deadline=deadline)
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("0.00")
    assert score.model_version == "platform-auto (채점 입력 없음)"

    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    assert not RepositorySnapshot.objects.filter(asset=repository_asset).exists()

    check = score.repository_reachability_check
    assert len(check) == 1
    assert check[0]["asset_id"] == repository_asset.id
    assert check[0]["is_public"] is False
    assert check[0]["source"] == "live_check"
    assert check[0]["detail"] == "private_or_not_found"

    # 참가자가 자기 제출에서 그 판정 사유를 본다.
    own_score = client.get(
        f"/api/submissions/{submission['id']}/score", **_auth_header(dev["access"])
    )
    assert own_score.status_code == 200
    own_check = own_score.json()["repository_reachability_check"]
    assert own_check[0]["asset_id"] == repository_asset.id
    assert own_check[0]["is_public"] is False


@pytest.mark.django_db
def test_recheck_failure_falls_back_to_the_last_known_value_and_scoring_does_not_get_stuck(
    client, category, landing_type
):
    """재확인이 GitHub 장애로 실패하면(404가 아닌 실패) 마지막으로 알던 값으로
    그대로 진행한다 — 채점이 멈추거나 실패하지 않는다. 마지막 값이 여전히
    확정되지 않았다면(null) 0%로 굳지 않고 다음 스캔이 다시 시도한다."""

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

    # "checkerror"는 check_public()이 항상(스캔이든 재확인이든) 실패하게 만든다
    # — 결코 확정 판정에 이르지 못하는 저장소를 흉내낸다.
    repo_url = _repository_url("checkerror-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )

    from core.models import ClockOverride

    _close_contest(client, contest, deadline=deadline)
    # 유예 기간을 넘긴다 — is_public이 계속 null이라 스캔 후보 조회
    # (`scoring.services._pending_submissions`)가 더 이상 이 Submission을
    # 미루지 않고 채점을 시도하게 한다.
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(hours=3)}
    )

    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "repository_unresolved"
    assert not Score.objects.filter(submission_id=submission["id"]).exists()
    assert ScoringAttempt.objects.filter(
        submission_id=submission["id"], permanent=False
    ).exists()

    # 운영자가 (예를 들어 참가자 신고를 보고) 저장소가 실제로 닫혀 있다고
    # 최종적으로 확인해 마지막 값을 채워 넣었다고 하자 — "checkerror" URL은
    # 재확인 때도 여전히 실패하므로, 이 Submission의 최종 결과는 그 last-known
    # 값(False)으로 결정돼야 한다.
    _mark_stale_scan_result(submission["id"], is_public=False)
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(hours=4)}
    )
    result2 = _run_scoring(client)

    assert result2["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("0.00")

    check = score.repository_reachability_check
    assert len(check) == 1
    assert check[0]["source"] == "fallback_last_known"
    assert check[0]["is_public"] is False
    assert check[0]["detail"].startswith("check_failed:")


@pytest.mark.django_db
def test_repository_reachability_check_is_not_overwritten_by_a_later_scan(
    client, category, landing_type
):
    """Score가 만들어지고 나면 그 판정 기록은 고정된다 — 이후 저장소 자산의
    `is_public`이 바뀌어도(가시성 스캔이 계속 도는 다른 이유로) Score에 남은
    기록은 그대로다."""

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

    repo_url = _repository_url("private-cloneerror-org")
    submission = _submit_repository_only(
        client, dev, contest["id"], requirement_id=requirement_id, repo_url=repo_url
    )
    _mark_stale_scan_result(submission["id"], is_public=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    score = Score.objects.get(submission_id=submission["id"])
    recorded_check = score.repository_reachability_check
    assert recorded_check[0]["is_public"] is False

    # 다른 무언가가 나중에 이 자산의 is_public을 손으로 바꿔도(가시성 스캔은
    # Score가 있는 Submission을 후보에서 빼므로 실제로는 일어나지 않지만,
    # append-only 성질을 직접 검증한다) Score의 기록은 그대로다.
    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    SubmissionAsset.objects.filter(pk=repository_asset.pk).update(is_public=True)

    score.refresh_from_db()
    assert score.repository_reachability_check == recorded_check
    assert score.repository_reachability_check[0]["is_public"] is False


@pytest.mark.django_db
def test_recheck_does_not_run_when_source_is_present(client, category, landing_type):
    """소스가 있으면 재확인 자체가 일어나지 않는다 — 채점 동작이 바뀌지 않는다
    (기존 사실은 `tests/test_repository_scoring.py`가 고정한다, 이 테스트는
    새 필드가 빈 채로 남는다는 것만 더한다)."""

    from tests.test_source_readings import _source_object_key, _zip_bytes
    from storage.adapters.fake import FakeStorageAdapter

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

    source_key = _source_object_key(contest["id"], dev["user_id"])
    marker = f"MARKER_{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": f"# {marker}\n"}))

    repo_url = _repository_url("private-cloneerror-org")
    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [
                {"kind": "source", "value": source_key},
                {"kind": "repository", "value": repo_url},
            ],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": marker}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    submission = response.json()
    _mark_stale_scan_result(submission["id"], is_public=True)

    _close_contest(client, contest, deadline=deadline)
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("100.00")  # 소스만으로 충족
    assert score.repository_reachability_check == []
