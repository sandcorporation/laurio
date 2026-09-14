"""채점 키가 거절당한 순간, 강사에게 한 번 알린다 (#356).

핵심 대상: 채점 키 상태가 "거부됨"으로 **바뀌는 그 순간**에만 강사에게
`classroom_scoring_key_rejected` 알림이 하나 간다 — 밀린 제출이 몇 건이든,
스캔이 몇 번을 돌든 한 번이다. 강사가 새 키를 저장했다가 그 키도 거절당하면
다시 한 번 간다. 참여자에게는 절대 가지 않는다.
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from django.test import override_settings

from notifications.models import Notification, NotificationType

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _login(client, uid="instructor-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _create_class(client, access: str, name: str = "웹 스터디") -> int:
    response = client.post(
        CLASSES_URL,
        data={"name": name, "instructor_display_name": "강사"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _set_key(client, access: str, class_id: int, key: str = "sk-test-instructor-key") -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": key},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _create_open_problem(client, access: str, class_id: int) -> tuple[int, int]:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    checklist = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 있다", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert checklist.status_code == 201
    item_id = checklist.json()["id"]

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return problem_id, item_id


def _join_code(client, access: str, class_id: int) -> str:
    detail = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert detail.status_code == 200
    return detail.json()["join_code"]


def _join(client, access: str, join_code: str, display_name: str = "참여자") -> None:
    response = client.post(
        f"/api/classroom/join/{join_code}",
        data={"display_name": display_name},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _submit_repository(client, access: str, class_id: int, problem_id: int, url: str) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": url, "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


class _FakeResponse:
    def __init__(self, status_code: int, json_data=None) -> None:
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self):
        return self._json_data


def _openai_success_body(item_id: int, *, is_met: bool = True) -> dict:
    return {
        "model": "gpt-4o-mini-2024-07-18",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"verdicts": [{"requirement_id": item_id, "is_met": is_met, "reasoning": "판정 근거"}]}
                    )
                },
            }
        ],
    }


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


def _setup_submission(client):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello-world"
    )
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


def _instructor_notifications():
    return Notification.objects.filter(notification_type=NotificationType.CLASSROOM_SCORING_KEY_REJECTED)


def test_rejection_sends_exactly_one_notification_to_the_instructor(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )

    _run_scan(client)

    notifications = list(_instructor_notifications())
    assert len(notifications) == 1
    from django.contrib.auth import get_user_model

    instructor_user_id = get_user_model().objects.get(username="kakao:instructor-1").id
    assert notifications[0].recipient_id == instructor_user_id
    assert notifications[0].context["class_id"] == ctx["class_id"]


def test_repeated_scans_do_not_send_a_second_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )

    _run_scan(client)
    _run_scan(client)
    _run_scan(client)

    assert _instructor_notifications().count() == 1


def test_a_second_submission_piling_up_does_not_send_another_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )
    _run_scan(client)

    _submit_repository(
        client,
        ctx["participant"]["access"],
        ctx["class_id"],
        ctx["problem_id"],
        "https://github.com/octocat/hello-world-again",
    )
    _run_scan(client)

    assert _instructor_notifications().count() == 1


def test_fixing_then_rejecting_again_sends_a_second_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )
    _run_scan(client)
    assert _instructor_notifications().count() == 1

    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(200))
    _set_key(client, ctx["instructor"]["access"], ctx["class_id"], key="sk-new-key-that-also-fails-later")

    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key again"}}),
    )
    _run_scan(client)

    assert _instructor_notifications().count() == 2


def test_never_sent_to_the_participant(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )

    _run_scan(client)

    from django.contrib.auth import get_user_model

    participant_user_id = get_user_model().objects.get(username="kakao:participant-1").id
    assert not _instructor_notifications().filter(recipient_id=participant_user_id).exists()


def test_notification_type_is_in_the_classroom_only_filter():
    from notifications.models import CLASSROOM_NOTIFICATION_TYPES

    assert NotificationType.CLASSROOM_SCORING_KEY_REJECTED in CLASSROOM_NOTIFICATION_TYPES


def test_successful_scoring_does_not_send_the_rejection_notification(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )

    _run_scan(client)

    assert _instructor_notifications().count() == 0
