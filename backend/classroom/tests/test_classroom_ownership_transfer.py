"""소유권 이전 — 소유자가 요청하고, 받는 공동 강사가 수락해야 넘어가고, 넘기면 채점 키가 비워진다
(#564, spec #558, ADR-0055, CONTEXT.md 「소유권 이전」).

준비와 확인은 전부 마운트된 HTTP API 로 한다(`tests.classroom_scenarios`). 7일 만료는 주입
가능한 시계(`core.clock.Clock`, ADR-0003)를 옮겨 본다.
"""

from __future__ import annotations

import threading
from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from classroom.instructor_scope import OWNER_ONLY_MESSAGE
from core.models import ClockOverride
from tests.classroom_scenarios import (
    CLASSES_URL,
    accept_ownership_transfer,
    add_co_instructor,
    archive_class,
    auth_header,
    cancel_ownership_transfer,
    co_instructor_id_of,
    create_class,
    create_open_problem,
    decline_ownership_transfer,
    force_real_scoring_adapter,
    get_class,
    join_class,
    leave_class,
    list_instructors,
    list_taught_classes,
    login,
    mine,
    patch_class,
    pending_ownership_transfer,
    remove_co_instructor,
    request_ownership_transfer,
    respond_to_models_endpoint,
    respond_with_verdict,
    run_scan,
    set_key,
    submit_repository,
    transfer_ownership,
)


def _set_clock(at) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _owner_with_co(client, *, co_name: str = "보조 강사"):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    patch_class(client, owner["access"], class_id, {"instructor_display_name": "주강사"})
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name=co_name)
    return owner, co, class_id


def _request(client, owner, class_id, name: str = "보조 강사") -> dict:
    response = request_ownership_transfer(
        client, owner["access"], class_id, co_instructor_id_of(client, owner["access"], class_id, name)
    )
    assert response.status_code == 201, response.content
    return response.json()


def _role(client, access: str, class_id: int) -> str | None:
    rows = {row["id"]: row["role"] for row in list_taught_classes(client, access)}
    return rows.get(class_id)


def _owner_only_calls(client, access: str, class_id: int) -> dict[str, int]:
    """소유자 전용 넷의 응답 — 키, 소유자의 강사 이름 칸, 공동 강사 내보내기(없는 줄이라 소유자면 404), 이전 요청
    (없는 줄이라 소유자면 404). 삭제는 클래스를 없애므로 따로 본다."""

    return {
        "key": client.put(
            f"{CLASSES_URL}/{class_id}/openai-key",
            data={"api_key": "sk-probe"},
            content_type="application/json",
            **auth_header(access),
        ).status_code,
        "owner_name": client.patch(
            f"{CLASSES_URL}/{class_id}",
            data={"instructor_display_name": "넘겨받은 강사"},
            content_type="application/json",
            **auth_header(access),
        ).status_code,
        "remove": remove_co_instructor(client, access, class_id, 987654321).status_code,
        "transfer": request_ownership_transfer(client, access, class_id, 987654321).status_code,
    }


# --- 요청 --------------------------------------------------------------------------------


def test_nothing_changes_before_the_recipient_accepts(client, db):
    owner, co, class_id = _owner_with_co(client)
    before = get_class(client, owner["access"], class_id)

    transfer = _request(client, owner, class_id)

    assert _role(client, owner["access"], class_id) == "owner"
    assert _role(client, co["access"], class_id) == "co_instructor"
    after = get_class(client, owner["access"], class_id)
    assert (after["has_openai_key"], after["openai_key_masked"]) == (True, before["openai_key_masked"])
    assert _owner_only_calls(client, co["access"], class_id) == {
        "key": 403, "owner_name": 403, "remove": 403, "transfer": 403,
    }
    # 두 사람 모두 클래스 화면에서 같은 대기 요청을 본다 — 받는 사람에게는 「나」로.
    seen_by_owner = pending_ownership_transfer(client, owner["access"], class_id)
    seen_by_co = pending_ownership_transfer(client, co["access"], class_id)
    assert seen_by_owner["id"] == seen_by_co["id"] == transfer["id"]
    assert seen_by_owner["recipient_display_name"] == "보조 강사"
    assert seen_by_owner["recipient_co_instructor_id"] == co_instructor_id_of(client, owner["access"], class_id, "보조 강사")
    assert (seen_by_owner["recipient_is_me"], seen_by_co["recipient_is_me"]) == (False, True)


def test_a_second_request_is_refused_while_one_is_pending(client, db):
    owner, co, class_id = _owner_with_co(client)
    other = login(client, "other")
    add_co_instructor(client, owner["access"], class_id, other["access"], display_name="조교")
    first = _request(client, owner, class_id)

    second = request_ownership_transfer(
        client, owner["access"], class_id, co_instructor_id_of(client, owner["access"], class_id, "조교")
    )

    assert second.status_code == 409
    assert pending_ownership_transfer(client, owner["access"], class_id)["id"] == first["id"]


