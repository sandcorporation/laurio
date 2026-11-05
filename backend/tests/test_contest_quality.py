"""공모전 완성도(#884, ADR-0072) — 마감·Score 뒤 스캔이 Requirement 마다 0~5 를 매기고, 개최자는 전부·
제출자는 자기 것만 본다. Score·Distribution·Award 는 그대로다.

시임은 HTTP 다 — 스캔은 `/api/internal/scans/{name}`, 조회는 마운트된 API 로 부른다.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, DeliverableType
from core.llm_scoring import FakeLLMScoringAdapter, LLMAdapterError, LLMAdapterPermanentError
from core.quality_review import QualityInput, QualityOutput
from distributions.models import Distribution, DistributionShare
from scoring.models import QualityReviewAttempt, Score, SubmissionQualityReview
from scoring.quality import QUALITY_FAILURE_LIMIT
from submissions.scoring_basis import PLATFORM_FAILURE_MODEL_VERSION
from tests.test_distributions import (
    _advance_past_distribution_wait,
    _end_judging_period,
    _internal_headers,
    _publish_contest,
    _run_due_distributions,
    _run_scoring,
    _submit,
    _verified_user,
)
from tests.test_source_readings import _close_contest  # 마감 스캔만 돈다(tick 은 채점·완성도까지 돈다).

CONTESTS_URL = "/api/contests"
QUALITY_SCAN_URL = "/api/internal/scans/submission-quality-review"

REQUIREMENTS = [
    {"text": "로그인 기능이 있다", "grade": "required"},
    {"text": "다크 모드를 지원한다", "grade": "optional"},
]


def _auth(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _run_quality(client) -> dict:
    response = client.post(QUALITY_SCAN_URL, **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


class _QualityFailsAdapter(FakeLLMScoringAdapter):
    """Score 는 흉내 그대로 내고 완성도만 일시 실패한다."""

    def review_quality(self, quality_input: QualityInput) -> QualityOutput:
        raise LLMAdapterError("벤더 일시 장애(흉내)")


class _QualityPermanentlyFailsAdapter(FakeLLMScoringAdapter):
    def review_quality(self, quality_input: QualityInput) -> QualityOutput:
        raise LLMAdapterPermanentError("모델 거부(흉내)")


class _AllPlatformFailureAdapter(FakeLLMScoringAdapter):
    """Score 채점이 영구 실패해 「채점 실패」 자동 0% 로 굳는다."""

    def score(self, scoring_input):
        raise LLMAdapterPermanentError("모델 거부(흉내)")


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


@pytest.fixture
def closed(client, category, landing_type):
    """마감·채점까지 끝난 공모전 하나, 제출 둘."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline, requirements=REQUIREMENTS
    )
    requirement_id = contest["requirements"][0]["id"]
    dev_a = _verified_user(client, "dev-qa", "dev-qa-ci")
    dev_b = _verified_user(client, "dev-qb", "dev-qb-ci")
    sub_a = _submit(client, dev_a, contest["id"], requirement_id=requirement_id, grounded=True)
    sub_b = _submit(client, dev_b, contest["id"], requirement_id=requirement_id, grounded=False)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    return {"sponsor": sponsor, "contest": contest, "dev_a": dev_a, "dev_b": dev_b, "a": sub_a["id"], "b": sub_b["id"]}


@pytest.mark.django_db
def test_scan_reviews_every_scored_submission_once_with_weighted_completeness(client, closed):
    result = _run_quality(client)
    assert {r["submission_id"]: r["status"] for r in result["rows"]} == {
        closed["a"]: "reviewed",
        closed["b"]: "reviewed",
    }

    review = SubmissionQualityReview.objects.get(submission_id=closed["a"])
    requirement_ids = [r["id"] for r in closed["contest"]["requirements"]]
    assert [i["item_id"] for i in review.items] == requirement_ids
    assert [i["required"] for i in review.items] == [True, False]
    assert all(0 <= i["score"] <= 5 and i["reasoning"] for i in review.items)
    # 필수 2·선택 1 — 최대 5×(2+1)=15.
    assert review.max_weighted_score == 15
    assert review.weighted_score == 2 * review.items[0]["score"] + review.items[1]["score"]
    assert review.completeness == pytest.approx(review.weighted_score / 15 * 100)
    # 제출물은 신뢰하지 않는 데이터로 경계 안에 실린다.
    assert "<<<SOURCE_FILE_START>>>" in review.prompt

    # 두 번째 스캔은 아무것도 집지 않는다 — 한 번만 매긴다.
    assert _run_quality(client)["rows"] == []
    assert SubmissionQualityReview.objects.count() == 2


