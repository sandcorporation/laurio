"""강사가 고른 채점 지침으로 채점된다 (#386, 부모 #385, CONTEXT.md 「채점 지침」).

핵심 대상: Problem이 채점 지침을 두 칸(단계·직접 입력 문장)으로 가지고,
만들기·편집 API가 그 두 칸을 받아 강사용 응답에 싣는다. 잘못된 값(모르는
단계, 빈 직접 입력 문장, 상한을 넘는 문장)은 422다. 채점 프롬프트에는 그
문제의 지침 문장이 실리고(직접 입력이면 강사의 문장), 모든 requirement_id
판정·한국어 근거라는 고정 지시는 그대로 남는다. 지침을 바꿔도 이미 매긴
판정은 조회에서 그대로다(ADR-0006).

**벤더로 나가는 요청을 가로채는 방식은 `test_classroom_scoring.py`와 같다** —
`CLASSROOM_SCORING_ADAPTER_MODE`를 `OpenAIScoringAdapter`로 강제하고
`core.llm_scoring.requests.post`를 monkeypatch한다.
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from django.test import override_settings

from classroom.models import ClassroomScore, Problem

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


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


def _create_problem(client, access: str, class_id: int, **overrides):
    payload = {
        "title": "1주차",
        "description": "",
        "submission_formats": ["source"],
    }
    payload.update(overrides)
    return client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


def _patch_problem(client, access: str, class_id: int, problem_id: int, **payload):
    return client.patch(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


# --- 저장·검증 -----------------------------------------------------------------


def test_a_new_problem_defaults_to_normal(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(client, access, class_id)

    assert response.status_code == 201
    body = response.json()
    assert body["grading_strictness"] == "normal"
    assert body["grading_guideline_text"] == ""


def test_a_problem_can_pick_strict_while_being_created(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(client, access, class_id, grading_strictness="strict")

    assert response.status_code == 201
    body = response.json()
    assert body["grading_strictness"] == "strict"
    assert Problem.objects.get(pk=body["id"]).grading_strictness == "strict"


def test_a_custom_guideline_carries_its_sentence(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    sentence = "함수 이름은 solve 여야 하지만 출력 형식은 자유롭게 판정한다."

    response = _create_problem(
        client, access, class_id, grading_strictness="custom", grading_guideline_text=sentence
    )

    assert response.status_code == 201
    body = response.json()
    assert body["grading_strictness"] == "custom"
    assert body["grading_guideline_text"] == sentence
    assert Problem.objects.get(pk=body["id"]).grading_guideline_text == sentence


def test_a_preset_strictness_discards_any_sent_custom_text(client, db):
    """저장 형태(#385 Implementation Decisions) — 문장은 직접 입력일 때만
    비어 있지 않다. 다른 단계를 고르면서 문장을 함께 보내도 저장되지 않는다."""

    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(
        client,
        access,
        class_id,
        grading_strictness="lenient",
        grading_guideline_text="이 문장은 저장되지 않아야 한다",
    )

    assert response.status_code == 201
    assert response.json()["grading_guideline_text"] == ""


def test_an_unknown_strictness_is_rejected_and_nothing_is_created(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(client, access, class_id, grading_strictness="harsh")

    assert response.status_code == 422
    assert Problem.objects.filter(classroom_id=class_id).count() == 0


def test_custom_strictness_with_an_empty_sentence_is_rejected(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(
        client, access, class_id, grading_strictness="custom", grading_guideline_text="   "
    )

    assert response.status_code == 422
    assert Problem.objects.filter(classroom_id=class_id).count() == 0


def test_a_sentence_over_the_length_cap_is_rejected(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)

    response = _create_problem(
        client, access, class_id, grading_strictness="custom", grading_guideline_text="가" * 501
    )

    assert response.status_code == 422
    assert Problem.objects.filter(classroom_id=class_id).count() == 0


def test_editing_can_change_the_strictness(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    problem_id = _create_problem(client, access, class_id).json()["id"]

    response = _patch_problem(client, access, class_id, problem_id, grading_strictness="strict")

    assert response.status_code == 200
    assert response.json()["grading_strictness"] == "strict"
    assert Problem.objects.get(pk=problem_id).grading_strictness == "strict"


def test_switching_to_custom_without_a_sentence_is_rejected(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    problem_id = _create_problem(client, access, class_id).json()["id"]

    response = _patch_problem(client, access, class_id, problem_id, grading_strictness="custom")

    assert response.status_code == 422
    assert Problem.objects.get(pk=problem_id).grading_strictness == "normal"


def test_switching_to_custom_together_with_a_sentence_succeeds(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    problem_id = _create_problem(client, access, class_id).json()["id"]

    response = _patch_problem(
        client,
        access,
        class_id,
        problem_id,
        grading_strictness="custom",
        grading_guideline_text="테스트가 하나 이상 있어야 한다",
    )

    assert response.status_code == 200
    body = response.json()
    assert body["grading_strictness"] == "custom"
    assert body["grading_guideline_text"] == "테스트가 하나 이상 있어야 한다"


def test_switching_away_from_custom_clears_the_stored_sentence(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    problem_id = _create_problem(
        client, access, class_id, grading_strictness="custom", grading_guideline_text="원래 문장"
    ).json()["id"]

    response = _patch_problem(client, access, class_id, problem_id, grading_strictness="normal")

    assert response.status_code == 200
    assert response.json()["grading_guideline_text"] == ""
    assert Problem.objects.get(pk=problem_id).grading_guideline_text == ""


def test_patching_only_the_sentence_keeps_the_existing_custom_strictness(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    problem_id = _create_problem(
        client, access, class_id, grading_strictness="custom", grading_guideline_text="옛 문장"
    ).json()["id"]

    response = _patch_problem(client, access, class_id, problem_id, grading_guideline_text="새 문장")

    assert response.status_code == 200
    body = response.json()
    assert body["grading_strictness"] == "custom"
    assert body["grading_guideline_text"] == "새 문장"


def test_unrelated_edits_leave_the_guideline_untouched(client, db):
    access = _login(client)["access"]
    class_id = _create_class(client, access)
    problem_id = _create_problem(client, access, class_id, grading_strictness="strict").json()["id"]

    response = _patch_problem(client, access, class_id, problem_id, title="새 제목")

    assert response.status_code == 200
    assert response.json()["grading_strictness"] == "strict"


# --- 채점 프롬프트 (#386 AC) -----------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

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
                        {
                            "verdicts": [
                                {"requirement_id": item_id, "is_met": is_met, "reasoning": "판정 근거"}
                            ]
                        }
                    )
                },
            }
        ],
    }


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _set_key(client, access: str, class_id: int, key: str = "sk-test-instructor-key") -> None:
    response = client.put(
        f"{CLASSES_URL}/{class_id}/openai-key",
        data={"api_key": key},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


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


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _setup_submission(client, **problem_overrides):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)

    created = _create_problem(
        client, instructor["access"], class_id, submission_formats=["repository"], **problem_overrides
    )
    assert created.status_code == 201, created.content
    problem_id = created.json()["id"]

    checklist = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "hello world 를 출력한다", "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert checklist.status_code == 201
    item_id = checklist.json()["id"]

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert opened.status_code == 200

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


def test_the_prompt_carries_the_preset_sentence_for_strict(client, db, monkeypatch):
    ctx = _setup_submission(client, grading_strictness="strict")
    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k["json"])
        or _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )

    _run_scan(client)

    user_content = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert "체크리스트에 적힌 출력·이름·값이 글자 그대로 일치해야 충족한다" in user_content


def test_the_prompt_carries_the_preset_sentence_for_lenient(client, db, monkeypatch):
    ctx = _setup_submission(client, grading_strictness="lenient")
    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k["json"])
        or _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )

    _run_scan(client)

    user_content = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert "핵심 동작이 되면 충족한다" in user_content


def test_the_prompt_carries_the_instructors_custom_sentence(client, db, monkeypatch):
    sentence = "함수 이름은 solve 여야 하지만 출력 형식은 자유롭게 판정한다."
    ctx = _setup_submission(client, grading_strictness="custom", grading_guideline_text=sentence)
    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k["json"])
        or _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )

    _run_scan(client)

    user_content = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert sentence in user_content


def test_the_fixed_instructions_still_ride_alongside_the_guideline(client, db, monkeypatch):
    """지침 문장이 실려도 고정 지시(모든 항목 판정, 한국어 근거)는 그대로
    남는다(#386 AC) — `test_classroom_scoring.py`가 이미 같은 사실을 한국어
    근거 지시 하나로 고정하고 있고, 여기서는 그 둘이 **함께** 실리는지 본다."""

    sentence = "정확히 solve 라는 이름의 함수가 있어야 한다."
    ctx = _setup_submission(client, grading_strictness="custom", grading_guideline_text=sentence)
    sent = []
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: sent.append(k["json"])
        or _FakeResponse(200, _openai_success_body(ctx["item_id"])),
    )

    _run_scan(client)

    user_content = {m["role"]: m["content"] for m in sent[0]["messages"]}["user"]
    assert sentence in user_content
    assert "한국어" in user_content
    assert "모든 requirement_id" in user_content
    assert f"requirement_id={ctx['item_id']}" in user_content


def test_changing_the_guideline_does_not_alter_a_score_already_made(client, db, monkeypatch):
    """지침을 바꿔도 이미 매긴 판정은 조회에서 그대로다(ADR-0006, #386 AC)."""

    ctx = _setup_submission(client, grading_strictness="normal")
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_success_body(ctx["item_id"], is_met=True)),
    )
    _run_scan(client)
    score_before = ClassroomScore.objects.get(submission_id=ctx["submission_id"])

    _patch_problem(
        client, ctx["instructor"]["access"], ctx["class_id"], ctx["problem_id"], grading_strictness="strict"
    )

    score_after = ClassroomScore.objects.get(submission_id=ctx["submission_id"])
    assert score_after.pk == score_before.pk
    assert score_after.created_at == score_before.created_at
    assert score_after.reasoning == score_before.reasoning
    assert ClassroomScore.objects.filter(submission_id=ctx["submission_id"]).count() == 1
