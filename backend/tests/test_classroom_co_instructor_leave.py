"""공동 강사가 클래스를 떠나는 세 길 — 스스로 떠나기, 소유자의 내보내기, 탈퇴 (#563, spec #558,
ADR-0055, CONTEXT.md 「공동 강사」).

세 길은 같은 정리를 한다: 공동 강사 자리를 지우고, 그 사람의 참여자 행이 있으면 내보낸
참여자로 표시하고(점검용 시도가 달성률에 섞이지 않게, 그 시도는 문제 삭제를 막는다 —
ADR-0050), 그 사람이 만든 대기 중 초대를 취소한다. 소유자는 떠날 수 없다. 보관된
클래스에서도 된다. 준비와 확인은 전부 마운트된 HTTP API 로 한다(`tests.classroom_scenarios`).
"""

from __future__ import annotations

import pytest

from classroom.co_instructors import OWNER_CANNOT_LEAVE_MESSAGE
from classroom.instructor_scope import OWNER_ONLY_MESSAGE
from tests.classroom_scenarios import (
    CLASSES_URL,
    accept_co_instructor_invite,
    add_co_instructor,
    archive_class,
    auth_header,
    create_class,
    create_co_instructor_invite,
    create_open_problem,
    force_real_scoring_adapter,
    join_class,
    leave_class,
    list_instructors,
    list_pending_co_instructor_invites,
    list_problems,
    list_taught_classes,
    login,
    preview_co_instructor_invite,
    remove_co_instructor,
    respond_with_verdict,
    run_scan,
    submit_repository,
)

WITHDRAWAL_URL = "/api/accounts/withdrawal"


@pytest.fixture
def real_scoring():
    # 통과를 만들려면 벤더 응답을 흉내 내야 한다 — 기본값(fake) 어댑터는 그 경로를 타지 않는다.
    with force_real_scoring_adapter():
        yield


def _co_instructor_id(client, access: str, class_id: int, display_name: str) -> int:
    rows = [r for r in list_instructors(client, access, class_id) if r["display_name"] == display_name]
    assert len(rows) == 1, rows
    return rows[0]["co_instructor_id"]


def _teaches(client, access: str, class_id: int) -> bool:
    return class_id in [row["id"] for row in list_taught_classes(client, access)]


def _members(client, access: str, class_id: int) -> dict[str, dict]:
    response = client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(access))
    assert response.status_code == 200, response.content
    return {m["display_name"]: m for m in response.json()}


def _withdraw(client, access: str):
    return client.post(WITHDRAWAL_URL, content_type="application/json", **auth_header(access))


# --- 스스로 떠나기 ----------------------------------------------------------------------


def test_a_co_instructor_who_leaves_loses_the_class(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])

    assert leave_class(client, co["access"], class_id).status_code == 204

    assert class_id not in [row["id"] for row in list_taught_classes(client, co["access"])]
    assert client.get(f"{CLASSES_URL}/{class_id}", **auth_header(co["access"])).status_code == 404
    assert client.get(f"{CLASSES_URL}/{class_id}/members", **auth_header(co["access"])).status_code == 404


def test_the_owner_cannot_leave_and_is_told_what_to_do_instead(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])

    response = leave_class(client, owner["access"], class_id)

    assert response.status_code == 409
    assert response.json()["detail"] == OWNER_CANNOT_LEAVE_MESSAGE
    assert _teaches(client, owner["access"], class_id)


def test_someone_who_does_not_teach_the_class_cannot_leave_it(client, db):
    owner = login(client, "owner")
    stranger = login(client, "stranger")
    class_id = create_class(client, owner["access"])

    assert leave_class(client, stranger["access"], class_id).status_code == 404


# --- 소유자의 내보내기 ----------------------------------------------------------------


def test_the_owner_removes_a_co_instructor(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    co_id = _co_instructor_id(client, owner["access"], class_id, "보조 강사")

    assert remove_co_instructor(client, owner["access"], class_id, co_id).status_code == 204

    assert not _teaches(client, co["access"], class_id)
    assert [r["role"] for r in list_instructors(client, owner["access"], class_id)] == ["owner"]
    # 이미 내보낸 줄은 없다.
    assert remove_co_instructor(client, owner["access"], class_id, co_id).status_code == 404


def test_a_co_instructor_cannot_remove_another_co_instructor(client, db):
    owner = login(client, "owner")
    first = login(client, "first")
    second = login(client, "second")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, first["access"], display_name="보조 강사")
    add_co_instructor(client, owner["access"], class_id, second["access"], display_name="조교")
    second_id = _co_instructor_id(client, owner["access"], class_id, "조교")

    response = remove_co_instructor(client, first["access"], class_id, second_id)

    assert response.status_code == 403
    assert response.json()["detail"] == OWNER_ONLY_MESSAGE
    assert _teaches(client, second["access"], class_id)