@pytest.mark.django_db
def test_nothing_is_reviewed_before_the_score_exists(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline, requirements=REQUIREMENTS
    )
    dev = _verified_user(client, "dev-early", "dev-early-ci")
    _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"], grounded=True)
    _close_contest(client, contest, deadline=deadline)

    assert _run_quality(client)["rows"] == []
    assert not SubmissionQualityReview.objects.exists()


@pytest.mark.django_db
def test_platform_failure_score_is_skipped(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline, requirements=REQUIREMENTS
    )
    dev = _verified_user(client, "dev-fail", "dev-fail-ci")
    sub = _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"], grounded=True)
    _close_contest(client, contest, deadline=deadline)
    with override_settings(LLM_ADAPTER_MODE="tests.test_contest_quality._AllPlatformFailureAdapter"):
        _run_scoring(client)  # 영구 실패 이력
        _run_scoring(client)  # 상한 → 자동 0%
    assert Score.objects.get(submission_id=sub["id"]).model_version == PLATFORM_FAILURE_MODEL_VERSION

    assert _run_quality(client)["rows"] == []
    assert not SubmissionQualityReview.objects.exists()


@pytest.mark.django_db
def test_transient_failures_are_recorded_and_stop_at_the_limit(client, closed):
    score_before = Score.objects.get(submission_id=closed["a"]).percentage
    with override_settings(LLM_ADAPTER_MODE="tests.test_contest_quality._QualityFailsAdapter"):
        for _ in range(QUALITY_FAILURE_LIMIT):
            rows = _run_quality(client)["rows"]
            assert {r["status"] for r in rows} == {"failed"}
        assert _run_quality(client)["rows"] == []

    assert QualityReviewAttempt.objects.filter(submission_id=closed["a"]).count() == QUALITY_FAILURE_LIMIT
    assert not SubmissionQualityReview.objects.exists()
    assert Score.objects.get(submission_id=closed["a"]).percentage == score_before


@pytest.mark.django_db
def test_permanent_failure_stops_at_once(client, closed):
    with override_settings(LLM_ADAPTER_MODE="tests.test_contest_quality._QualityPermanentlyFailsAdapter"):
        assert {r["status"] for r in _run_quality(client)["rows"]} == {"failed_permanently"}
        assert _run_quality(client)["rows"] == []
    assert QualityReviewAttempt.objects.filter(permanent=True).count() == 2


@pytest.mark.django_db
def test_sponsor_sees_every_submissions_quality_with_rank(client, closed):
    _run_quality(client)
    response = client.get(
        f"{CONTESTS_URL}/{closed['contest']['id']}/submissions/compare", **_auth(closed["sponsor"]["access"])
    )
    assert response.status_code == 200, response.content
    by_id = {s["submission_id"]: s["quality"] for s in response.json()["submissions"]}
    assert set(by_id) == {closed["a"], closed["b"]}
    weighted = {sid: q["weighted_score"] for sid, q in by_id.items()}
    for sid, quality in by_id.items():
        assert quality["max_weighted_score"] == 15
        assert len(quality["items"]) == 2 and quality["items"][0]["reasoning"]
        other = weighted[closed["b"] if sid == closed["a"] else closed["a"]]
        assert quality["rank"] == (1 if weighted[sid] >= other else 2)


@pytest.mark.django_db
def test_compare_shows_null_quality_until_reviewed(client, closed):
    response = client.get(
        f"{CONTESTS_URL}/{closed['contest']['id']}/submissions/compare", **_auth(closed["sponsor"]["access"])
    )
    assert response.status_code == 200
    assert all(s["quality"] is None for s in response.json()["submissions"])


