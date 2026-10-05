"""공동 강사 초대 — 만들고, 받은 사람이 수락하면 공동 강사가 된다 (#561, spec #558,
ADR-0055, CONTEXT.md 「공동 강사」·「공동 강사 초대」).

준비와 확인은 전부 마운트된 HTTP API 로 한다(`tests.classroom_scenarios`). 시계만 예외다 —
7일 만료는 주입 가능한 시계(`core.clock.Clock`, ADR-0003)를 옮겨 본다.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

import pytest
from django.utils import timezone

from core.models import ClockOverride
from tests.classroom_scenarios import (
    CLASSES_URL,
    accept_co_instructor_invite,
    add_co_instructor,
    archive_class,
    auth_header,
    create_class,
    force_real_scoring_adapter,
    create_co_instructor_invite,
    create_open_problem,
    instructor_submissions,
    join_class,
    list_problems,
    list_taught_classes,
    login,
    mine,
    preview_co_instructor_invite,
    respond_with_verdict,
    roster_grid,
    run_scan,
    submit_repository,
)


@pytest.fixture
def real_scoring():
    # 통과를 만들려면 벤더 응답을 흉내 내야 한다 — 기본값(fake) 어댑터는 그 경로를 타지 않는다.
    with force_real_scoring_adapter():
        yield


def _set_clock(at) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _joined_class_ids(client, access: str) -> list[int]:
    response = client.get(f"{CLASSES_URL}/joined", **auth_header(access))
    assert response.status_code == 200, response.content
    return [row["id"] for row in response.json()]


# --- 만들고 수락한다 ------------------------------------------------------------------


def test_an_accepted_invite_puts_the_class_in_the_accepters_list_as_co_instructor(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], name="파이썬 기초")
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    helper = login(client, "helper")
    accepted = accept_co_instructor_invite(client, helper["access"], invite["token"], display_name="보조 강사")

    assert accepted.status_code == 200, accepted.content
    assert accepted.json() == {"class_id": class_id, "class_name": "파이썬 기초"}
    rows = {row["id"]: row for row in list_taught_classes(client, helper["access"])}
    assert rows[class_id]["role"] == "co_instructor"
    assert {row["id"]: row["role"] for row in list_taught_classes(client, owner["access"])} == {class_id: "owner"}


def test_the_invite_expires_seven_days_after_it_was_made(client, db):
    start = timezone.now()
    _set_clock(start)
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)
    assert datetime.fromisoformat(invite["expires_at"]) - start < timedelta(days=7, milliseconds=1)
    assert datetime.fromisoformat(invite["expires_at"]) - start > timedelta(days=7, milliseconds=-1)

    _set_clock(start + timedelta(days=7))
    late = login(client, "late")
    rejected = accept_co_instructor_invite(client, late["access"], invite["token"])

    assert rejected.status_code == 410
    assert "만료" in rejected.json()["detail"]
    assert preview_co_instructor_invite(client, invite["token"]).json()["status"] == "expired"
    assert class_id not in [row["id"] for row in list_taught_classes(client, late["access"])]


def test_the_invite_is_still_good_just_before_seven_days(client, db):
    start = timezone.now()
    _set_clock(start)
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    _set_clock(start + timedelta(days=7) - timedelta(seconds=1))
    helper = login(client, "helper")

    assert accept_co_instructor_invite(client, helper["access"], invite["token"]).status_code == 200


def test_an_invite_is_used_once(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)
    first = login(client, "first")
    second = login(client, "second")

    assert accept_co_instructor_invite(client, first["access"], invite["token"]).status_code == 200
    again = accept_co_instructor_invite(client, second["access"], invite["token"])

    assert again.status_code == 410
    assert "이미 쓰인" in again.json()["detail"]
    assert class_id not in [row["id"] for row in list_taught_classes(client, second["access"])]


def test_several_invites_can_be_open_at_once(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    one = create_co_instructor_invite(client, owner["access"], class_id)
    two = create_co_instructor_invite(client, owner["access"], class_id)
    assert one["token"] != two["token"]

    first = login(client, "first")
    second = login(client, "second")
    assert accept_co_instructor_invite(client, first["access"], one["token"]).status_code == 200
    assert accept_co_instructor_invite(client, second["access"], two["token"]).status_code == 200


def test_a_co_instructor_can_invite_too(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    helper = login(client, "helper")
    add_co_instructor(client, owner["access"], class_id, helper["access"])

    invite = create_co_instructor_invite(client, helper["access"], class_id)
    third = login(client, "third")

    assert accept_co_instructor_invite(client, third["access"], invite["token"]).status_code == 200


def test_someone_who_is_not_an_instructor_cannot_make_an_invite(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    stranger = login(client, "stranger")

    response = client.post(
        f"{CLASSES_URL}/{class_id}/co-instructor-invites", **auth_header(stranger["access"])
    )

    assert response.status_code == 404


# --- 이미 강사인 사람 -----------------------------------------------------------------


def test_the_owner_accepting_their_own_invite_is_409_and_the_invite_survives(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    rejected = accept_co_instructor_invite(client, owner["access"], invite["token"])

    assert rejected.status_code == 409
    assert preview_co_instructor_invite(client, invite["token"]).json()["status"] == "pending"
    helper = login(client, "helper")
    assert accept_co_instructor_invite(client, helper["access"], invite["token"]).status_code == 200


def test_a_co_instructor_accepting_another_invite_is_409(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    helper = login(client, "helper")
    add_co_instructor(client, owner["access"], class_id, helper["access"])
    second_invite = create_co_instructor_invite(client, owner["access"], class_id)

    assert accept_co_instructor_invite(client, helper["access"], second_invite["token"]).status_code == 409
    assert preview_co_instructor_invite(client, second_invite["token"]).json()["status"] == "pending"


# --- 미리보기 --------------------------------------------------------------------------


def test_the_preview_opens_without_login_and_names_the_class_and_its_instructors(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"], name="자료구조")
    helper = login(client, "helper")
    add_co_instructor(client, owner["access"], class_id, helper["access"], display_name="김보조")
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    response = preview_co_instructor_invite(client, invite["token"])

    assert response.status_code == 200
    body = response.json()
    assert body["class_id"] == class_id
    assert body["class_name"] == "자료구조"
    assert body["instructor_names"] == ["강사", "김보조"]
    assert body["status"] == "pending"
    assert body["status_message"] is None
    assert body["already_instructor"] is False


def test_the_preview_tells_an_instructor_they_already_teach_here(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    assert preview_co_instructor_invite(client, invite["token"], owner["access"]).json()["already_instructor"] is True


def test_a_used_invite_preview_says_so(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)
    helper = login(client, "helper")
    accept_co_instructor_invite(client, helper["access"], invite["token"])

    body = preview_co_instructor_invite(client, invite["token"]).json()

    assert body["status"] == "accepted"
    assert "이미 쓰인" in body["status_message"]


def test_an_unknown_token_is_404(client, db):
    someone = login(client, "someone")

    assert preview_co_instructor_invite(client, "no-such-token").status_code == 404
    assert accept_co_instructor_invite(client, someone["access"], "no-such-token").status_code == 404


def test_accepting_needs_login(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    response = client.post(
        f"/api/classroom/co-instructor-invites/{invite['token']}/accept",
        data={"display_name": "익명"},
        content_type="application/json",
    )

    assert response.status_code == 401


def test_the_instructor_name_is_checked_for_banned_words(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)
    helper = login(client, "helper")

    rejected = accept_co_instructor_invite(client, helper["access"], invite["token"], display_name="운영자")

    assert rejected.status_code == 422
    assert preview_co_instructor_invite(client, invite["token"]).json()["status"] == "pending"


# --- 보관된 클래스 ---------------------------------------------------------------------


def test_an_archived_class_can_still_invite_and_accept(client, db):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    archive_class(client, owner["access"], class_id)

    invite = create_co_instructor_invite(client, owner["access"], class_id)
    assert preview_co_instructor_invite(client, invite["token"]).json()["archived"] is True
    helper = login(client, "helper")

    assert accept_co_instructor_invite(client, helper["access"], invite["token"]).status_code == 200
    assert class_id in [row["id"] for row in list_taught_classes(client, helper["access"])]


# --- 참여자가 수락하면 집계에서 빠지고 시도는 남는다 ------------------------------------


def test_a_participant_who_accepts_leaves_the_rate_but_keeps_their_attempts(client, db, monkeypatch, real_scoring):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id)
    learner = login(client, "learner")
    other = login(client, "other")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"], display_name="학생A")
    join_class(client, other["access"], class_id, instructor_access=owner["access"], display_name="학생B")
    submit_repository(client, learner["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)
    before = list_problems(client, owner["access"], class_id)[0]
    assert (before["passed_count"], before["member_count"]) == (1, 2)

    add_co_instructor(client, owner["access"], class_id, learner["access"])

    after = list_problems(client, owner["access"], class_id)[0]
    assert (after["passed_count"], after["member_count"]) == (0, 1)
    grid = roster_grid(client, owner["access"], class_id)
    assert [m["is_instructor"] for m in grid["members"] if m["display_name"] == "학생A"] == [True]
    assert (grid["problems"][0]["passed_count"], grid["problems"][0]["member_count"]) == (0, 1)
    # 시도는 남는다 — 강사의 제출 현황에도, 그 사람 자신의 화면에도.
    assert len(instructor_submissions(client, owner["access"], class_id, problem.id)) == 1
    assert len(mine(client, learner["access"], class_id, problem.id)["submissions"]) == 1
    # 참여자로 든 클래스가 아니라 가르치는 클래스로 보인다.
    assert class_id not in _joined_class_ids(client, learner["access"])
    assert class_id in [row["id"] for row in list_taught_classes(client, learner["access"])]


def test_a_co_instructors_own_attempt_does_not_count_and_does_not_block_deletion(
    client, db, monkeypatch, real_scoring
):
    owner = login(client, "owner")
    class_id = create_class(client, owner["access"])
    problem = create_open_problem(client, owner["access"], class_id)
    helper = login(client, "helper")
    add_co_instructor(client, owner["access"], class_id, helper["access"])
    learner = login(client, "learner")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"])

    submit_repository(client, helper["access"], class_id, problem.id)
    submit_repository(client, owner["access"], class_id, problem.id)
    respond_with_verdict(monkeypatch, problem.item_id, is_met=True)
    run_scan(client)

    row = list_problems(client, owner["access"], class_id)[0]
    assert (row["passed_count"], row["member_count"]) == (0, 1)
    assert row["deletable"] is True
    deleted = client.delete(f"{CLASSES_URL}/{class_id}/problems/{problem.id}", **auth_header(helper["access"]))
    assert deleted.status_code == 204


# --- 1회용은 동시에 눌러도 1회용이다 ---------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_two_people_accepting_the_same_invite_at_once_leaves_one_co_instructor(django_db_blocker):
    """초대 행 잠금(select_for_update)이 두 수락을 줄 세운다 — 순차 이중 호출로는 실제 경합이
    재현되지 않으므로 스레드 둘로 진짜 동시 요청을 만든다(`test_contest_reopen`과 같은 방식)."""

    from django.db import connections
    from django.test import Client

    with django_db_blocker.unblock():
        setup = Client()
        owner = login(setup, "owner")
        class_id = create_class(setup, owner["access"], with_key=False)
        token = create_co_instructor_invite(setup, owner["access"], class_id)["token"]
        people = [login(setup, "racer-1"), login(setup, "racer-2")]

        results: list = []
        barrier = threading.Barrier(2)

        def worker(person):
            try:
                with django_db_blocker.unblock():
                    local = Client()
                    barrier.wait()
                    results.append(accept_co_instructor_invite(local, person["access"], token).status_code)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker, args=(person,)) for person in people]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        assert sorted(results) == [200, 410]
        teaching = [class_id in [row["id"] for row in list_taught_classes(setup, p["access"])] for p in people]
        assert sorted(teaching) == [False, True]
