"""그 키로 쓸 수 없는 채점 모델이면 채점하지 못함으로 남고 이유가 보인다
(#403, CONTEXT.md 「채점 모델」).

핵심 대상: 벤더가 모델을 그 키로 쓸 수 없다고 거부하면(`error.code ==
"model_not_found"`) 그 시도가 「채점하지 못함」으로 남는다 — 재시도하지
않고, 클래스의 채점 키 상태는 바뀌지 않는다(키 거부와 다른 사유다, #355와
대비되는 지점). 강사 화면에는 이유와 채점 모델 설정 링크가, 참여자 화면에는
기존 키 문제 안내와 같은 문구가 보인다. 강사가 모델을 바꾸면 새 시도부터
다시 채점된다.
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from django.test import override_settings

from classroom.models import Class, ClassroomScore, ClassroomScoringAttempt, Problem

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


def _create_open_problem(client, access: str, class_id: int, model: str = "gpt-5-mini") -> tuple[int, int]:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"], "model": model},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201, created.content
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


def _instructor_submissions(client, access: str, class_id: int, problem_id: int) -> list[dict]:
    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions", **_auth_header(access)
    )
    assert response.status_code == 200
    return response.json()


class _FakeResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data


def _model_rejected_body() -> dict:
    return {"error": {"message": "The model `gpt-5` does not exist", "code": "model_not_found"}}


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


def _setup_submission(client, *, model: str = "gpt-5-mini"):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, model=model)
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


@pytest.mark.parametrize("status_code", [400, 404])
def test_model_rejection_does_not_create_a_score(client, db, monkeypatch, status_code):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(status_code, _model_rejected_body())
    )

    result = _run_scan(client)

    assert result["rows"][0]["status"] == "model_rejected"
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_model_rejection_does_not_retry(client, db, monkeypatch):
    """no_key·key_rejected와 같은 규율 — 「아직 시도하지 않았다」로 남아야
    `_scoring_cap_reached`가 이 실패로 상한에 닿지 않는다."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )

    for _ in range(6):
        _run_scan(client)

    assert ClassroomScoringAttempt.objects.filter(submission_id=ctx["submission_id"]).count() == 0
    assert not ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()


def test_model_rejection_leaves_the_class_key_status_untouched(client, db, monkeypatch):
    ctx = _setup_submission(client)
    class_before = Class.objects.get(id=ctx["class_id"]).openai_api_key_status

    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)

    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == class_before
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status != Class.ScoringKeyStatus.REJECTED


def test_model_rejection_marks_the_problem_and_excludes_it_from_the_scan(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)

    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    called = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: called.append(1) or _FakeResponse(200, {})
    )
    result = _run_scan(client)

    assert result["count"] == 0
    assert not called


@pytest.mark.parametrize("status_code", [401, 403])
def test_key_rejection_is_unaffected_regression(client, db, monkeypatch, status_code):
    """키 거부(401·403)는 지금처럼 키 사유로 남는다 — 모델 거부 판정을
    더해도 회귀가 없다."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(status_code, {"error": {"message": "invalid key"}}),
    )

    result = _run_scan(client)

    assert result["rows"][0]["status"] == "key_rejected"
    assert Class.objects.get(id=ctx["class_id"]).openai_api_key_status == Class.ScoringKeyStatus.REJECTED
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is None


def test_instructor_screen_shows_the_model_rejected_reason(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)

    rows = _instructor_submissions(client, ctx["instructor"]["access"], ctx["class_id"], ctx["problem_id"])
    assert rows[0]["status"] == "pending"
    assert rows[0]["pending_reason"] == "model_rejected"


def test_participant_screen_uses_the_existing_could_not_score_reason(client, db, monkeypatch):
    """참여자 화면은 모델 거부를 키 문제와 구별하지 않는다(#403 AC)."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    submission_out = mine["submissions"][0]
    assert submission_out["status"] == "pending"
    assert submission_out["pending_reason"] == "model_rejected"


def test_problem_detail_reports_scoring_model_rejected(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)

    detail = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        **_auth_header(ctx["instructor"]["access"]),
    )
    assert detail.json()["scoring_model_rejected"] is True


def test_changing_the_problems_model_resumes_scoring_for_queued_submissions(client, db, monkeypatch):
    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    patched = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"model": "gpt-4o-mini"},
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )
    assert patched.status_code == 200
    assert patched.json()["scoring_model_rejected"] is False
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is None

    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )
    result = _run_scan(client)

    assert result["count"] == 1
    score = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score.reasoning[0]["is_met"] is True


def test_changing_the_class_default_model_resumes_problems_that_inherit_it(client, db, monkeypatch):
    """문제 자신의 모델이 비어 클래스 기본값을 따르던 경우, 클래스 기본값을
    바꾸면 그 문제도 다시 채점 후보에 든다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5-mini"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    # model=""(클래스 기본값을 따름)인 문제를 연다.
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": "1주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id = created.json()["id"]
    item = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 있다", "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    item_id = item.json()["id"]
    client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submission_id = _submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello-world"
    )["id"]

    import core.llm_scoring as llm_scoring_module

    monkeypatch.setattr(
        llm_scoring_module.requests, "post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)
    assert Problem.objects.get(id=problem_id).scoring_model_rejected_at is not None

    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-4o-mini"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert Problem.objects.get(id=problem_id).scoring_model_rejected_at is None

    monkeypatch.setattr(
        llm_scoring_module.requests, "post", lambda *a, **k: _FakeResponse(200, _openai_success_body(item_id))
    )
    result = _run_scan(client)
    assert result["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=submission_id).exists()


def test_editing_the_title_without_the_model_field_keeps_the_rejection(client, db, monkeypatch):
    """제목만 고쳐 저장해도(#437) 화면이 모델 필드를 보내지 않으면 거부
    표시가 그대로 남는다 — 거부된 모델로 새 시도가 헛되이 다시 채점되지
    않는다."""

    ctx = _setup_submission(client)
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    patched = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"title": "1주차 (고침)"},
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )
    assert patched.status_code == 200
    assert patched.json()["scoring_model_rejected"] is True
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    called = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: called.append(1) or _FakeResponse(200, {})
    )
    result = _run_scan(client)
    assert result["count"] == 0
    assert not called


def test_resending_the_same_model_clears_the_rejection(client, db, monkeypatch):
    """같은 모델 값을 다시 보내면(#437 「이 모델로 다시 시도」) 값이 실제로
    달라지지 않았어도 거부 표시가 풀린다 — "설정을 확인했다"는 사실 자체가
    재시도 트리거다(기존 #403 규칙, 화면이 이 요청을 쓰는 경로가 새로
    생겼을 뿐이다)."""

    ctx = _setup_submission(client, model="gpt-5-mini")
    monkeypatch.setattr(
        "core.llm_scoring.requests.post", lambda *a, **k: _FakeResponse(404, _model_rejected_body())
    )
    _run_scan(client)
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is not None

    patched = client.patch(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{ctx['problem_id']}",
        data={"model": "gpt-5-mini"},
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )
    assert patched.status_code == 200
    assert patched.json()["scoring_model_rejected"] is False
    assert Problem.objects.get(id=ctx["problem_id"]).scoring_model_rejected_at is None

    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )
    result = _run_scan(client)
    assert result["count"] == 1
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).exists()
