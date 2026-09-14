"""추론 모델엔 추론 강도를 정하고 그 강도로 채점된다 (#402, CONTEXT.md
「추론 강도」).

핵심 대상: 채점 모델이 추론 모델(GPT-5 이후)일 때만 뜻이 있는 추론 강도를
클래스 기본값·문제별로 두고, 채점 호출이 추론 모델이면 temperature 대신
그 강도를 보낸다 — 4.1·4o는 지금처럼 temperature 0 그대로다. 복사·템플릿은
이 값을 옮기지 않는다. 공모전 채점(`scoring` 앱)은 이 티켓의 영향을 받지
않는다(`test_openai_scoring_adapter.py`가 그대로 초록인 것으로 고정된다).
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from django.test import override_settings

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


def _create_problem(client, access: str, class_id: int, **extra) -> dict:
    payload = {"title": "1주차", "submission_formats": ["source"]}
    payload.update(extra)
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _create_open_problem(client, access: str, class_id: int, **extra) -> tuple[int, int]:
    problem = _create_problem(client, access, class_id, submission_formats=["repository"], **extra)
    problem_id = problem["id"]
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
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data

    def json(self):
        return self._json_data


def _openai_success_body(item_id: int) -> dict:
    return {
        "model": "gpt-5-mini-2026-01-01",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"verdicts": [{"requirement_id": item_id, "is_met": True, "reasoning": "판정 근거"}]}
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


def _setup_submission(client, *, model: str, reasoning_effort: str = "") -> dict:
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    problem_id, item_id = _create_open_problem(
        client, instructor["access"], class_id, model=model, reasoning_effort=reasoning_effort
    )
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submitted = _submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello-world"
    )
    return {
        "instructor": instructor,
        "class_id": class_id,
        "problem_id": problem_id,
        "item_id": item_id,
        "submission_id": submitted["id"],
    }


# --- 저장 검증 --------------------------------------------------------------------


def test_class_default_reasoning_effort_defaults_to_low(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"]))
    assert response.json()["default_reasoning_effort"] == "low"


def test_instructor_changes_the_class_default_reasoning_effort(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_reasoning_effort": "high"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    assert response.json()["default_reasoning_effort"] == "high"


def test_unknown_class_default_reasoning_effort_is_rejected(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])

    response = client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_reasoning_effort": "extreme"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_a_new_problem_inherits_the_class_default_reasoning_effort(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_reasoning_effort": "medium"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    problem = _create_problem(client, pair["access"], class_id)

    response = client.get(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}", **_auth_header(pair["access"])
    )
    body = response.json()
    assert body["reasoning_effort"] == ""
    assert body["effective_reasoning_effort"] == "medium"


def test_instructor_overrides_a_problems_reasoning_effort(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem = _create_problem(client, pair["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}",
        data={"reasoning_effort": "high"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reasoning_effort"] == "high"
    assert body["effective_reasoning_effort"] == "high"


def test_unknown_problem_reasoning_effort_is_rejected(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem = _create_problem(client, pair["access"], class_id)

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}",
        data={"reasoning_effort": "extreme"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 422


def test_clearing_a_problems_reasoning_effort_override_falls_back_to_class_default(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    problem = _create_problem(client, pair["access"], class_id)
    client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}",
        data={"reasoning_effort": "high"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    response = client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem['id']}",
        data={"reasoning_effort": ""},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["reasoning_effort"] == ""
    assert body["effective_reasoning_effort"] == "low"


def test_is_reasoning_flags_are_reported_on_class_and_problem(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    _set_key(client, pair["access"], class_id)

    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_model": "gpt-5-mini"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    class_body = client.get(f"{CLASSES_URL}/{class_id}", **_auth_header(pair["access"])).json()
    assert class_body["default_model_is_reasoning"] is True

    problem = _create_problem(client, pair["access"], class_id, model="gpt-4o")
    assert problem["effective_model_is_reasoning"] is False


# --- 채점 호출 --------------------------------------------------------------------


def test_reasoning_model_request_omits_temperature_and_sends_reasoning_effort(client, db, monkeypatch):
    ctx = _setup_submission(client, model="gpt-5-mini", reasoning_effort="high")
    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k) or _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )

    _run_scan(client)

    payload = sent[0]["json"]
    assert "temperature" not in payload
    assert payload["reasoning_effort"] == "high"
    assert payload["model"] == "gpt-5-mini"
    # 고정 지시(한국어 근거)와 Structured Outputs는 그대로다.
    messages = {m["role"]: m["content"] for m in payload["messages"]}
    assert "한국어" in messages["system"]
    assert payload["response_format"]["type"] == "json_schema"


def test_reasoning_model_falls_back_to_the_class_default_reasoning_effort(client, db, monkeypatch):
    """문제가 자기 추론 강도를 갖지 않으면 클래스 기본값을 쓴다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_reasoning_effort": "medium"},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    problem_id, item_id = _create_open_problem(client, instructor["access"], class_id, model="gpt-5-mini")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    submission_id = _submit_repository(
        client, participant["access"], class_id, problem_id, "https://github.com/octocat/hello-world"
    )["id"]

    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k) or _FakeResponse(200, _openai_success_body(item_id)),
    )
    _run_scan(client)

    assert sent[0]["json"]["reasoning_effort"] == "medium"


