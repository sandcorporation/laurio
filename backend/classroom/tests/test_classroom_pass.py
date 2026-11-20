"""통과 판정과 참여자가 보는 결과 (#288, CONTEXT.md 「강의실」 「통과」).

핵심 대상: 필수 체크리스트 항목을 전부 충족한 시도가 통과로 판정된다 —
선택 항목은 관여하지 않는다. 참여자는 항목별 충족 여부와 사유를 본다.
참여자의 문제 목록에서 통과/미통과가 한눈에 보이고, 한 번 통과하면 나중에
다시 내서 미통과가 나와도 그 통과는 유지된다.
"""

from __future__ import annotations

import pytest
from django.conf import settings
from django.test import override_settings

from tests.classroom_scenarios import respond_with_verdicts

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


def _create_open_problem_with_checklist(client, access: str, class_id: int, title: str = "1주차") -> dict:
    """필수 항목 하나 + 선택 항목 하나를 가진 열린 문제를 만든다 — 「선택
    항목은 통과 판정에 영향을 주지 않는다」를 검증하려면 둘 다 필요하다."""

    created = client.post(
        f"{CLASSES_URL}/{class_id}/problems",
        data={"title": title, "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(access),
    )
    assert created.status_code == 201
    problem_id = created.json()["id"]

    required = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "테스트가 있다", "required": True},
        content_type="application/json",
        **_auth_header(access),
    )
    assert required.status_code == 201
    required_id = required.json()["id"]

    optional = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/checklist-items",
        data={"label": "스타일 가이드를 따른다", "required": False},
        content_type="application/json",
        **_auth_header(access),
    )
    assert optional.status_code == 201
    optional_id = optional.json()["id"]

    opened = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/open",
        content_type="application/json",
        **_auth_header(access),
    )
    assert opened.status_code == 200
    return {"problem_id": problem_id, "required_id": required_id, "optional_id": optional_id}


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


def _my_problems(client, access: str, class_id: int) -> list:
    response = client.get(f"{CLASSES_URL}/{class_id}/problems/mine", **_auth_header(access))
    assert response.status_code == 200
    return response.json()["problems"]


def _run_scan(client) -> dict:
    response = client.post(SCAN_URL, content_type="application/json", **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _setup(client):
    instructor = _login(client, uid="instructor-1")
    class_id = _create_class(client, instructor["access"])
    _set_key(client, instructor["access"], class_id)
    checklist = _create_open_problem_with_checklist(client, instructor["access"], class_id)
    participant = _login(client, uid="participant-1")
    _join(client, participant["access"], _join_code(client, instructor["access"], class_id))
    return {
        "instructor": instructor,
        "participant": participant,
        "class_id": class_id,
        **checklist,
    }


def _submit_and_score(client, ctx, monkeypatch, *, required_met: bool, optional_met: bool, url: str):
    submitted = _submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"], url
    )
    respond_with_verdicts(
        monkeypatch,
        [
            {"requirement_id": ctx["required_id"], "is_met": required_met, "reasoning": "필수 항목 사유"},
            {"requirement_id": ctx["optional_id"], "is_met": optional_met, "reasoning": "선택 항목 사유"},
        ],
    )
    _run_scan(client)
    return submitted


def test_all_required_items_met_marks_the_attempt_passed(client, db, monkeypatch):
    ctx = _setup(client)
    submitted = _submit_and_score(
        client, ctx, monkeypatch, required_met=True, optional_met=True, url="https://github.com/octocat/one"
    )

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    row = next(s for s in mine["submissions"] if s["id"] == submitted["id"])
    assert row["passed"] is True
    assert mine["problem"]["passed"] is True


def test_a_missing_required_item_is_not_passed(client, db, monkeypatch):
    ctx = _setup(client)
    submitted = _submit_and_score(
        client, ctx, monkeypatch, required_met=False, optional_met=True, url="https://github.com/octocat/one"
    )

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    row = next(s for s in mine["submissions"] if s["id"] == submitted["id"])
    assert row["passed"] is False
    assert mine["problem"]["passed"] is False


def test_an_unmet_optional_item_does_not_block_passing(client, db, monkeypatch):
    """선택 항목은 통과 판정에 영향을 주지 않는다(#288 AC)."""

    ctx = _setup(client)
    submitted = _submit_and_score(
        client, ctx, monkeypatch, required_met=True, optional_met=False, url="https://github.com/octocat/one"
    )

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    row = next(s for s in mine["submissions"] if s["id"] == submitted["id"])
    assert row["passed"] is True


