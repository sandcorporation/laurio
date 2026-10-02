"""공개 GitHub 저장소를 스냅샷으로 보관해 채점한다 (#193, ADR-0027).

핵심 대상:

- 저장소 공개 여부는 스캔(`repository-visibility`)이 마감 전에 채운다 —
  제출/수정 API는 GitHub을 치지 않는다.
- 공개로 확인된 저장소만 채점 시점에 clone되어 소스와 같은 예산·선별 규율로
  채점 입력에 들어간다(#191의 라운드로빈이 그대로 적용된다).
- 비공개 저장소는 clone을 시도하지 않고, clone 실패는 그 자산만 빼고 진행한다
  — 둘 다 `permanent`로 표시되지 않아 다음 스캔에서도 Submission이 채점 대상이다.
- `RepositorySnapshot`은 clone에 성공한 저장소 자산마다 남는다(#224, ADR-0031) —
  선별이 그 저장소에서 파일을 하나도 고르지 못했어도 남는다. 실제로 채점 근거로
  쓰였는지는 별도로 `OwnScoreOut.scored_assets`가 답한다(커밋 SHA도 거기 나간다).

시임은 언제나 HTTP다(CLAUDE.md) — `repositories`/`scoring` 도메인 함수를 테스트가
직접 부르지 않는다.
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
from repositories.models import RepositorySnapshot
from scoring.models import Score
from storage.adapters.fake import FakeStorageAdapter
from submissions.models import Submission, SubmissionAsset

from tests.test_source_readings import (
    _auth_header,
    _close_contest,
    _internal_headers,
    _publish_contest,
    _run_scoring,
    _source_object_key,
    _verified_user,
    _zip_bytes,
)

CONTESTS_URL = "/api/contests"
VISIBILITY_SCAN_URL = "/api/internal/scans/repository-visibility"


def _score_url(submission_id: int) -> str:
    return f"/api/submissions/{submission_id}/score"


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _run_visibility_scan(client) -> dict:
    response = client.post(VISIBILITY_SCAN_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _submit_with_repository(
    client,
    dev: dict,
    contest_id: int,
    *,
    requirement_id: int,
    repo_url: str,
    source_marker: str,
    evidence_value: str | None = None,
) -> dict:
    """소스 하나(무관한 마커) + 저장소 자산 하나를 담아 제출한다.

    `evidence_value`가 주어지지 않으면 Evidence는 소스의 마커를 가리킨다.
    저장소 clone 내용만이 근거를 담고 있는 시나리오를 만들려면 `evidence_value`에
    저장소 쪽 마커를 직접 준다.
    """

    source_key = _source_object_key(contest_id, dev["user_id"])
    FakeStorageAdapter().write_object(
        source_key, _zip_bytes({"app.py": f"# {source_marker}\n"})
    )

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [
                {"kind": "source", "value": source_key},
                {"kind": "repository", "value": repo_url},
            ],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [
                        {
                            "kind": "source_location",
                            "value": evidence_value or source_marker,
                        }
                    ],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _repository_url(owner: str) -> str:
    return f"https://github.com/{owner}/repo-{uuid.uuid4().hex[:12]}"


# --- 공개 여부는 스캔이 판정한다 (비동기, ADR-0027) ----------------------------------


@pytest.mark.django_db
def test_visibility_scan_marks_a_public_repository_public(client, category, landing_type):
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

    detail = client.get(
        f"/api/submissions/{submission['id']}", **_auth_header(dev["access"])
    )
    assert detail.status_code == 200
    repo_asset = next(a for a in detail.json()["assets"] if a["kind"] == "repository")
    assert repo_asset["is_public"] is True


@pytest.mark.django_db
def test_visibility_scan_marks_a_private_repository_private(client, category, landing_type):
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
    submission = _submit_with_repository(
        client,
        dev,
        contest["id"],
        requirement_id=requirement_id,
        repo_url=repo_url,
        source_marker="SRC_MARKER",
    )

    _run_visibility_scan(client)

    detail = client.get(
        f"/api/submissions/{submission['id']}", **_auth_header(dev["access"])
    )
    repo_asset = next(a for a in detail.json()["assets"] if a["kind"] == "repository")
    assert repo_asset["is_public"] is False


# --- 채점에 꽂는다 — 공개 저장소만, clone 실패·비공개는 그 자산만 빼고 진행 ----------


@pytest.mark.django_db
def test_public_repository_is_cloned_and_its_content_scores_the_submission(
    client, category, landing_type
):
    """저장소 clone 내용만이 근거를 담고 있으면, 그 근거로 충족 판정이 나야 한다 —
    저장소가 실제로 채점 입력에 들어갔다는 직접 증거다."""

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
        # Evidence는 소스가 아니라 저장소 clone 내용에만 있는 마커를 가리킨다.
        submission = _submit_with_repository(
            client,
            dev,
            contest["id"],
            requirement_id=requirement_id,
            repo_url=repo_url,
            source_marker="UNRELATED_SOURCE_MARKER",
            evidence_value=repo_marker,
        )

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
    snapshot = RepositorySnapshot.objects.get(asset=repository_asset)
    assert len(snapshot.commit_sha) == 40

    own_score = client.get(_score_url(submission["id"]), **_auth_header(dev["access"]))
    assert own_score.status_code == 200
    scored_assets = own_score.json()["scored_assets"]
    repo_entry = next(e for e in scored_assets if e["asset_id"] == repository_asset.id)
    assert repo_entry["kind"] == "repository"
    assert repo_entry["commit_sha"] == snapshot.commit_sha


@pytest.mark.django_db
def test_private_repository_is_never_cloned_and_scoring_relies_on_source_alone(
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
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("100.00")  # 소스만으로 충족

    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    assert not RepositorySnapshot.objects.filter(asset=repository_asset).exists()
    assert all(e["asset_id"] != repository_asset.id for e in score.scored_assets)


@pytest.mark.django_db
def test_repository_snapshot_is_kept_even_when_source_selection_picks_no_file_from_it(
    client, category, landing_type
):
    """clone은 성공했지만 그 저장소의 파일이 소스 선별을 하나도 통과하지
    못해 채점 근거로 선택되지 않았다면(=`Score.scored_assets`에 없다), 그래도
    스냅샷은 남아야 한다(#224, ADR-0031 「clone 한 커밋은 전부 남긴다」) —
    「이 저장소를 언제 어느 커밋으로 받았는가」와 「그중 무엇이 채점에 쓰였는가」는
    다른 질문이다. staging에서 `octocat/Hello-World`가 실제로 이 경로를 밟았다 —
    확장자 없는 파일(README)만 있어 선별이 하나도 못 골랐는데, 박제본은 만들어졌고
    스냅샷은 없었다. (선별이 차단 목록으로 뒤집힌 2026-10-02 부터 README 는
    선택된다 — 이 테스트는 여전히 차단되는 잠금 파일로 같은 경로를 만든다.)
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

    repo_url = _repository_url("public-org")

    # 잠금 파일은 `core.source_selection.EXCLUDED_FILE_NAMES` 에 걸려 선별에서
    # 통째로 빠진다 — octocat/Hello-World 가 staging 에서 밟은 「clone 은 됐는데
    # 고를 파일이 없다」 경로를 그대로 만든다. 소스 자료는 하나도 내지 않는다(저장소만 낸 제출) — ADR-0030의
    # 박제 조건과 이 티켓의 스냅샷 조건이 같은 clone 위에서 함께 성립하는지를
    # 이 테스트가 함께 고정한다.
    with override_settings(GITHUB_FAKE_REPO_FILES={repo_url: {"package-lock.json": "{}\n"}}):
        response = client.post(
            f"{CONTESTS_URL}/{contest['id']}/submissions",
            data={
                "assets": [{"kind": "repository", "value": repo_url}],
                "requirement_responses": [
                    {
                        "requirement_id": requirement_id,
                        "is_met": True,
                        "evidence": [
                            {"kind": "source_location", "value": "never appears anywhere"}
                        ],
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
    # 근거가 선별된 소스 어디에도 없었으니 미달로 채점된다 — LLM이 실제로 호출된
    # 정상 경로다(ADR-0030의 "채점 입력 0건" 자동 미달과는 다르다: clone은
    # 성공했으므로 `cloned_repositories`가 비지 않아 그 분기를 타지 않는다).
    assert score.percentage == Decimal("0.00")
    assert score.model_version != "platform-auto (채점 입력 없음)"

    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    # 선별이 그 저장소에서 파일을 하나도 고르지 못했으므로 scored_assets에는
    # 없다 — "쓰였는가"는 여전히 그것이 답한다. 스냅샷에 그 구분을 담는 필드를
    # 만들지 않는다는 것이 이 티켓의 규율이다(#224).
    assert all(e["asset_id"] != repository_asset.id for e in score.scored_assets)

    # 그래도 clone은 성공했으므로 스냅샷은 남아야 한다 — 이 티켓의 핵심.
    snapshot = RepositorySnapshot.objects.get(asset=repository_asset)
    assert len(snapshot.commit_sha) == 40

    # 소스 자료가 하나도 없는 제출이므로 ADR-0030의 박제도 함께 일어난다 — 박제와
    # 스냅샷이 이제 같은 조건(clone 성공) 위에서 함께 생긴다.
    archived = Submission.objects.get(id=submission["id"]).assets.filter(
        kind=SubmissionAsset.Kind.SOURCE, created_by_platform=True
    )
    assert archived.count() == 1
    assert snapshot.commit_sha[:12] in archived.get().label


@pytest.mark.django_db
def test_repository_clone_failure_is_excluded_without_marking_the_submission_permanent(
    client, category, landing_type
):
    """clone 실패(네트워크 순단 등, "cloneerror" 시나리오)는 그 저장소 자산만 빼고
    나머지(소스)로 채점을 진행한다 — permanent로 표시되지 않는다."""

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

    # "cloneerror"가 owner에 있으면 공개로 판정되지만(check_public은 "private"만
    # 본다) clone()은 실패한다.
    repo_url = _repository_url("cloneerror-org")
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
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("100.00")

    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    assert not RepositorySnapshot.objects.filter(asset=repository_asset).exists()
    assert all(e["asset_id"] != repository_asset.id for e in score.scored_assets)

    # clone 실패는 permanent 이력을 남기지 않는다 — Submission 자체는 이미
    # 정상적으로 채점됐다(Score가 있다). ScoringAttempt는 소스/전체 실패
    # 경로에서만 만들어지고, 저장소 하나의 clone 실패는 로그만 남기고 넘어간다.
    assert not submission_id_has_permanent_attempt(submission["id"])


def submission_id_has_permanent_attempt(submission_id: int) -> bool:
    from scoring.models import ScoringAttempt

    return ScoringAttempt.objects.filter(submission_id=submission_id, permanent=True).exists()


# --- 코드리뷰 지적 반영 -------------------------------------------------------------


@pytest.mark.django_db
def test_repository_asset_is_still_checked_after_contest_closes(client, category, landing_type):
    """`SCAN_REGISTRY`는 `INSTALLED_APPS` 등록 순서를 따르는 평범한 dict라
    `core.scans.run_all`(`/api/internal/tick`)이 한 틱 안에서 `contest-close`
    스캔을 이 스캔보다 먼저 돌린다 — 마감 직전에 제출된 저장소는 `PUBLISHED`인
    동안 한 번도 확인되지 못한 채 Contest가 CLOSED로 넘어갈 수 있다.

    후보를 Contest 상태로 좁히면 그 저장소는 영원히 스캔 대상에서 빠져 채점
    (`is_public=True` 필터)에도 절대 clone되지 못한다 — 이 테스트는 마감 후에도
    (Score가 아직 없는 한) 스캔이 여전히 그 자산을 본다는 것을 고정한다.
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

    repo_url = _repository_url("public-org")
    submission = _submit_with_repository(
        client,
        dev,
        contest["id"],
        requirement_id=requirement_id,
        repo_url=repo_url,
        source_marker="SRC_MARKER",
    )

    # 마감 전 스캔을 한 번도 돌리지 않고 바로 마감시킨다 — "contest-close가
    # repository-visibility보다 먼저 도는 틱"을 재현한다.
    _close_contest(client, contest, deadline=deadline)

    _run_visibility_scan(client)

    detail = client.get(
        f"/api/submissions/{submission['id']}", **_auth_header(dev["access"])
    )
    repo_asset = next(a for a in detail.json()["assets"] if a["kind"] == "repository")
    assert repo_asset["is_public"] is True


@pytest.mark.django_db
def test_visibility_check_transient_failure_leaves_is_public_null_not_false(
    client, category, landing_type
):
    """네트워크 순단·5xx·rate limit 같은 "아직 확인 못 했다"를 "비공개로
    확인됐다"로 오분류하면 안 된다 — null로 남아야 다음 스캔이 다시 본다.
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

    # "checkerror"는 404가 아닌 실패(네트워크 순단 등)를 흉내낸다.
    repo_url = _repository_url("checkerror-org")
    submission = _submit_with_repository(
        client,
        dev,
        contest["id"],
        requirement_id=requirement_id,
        repo_url=repo_url,
        source_marker="SRC_MARKER",
    )

    result = _run_visibility_scan(client)
    assert result["failed"], "일시적 실패가 성공으로 조용히 넘어갔다"

    detail = client.get(
        f"/api/submissions/{submission['id']}", **_auth_header(dev["access"])
    )
    repo_asset = next(a for a in detail.json()["assets"] if a["kind"] == "repository")
    assert repo_asset["is_public"] is None


@pytest.mark.django_db
def test_scoring_is_deferred_while_repository_visibility_is_still_unresolved(
    client, category, landing_type
):
    """`SCAN_REGISTRY`는 `INSTALLED_APPS` 등록 순서를 따르는 평범한 dict라
    `submission-scoring`이 `repository-visibility`보다 먼저 등록·실행된다 —
    마감이 일어난 바로 그 틱에서 채점이 먼저 돌면, 방금 마감된 저장소는
    `is_public`이 아직 null이라 조회조차 되지 못한 채(`is_public=True` 필터)
    Score가 확정되고, Score는 append-only라(ADR-0006) 그 뒤 가시성 스캔이
    아무리 부지런히 값을 채워도 이미 늦는다.

    이 테스트는 정확히 그 순서(`submission-scoring`을 `repository-visibility`
    보다 먼저 호출)로 재현해, 채점이 그 틱에서 진행되지 않고 가시성이 확정된
    뒤에야 진행되는지를 고정한다(#193 코드리뷰 지적).
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

    repo_url = _repository_url("public-org")
    submission = _submit_with_repository(
        client,
        dev,
        contest["id"],
        requirement_id=requirement_id,
        repo_url=repo_url,
        source_marker="SRC_MARKER",
    )

    # 가시성 스캔을 아직 한 번도 돌리지 않은 채(is_public이 여전히 null) 마감시키고
    # 채점 스캔을 먼저 부른다 — "contest-close 직후 submission-scoring이
    # repository-visibility보다 먼저 도는 틱"을 그대로 재현한다.
    _close_contest(client, contest, deadline=deadline)
    deferred = _run_scoring(client)

    assert not Score.objects.filter(submission_id=submission["id"]).exists(), (
        "저장소 공개 여부가 아직 안 정해졌는데 채점이 먼저 진행됐다"
    )
    assert all(row["submission_id"] != submission["id"] for row in deferred["rows"])

    # 이제 가시성이 확정된다 — 다음 채점 스캔은 더 이상 미루지 않는다.
    _run_visibility_scan(client)
    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    assert Score.objects.filter(submission_id=submission["id"]).exists()


@pytest.mark.django_db
def test_scoring_proceeds_after_the_grace_period_even_if_visibility_never_resolves(
    client, category, landing_type
):
    """GitHub이 계속 죽어 있어도(가시성 스캔이 한 번도 성공하지 못해도) 그
    Submission이 영원히 Score 없이 남으면 안 된다 — 배분 컷라인에서 조용히
    탈락한다(#190·#191이 `no_source_asset`/`source_not_found`를 가른 것과 같은
    이유). 유예 기간이 지나면 미해결 저장소를 "채점 입력이 아님"으로 확정하고
    소스만으로 채점을 진행해야 한다(#193 코드리뷰 지적).
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

    repo_url = _repository_url("public-org")
    submission = _submit_with_repository(
        client,
        dev,
        contest["id"],
        requirement_id=requirement_id,
        repo_url=repo_url,
        source_marker="SRC_MARKER",
    )

    _close_contest(client, contest, deadline=deadline)
    # 가시성 스캔을 한 번도 성공시키지 않은 채(is_public은 계속 null) 유예 기간을
    # 훌쩍 넘긴 시각으로 시계를 옮긴다.
    from core.models import ClockOverride

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(hours=3)}
    )

    result = _run_scoring(client)

    assert result["rows"][0]["status"] == "scored"
    score = Score.objects.get(submission_id=submission["id"])
    assert score.percentage == Decimal("100.00")  # 소스만으로 충족

    repository_asset = Submission.objects.get(id=submission["id"]).assets.get(
        kind=SubmissionAsset.Kind.REPOSITORY
    )
    assert all(e["asset_id"] != repository_asset.id for e in score.scored_assets)
    assert not RepositorySnapshot.objects.filter(asset=repository_asset).exists()
