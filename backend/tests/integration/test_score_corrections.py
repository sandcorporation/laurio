"""운영자 정정 채점(#1180, 스펙 #1178) — 거는 API, 처음 커밋 고정, 배분 끝남 판정, 배분 스캔 붙잡기.

정정이 바로잡는 것은 「플랫폼 오류로 틀린 점수」다. 여기서 그 오류는 벤더가 연달아 실패해 실패 상한이 0% 로 굳힌
경우로 만든다 — 같은 소스를 다시 채점하면 흉내 LLM(`FakeLLMScoringAdapter`)이 제대로 판정한다.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from certificates.models import Certificate
from contests.models import ContestSubmission
from distributions.models import Distribution, DistributionShare
from scoring.models import Score, ScoreCorrection, ScoringAttempt
from scoring.services import PLATFORM_FAILURE_MODEL_VERSION, SCORING_FAILURE_GRACE, SCORING_FAILURE_LIMIT
from submissions.models import SubmissionAsset

from payouts.tests.test_distributions import (  # noqa: F401 - 픽스처(category·landing_type·_default_cutline)도 들여온다
    _advance_to_distribution_due,
    _close_contest,
    _default_cutline,
    _freeze,
    _internal_headers,
    _publish_contest,
    _run_due_distributions,
    _run_scoring,
    _submit,
    _verified_user,
    category,
    landing_type,
)
from tests.integration.test_repository_reachability_recheck import _repository_url, _submit_repository_only
from tests.integration.test_source_readings import OPERATOR_ORIGIN, _operator_client

LOGIN = "로그인 기능이 있다"


def _corrections_url(contest_id: int) -> str:
    return f"/api/operator/contests/{contest_id}/score-corrections"


def _request(operator, contest_id: int, *, reason="플랫폼 오류로 0% 가 굳었다", submission_ids=None):
    body: dict = {"reason": reason}
    if submission_ids is not None:
        body["submission_ids"] = submission_ids
    return operator.post(
        _corrections_url(contest_id), data=body, content_type="application/json", HTTP_ORIGIN=OPERATOR_ORIGIN
    )


def _run_corrections(client) -> dict:
    response = client.post("/api/internal/scans/score-correction", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _contest_with_platform_failure(client, *, uid: str) -> dict:
    """참가자 둘 — `honest` 는 제대로 100%, `failed` 는 같은 충족 소스인데 벤더 실패가 상한에 닿아 0% 로 굳었다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=client.category,
        deliverable_type=client.landing_type,
        sponsor_uid=f"{uid}-sponsor",
        sponsor_ci=f"{uid}-sponsor-ci",
        deadline_at=deadline,
        requirements=[{"text": LOGIN, "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    honest_dev = _verified_user(client, f"{uid}-honest", f"{uid}-honest-ci")
    failed_dev = _verified_user(client, f"{uid}-failed", f"{uid}-failed-ci")
    honest = _submit(client, honest_dev, contest["id"], requirement_id=requirement_id, grounded=True)
    failed = _submit(client, failed_dev, contest["id"], requirement_id=requirement_id, grounded=True)
    _close_contest(client, contest, deadline=deadline)
    with override_settings(LLM_FAKE_RAISING_SUBMISSION_IDS=[failed["id"]]):
        for _ in range(SCORING_FAILURE_LIMIT):
            _run_scoring(client)
        _freeze(deadline + SCORING_FAILURE_GRACE + timedelta(minutes=5))
        _run_scoring(client)
    failed_score = Score.objects.get(submission_id=failed["id"])
    assert failed_score.model_version == PLATFORM_FAILURE_MODEL_VERSION
    assert failed_score.percentage == Decimal("0.00")
    assert Score.objects.get(submission_id=honest["id"]).percentage == Decimal("100.00")
    return {
        "contest_id": contest["id"],
        "honest_id": honest["id"],
        "failed_id": failed["id"],
        "sponsor": sponsor,
        "deadline": deadline,
    }


@pytest.fixture
def world(client, category, landing_type):
    client.category = category
    client.landing_type = landing_type
    return client


@pytest.mark.django_db
def test_a_correction_before_distribution_moves_the_submission_over_the_cutline(world):
    """받아들임: 배분 전 공모전에서 정정 한 건이 컷라인 통과 여부를 바꾸고, 배분이 새 점수로 나뉜다."""

    seeded = _contest_with_platform_failure(world, uid="corr-before")
    operator = _operator_client("op-corr-before")

    requested = _request(operator, seeded["contest_id"], submission_ids=[seeded["failed_id"]])
    assert requested.status_code == 201, requested.content
    body = requested.json()
    assert body["prize_settled"] is False
    assert body["skipped"] == []
    [row] = body["corrections"]
    assert row["status"] == "in_progress"
    assert row["original_percentage"] == "0.00"
    assert row["certificates_issued"] == 0

    result = _run_corrections(world)
    assert [r["status"] for r in result["rows"]] == ["done"]

    listed = operator.get(_corrections_url(seeded["contest_id"]), HTTP_ORIGIN=OPERATOR_ORIGIN)
    assert listed.status_code == 200
    [done] = listed.json()["corrections"]
    assert (done["status"], done["percentage"], done["original_percentage"]) == ("done", "100.00", "0.00")
    assert done["model_version"] == "fake-llm-v1"

    _advance_to_distribution_due(world, seeded["contest_id"])
    _run_due_distributions(world)
    distribution = Distribution.objects.get(contest_id=seeded["contest_id"])
    assert distribution.qualifying_count == 2, "정정된 제출이 컷라인을 넘었는데 배분 대상에 없다"
    assert set(distribution.shares.values_list("submission_id", flat=True)) == {
        seeded["honest_id"],
        seeded["failed_id"],
    }


@pytest.mark.django_db
def test_a_correction_after_distribution_leaves_the_distribution_as_it_was(world):
    """받아들임: 배분이 끝난 공모전에서 정정하면 정정 기록만 남고 `Distribution`·`DistributionShare` 가 그대로다."""

    seeded = _contest_with_platform_failure(world, uid="corr-after")
    _advance_to_distribution_due(world, seeded["contest_id"])
    _run_due_distributions(world)
    distribution = Distribution.objects.get(contest_id=seeded["contest_id"])
    before = (
        list(Distribution.objects.filter(pk=distribution.pk).values()),
        list(DistributionShare.objects.filter(distribution=distribution).order_by("id").values()),
    )
    assert distribution.qualifying_count == 1

    operator = _operator_client("op-corr-after")
    requested = _request(operator, seeded["contest_id"], submission_ids=[seeded["failed_id"]])
    assert requested.status_code == 201, requested.content
    assert requested.json()["prize_settled"] is True
    _run_corrections(world)
    _run_due_distributions(world)

    correction = ScoreCorrection.objects.get(score__submission_id=seeded["failed_id"])
    assert (correction.status, correction.percentage) == (ScoreCorrection.Status.DONE, Decimal("100.00"))
    after = (
        list(Distribution.objects.filter(pk=distribution.pk).values()),
        list(DistributionShare.objects.filter(distribution=distribution).order_by("id").values()),
    )
    assert after == before
    listed = operator.get(_corrections_url(seeded["contest_id"]), HTTP_ORIGIN=OPERATOR_ORIGIN)
    assert listed.json()["prize_settled"] is True


@pytest.mark.django_db
def test_an_in_progress_correction_holds_the_distribution_scan_until_it_finishes(world):
    """받아들임: 진행 중 정정이 있으면 배분 스캔이 그 공모전을 건너뛴다 — 끝나면 저절로 풀린다."""

    seeded = _contest_with_platform_failure(world, uid="corr-hold")
    operator = _operator_client("op-corr-hold")
    assert _request(operator, seeded["contest_id"]).status_code == 201

    _advance_to_distribution_due(world, seeded["contest_id"])
    _run_due_distributions(world)
    assert not Distribution.objects.filter(contest_id=seeded["contest_id"]).exists(), (
        "정정 채점이 도는데 배분이 만들어졌다"
    )

    _run_corrections(world)
    _run_due_distributions(world)
    assert Distribution.objects.get(contest_id=seeded["contest_id"]).qualifying_count == 2


@pytest.mark.django_db
def test_a_correction_scores_the_first_commit_not_the_new_default_branch(world):
    """받아들임: 기본 브랜치에 새 커밋이 있어도 정정은 처음 채점 때 받은 커밋을 받는다. 박제본은 싣지 않는다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        world,
        category=world.category,
        deliverable_type=world.landing_type,
        sponsor_uid="corr-pin-sponsor",
        sponsor_ci="corr-pin-sponsor-ci",
        deadline_at=deadline,
        requirements=[{"text": LOGIN, "grade": "required"}],
    )
    dev = _verified_user(world, "corr-pin-dev", "corr-pin-dev-ci")
    repo_url = _repository_url("public-org")
    first_files = {"main.py": "print('처음 커밋')\n"}

    with override_settings(GITHUB_FAKE_REPO_FILES={repo_url: first_files}):
        submission = _submit_repository_only(
            world, dev, contest["id"], requirement_id=contest["requirements"][0]["id"], repo_url=repo_url
        )
        SubmissionAsset.objects.filter(submission_id=submission["id"], kind=SubmissionAsset.Kind.REPOSITORY).update(
            is_public=True, is_public_checked_at=timezone.now()
        )
        _close_contest(world, contest, deadline=deadline)
        _run_scoring(world)
    score = Score.objects.get(submission_id=submission["id"])
    [scored] = score.scored_assets
    first_sha = scored["commit_sha"]
    assert first_sha and score.percentage == Decimal("0.00")
    # 소스 자료 없이 저장소만 낸 제출이라 처음 채점이 저장소를 박제했다(#220) — 정정이 이것을 함께 실으면 안 된다.
    assert SubmissionAsset.objects.filter(submission_id=submission["id"], created_by_platform=True).count() == 1

    # 마감 뒤 기본 브랜치에 요구사항을 채우는 커밋이 들어왔다. 처음 커밋은 그대로 받을 수 있다.
    new_default = {"main.py": f"# {LOGIN}\n"}
    operator = _operator_client("op-corr-pin")
    assert _request(operator, contest["id"]).status_code == 201
    with override_settings(GITHUB_FAKE_REPO_FILES={repo_url: new_default, f"{repo_url}@{first_sha}": first_files}):
        _run_corrections(world)

    correction = ScoreCorrection.objects.get(score=score)
    assert correction.status == ScoreCorrection.Status.DONE, correction.error
    assert correction.percentage == Decimal("0.00"), "정정이 마감 뒤 기본 브랜치를 채점했다"
    assert correction.scored_assets == [{"asset_id": scored["asset_id"], "commit_sha": first_sha}]
    assert SubmissionAsset.objects.filter(submission_id=submission["id"], created_by_platform=True).count() == 1
    # 박제본(같은 저장소의 zip)을 함께 실었다면 같은 파일이 두 번 실린다.
    assert correction.prompt.count("처음 커밋") == 1


@pytest.mark.django_db
def test_a_correction_needs_a_reason_and_only_one_runs_per_submission(world):
    seeded = _contest_with_platform_failure(world, uid="corr-rules")
    operator = _operator_client("op-corr-rules")

    blank = _request(operator, seeded["contest_id"], reason="   ")
    assert blank.status_code == 422
    assert not ScoreCorrection.objects.exists()

    outside = _request(operator, seeded["contest_id"], submission_ids=[seeded["failed_id"], 987654321])
    assert outside.status_code == 422

    first = _request(operator, seeded["contest_id"])
    assert first.status_code == 201
    assert {c["submission_id"] for c in first.json()["corrections"]} == {seeded["honest_id"], seeded["failed_id"]}
    second = _request(operator, seeded["contest_id"], submission_ids=[seeded["failed_id"]])
    assert second.status_code == 201
    assert second.json()["corrections"] == []
    assert second.json()["skipped"] == [{"submission_id": seeded["failed_id"], "reason": "in_progress"}]

    anonymous = world.post(
        _corrections_url(seeded["contest_id"]),
        data={"reason": "x"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert anonymous.status_code in (401, 403)


@pytest.mark.django_db
def test_a_held_correction_fails_with_its_reason_and_leaves_the_first_score_alone(world):
    """보류·오류는 정정을 「실패」로 넘기고 까닭을 남긴다 — 처음 채점의 시도 기록에는 닿지 않는다."""

    seeded = _contest_with_platform_failure(world, uid="corr-fail")
    operator = _operator_client("op-corr-fail")
    assert _request(operator, seeded["contest_id"], submission_ids=[seeded["failed_id"]]).status_code == 201
    attempts_before = ScoringAttempt.objects.filter(submission_id=seeded["failed_id"]).count()

    with override_settings(LLM_FAKE_RAISING_SUBMISSION_IDS=[seeded["failed_id"]]):
        result = _run_corrections(world)

    assert [r["status"] for r in result["rows"]] == ["failed"]
    correction = ScoreCorrection.objects.get(score__submission_id=seeded["failed_id"])
    assert correction.status == ScoreCorrection.Status.FAILED
    assert "fake LLM adapter" in correction.error
    assert correction.finished_at is not None
    assert ScoringAttempt.objects.filter(submission_id=seeded["failed_id"]).count() == attempts_before
    # 실패한 정정 뒤에 다시 걸 수 있다.
    assert _request(operator, seeded["contest_id"], submission_ids=[seeded["failed_id"]]).json()["skipped"] == []



@pytest.mark.django_db
def test_a_correction_reports_the_certificates_issued_to_that_submission_and_keeps_them(world):
    """정정은 상장을 취소하지 않는다 — 발급된 수를 응답에 실어 운영자가 개최자에게 알릴 근거를 준다."""

    seeded = _contest_with_platform_failure(world, uid="corr-cert")
    # 발급 API 는 PDF 를 그려 CPU 한도를 넘긴다 — 셈만 보면 되니 행을 바로 만든다(발급 자체는 상장 시험 몫).
    submission = ContestSubmission.objects.select_related("contest__sponsor").get(pk=seeded["failed_id"])
    Certificate.objects.create(
        contest=submission.contest,
        submission=submission,
        recipient=submission.user,
        number="CORR-CERT-1",
        token="corr-cert-token",
        award_name="최우수상",
        giver_name="홍길동",
        award_date=timezone.localtime(seeded["deadline"]).date(),
        pdf_object_key="certificates/corr-cert.pdf",
        issued_at=timezone.now(),
        issued_by=submission.contest.sponsor.user,
    )

    operator = _operator_client("op-corr-cert")
    body = _request(operator, seeded["contest_id"]).json()
    by_submission = {c["submission_id"]: c["certificates_issued"] for c in body["corrections"]}
    assert by_submission == {seeded["honest_id"]: 0, seeded["failed_id"]: 1}
    _run_corrections(world)
    listed = operator.get(_corrections_url(seeded["contest_id"]), HTTP_ORIGIN=OPERATOR_ORIGIN).json()
    assert {c["submission_id"]: c["certificates_issued"] for c in listed["corrections"]}[seeded["failed_id"]] == 1
    # 거는 화면이 고를 제출 목록 — 처음 채점 점수 그대로(정정이 끝나도 원래 점수가 남는다).
    originals = {s["submission_id"]: s["original_percentage"] for s in listed["submissions"]}
    assert originals == {seeded["honest_id"]: "100.00", seeded["failed_id"]: "0.00"}
