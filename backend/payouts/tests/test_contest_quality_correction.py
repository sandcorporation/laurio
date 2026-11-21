"""점수 정정 뒤 완성도 리뷰를 정정 판으로 다시 돌린다(#1181, 스펙 #1178).

시임은 마운트된 HTTP API 다 — 운영자가 정정을 걸고(`score-corrections`), 정정 스캔·완성도 스캔을 내부 API 로 돌리고,
개최자 비교 화면·참가자 점수 화면으로 읽는다.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from core.llm_scoring import FakeLLMScoringAdapter, LLMAdapterPermanentError
from core.quality_review import QualityInput, QualityItemScore, QualityOutput
from scoring.models import QualityReviewAttempt, ScoreCorrection, SubmissionQualityReview
from payouts.tests.test_contest_quality import (  # noqa: F401 - 픽스처(category·landing_type·closed)도 들여온다
    CONTESTS_URL,
    _auth,
    _run_quality,
    category,
    closed,
    landing_type,
)
from payouts.tests.test_distributions import _advance_to_distribution_due, _internal_headers, _run_due_distributions
from tests.integration.test_source_readings import OPERATOR_ORIGIN, _operator_client

ALL_FIVE = "payouts.tests.test_contest_quality_correction._AllFiveAdapter"
REFUSES = "payouts.tests.test_contest_quality_correction._RefusesQualityAdapter"


class _AllFiveAdapter(FakeLLMScoringAdapter):
    """정정 판의 리뷰를 처음 리뷰와 가려 보도록 모든 항목에 5 를 준다."""

    def review_quality(self, quality_input: QualityInput) -> QualityOutput:
        return QualityOutput(
            scores=tuple(
                QualityItemScore(
                    item_id=item.item_id, label=item.label, required=item.required, score=5, reasoning="정정 판"
                )
                for item in quality_input.items
            ),
            model_version=self.model_version,
        )


class _RefusesQualityAdapter(FakeLLMScoringAdapter):
    def review_quality(self, quality_input: QualityInput) -> QualityOutput:
        raise LLMAdapterPermanentError("모델 거부(흉내)")


def _correct(client, contest_id: int, submission_id: int, *, uid: str) -> ScoreCorrection:
    operator = _operator_client(uid)
    response = operator.post(
        f"/api/operator/contests/{contest_id}/score-corrections",
        data={"reason": "플랫폼 오류로 다시 채점한다", "submission_ids": [submission_id]},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 201, response.content
    scan = client.post("/api/internal/scans/score-correction", **_internal_headers())
    assert [r["status"] for r in scan.json()["rows"]] == ["done"]
    return ScoreCorrection.objects.get(score__submission_id=submission_id)


def _compare_quality(client, closed) -> dict[int, dict]:
    response = client.get(
        f"{CONTESTS_URL}/{closed['contest']['id']}/submissions/compare", **_auth(closed["sponsor"]["access"])
    )
    assert response.status_code == 200, response.content
    return {s["submission_id"]: s["quality"] for s in response.json()["submissions"]}


@pytest.mark.django_db
def test_a_finished_correction_adds_a_review_of_the_corrected_version_and_the_ranking_reads_it(client, closed):
    """받아들임: 배분 전 정정 뒤 리뷰가 새 판으로 하나 더 생기고, 순위 API 가 그것을 읽는다."""

    _run_quality(client)
    first_a = SubmissionQualityReview.objects.get(submission_id=closed["a"])
    assert first_a.correction_id is None
    assert _compare_quality(client, closed)[closed["a"]]["weighted_score"] == first_a.weighted_score != 15

    correction = _correct(client, closed["contest"]["id"], closed["a"], uid="op-quality-before")
    with override_settings(LLM_ADAPTER_MODE=ALL_FIVE):
        rows = _run_quality(client)["rows"]
        assert [(r["submission_id"], r["status"]) for r in rows] == [(closed["a"], "reviewed")]
        assert _run_quality(client)["rows"] == [], "같은 판을 두 번 리뷰했다"

    reviews = list(SubmissionQualityReview.objects.filter(submission_id=closed["a"]).order_by("id"))
    assert [r.correction_id for r in reviews] == [None, correction.id]
    assert reviews[0].weighted_score == first_a.weighted_score, "처음 리뷰가 바뀌었다(append-only)"
    assert reviews[1].ranked is True
    assert reviews[1].prompt and reviews[1].weighted_score == 15

    quality = _compare_quality(client, closed)
    assert (quality[closed["a"]]["weighted_score"], quality[closed["a"]]["rank"]) == (15, 1)
    own = client.get(f"/api/submissions/{closed['a']}/score", **_auth(closed["dev_a"]["access"]))
    assert own.json()["quality"]["weighted_score"] == 15


@pytest.mark.django_db
def test_after_distribution_the_review_still_reruns_but_the_ranking_stays(client, closed):
    """받아들임: 배분이 끝난 공모전에서 정정하면 리뷰는 다시 돌되 순위는 그대로다."""

    _run_quality(client)
    _advance_to_distribution_due(client, closed["contest"]["id"])
    _run_due_distributions(client)
    before = _compare_quality(client, closed)

    correction = _correct(client, closed["contest"]["id"], closed["a"], uid="op-quality-after")
    with override_settings(LLM_ADAPTER_MODE=ALL_FIVE):
        assert [r["status"] for r in _run_quality(client)["rows"]] == ["reviewed"]

    rerun = SubmissionQualityReview.objects.get(submission_id=closed["a"], correction=correction)
    assert (rerun.weighted_score, rerun.ranked) == (15, False)
    assert _compare_quality(client, closed) == before


@pytest.mark.django_db
def test_failures_of_the_first_review_do_not_block_the_corrected_version(client, closed):
    """처음 판의 영구 실패는 그 판의 것이다 — 정정 판은 제 실패 기록으로 따로 센다."""

    with override_settings(LLM_ADAPTER_MODE=REFUSES):
        assert {r["status"] for r in _run_quality(client)["rows"]} == {"failed_permanently"}
    assert _run_quality(client)["rows"] == []

    correction = _correct(client, closed["contest"]["id"], closed["a"], uid="op-quality-failed")
    with override_settings(LLM_ADAPTER_MODE=ALL_FIVE):
        assert [(r["submission_id"], r["status"]) for r in _run_quality(client)["rows"]] == [
            (closed["a"], "reviewed")
        ]
    assert SubmissionQualityReview.objects.get(submission_id=closed["a"]).correction_id == correction.id
    assert QualityReviewAttempt.objects.filter(submission_id=closed["a"], correction__isnull=True).count() == 1
