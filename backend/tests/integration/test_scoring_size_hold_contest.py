"""공모전 「크기 초과」 보류의 뒤처리(#989 A2) — 보류가 정해질 때 알리고, 유료는 보류 중에도 이의를 받고,
심사 종료 때 자동 0%(`source_too_large`)가 된다. 시임은 마운트된 HTTP API 와 스캔 엔드포인트다."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Contest
from notifications.models import Notification, NotificationType
from notifications.rendering import render_message
from scoring import services
from scoring.models import Score
from submissions.scoring_basis import SOURCE_TOO_LARGE_MODEL_VERSION
from tests.integration.test_appeals import OPERATOR_APPEALS_URL, _operator_client
from tests.integration.test_scoring import (  # noqa: F401 - fixture 들을 이 모듈에도 등록한다.
    _auth_header,
    _close_contest,
    _freeze,
    _internal_headers,
    _publish_contest,
    _run_pending,
    _submit_with_marker,
    _verified_user,
    category,
    landing_type,
)
from tests.integration.test_scoring_source_hold import _MustNotBeCalled, _tiny_budget

EXPIRY_URL = "/api/internal/scans/scoring-size-hold-expiry"


def _held_submission(client, category, landing_type, monkeypatch):
    deadline = timezone.now() + timedelta(hours=1)
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
    _tiny_budget(monkeypatch)
    monkeypatch.setattr(services, "get_adapter", lambda *, timeout=None: _MustNotBeCalled())
    assert _run_pending(client)["rows"][0]["status"] == "held"
    return submission_id, dev, Contest.objects.get(id=contest["id"])


@pytest.mark.django_db
def test_the_participant_is_told_once_when_the_hold_is_decided(client, category, landing_type, monkeypatch):
    submission_id, dev, contest = _held_submission(client, category, landing_type, monkeypatch)

    notes = Notification.objects.filter(
        recipient_id=dev["user_id"], notification_type=NotificationType.SCORING_HELD_SIZE
    )
    assert notes.count() == 1
    note = notes.get()
    assert note.context["submission_id"] == submission_id
    assert note.context["is_free"] is False
    message = render_message(note)
    assert "채점 한도를 넘어 채점이 보류되었습니다" in message
    assert "필수 요건 전체 미달(0점)" in message
    assert "이의를 신청할 수 있습니다" in message


def test_free_contest_hold_message_points_to_the_contact_not_an_appeal(settings):
    settings.PUBLIC_SUPPORT_EMAIL = ""

    note = Notification(
        notification_type=NotificationType.SCORING_HELD_SIZE,
        context={"contest_title": "무료전", "is_free": True, "judging_ends_at": "2026-11-30T09:00:00+00:00"},
    )

    message = render_message(note)

    assert "심사 종료(11월 30일 18:00) 때 0점으로 처리됩니다" in message
    assert "문의처" in message
    assert "이의" not in message


@pytest.mark.django_db
def test_paid_held_submission_can_be_appealed_before_judging_ends(client, category, landing_type, monkeypatch):
    submission_id, dev, _contest = _held_submission(client, category, landing_type, monkeypatch)
    auth = _auth_header(dev["access"])

    assert client.get(f"/api/submissions/{submission_id}/score", **auth).status_code == 404
    hold = client.get(f"/api/submissions/{submission_id}/scoring-hold", **auth)
    assert hold.status_code == 200, hold.content
    assert hold.json()["can_appeal"] is True
    assert hold.json()["is_free"] is False

    created = client.post(
        f"/api/submissions/{submission_id}/appeal",
        data={"reason": "앱 코드는 작습니다 — 생성물이 커서 넘친 것 같습니다"},
        content_type="application/json",
        **auth,
    )
    assert created.status_code == 201, created.content
    assert client.get(f"/api/submissions/{submission_id}/scoring-hold", **auth).json()["can_appeal"] is False

    operator = _operator_client()
    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{created.json()['id']}")
    assert detail.status_code == 200, detail.content
    assert detail.json()["score"] is None


@pytest.mark.django_db
def test_unscored_submission_that_is_not_held_still_cannot_be_appealed(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
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
    auth = _auth_header(dev["access"])

    assert client.get(f"/api/submissions/{submission_id}/scoring-hold", **auth).status_code == 404
    response = client.post(
        f"/api/submissions/{submission_id}/appeal",
        data={"reason": "아직 채점 전"},
        content_type="application/json",
        **auth,
    )
    assert response.status_code == 409


@pytest.mark.django_db
def test_hold_becomes_an_automatic_zero_when_judging_ends(client, category, landing_type, monkeypatch):
    submission_id, dev, contest = _held_submission(client, category, landing_type, monkeypatch)
    auth = _auth_header(dev["access"])

    _freeze(contest.judging_ends_at - timedelta(minutes=1))
    assert client.post(EXPIRY_URL, **_internal_headers()).json()["rows"] == []
    assert not Score.objects.filter(submission_id=submission_id).exists()

    _freeze(contest.judging_ends_at + timedelta(minutes=1))
    rows = client.post(EXPIRY_URL, **_internal_headers()).json()["rows"]
    assert [row["submission_id"] for row in rows] == [submission_id]
    assert client.post(EXPIRY_URL, **_internal_headers()).json()["rows"] == []

    score = Score.objects.get(submission_id=submission_id)
    assert score.percentage == 0
    assert score.model_version == SOURCE_TOO_LARGE_MODEL_VERSION
    own = client.get(f"/api/submissions/{submission_id}/score", **auth).json()
    assert own["scoring_basis"] == "source_too_large"
    assert own["can_appeal"] is False
    # 이의 창이 닫힌 뒤라 「이의 기간이 시작됩니다」 채점 완료 알림은 보내지 않는다.
    assert not Notification.objects.filter(
        recipient_id=dev["user_id"], notification_type=NotificationType.SCORING_COMPLETE
    ).exists()


def test_free_contest_hold_message_carries_the_support_address_when_configured(settings):
    settings.PUBLIC_SUPPORT_EMAIL = "help@example.test"
    note = Notification(
        notification_type=NotificationType.SCORING_HELD_SIZE,
        context={"contest_title": "무료전", "is_free": True, "judging_ends_at": "2026-11-30T09:00:00+00:00"},
    )

    assert "문의처(help@example.test)로 알려 주세요" in render_message(note)
