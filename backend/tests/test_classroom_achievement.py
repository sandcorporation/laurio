"""문제별 달성률 — 강사가 수업이 어디서 막혔는지 본다 (#289, CONTEXT.md
「강의실」 「달성률」).

핵심 대상: 문제마다 달성률과 통과 인원이 보인다. 분자는 한 번이라도 통과한
사람이지 최신 시도가 아니다. 강사 본인과 내보내진 사람은 분모·분자 어디에도
들지 않는다. 체크리스트를 고치면 지금 기준으로 다시 셈된다. 참여자가 0명이면
분모가 0이라는 사실 자체가 화면의 "아직 없음"을 뒷받침한다.
"""

from __future__ import annotations

import json

from django.conf import settings

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


def _create_problem(client, access: str, class_id: int, title: str = "1주차") -> int:
    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_format": "repository"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    return created.json()["id"]


def _add_required_item(client, access: str, class_id: int, problem_id: int, label: str = "테스트가 있다") -> int:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": label, "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201
    return response.json()["id"]


def _open_problem(client, access: str, class_id: int, problem_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
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


def _expel(client, access: str, class_id: int, member_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200


def _members(client, access: str, class_id: int) -> list:
    response = client.get(f"{CLASSES_URL}/{class_id}/members", **_auth_header(access))
    assert response.status_code == 200
    return response.json()


def _submit_repository(client, access: str, class_id: int, problem_id: int, url: str) -> dict:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/submissions",
        data={"value": url},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _problems(client, access: str, class_id: int) -> list:
    response = client.get(f"{CLASSES_URL}/{class_id}/problems", **_auth_header(access))
    assert response.status_code == 200
    return response.json()


class _FakeResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def _openai_body(item_id: int, *, is_met: bool) -> dict:
    return {
        "model": "gpt-4o-mini-2024-07-18",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"verdicts": [{"requirement_id": item_id, "is_met": is_met, "reasoning": "사유"}]}
                    )
                },
            }
        ],
    }


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _setup_open_problem(client, instructor_access: str, class_id: int, title: str = "1주차") -> dict:
    problem_id = _create_problem(client, instructor_access, class_id, title)
    item_id = _add_required_item(client, instructor_access, class_id, problem_id)
    _open_problem(client, instructor_access, class_id, problem_id)
    return {"problem_id": problem_id, "item_id": item_id}


def test_a_freshly_opened_problem_with_no_participants_has_no_denominator(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _setup_open_problem(client, instructor["access"], class_id)

    problems = _problems(client, instructor["access"], class_id)

    assert problems[0]["member_count"] == 0
    assert problems[0]["passed_count"] == 0
    assert problems[0]["pass_rate"] is None


def test_a_participant_who_passes_counts_toward_the_rate(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    _submit_repository(
        client, participant["access"], class_id, ctx["problem_id"], "https://github.com/octocat/hello"
    )
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_body(ctx["item_id"], is_met=True)),
    )
    _run_scan(client)

    problems = _problems(client, instructor["access"], class_id)

    assert problems[0]["member_count"] == 1
    assert problems[0]["passed_count"] == 1
    assert problems[0]["pass_rate"] == 1.0


def test_the_instructor_joining_their_own_class_does_not_move_the_rate(client, db, monkeypatch):
    """강사 본인이 참여자로 들어와 통과해도 분모·분자 어디에도 들지 않는다(AC)."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    _join(client, instructor["access"], _join_code(client, instructor["access"], class_id), display_name="강사")

    _submit_repository(
        client, instructor["access"], class_id, ctx["problem_id"], "https://github.com/octocat/hello"
    )
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_body(ctx["item_id"], is_met=True)),
    )
    _run_scan(client)

    problems = _problems(client, instructor["access"], class_id)

    assert problems[0]["member_count"] == 0
    assert problems[0]["passed_count"] == 0
    assert problems[0]["pass_rate"] is None


def test_an_expelled_participant_leaves_the_denominator(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    member_id = _members(client, instructor["access"], class_id)[0]["id"]

    _expel(client, instructor["access"], class_id, member_id)

    problems = _problems(client, instructor["access"], class_id)

    assert problems[0]["member_count"] == 0
    assert problems[0]["pass_rate"] is None


def test_a_later_failing_attempt_does_not_undo_an_earlier_pass_in_the_rate(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    _submit_repository(client, participant["access"], class_id, ctx["problem_id"], "https://github.com/octocat/first")
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_body(ctx["item_id"], is_met=True)),
    )
    _run_scan(client)

    _submit_repository(client, participant["access"], class_id, ctx["problem_id"], "https://github.com/octocat/second")
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_body(ctx["item_id"], is_met=False)),
    )
    _run_scan(client)

    problems = _problems(client, instructor["access"], class_id)

    assert problems[0]["passed_count"] == 1
    assert problems[0]["member_count"] == 1
    assert problems[0]["pass_rate"] == 1.0


def test_editing_the_checklist_after_scoring_recomputes_the_rate(client, db, monkeypatch):
    """체크리스트를 고치면 달성률이 새 기준으로 다시 셈된다(AC) — 지난 Score
    는 append-only라 그대로지만, 통과 판정은 지금의 필수 항목 기준이다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    _submit_repository(client, participant["access"], class_id, ctx["problem_id"], "https://github.com/octocat/hello")
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_body(ctx["item_id"], is_met=True)),
    )
    _run_scan(client)

    problems_before = _problems(client, instructor["access"], class_id)
    assert problems_before[0]["pass_rate"] == 1.0

    # 새 필수 항목을 더한다 — 지난 채점은 이 항목을 본 적이 없으므로
    # "충족 확인 안 됨"으로 보고 통과가 풀려야 한다.
    new_required = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{ctx['problem_id']}/checklist-items",
        data={"label": "새 필수 항목", "required": True},
        content_type="application/json",
        **_auth_header(instructor["access"]),
    )
    assert new_required.status_code == 201

    problems_after = _problems(client, instructor["access"], class_id)
    assert problems_after[0]["pass_rate"] == 0.0
    assert problems_after[0]["passed_count"] == 0


def test_the_problem_list_screen_says_not_yet_when_there_are_no_participants(client, db):
    """참여자가 0명일 때 화면이 0% 가 아니라 「아직 없음」으로 말한다(AC) —
    백엔드는 그 판단이 가능하도록 `member_count`·`pass_rate`(null)를 함께
    내려준다. 화면 문구 자체는 프론트가 만든다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _setup_open_problem(client, instructor["access"], class_id)

    problems = _problems(client, instructor["access"], class_id)

    assert problems[0]["member_count"] == 0
    assert problems[0]["pass_rate"] is None
