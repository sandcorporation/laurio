"""#991: 공모전 AI 채점만 끄는 런타임 스위치(`CONTEST_AI_SCORING`) — 값이 없으면 꺼짐.

공모전 채점만 멈출 길이 없어 2026-11-20 00:33 KST 부터 celery-worker 전체를 세웠고, 강의실
채점·마감 전이·알림까지 함께 멈췄다. 이 스위치가 꺼지면 공모전 채점(`submission-scoring`)과
완성도 리뷰(`submission-quality-review`) 두 스캔만 멈추고 나머지는 그대로 돈다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from core import scans
from core import tasks as core_tasks
from policies.runtime_settings import SPECS, contest_ai_scoring_enabled, contest_quality_review_enabled
from scoring.models import QualityReviewAttempt, Score, ScoringAttempt, SubmissionQualityReview
from contests.tests.test_runtime_settings import _client_for, _clear, _save
from tests.integration.test_scoring import (  # noqa: F401 - fixture 들을 이 모듈에도 등록한다.
    RUN_PENDING_URL,
    _close_contest,
    _freeze,
    _internal_headers,
    _publish_contest,
    _submit_with_marker,
    _verified_user,
    category,
    landing_type,
)

CONTEST_SCANS = ("submission-scoring", "submission-quality-review")


def _off(monkeypatch):
    monkeypatch.delenv("CONTEST_AI_SCORING", raising=False)
    monkeypatch.delenv("CONTEST_AI_QUALITY_REVIEW", raising=False)


def _closed_submission(client, category, landing_type):
    deadline = timezone_now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission_id = _submit_with_marker(client, contest, contest["requirements"][0]["id"], dev)
    _close_contest(client, contest, deadline=deadline)
    return submission_id, deadline


def timezone_now():
    from django.utils import timezone

    return timezone.now()


def _run_everything(client) -> None:
    """beat·직접 호출·tick 세 입구를 모두 두드린다."""

    for name in CONTEST_SCANS:
        assert core_tasks.run_scan.run(name) == {"scan": name, "skipped": "disabled"}
        response = client.post(f"/api/internal/scans/{name}", **_internal_headers())
        assert response.status_code == 404
    assert client.post("/api/internal/tick", **_internal_headers()).status_code == 200


def test_the_switch_is_off_when_nothing_is_set(monkeypatch):
    _off(monkeypatch)

    assert SPECS["CONTEST_AI_SCORING"].default == "off"
    assert not contest_ai_scoring_enabled()


@pytest.mark.parametrize("value", ["off", "OFF", "", "아무거나"])
def test_anything_but_on_is_off(monkeypatch, value):
    monkeypatch.setenv("CONTEST_AI_SCORING", value)

    assert not contest_ai_scoring_enabled()


@pytest.mark.django_db
def test_switched_off_contest_scoring_leaves_no_trace(client, category, landing_type, monkeypatch):
    """꺼져 있으면 시도 기록·실패 상한 0%·「입력 없음」 0%·완성도 리뷰가 하나도 생기지 않는다."""

    submission_id, deadline = _closed_submission(client, category, landing_type)
    # 켜져 있었다면 실패 상한으로 0% 가 확정될 조건(시도 5회 + 마감 6시간 뒤)을 만든다.
    for _ in range(5):
        ScoringAttempt.objects.create(submission_id=submission_id, error="RuntimeError: 흉내")
    _freeze(deadline + timedelta(days=2))
    _off(monkeypatch)

    _run_everything(client)

    assert ScoringAttempt.objects.filter(submission_id=submission_id).count() == 5
    assert not Score.objects.exists()
    assert not SubmissionQualityReview.objects.exists()
    assert not QualityReviewAttempt.objects.exists()


@pytest.mark.django_db
def test_switched_off_submission_without_input_is_not_finalized(client, category, landing_type, monkeypatch):
    """「입력 없음」(소스가 스토리지에 없음 등) 0% 도 스캔이 돌아야 생긴다."""

    submission_id, _deadline = _closed_submission(client, category, landing_type)
    from storage.adapters.fake import FakeStorageAdapter

    FakeStorageAdapter._store.clear()  # 소스가 사라진 제출 — 켜져 있으면 시도·확정 경로를 탄다.
    _off(monkeypatch)

    _run_everything(client)

    assert not ScoringAttempt.objects.exists()
    assert not Score.objects.exists()


@pytest.mark.django_db
def test_the_next_scan_follows_the_switch(client, category, landing_type, monkeypatch):
    submission_id, _deadline = _closed_submission(client, category, landing_type)
    _off(monkeypatch)
    assert client.post(RUN_PENDING_URL, **_internal_headers()).status_code == 404

    monkeypatch.setenv("CONTEST_AI_SCORING", "on")
    response = client.post(RUN_PENDING_URL, **_internal_headers())

    assert response.status_code == 200
    assert response.json()["rows"][0]["status"] == "scored"
    assert Score.objects.filter(submission_id=submission_id).exists()


@pytest.mark.django_db
def test_operator_screen_turns_it_on_and_off(monkeypatch, django_capture_on_commit_callbacks):
    _off(monkeypatch)
    su = _client_for("rs_switch", superuser=True)

    assert _save(su, "CONTEST_AI_SCORING", "on", django_capture_on_commit_callbacks).status_code == 200
    assert contest_ai_scoring_enabled()
    assert _save(su, "CONTEST_AI_SCORING", "켜기", django_capture_on_commit_callbacks).status_code == 422
    assert _save(su, "CONTEST_AI_SCORING", "OFF", django_capture_on_commit_callbacks).status_code == 200
    assert not contest_ai_scoring_enabled()
    _clear(su, "CONTEST_AI_SCORING", django_capture_on_commit_callbacks)
    assert not contest_ai_scoring_enabled()


def test_contest_scans_stay_on_the_beat_schedule_while_off(monkeypatch):
    """beat 가 꺼진 채 떠도 화면에서 켜면 다음 실행부터 돈다 — 일정에서 빠지지 않는다."""

    _off(monkeypatch)

    schedule = scans.beat_schedule()

    for name in CONTEST_SCANS:
        assert f"scan:{name}" in schedule
        assert not scans.is_scan_active(name)


def test_other_scans_do_not_follow_the_switch(monkeypatch):
    _off(monkeypatch)

    gated = {
        name
        for name, spec in scans.SCAN_REGISTRY.items()
        if spec.enabled in (contest_ai_scoring_enabled, contest_quality_review_enabled)
    }

    assert gated == set(CONTEST_SCANS)
    assert scans.is_scan_active("classroom-submission-scoring")


def test_the_two_switches_are_independent_and_off_by_default(monkeypatch):
    monkeypatch.delenv("CONTEST_AI_SCORING", raising=False)
    monkeypatch.delenv("CONTEST_AI_QUALITY_REVIEW", raising=False)
    assert SPECS["CONTEST_AI_QUALITY_REVIEW"].default == "off"
    assert not contest_ai_scoring_enabled()
    assert not contest_quality_review_enabled()

    monkeypatch.setenv("CONTEST_AI_QUALITY_REVIEW", "on")
    assert contest_quality_review_enabled()
    assert not contest_ai_scoring_enabled()

    monkeypatch.delenv("CONTEST_AI_QUALITY_REVIEW")
    monkeypatch.setenv("CONTEST_AI_SCORING", "on")
    assert contest_ai_scoring_enabled()
    assert not contest_quality_review_enabled()


def test_each_switch_opens_only_its_own_scan(monkeypatch):
    _off(monkeypatch)
    monkeypatch.setenv("CONTEST_AI_QUALITY_REVIEW", "on")
    assert not scans.is_scan_active("submission-scoring")
    assert scans.is_scan_active("submission-quality-review")

    monkeypatch.delenv("CONTEST_AI_QUALITY_REVIEW")
    monkeypatch.setenv("CONTEST_AI_SCORING", "on")
    assert scans.is_scan_active("submission-scoring")
    assert not scans.is_scan_active("submission-quality-review")
