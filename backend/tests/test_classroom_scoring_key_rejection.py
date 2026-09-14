"""채점 중 키가 거절당해도 참여자가 0%를 받지 않는다 (#355, ADR-0045).

핵심 대상: 채점이 벤더에게 401·403을 받으면 `ClassroomScore`를 만들지 않고,
그 클래스의 채점 키 상태를 "거부됨"으로 바꾸며, 채점 스캔의 후보에서 그
클래스를 뺀다. 강사가 새 키를 저장하면(#354의 검증을 통과하거나 미검증으로
저장되면) 상태가 덮이고 밀려 있던 제출물이 다시 채점된다. 401·403 밖의
영구 실패는 이 티켓이 건드리지 않는다 — 그 고정은 `test_classroom_scoring.py`
의 `test_non_auth_permanent_failure_still_finalizes_immediately`가 맡는다.

공모전 채점(`scoring` 앱)은 이 파일의 대상이 아니다 — ADR-0037의 경계 안에서
의도된 비대칭이다.
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from django.test import override_settings

from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt

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


def _mine(client, access: str, class_id: int, problem_id: int) -> dict:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/mine", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


def _class_detail(client, access: str, class_id: int) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(access))
    assert response.status_code == 200
    return response.json()


class _FakeResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data

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


@pytest.mark.parametrize("status_code", [401, 403])
def test_rejected_key_does_not_create_a_score(client, db, monkeypatch, status_code):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(status_code, {"error": {"message": "invalid key"}}),
    )

    result = _run_scan(client)

    assert result["rows"][0]["status"] == "key_rejected"
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_rejected_key_marks_the_class_status(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )

    _run_scan(client)

    class_obj = Class.objects.get(id=ctx["class_id"])
    assert class_obj.openai_api_key_status == Class.ScoringKeyStatus.REJECTED


def test_rejected_key_leaves_no_scoring_attempt_history(client, db, monkeypatch):
    """no_key와 같은 규율 — "아직 시도하지 않았다"로 남아야 `_scoring_cap_reached`가
    이 실패로 상한에 닿지 않는다."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )

    for _ in range(6):
        _run_scan(client)

    assert ClassroomScoringAttempt.objects.filter(submission_id=ctx["submission_id"]).count() == 0
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_rejected_class_is_excluded_from_the_scan_candidates(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )
    _run_scan(client)

    called = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: called.append(1) or _FakeResponse(200, {})
    )
    result = _run_scan(client)

    assert result["count"] == 0
    assert not called


def test_participant_screen_does_not_distinguish_rejected_from_missing_key(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )
    _run_scan(client)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] == "no_api_key"


def test_saving_a_new_valid_key_resumes_scoring_for_the_queued_submission(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )
    _run_scan(client)
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == Class.ScoringKeyStatus.REJECTED

    monkeypatch.setattr("core.llm_scoring.requests.get", lambda *a, **k: _FakeResponse(200, {}))
    _set_key(client, ctx["instructor"]["access"], ctx["class_id"], key="sk-new-good-key")
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == Class.ScoringKeyStatus.VERIFIED

    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )
    result = _run_scan(client)

    assert result["count"] == 1
    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.reasoning[0]["is_met"] is True


def test_instructor_class_detail_distinguishes_rejected_from_missing(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(401, {"error": {"message": "invalid key"}}),
    )
    _run_scan(client)

    body = _class_detail(client, ctx["instructor"]["access"], ctx["class_id"])
    assert body["has_openai_key"] is True
    assert body["openai_key_status"] == "rejected"