def test_only_a_co_instructor_of_this_class_can_receive(client, db):
    owner, co, class_id = _owner_with_co(client)
    other_owner = login(client, "other-owner")
    other_class = create_class(client, other_owner["access"], name="남의 클래스")
    stranger = login(client, "stranger")
    add_co_instructor(client, other_owner["access"], other_class, stranger["access"], display_name="남의 조교")
    strangers_row = co_instructor_id_of(client, other_owner["access"], other_class, "남의 조교")

    assert request_ownership_transfer(client, owner["access"], class_id, strangers_row).status_code == 404
    assert pending_ownership_transfer(client, owner["access"], class_id) is None


def test_a_co_instructor_cannot_request_or_cancel(client, db):
    owner, co, class_id = _owner_with_co(client)
    other = login(client, "other")
    add_co_instructor(client, owner["access"], class_id, other["access"], display_name="조교")
    transfer = _request(client, owner, class_id)

    cancelled = cancel_ownership_transfer(client, other["access"], class_id, transfer["id"])

    assert cancelled.status_code == 403
    assert cancelled.json()["detail"] == OWNER_ONLY_MESSAGE
    assert pending_ownership_transfer(client, owner["access"], class_id)["id"] == transfer["id"]


def test_only_the_recipient_can_accept_or_decline(client, db):
    owner, co, class_id = _owner_with_co(client)
    other = login(client, "other")
    add_co_instructor(client, owner["access"], class_id, other["access"], display_name="조교")
    transfer = _request(client, owner, class_id)

    for who in (owner, other):
        assert accept_ownership_transfer(client, who["access"], class_id, transfer["id"]).status_code == 403
        assert decline_ownership_transfer(client, who["access"], class_id, transfer["id"]).status_code == 403
    assert _role(client, owner["access"], class_id) == "owner"


# --- 수락 --------------------------------------------------------------------------------


def test_accepting_moves_owner_only_work_to_the_recipient_and_keeps_the_giver_as_co_instructor(client, db):
    owner, co, class_id = _owner_with_co(client)
    transfer = _request(client, owner, class_id)

    accepted = accept_ownership_transfer(client, co["access"], class_id, transfer["id"])

    assert accepted.status_code == 200, accepted.content
    assert accepted.json()["role"] == "owner"
    assert _role(client, co["access"], class_id) == "owner"
    assert _role(client, owner["access"], class_id) == "co_instructor"
    # 넘긴 사람에게 소유자 전용 넷은 403 이고, 공동 강사로 클래스를 계속 다룬다.
    assert _owner_only_calls(client, owner["access"], class_id) == {
        "key": 403, "owner_name": 403, "remove": 403, "transfer": 403,
    }
    assert client.delete(f"{CLASSES_URL}/{class_id}", **auth_header(owner["access"])).status_code == 403
    problem = create_open_problem(client, owner["access"], class_id)
    assert problem.id
    # 강사 이름은 각자의 것을 들고 자리만 바꾼다.
    rows = [(r["role"], r["display_name"]) for r in list_instructors(client, co["access"], class_id)]
    assert rows == [("owner", "보조 강사"), ("co_instructor", "주강사")]
    assert get_class(client, co["access"], class_id)["instructor_display_name"] == "보조 강사"
    assert pending_ownership_transfer(client, co["access"], class_id) is None
    # 새 소유자에게는 소유자 전용이 열린다(키는 위에서 따로 본다).
    calls = _owner_only_calls(client, co["access"], class_id)
    assert (calls["owner_name"], calls["remove"], calls["transfer"]) == (200, 404, 404)
    giver_row = co_instructor_id_of(client, co["access"], class_id, "주강사")
    assert remove_co_instructor(client, co["access"], class_id, giver_row).status_code == 204
    assert _role(client, owner["access"], class_id) is None


def test_the_new_owner_can_hand_it_back(client, db):
    owner, co, class_id = _owner_with_co(client)
    transfer_ownership(client, owner["access"], class_id, co["access"], recipient_name="보조 강사")

    transfer_ownership(client, co["access"], class_id, owner["access"], recipient_name="주강사")

    assert _role(client, owner["access"], class_id) == "owner"
    rows = [(r["role"], r["display_name"]) for r in list_instructors(client, owner["access"], class_id)]
    assert rows == [("owner", "주강사"), ("co_instructor", "보조 강사")]