def test_non_reasoning_model_request_is_unchanged(client, db, monkeypatch):
    ctx = _setup_submission(client, model="gpt-4.1", reasoning_effort="high")
    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k) or _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )

    _run_scan(client)

    payload = sent[0]["json"]
    assert payload["temperature"] == 0
    assert "reasoning_effort" not in payload


def test_classroom_scoring_requests_use_a_longer_timeout(client, db, monkeypatch):
    """강의실 채점은 워커 작업이라 beat의 30초 제약과 무관하다(모듈 docstring)
    — 공모전이 쓰는 20초 기본값보다 넉넉해야 한다."""

    ctx = _setup_submission(client, model="gpt-4.1")
    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k) or _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )

    _run_scan(client)

    assert sent[0]["timeout"] > 20


# --- 공모전 채점 불변 --------------------------------------------------------------


def test_contest_adapter_default_construction_still_sends_temperature(monkeypatch):
    """`reasoning_effort`를 주지 않으면 지금 동작 그대로다 — 공모전 어댑터는
    이 인자를 한 번도 넘기지 않는다."""

    from scoring.adapters import OpenAIScoringAdapter, RequirementInput, ScoringInput

    monkeypatch.setenv("OPEN_AI_API_KEY", "sk-contest-key")
    sent = []

    def fake_post(url, headers=None, json=None, timeout=None):
        sent.append(json)
        return _FakeResponse(
            200,
            {
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": '{"verdicts": [{"requirement_id": 1, "is_met": true, "reasoning": "ok"}]}'
                        },
                    }
                ],
            },
        )

    monkeypatch.setattr("scoring.adapters.requests.post", fake_post)

    adapter = OpenAIScoringAdapter()
    adapter.score(
        ScoringInput(
            submission_id=1,
            contest_id=1,
            prompt="프롬프트",
            source_files=[],
            requirements=[
                RequirementInput(
                    requirement_id=1, text="req", grade="필수", self_reported_met=False, evidence=[]
                )
            ],
        )
    )

    assert "reasoning_effort" not in sent[0]
    assert sent[0]["temperature"] == 0


# --- 복사·템플릿은 추론 강도를 옮기지 않는다 --------------------------------------


def test_copying_a_problem_does_not_carry_the_reasoning_effort(client, db):
    pair = _login(client)
    source_class_id = _create_class(client, pair["access"], name="원본 클래스")
    target_class_id = _create_class(client, pair["access"], name="대상 클래스")
    problem = _create_problem(client, pair["access"], source_class_id, reasoning_effort="high")
    assert problem["reasoning_effort"] == "high"

    copied = client.post(
        f"{CLASSES_URL}/{source_class_id}/problems/{problem['id']}/copy",
        data={"target_class_id": target_class_id},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert copied.status_code == 201
    assert copied.json()["reasoning_effort"] == ""


def test_copying_a_class_does_not_carry_the_default_reasoning_effort(client, db):
    pair = _login(client)
    class_id = _create_class(client, pair["access"])
    client.patch(
        f"{CLASSES_URL}/{class_id}",
        data={"default_reasoning_effort": "high"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )

    copied = client.post(f"{CLASSES_URL}/{class_id}/copy", **_auth_header(pair["access"]))
    assert copied.status_code == 201
    assert copied.json()["default_reasoning_effort"] == "low"


def test_importing_a_problem_template_does_not_carry_the_reasoning_effort(client, db):
    pair = _login(client)
    source_class_id = _create_class(client, pair["access"], name="원본 클래스")
    problem = _create_problem(client, pair["access"], source_class_id, reasoning_effort="high")

    published = client.post(
        f"{CLASSES_URL}/{source_class_id}/problems/{problem['id']}/publish-template",
        data={"publisher_display_name": "공유 강사"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert published.status_code in (200, 201), published.content
    share_code = published.json()["share_code"]

    target_class_id = _create_class(client, pair["access"], name="가져오는 클래스")
    imported = client.post(
        f"/api/classroom/problem-templates/{share_code}/import",
        data={"target_class_id": target_class_id},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert imported.status_code == 201, imported.content
    assert imported.json()["reasoning_effort"] == ""