def test_the_owner_cannot_remove_a_co_instructor_of_another_class(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    mine_id = create_class(client, owner["access"], name="내 클래스")
    other_owner = login(client, "other-owner")
    other_id = create_class(client, other_owner["access"], name="남의 클래스")
    add_co_instructor(client, other_owner["access"], other_id, co["access"], display_name="보조 강사")
    co_id = _co_instructor_id(client, other_owner["access"], other_id, "보조 강사")

    assert remove_co_instructor(client, owner["access"], mine_id, co_id).status_code == 404
    assert _teaches(client, co["access"], other_id)


# --- 떠난 사람의 참여자 행과 시도 -------------------------------------------------------


@pytest.mark.parametrize("how", ["leave", "remove"])
def test_a_departed_participant_becomes_an_expelled_participant_and_the_rate_does_not_move(
    client, db, monkeypatch, real_scoring, how
):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id)
    helper = login(client, "helper")
    learner = login(client, "learner")
    join_class(client, helper["access"], class_id, instructor_access=owner["access"], display_name="조교였던 학생")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"], display_name="학생")
    add_co_instructor(client, owner["access"], class_id, helper["access"], display_name="조교")
    submit_repository(client, helper["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)
    before = list_problems(client, owner["access"], class_id)[0]
    assert (before["passed_count"], before["member_count"]) == (0, 1)
    assert before["deletable"] is True  # 강사의 점검용 시도뿐이다.

    if how == "leave":
        assert leave_class(client, helper["access"], class_id).status_code == 204
    else:
        co_id = _co_instructor_id(client, owner["access"], class_id, "조교")
        assert remove_co_instructor(client, owner["access"], class_id, co_id).status_code == 204

    after = list_problems(client, owner["access"], class_id)[0]
    assert (after["passed_count"], after["member_count"]) == (0, 1)
    members = _members(client, owner["access"], class_id)
    assert (members["조교였던 학생"]["expelled"], members["조교였던 학생"]["is_instructor"]) == (True, False)
    assert members["학생"]["expelled"] is False
    # 떠난 사람의 시도는 내보낸 참여자의 시도로 남아 삭제를 막는다(ADR-0050).
    assert after["deletable"] is False
    deleted = client.delete(f"{CLASSES_URL}/{class_id}/problems/{problem.id}", **auth_header(owner["access"]))
    assert deleted.status_code == 403


def test_a_co_instructor_who_only_tried_problems_leaves_an_attempt_that_blocks_deletion(client, db):
    """참여자로 든 적이 없어도 문제를 점검하려고 낸 시도가 있으면 참여자 행이 있다 —
    떠나면 그 행이 내보낸 참여자가 되고 문제를 지울 수 없게 된다."""

    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id)
    helper = login(client, "helper")
    add_co_instructor(client, owner["access"], class_id, helper["access"], display_name="조교")
    submit_repository(client, helper["access"], class_id, problem.id)
    assert list_problems(client, owner["access"], class_id)[0]["deletable"] is True

    assert leave_class(client, helper["access"], class_id).status_code == 204

    row = list_problems(client, owner["access"], class_id)[0]
    assert (row["member_count"], row["deletable"]) == (0, False)


# --- 떠난 사람이 만든 대기 중 초대 -------------------------------------------------------


def test_invites_made_by_the_departed_are_cancelled_and_others_stay(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    theirs = create_co_instructor_invite(client, co["access"], class_id)
    owners = create_co_instructor_invite(client, owner["access"], class_id)

    assert leave_class(client, co["access"], class_id).status_code == 204

    assert [i["id"] for i in list_pending_co_instructor_invites(client, owner["access"], class_id)] == [owners["id"]]
    assert preview_co_instructor_invite(client, theirs["token"]).json()["status"] == "cancelled"
    newcomer = login(client, "newcomer")
    assert accept_co_instructor_invite(client, newcomer["access"], theirs["token"]).status_code == 410


# --- 보관된 클래스 ----------------------------------------------------------------------


def test_leaving_and_removing_work_in_an_archived_class(client, db):
    owner = login(client, "owner")
    first = login(client, "first")
    second = login(client, "second")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, first["access"], display_name="보조 강사")
    add_co_instructor(client, owner["access"], class_id, second["access"], display_name="조교")
    archive_class(client, owner["access"], class_id)

    assert leave_class(client, first["access"], class_id).status_code == 204
    second_id = _co_instructor_id(client, owner["access"], class_id, "조교")
    assert remove_co_instructor(client, owner["access"], class_id, second_id).status_code == 204

    assert [r["role"] for r in list_instructors(client, owner["access"], class_id)] == ["owner"]


# --- 탈퇴 ------------------------------------------------------------------------------


def test_someone_who_only_co_teaches_can_withdraw_and_leaves_the_class(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    invite = create_co_instructor_invite(client, co["access"], class_id)

    eligibility = client.get(WITHDRAWAL_URL, **auth_header(co["access"]))
    assert eligibility.json()["blocking_reasons"] == []
    assert _withdraw(client, co["access"]).status_code == 200

    assert [r["role"] for r in list_instructors(client, owner["access"], class_id)] == ["owner"]
    assert preview_co_instructor_invite(client, invite["token"]).json()["status"] == "cancelled"


def test_an_owner_with_an_open_class_is_still_blocked_and_keeps_co_teaching(client, db):
    """소유한 클래스가 진행 중이면 탈퇴는 지금처럼 막힌다 — 막힌 탈퇴는 공동 강사 자리도
    건드리지 않는다."""

    co = login(client, "co")
    create_class(client, co["access"], name="내가 연 클래스")
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], name="함께 가르치는 클래스")
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")

    assert _withdraw(client, co["access"]).status_code == 409

    assert _teaches(client, co["access"], class_id)