def test_accepting_empties_the_scoring_key_but_keeps_usage(client, db, monkeypatch):
    owner, co, class_id = _owner_with_co(client)
    problem = create_open_problem(client, owner["access"], class_id)
    learner = login(client, "learner")
    join_class(client, learner["access"], class_id, instructor_access=owner["access"])
    with force_real_scoring_adapter():
        submit_repository(client, learner["access"], class_id, problem.id)
        respond_with_verdict(monkeypatch, problem.item_id, total_tokens=120)
        run_scan(client)
    before = get_class(client, owner["access"], class_id)
    assert before["token_usage_total"] == 120

    transfer_ownership(client, owner["access"], class_id, co["access"], recipient_name="보조 강사")

    after = get_class(client, co["access"], class_id)
    assert (after["has_openai_key"], after["openai_key_masked"], after["openai_key_status"]) == (False, None, None)
    assert after["token_usage_total"] == 120

    # 키가 빈 동안 낸 시도는 「키」 사유로 대기하다 새 키 저장 뒤 채점된다.
    with force_real_scoring_adapter():
        submit_repository(client, learner["access"], class_id, problem.id)
        respond_with_verdict(monkeypatch, problem.item_id, total_tokens=30)
        run_scan(client)
        waiting = mine(client, learner["access"], class_id, problem.id)["submissions"][0]
        assert (waiting["status"], waiting["pending_reason"]) == ("pending", "no_api_key")

        respond_to_models_endpoint(monkeypatch)
        set_key(client, co["access"], class_id, "sk-new-owner-key")
        run_scan(client)
    scored = mine(client, learner["access"], class_id, problem.id)["submissions"][0]
    assert (scored["status"], scored["pending_reason"]) == ("scored", None)
    assert get_class(client, co["access"], class_id)["token_usage_total"] == 150


def test_transfer_works_in_an_archived_class(client, db):
    owner, co, class_id = _owner_with_co(client)
    archive_class(client, owner["access"], class_id)

    transfer_ownership(client, owner["access"], class_id, co["access"], recipient_name="보조 강사")

    assert _role(client, co["access"], class_id) == "owner"


# --- 거절·취소·만료 ------------------------------------------------------------------------


def test_a_declined_request_cannot_be_accepted_and_a_new_one_can_be_made(client, db):
    owner, co, class_id = _owner_with_co(client)
    transfer = _request(client, owner, class_id)

    assert decline_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 204

    assert accept_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 409
    assert pending_ownership_transfer(client, owner["access"], class_id) is None
    assert _role(client, owner["access"], class_id) == "owner"
    assert _request(client, owner, class_id)["id"] != transfer["id"]


def test_a_cancelled_request_cannot_be_accepted(client, db):
    owner, co, class_id = _owner_with_co(client)
    transfer = _request(client, owner, class_id)

    assert cancel_ownership_transfer(client, owner["access"], class_id, transfer["id"]).status_code == 204

    refused = accept_ownership_transfer(client, co["access"], class_id, transfer["id"])
    assert refused.status_code == 409
    assert "취소" in refused.json()["detail"]
    assert pending_ownership_transfer(client, co["access"], class_id) is None
    assert cancel_ownership_transfer(client, owner["access"], class_id, transfer["id"]).status_code == 409


def test_a_request_expires_after_seven_days(client, db):
    start = timezone.now()
    _set_clock(start)
    owner, co, class_id = _owner_with_co(client)
    transfer = _request(client, owner, class_id)

    _set_clock(start + timedelta(days=7) - timedelta(seconds=1))
    assert pending_ownership_transfer(client, co["access"], class_id)["id"] == transfer["id"]

    _set_clock(start + timedelta(days=7))
    assert pending_ownership_transfer(client, co["access"], class_id) is None
    refused = accept_ownership_transfer(client, co["access"], class_id, transfer["id"])
    assert refused.status_code == 409
    assert "만료" in refused.json()["detail"]
    assert _role(client, owner["access"], class_id) == "owner"
    # 만료된 요청은 새 요청을 막지 않는다.
    assert _request(client, owner, class_id)["id"] != transfer["id"]


def test_another_class_request_id_is_404(client, db):
    owner, co, class_id = _owner_with_co(client)
    transfer = _request(client, owner, class_id)
    other_class = create_class(client, owner["access"], name="다른 클래스")
    add_co_instructor(client, owner["access"], other_class, co["access"], display_name="보조 강사")

    assert accept_ownership_transfer(client, co["access"], other_class, transfer["id"]).status_code == 404
    assert cancel_ownership_transfer(client, owner["access"], other_class, transfer["id"]).status_code == 404


# --- 받는 사람이 떠나면 ----------------------------------------------------------------------


