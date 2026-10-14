"""채점 사용량 — 클래스가 지금까지 쓴 토큰을 센다(#629, ADR-0060).

누적 토큰 상한(#295)은 걷어냈다: 누적 사용량이 아무리 커도 채점은 멈추지 않는다. 멈추는
사유는 키·모델·크레딧·서버뿐이고(`classroom.pending_scoring`), 지출의 진짜 상한은
OpenAI 쪽(프로젝트 한도·크레딧, #586)에 있다. 사용량(`token_usage_total`)과 그
가운데 어림한 몫(`token_usage_estimated`, #604)은 강사 화면(`ClassOut`)에 보인다.
"""

from __future__ import annotations

import pytest
from django.test import override_settings

from classroom.models import Class, ClassroomScore
from notifications.models import NotificationType
from tests.classroom_scenarios import respond_with_verdict

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    # 실물 OpenAIScoringAdapter 경로가 usage 를 읽는다 — 기본값(fake)은 그 경로를 안
    # 탄다(#340, ADR-0043). 벤더 응답은 respond_with_verdict(#469)로 흉내 낸다.
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


def _setup_submission(client, *, url="https://github.com/octocat/hello-world"):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit_repository(client, participant["access"], class_id, problem_id, url)
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


_BUDGET_KEYS = {
    "token_budget",
    "token_budget_warning_threshold_percent",
    "token_budget_remaining",
    "token_budget_exhausted",
}


def test_class_shows_usage_and_no_budget(client, db):
    instructor = _login(client)
    class_id = _create_class(client, instructor["access"])

    shown = _get_class(client, instructor["access"], class_id)

    assert shown["token_usage_total"] == 0
    assert shown["token_usage_estimated"] == 0
    assert not _BUDGET_KEYS & shown.keys()


def test_scoring_success_accumulates_usage_on_the_class(client, db, monkeypatch):
    ctx = _setup_submission(client)
    respond_with_verdict(monkeypatch, ctx["item_id"], total_tokens=120)

    _run_scan(client)

    updated = _get_class(client, ctx["instructor"]["access"], ctx["class_id"])
    assert updated["token_usage_total"] == 120
    assert updated["token_usage_estimated"] == 0


def test_large_usage_does_not_stop_scoring(client, db, monkeypatch):
    ctx = _setup_submission(client)
    Class.objects.filter(id=ctx["class_id"]).update(token_usage_total=10**9)
    respond_with_verdict(monkeypatch, ctx["item_id"], total_tokens=10)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    assert mine["submissions"][0]["pending_reason"] is None

    scanned = _run_scan(client)

    assert scanned["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
    assert _get_class(client, ctx["instructor"]["access"], ctx["class_id"])["token_usage_total"] == 10**9 + 10


def test_budget_fields_are_not_accepted_by_class_settings(client, db):
    instructor = _login(client)
    class_id = _create_class(client, instructor["access"])

    shown = _patch_class(client, instructor["access"], class_id, {"token_budget": 100})

    assert not _BUDGET_KEYS & shown.keys()


def test_there_is_no_budget_warning_notification_type():
    assert not [value for value in NotificationType.values if "budget" in value]