@pytest.mark.django_db
def test_submitter_sees_only_their_own_quality_without_rank(client, closed):
    _run_quality(client)

    own = client.get(f"/api/submissions/{closed['a']}/score", **_auth(closed["dev_a"]["access"]))
    assert own.status_code == 200
    quality = own.json()["quality"]
    review = SubmissionQualityReview.objects.get(submission_id=closed["a"])
    assert quality["weighted_score"] == review.weighted_score
    assert [i["score"] for i in quality["items"]] == [i["score"] for i in review.items]
    assert "rank" not in quality  # 등수는 남의 제출과 견준 값이다.

    # 남의 제출: 점수 API 는 403, 공개 단건·비교 목록에는 완성도가 없다.
    assert client.get(f"/api/submissions/{closed['b']}/score", **_auth(closed["dev_a"]["access"])).status_code == 403
    public = client.get(f"/api/submissions/{closed['b']}", **_auth(closed["dev_a"]["access"]))
    assert public.status_code == 200
    assert "quality" not in public.content.decode()
    compare = client.get(
        f"{CONTESTS_URL}/{closed['contest']['id']}/submissions/compare", **_auth(closed["dev_a"]["access"])
    )
    assert compare.status_code == 403


@pytest.mark.django_db
def test_quality_is_not_an_appeal_target(client, closed):
    """이의는 지금처럼 Score 에만 건다 — 완성도가 생겨도 이의 창·접수가 그대로다."""

    before = client.get(f"/api/submissions/{closed['a']}/score", **_auth(closed["dev_a"]["access"])).json()
    _run_quality(client)
    after = client.get(f"/api/submissions/{closed['a']}/score", **_auth(closed["dev_a"]["access"])).json()
    assert after["can_appeal"] == before["can_appeal"]
    for key in ("percentage", "reasoning", "scoring_basis", "model_version"):
        assert after[key] == before[key]

    appeal = client.post(
        f"/api/submissions/{closed['a']}/appeal",
        data={"reason": "Evidence가 실제로 소스에 있습니다."},
        content_type="application/json",
        **_auth(closed["dev_a"]["access"]),
    )
    assert appeal.status_code == 201, appeal.content
    assert "quality" not in appeal.content.decode()


@pytest.mark.django_db
def test_distribution_is_unchanged_by_quality(client, closed):
    """완성도는 상금 배분에 쓰지 않는다 — 컷라인을 넘은 제출만 배분받는 것이 그대로다."""

    from policies.models import PlatformPolicy

    PlatformPolicy.objects.update_or_create(pk=1, defaults={"distribution_cutline_percentage": Decimal("60.00")})
    _run_quality(client)
    scores_before = {s.submission_id: (s.percentage, s.reasoning) for s in Score.objects.all()}

    _end_judging_period(client, closed["contest"]["id"])
    _advance_past_distribution_wait(closed["contest"]["id"])
    _run_due_distributions(client)

    distribution = Distribution.objects.get(contest_id=closed["contest"]["id"])
    assert distribution.qualifying_count == 1
    assert [s.submission_id for s in DistributionShare.objects.filter(distribution=distribution)] == [closed["a"]]
    assert {s.submission_id: (s.percentage, s.reasoning) for s in Score.objects.all()} == scores_before
    assert SubmissionQualityReview.objects.count() == 2


@pytest.mark.django_db
def test_award_is_the_sponsors_choice_regardless_of_quality(client, closed):
    """선정은 개최자가 한다 — 완성도가 낮은 제출도 그대로 선정된다. 선정 뒤(AWARDED)에도 남은 제출을 매긴다."""

    from awards.models import Award

    with override_settings(LLM_ADAPTER_MODE="tests.test_contest_quality._QualityFailsAdapter"):
        _run_quality(client)  # 아직 아무것도 매기지 못했다.
    award = client.post(
        f"{CONTESTS_URL}/{closed['contest']['id']}/award",
        data={"submission_id": closed["b"]},
        content_type="application/json",
        **_auth(closed["sponsor"]["access"]),
    )
    assert award.status_code == 200, award.content
    assert Award.objects.get(contest_id=closed["contest"]["id"]).submission_id == closed["b"]

    assert {r["status"] for r in _run_quality(client)["rows"]} == {"reviewed"}
    assert Award.objects.get(contest_id=closed["contest"]["id"]).submission_id == closed["b"]