@pytest.mark.parametrize("how", ["leave", "remove", "withdraw"])
def test_the_request_disappears_when_the_recipient_leaves(client, db, how):
    owner, co, class_id = _owner_with_co(client)
    transfer = _request(client, owner, class_id)

    if how == "leave":
        assert leave_class(client, co["access"], class_id).status_code == 204
    elif how == "remove":
        co_row = co_instructor_id_of(client, owner["access"], class_id, "보조 강사")
        assert remove_co_instructor(client, owner["access"], class_id, co_row).status_code == 204
    else:
        withdrawn = client.post("/api/accounts/withdrawal", content_type="application/json", **auth_header(co["access"]))
        assert withdrawn.status_code in (200, 204), withdrawn.content

    assert pending_ownership_transfer(client, owner["access"], class_id) is None
    if how != "withdraw":
        assert accept_ownership_transfer(client, co["access"], class_id, transfer["id"]).status_code == 404
    # 사라졌으니 새 요청을 막지 않는다.
    other = login(client, "other")
    add_co_instructor(client, owner["access"], class_id, other["access"], display_name="조교")
    assert _request(client, owner, class_id, "조교")["id"] != transfer["id"]


def test_the_owner_cannot_leave_but_is_told_to_hand_over(client, db):
    owner, co, class_id = _owner_with_co(client)

    refused = leave_class(client, owner["access"], class_id)

    assert refused.status_code == 409
    assert "넘기" in refused.json()["detail"]


# --- 동시성 ---------------------------------------------------------------------------------
#
# 이전 요청 행 잠금(select_for_update)이 수락·거절·취소를 줄 세운다 — 순차 이중 호출로는 실제
# 경합이 재현되지 않으므로 스레드 둘로 진짜 동시 요청을 만든다(초대 동시 수락과 같은 방식).


def _race(django_db_blocker, *calls) -> list[int]:
    from django.db import connections

    results: list[int] = [0] * len(calls)
    barrier = threading.Barrier(len(calls))

    def worker(i, call):
        try:
            with django_db_blocker.unblock():
                local = Client()
                barrier.wait()
                results[i] = call(local)
        finally:
            connections.close_all()

    threads = [threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(calls)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return results


@pytest.mark.django_db(transaction=True)
def test_two_accepts_at_once_transfer_only_once(django_db_blocker):
    with django_db_blocker.unblock():
        client = Client()
        owner, co, class_id = _owner_with_co(client)
        transfer = _request(client, owner, class_id)

        codes = _race(
            django_db_blocker,
            lambda c: accept_ownership_transfer(c, co["access"], class_id, transfer["id"]).status_code,
            lambda c: accept_ownership_transfer(c, co["access"], class_id, transfer["id"]).status_code,
        )

        assert sorted(codes) == [200, 409]
        rows = [(r["role"], r["display_name"]) for r in list_instructors(client, co["access"], class_id)]
        assert rows == [("owner", "보조 강사"), ("co_instructor", "주강사")]


@pytest.mark.django_db(transaction=True)
def test_accept_and_cancel_at_once_only_one_wins(django_db_blocker):
    with django_db_blocker.unblock():
        client = Client()
        owner, co, class_id = _owner_with_co(client)
        transfer = _request(client, owner, class_id)

        accept_code, cancel_code = _race(
            django_db_blocker,
            lambda c: accept_ownership_transfer(c, co["access"], class_id, transfer["id"]).status_code,
            lambda c: cancel_ownership_transfer(c, owner["access"], class_id, transfer["id"]).status_code,
        )

        if accept_code == 200:
            # 수락이 먼저 끝났다 — 넘긴 사람은 이제 소유자가 아니거나(403) 끝난 요청을 본다(409).
            assert cancel_code in (403, 409)
            assert _role(client, co["access"], class_id) == "owner"
        else:
            assert (accept_code, cancel_code) == (409, 204)
            assert _role(client, owner["access"], class_id) == "owner"


@pytest.mark.django_db(transaction=True)
def test_accept_and_the_recipient_being_removed_at_once_never_half_transfers(django_db_blocker):
    with django_db_blocker.unblock():
        client = Client()
        owner, co, class_id = _owner_with_co(client)
        transfer = _request(client, owner, class_id)
        co_row = co_instructor_id_of(client, owner["access"], class_id, "보조 강사")

        accept_code, remove_code = _race(
            django_db_blocker,
            lambda c: accept_ownership_transfer(c, co["access"], class_id, transfer["id"]).status_code,
            lambda c: remove_co_instructor(c, owner["access"], class_id, co_row).status_code,
        )

        roles = (_role(client, owner["access"], class_id), _role(client, co["access"], class_id))
        if accept_code == 200:
            assert remove_code in (403, 404)
            assert roles == ("co_instructor", "owner")
        else:
            assert (accept_code, remove_code) == (404, 204)
            assert roles == ("owner", None)
