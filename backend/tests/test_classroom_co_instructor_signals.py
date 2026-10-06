"""공동 강사도 강사용 신호를 받는다 — 키·예산 알림은 소유자에게만 (#566, spec #558, ADR-0055).

두 갈래가 수신자를 다르게 고른다(`CONTEXT.md` 「공동 강사」):

- **참여자 활동에 관한 강사용 실시간 신호**(`attempt-submitted`·`attempt-scored`)는 강사
  전원(소유자 + 공동 강사)에게 간다 — 「강사인가」(`classroom.instructors.instructor_user_ids`).
- **채점 키·예산 알림**(예산 경고·키 거부)은 소유자에게만 간다 — 바꿀 수 있는 사람이
  소유자뿐이고 비용이 그 사람의 몫이다. 소유권이 넘어가면 새 소유자에게 간다.

준비는 마운트된 HTTP API 로(`tests.classroom_scenarios`), 알림은 각자의 알림 목록
(`/api/notifications/me?classroom_only=true`)으로 본다. 실시간 신호는 fake 이벤트 버스의
수신자별 큐로 본다(`tests/test_classroom_events.py` 와 같은 결).
"""

from __future__ import annotations

import pytest

from core.events import FakeEventBus
from notifications.models import NotificationType
from tests.classroom_scenarios import (
    add_co_instructor,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    login,
    patch_class,
    respond_to_models_endpoint,
    respond_with_key_rejection,
    respond_with_verdict,
    run_scan,
    set_key,
    submit_repository,
    transfer_ownership,
    user_id,
)

ME_URL = "/api/notifications/me"


def _classroom_notification_types(client, access: str) -> list[str]:
    response = client.get(f"{ME_URL}?classroom_only=true", **auth_header(access))
    assert response.status_code == 200, response.content
    return [row["notification_type"] for row in response.json()["items"]]


def _signals(uid: str, kind: str) -> list:
    return [e for e in FakeEventBus._queues.get(user_id(uid), []) if e.kind == kind]


def _class_with_a_co_instructor_and_a_participant(client):
    owner = login(client, uid="owner")
    co = login(client, uid="co")
    participant = login(client, uid="participant")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    problem = create_open_problem(client, owner["access"], class_id)
    join_class(client, participant["access"], class_id, instructor_access=owner["access"])
    return owner, co, participant, class_id, problem


# --- 강사용 실시간 신호 — 강사 전원 -------------------------------------------------


def test_a_participants_submission_signals_the_owner_and_the_co_instructor(
    client, db, django_capture_on_commit_callbacks
):
    _, _, participant, class_id, problem = _class_with_a_co_instructor_and_a_participant(client)

    with django_capture_on_commit_callbacks(execute=True):
        submitted = submit_repository(client, participant["access"], class_id, problem.id)

    expected = {"class_id": class_id, "problem_id": problem.id, "submission_id": submitted["id"]}
    for uid in ("owner", "co"):
        assert [e.payload for e in _signals(uid, "attempt-submitted")] == [expected], uid

    with django_capture_on_commit_callbacks(execute=True):
        run_scan(client)

    for uid in ("owner", "co"):
        assert [e.payload for e in _signals(uid, "attempt-scored")] == [expected], uid


def test_a_co_instructor_of_another_class_gets_no_signal(client, db, django_capture_on_commit_callbacks):
    _, _, participant, class_id, problem = _class_with_a_co_instructor_and_a_participant(client)
    other_owner = login(client, uid="other-owner")
    other_co = login(client, uid="other-co")
    other_class = create_class(client, other_owner["access"], name="다른 클래스", with_key=False)
    add_co_instructor(client, other_owner["access"], other_class, other_co["access"])

    with django_capture_on_commit_callbacks(execute=True):
        submit_repository(client, participant["access"], class_id, problem.id)
        run_scan(client)

    assert FakeEventBus._queues.get(user_id("other-co"), []) == []


# --- 채점 키·예산 알림 — 소유자에게만 ------------------------------------------------


@pytest.fixture
def real_scoring():
    with force_real_scoring_adapter():
        yield


def test_the_budget_warning_reaches_only_the_owner(client, db, monkeypatch, real_scoring):
    owner, co, participant, class_id, problem = _class_with_a_co_instructor_and_a_participant(client)
    patch_class(client, owner["access"], class_id, {"token_budget": 100, "token_budget_warning_threshold_percent": 50})
    submit_repository(client, participant["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, total_tokens=60)

    run_scan(client)

    assert _classroom_notification_types(client, owner["access"]).count(NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING) == 1
    assert NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING not in _classroom_notification_types(client, co["access"])


def test_the_key_rejection_reaches_only_the_owner(client, db, monkeypatch, real_scoring):
    owner, co, participant, class_id, problem = _class_with_a_co_instructor_and_a_participant(client)
    submit_repository(client, participant["access"], class_id, problem.id)
    respond_with_key_rejection(monkeypatch)

    run_scan(client)

    assert _classroom_notification_types(client, owner["access"]).count(NotificationType.CLASSROOM_SCORING_KEY_REJECTED) == 1
    assert NotificationType.CLASSROOM_SCORING_KEY_REJECTED not in _classroom_notification_types(client, co["access"])


def test_after_a_transfer_the_budget_warning_follows_the_new_owner(client, db, monkeypatch, real_scoring):
    """넘긴 사람은 공동 강사로 남는다 — 그래서 더는 받지 않는다(#564). 넘겨받은 사람이 새 키를
    넣어야 채점이 다시 돈다(키는 이전에서 비워진다)."""

    owner, co, participant, class_id, problem = _class_with_a_co_instructor_and_a_participant(client)
    transfer_ownership(client, owner["access"], class_id, co["access"], recipient_name="보조 강사")
    respond_to_models_endpoint(monkeypatch)
    set_key(client, co["access"], class_id)
    patch_class(client, co["access"], class_id, {"token_budget": 100, "token_budget_warning_threshold_percent": 50})
    submit_repository(client, participant["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, total_tokens=60)

    run_scan(client)

    assert _classroom_notification_types(client, co["access"]).count(NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING) == 1
    assert NotificationType.CLASSROOM_TOKEN_BUDGET_WARNING not in _classroom_notification_types(client, owner["access"])
