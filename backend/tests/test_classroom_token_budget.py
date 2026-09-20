"""토큰 예산이 바닥나기 전에 알리고, 바닥나면 채점을 멈춘다 (#295,
CONTEXT.md 「강의실」, ADR-0037).

핵심 대상: 강사가 클래스의 예산 한도와 경고 임계를 정하고, 임계에 닿으면
서비스 내부 알림이 강사에게 가고, 한도에 닿으면 새 채점이 시작되지 않되
제출은 계속 쌓인다. 참여자 화면은 「채점 대기」와 그 이유를 말하고, 예산을
채우면 쌓인 시도부터 순서대로 이어서 채점된다. 사용량과 남은 양은 강사
화면(`ClassOut`)에 보인다.
"""

from __future__ import annotations

import pytest
from django.contrib.auth import get_user_model
from django.test import override_settings

from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt
from notifications.models import Notification, NotificationType
from tests.classroom_scenarios import respond_with_verdict, track_vendor_calls

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    # 이 파일은 실물 OpenAIScoringAdapter 경로 자체를 검증한다 —
    # CLASSROOM_SCORING_ADAPTER_MODE 기본값(fake)이 그 경로를 안 타므로
    # 강제한다(#340, ADR-0043). 벤더 응답은 respond_with_verdict(#469,
    # tests.classroom_scenarios)로 흉내 낸다.
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


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


def _create_open_problem(client, access: str, class_id: int, submission_format: str = "repository"):
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": [submission_format]},
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


def _mine(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


def _get_class(client, access: str, class_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert response.status_code == 200
    return response.json()


def _patch_class(client, access: str, class_id: int, payload: dict) -> dict:
    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content
    return response.json()


def _run_scan(client) -> dict:
    from django.conf import settings

    response = client.post(
        SCAN_URL, content_type="application/json", HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN
    )
    assert response.status_code == 200, response.content
    return response.json()


def _setup_submission(client, *, submission_format="repository"):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, submission_format)
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


def test_instructor_sets_budget_and_warning_threshold(client, db):
    instructor = _login(client)
    class_id = _create_class(client, instructor["access"])

    before = _get_class(client, instructor["access"], class_id)
    assert before["token_budget"] is None
    assert before["token_usage_total"] == 0
    assert before["token_budget_remaining"] is None
    assert before["token_budget_exhausted"] is False

    updated = _patch_class(
        client,
        instructor["access"],
        class_id,
        {"token_budget": 1000, "token_budget_warning_threshold_percent": 50},
    )
    assert updated["token_budget"] == 1000
    assert updated["token_budget_warning_threshold_percent"] == 50
    assert updated["token_budget_remaining"] == 1000


def test_scoring_success_accumulates_usage_on_the_class(client, db, monkeypatch):
    ctx = _setup_submission(client)
    _patch_class(client, ctx["instructor"]["access"], ctx["class_id"], {"token_budget": 1000})
    respond_with_verdict(monkeypatch, ctx["item_id"], total_tokens=120)

    _run_scan(client)

    updated = _get_class(client, ctx["instructor"]["access"], ctx["class_id"])
    assert updated["token_usage_total"] == 120
    assert updated["token_budget_remaining"] == 880


def test_warning_notification_fires_when_threshold_crossed(client, db, monkeypatch):
    ctx = _setup_submission(client)
    _patch_class(
        client,
        ctx["instructor"]["access"],
        ctx["class_id"],
        {"token_budget": 100, "token_budget_warning_threshold_percent": 50},
    )
    respond_with_verdict(monkeypatch, ctx["item_id"], total_tokens=60)

    _run_scan(client)

    instructor_user_id = get_user_model().objects.get(username="kakao:instructor-1").id
    notifications = Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING
    )
    assert notifications.count() == 1
    notification = notifications.get()
    assert notification.recipient_id == instructor_user_id
    assert notification.context["class_id"] == ctx["class_id"]


def test_warning_notification_does_not_fire_below_threshold(client, db, monkeypatch):
    ctx = _setup_submission(client)
    _patch_class(
        client,
        ctx["instructor"]["access"],
        ctx["class_id"],
        {"token_budget": 100, "token_budget_warning_threshold_percent": 80},
    )
    respond_with_verdict(monkeypatch, ctx["item_id"], total_tokens=60)

    _run_scan(client)

    assert not Notification.objects.filter(
        notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING
    ).exists()


def test_warning_notification_fires_only_once_per_budget_cycle(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    _patch_class(
        client, instructor["access"], class_id, {"token_budget": 1000, "token_budget_warning_threshold_percent": 50}
    )
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    respond_with_verdict(monkeypatch, item_id, total_tokens=600)

    _submit_repository(client, participant["access"], class_id, problem_id, "https://github.com/a/one")
    _run_scan(client)
    _submit_repository(client, participant["access"], class_id, problem_id, "https://github.com/a/two")
    _run_scan(client)

    assert (
        Notification.objects.filter(
            notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING
        ).count()
        == 1
    )


def test_budget_reached_stops_new_scoring_but_submission_is_still_accepted(client, db, monkeypatch):
    ctx = _setup_submission(client)
    Class.objects.filter(id=ctx["class_id"]).update(token_budget=100, token_usage_total=100)

    calls = track_vendor_calls(monkeypatch)

    result = _run_scan(client)

    assert result["count"] == 0
    assert not calls
    assert ClassroomScore.objects.count() == 0
    assert ClassroomScoringAttempt.objects.count() == 0

    # 멈춘 동안에도 제출은 계속 쌓인다(AC).
    second = _submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"], "https://github.com/octocat/second"
    )
    assert second["status"] == "pending"
    assert second["pending_reason"] == "budget_exhausted"


def test_participant_screen_shows_pending_reason_when_budget_exhausted(client, db):
    ctx = _setup_submission(client)
    Class.objects.filter(id=ctx["class_id"]).update(token_budget=100, token_usage_total=100)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])

    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] == "budget_exhausted"


def test_participant_screen_has_no_pending_reason_when_budget_is_fine(client, db):
    ctx = _setup_submission(client)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])

    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] is None


def test_refilling_the_budget_resumes_scoring_for_queued_attempts(client, db, monkeypatch):
    ctx = _setup_submission(client)
    Class.objects.filter(id=ctx["class_id"]).update(token_budget=100, token_usage_total=100)

    respond_with_verdict(monkeypatch, ctx["item_id"], total_tokens=10)

    blocked = _run_scan(client)
    assert blocked["count"] == 0

    _patch_class(client, ctx["instructor"]["access"], ctx["class_id"], {"token_budget": 1000})

    resumed = _run_scan(client)
    assert resumed["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_repatching_the_same_budget_does_not_reopen_the_warning_cycle(client, db, monkeypatch):
    ctx = _setup_submission(client)
    _patch_class(
        client,
        ctx["instructor"]["access"],
        ctx["class_id"],
        {"token_budget": 100, "token_budget_warning_threshold_percent": 50},
    )
    respond_with_verdict(monkeypatch, ctx["item_id"], total_tokens=60)
    _run_scan(client)
    assert (
        Notification.objects.filter(
            notification_type=NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING
        ).count()
        == 1
    )

    # 같은 값을 다시 보내는 것은 "새 주기"가 아니다 — 경고가 다시 뜨지 않는다.
    _patch_class(client, ctx["instructor"]["access"], ctx["class_id"], {"token_budget": 100})
    class_obj = Class.objects.get(id=ctx["class_id"])
    assert class_obj.token_budget_warning_sent_at is not None