def test_a_pending_attempt_is_never_passed(client, db):
    ctx = _setup(client)
    submitted = _submit_repository(
        client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"], "https://github.com/octocat/one"
    )

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    row = next(s for s in mine["submissions"] if s["id"] == submitted["id"])
    assert row["status"] == "pending"
    assert row["passed"] is False
    assert mine["problem"]["passed"] is False


def test_a_later_failing_attempt_does_not_undo_an_earlier_pass(client, db, monkeypatch):
    """한 번 통과한 뒤 다시 내서 미통과가 나와도 「통과함」은 유지된다(#288 AC)."""

    ctx = _setup(client)
    _submit_and_score(
        client, ctx, monkeypatch, required_met=True, optional_met=True, url="https://github.com/octocat/first"
    )
    second = _submit_and_score(
        client, ctx, monkeypatch, required_met=False, optional_met=True, url="https://github.com/octocat/second"
    )

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    second_row = next(s for s in mine["submissions"] if s["id"] == second["id"])
    assert second_row["passed"] is False
    # 개별 시도는 미통과지만, 문제 전체는 여전히 통과다 — 최신이 아니라 OR.
    assert mine["problem"]["passed"] is True


def test_problem_list_shows_passed_status_at_a_glance(client, db, monkeypatch):
    ctx = _setup(client)
    _submit_and_score(
        client, ctx, monkeypatch, required_met=True, optional_met=True, url="https://github.com/octocat/one"
    )

    # 아직 아무도 안 낸 두 번째 문제 — 미통과여야 한다.
    second_problem = client.post(
        f"{CLASSES_URL}/{ctx['class_id']}/problems",
        data={"title": "2주차", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )
    assert second_problem.status_code == 201
    second_problem_id = second_problem.json()["id"]
    client.post(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{second_problem_id}/checklist-items",
        data={"label": "두 번째 문제 항목", "required": True},
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )
    client.post(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/{second_problem_id}/open",
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )

    problems = _my_problems(client, ctx["participant"]["access"], ctx["class_id"])

    by_id = {p["id"]: p for p in problems}
    assert by_id[ctx["problem_id"]]["passed"] is True
    assert by_id[second_problem_id]["passed"] is False


def test_draft_problems_are_excluded_from_the_participant_list(client, db, monkeypatch):
    ctx = _setup(client)
    draft = client.post(
        f"{CLASSES_URL}/{ctx['class_id']}/problems",
        data={"title": "초안 문제", "submission_formats": ["repository"]},
        content_type="application/json",
        **_auth_header(ctx["instructor"]["access"]),
    )
    assert draft.status_code == 201

    problems = _my_problems(client, ctx["participant"]["access"], ctx["class_id"])

    assert draft.json()["id"] not in {p["id"] for p in problems}


def test_non_participant_cannot_see_the_problem_list(client, db):
    ctx = _setup(client)
    stranger = _login(client, uid="stranger-1")

    response = client.get(
        f"{CLASSES_URL}/{ctx['class_id']}/problems/mine", **_auth_header(stranger["access"])
    )

    assert response.status_code == 404


def test_participant_sees_the_reasoning_behind_each_checklist_verdict(client, db, monkeypatch):
    ctx = _setup(client)
    submitted = _submit_and_score(
        client, ctx, monkeypatch, required_met=True, optional_met=False, url="https://github.com/octocat/one"
    )

    mine = _mine(client, ctx["participant"]["access"], ctx["class_id"], ctx["problem_id"])
    row = next(s for s in mine["submissions"] if s["id"] == submitted["id"])
    reasoning_by_item = {r["checklist_item_id"]: r for r in row["score"]["reasoning"]}
    assert reasoning_by_item[ctx["required_id"]] == {
        "checklist_item_id": ctx["required_id"],
        "is_met": True,
        "verdict": "met",
        "reasoning": "필수 항목 사유",
    }
    assert reasoning_by_item[ctx["optional_id"]] == {
        "checklist_item_id": ctx["optional_id"],
        "is_met": False,
        "verdict": "unmet",
        "reasoning": "선택 항목 사유",
    }
