"""채점 키가 거절당한 순간, 강사에게 한 번 알린다 (#356).

핵심 대상: 채점 키 상태가 "거부됨"으로 **바뀌는 그 순간**에만 강사에게
`classroom_scoring_key_rejected` 알림이 하나 간다 — 밀린 제출이 몇 건이든,
스캔이 몇 번을 돌든 한 번이다. 강사가 새 키를 저장했다가 그 키도 거절당하면
다시 한 번 간다. 참여자에게는 절대 가지 않는다.

**공용 시나리오 빌더(#433, #469) 위로 옮겼다** — `tests/classroom_scenarios.py` 참고.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model

from notifications.models import CLASSROOM_NOTIFICATION_TYPES, Notification, NotificationType
from tests.classroom_scenarios import (
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    respond_to_models_endpoint,
    respond_with_key_rejection,
    respond_with_verdict,
    run_scan,
    set_key,
    submit_repository,
    user_id,
)


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with force_real_scoring_adapter():
        yield


def _setup_submission(client):
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    participant = login(client, uid="participant-1")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"])
    submitted = submit_repository(
        client, participant["access"], class_id, problem.id, "https://github.com/octocat/hello-world"
    )
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem.id,
        "item_id": problem.item_id,
        "submission_id": submitted["id"],
    }


def _instructor_notifications():
    return Notification.objects.filter(notification_type=NotificationType.CLASSROOM_SCORING_KEY_REJECTED)


def test_rejection_sends_exactly_one_notification_to_the_instructor(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)

    run_scan(client)

    notifications = list(_instructor_notifications())
    assert len(notifications) == 1
    assert notifications[0].recipient_id == user_id("instructor-1")
    assert notifications[0].context["class_id"] == ctx["class_id"]


def test_repeated_scans_do_not_send_a_second_notification(client, db, monkeypatch):
    _setup_submission(client)
    respond_with_key_rejection(monkeypatch)

    run_scan(client)
    run_scan(client)
    run_scan(client)

    assert _instructor_notifications().count() == 1


def test_a_second_submission_piling_up_does_not_send_another_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)
    run_scan(client)

    submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world-again",
    )
    run_scan(client)

    assert _instructor_notifications().count() == 1


def test_fixing_then_rejecting_again_sends_a_second_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_key_rejection(monkeypatch)
    run_scan(client)
    assert _instructor_notifications().count() == 1

    respond_to_models_endpoint(monkeypatch)
    set_key(client, ctx["instructor"]["access"], ctx["class_id"], "sk-new-key-that-also-fails-later")

    respond_with_key_rejection(monkeypatch, message="invalid key again")
    run_scan(client)

    assert _instructor_notifications().count() == 2


def test_never_sent_to_the_participant(client, db, monkeypatch):
    _setup_submission(client)
    respond_with_key_rejection(monkeypatch)

    run_scan(client)

    participant_user_id = get_user_model().objects.get(username="kakao:participant-1").id
    assert not _instructor_notifications().filter(recipient_id=participant_user_id).exists()


def test_notification_type_is_in_the_classroom_only_filter():
    assert NotificationType.CLASSROOM_SCORING_KEY_REJECTED in CLASSROOM_NOTIFICATION_TYPES


def test_successful_scoring_does_not_send_the_rejection_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], is_met=True)

    run_scan(client)

    assert _instructor_notifications().count() == 0
