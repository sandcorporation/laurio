"""참여자 × 문제 격자 — 누가 어디서 막혔는지 (#290, CONTEXT.md 「강의실」).

핵심 대상: 셀이 최신 시도가 아니라 통과 이력을 그린다(#289 「달성률」과 같은
규칙) — 통과·시도했으나 미통과·채점 중·미제출 넷을 구별한다. 강사 본인과
내보내진 참여자도 격자에는 나오지만 달성률 계산에서는 빠진다. 그 달성률
값은 문제 중심 탭(`GET .../problems`)의 값과 정확히 같아야 한다.
"""

from __future__ import annotations

import json

import pytest
from django.conf import settings
from django.test import override_settings

CLASSES_URL = "/api/classroom/classes"
SCAN_URL = "/api/internal/scans/classroom-submission-scoring"


@pytest.fixture(autouse=True)
def _force_real_scoring_adapter():
    # 이 파일은 core.llm_scoring.requests.post를 모킹해 OpenAIScoringAdapter
    # 경로 자체를 검증한다 — CLASSROOM_SCORING_ADAPTER_MODE 기본값(fake)이
    # 그 경로를 안 타므로 강제한다(#340, ADR-0043).
    with override_settings(CLASSROOM_SCORING_ADAPTER_MODE="core.llm_scoring.OpenAIScoringAdapter"):
        yield


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


def _setup_open_problem(client, instructor_access: str, class_id: int, title: str = "1주차") -> dict:
    problem_id = _create_problem(client, instructor_access, class_id, title)
    item_id = _add_required_item(client, instructor_access, class_id, problem_id)
    _open_problem(client, instructor_access, class_id, problem_id)
    return {"problem_id": problem_id, "item_id": item_id}


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


def _grid(client, access: str, class_id: int, *, expect_status: int = 200) -> dict:
    response = client.get(f"{CLASSES_URL}/{class_id}/roster-grid", **_auth_header(access))
    assert response.status_code == expect_status, response.content
    return response.json() if expect_status == 200 else response.json()


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


def _member_row(grid: dict, member_id: int) -> dict:
    return next(m for m in grid["members"] if m["id"] == member_id)


def _cell(row: dict, problem_id: int) -> dict:
    return next(c for c in row["cells"] if c["problem_id"] == problem_id)


def test_a_member_with_no_attempt_is_not_submitted(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    grid = _grid(client, instructor["access"], class_id)

    member = grid["members"][0]
    cell = _cell(member, ctx["problem_id"])
    assert cell["status"] == "not_submitted"


def test_a_pending_attempt_shows_as_scoring(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit_repository(client, participant["access"], class_id, ctx["problem_id"], "https://github.com/octocat/hello")

    grid = _grid(client, instructor["access"], class_id)

    member = grid["members"][0]
    assert _cell(member, ctx["problem_id"])["status"] == "scoring"


def test_a_scored_failing_attempt_shows_as_attempted_not_passed(client, db, monkeypatch):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    _submit_repository(client, participant["access"], class_id, ctx["problem_id"], "https://github.com/octocat/hello")
    monkeypatch.setattr(
        "core.llm_scoring.requests.post",
        lambda *a, **k: _FakeResponse(200, _openai_body(ctx["item_id"], is_met=False)),
    )
    _run_scan(client)

    grid = _grid(client, instructor["access"], class_id)

    member = grid["members"][0]
    assert _cell(member, ctx["problem_id"])["status"] == "attempted_not_passed"


def test_a_pass_anywhere_in_history_shows_as_passed_even_after_a_later_failure(client, db, monkeypatch):
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

    grid = _grid(client, instructor["access"], class_id)

    member = grid["members"][0]
    assert _cell(member, ctx["problem_id"])["status"] == "passed"


def test_the_pass_rate_row_matches_the_problem_centric_tab_exactly(client, db, monkeypatch):
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

    problems = _problems(client, instructor["access"], class_id)
    grid = _grid(client, instructor["access"], class_id)

    grid_problem = next(p for p in grid["problems"] if p["id"] == ctx["problem_id"])
    list_problem = next(p for p in problems if p["id"] == ctx["problem_id"])
    assert grid_problem["passed_count"] == list_problem["passed_count"]
    assert grid_problem["member_count"] == list_problem["member_count"]
    assert grid_problem["pass_rate"] == list_problem["pass_rate"]


def test_the_instructor_and_an_expelled_member_appear_in_the_grid_rows(client, db):
    """강사 본인과 내보내진 사람이 달성률 행과 어긋나지 않게 표시된다(AC) —
    격자에서 지워지지는 않되, 그 신분이 함께 드러나 달성률 집계가 그들을
    뺀 것과 모순되지 않는다."""

    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    ctx = _setup_open_problem(client, instructor["access"], class_id)
    _join(client, instructor["access"], _join_code(client, instructor["access"], class_id), display_name="강사")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    expelled_member_id = _members(client, instructor["access"], class_id)[1]["id"]
    _expel(client, instructor["access"], class_id, expelled_member_id)

    grid = _grid(client, instructor["access"], class_id)

    assert len(grid["members"]) == 2
    instructor_row = next(m for m in grid["members"] if m["is_instructor"])
    expelled_row = next(m for m in grid["members"] if m["expelled"])
    assert instructor_row["id"] != expelled_row["id"]


def test_a_non_instructor_cannot_see_the_grid(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    stranger = _login(client, uid="stranger-1")

    response = client.get(f"{CLASSES_URL}/{class_id}/roster-grid", **_auth_header(stranger["access"]))

    assert response.status_code == 404


def test_columns_include_every_problem_in_class_order(client, db):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    first = _setup_open_problem(client, instructor["access"], class_id, title="1주차")
    second = _setup_open_problem(client, instructor["access"], class_id, title="2주차")
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))

    grid = _grid(client, instructor["access"], class_id)

    assert [p["id"] for p in grid["problems"]] == [first["problem_id"], second["problem_id"]]
    member = grid["members"][0]
    assert {c["problem_id"] for c in member["cells"]} == {first["problem_id"], second["problem_id"]}
