"""클래스 관리의 「강사」 영역 — 강사 목록과 대기 중인 공동 강사 초대를 보고 취소한다
(#562, spec #558, ADR-0055, CONTEXT.md 「공동 강사」·「공동 강사 초대」).

강사 누구나(소유자든 공동 강사든) 보고 누구나 취소한다 — 초대는 소유자 전용이 아니다.
보관된 클래스에서도 된다. 준비와 확인은 전부 마운트된 HTTP API 로 한다
(`tests.classroom_scenarios`). 만료만 주입 가능한 시계(ADR-0003)를 옮겨 본다.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

from core.models import ClockOverride
from tests.classroom_scenarios import (
    CLASSES_URL,
    accept_co_instructor_invite,
    add_co_instructor,
    archive_class,
    auth_header,
    cancel_co_instructor_invite,
    create_class,
    create_co_instructor_invite,
    list_instructors,
    list_pending_co_instructor_invites,
    login,
    preview_co_instructor_invite,
)


def _set_clock(at) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


# --- 강사 목록 ------------------------------------------------------------------------


def test_the_roster_shows_the_owner_first_and_then_co_instructors_in_the_order_they_accepted(client, db):
    owner = login(client, "owner")
    first = login(client, "first")
    second = login(client, "second")
    class_id = create_class(client, owner["access"])  # 소유자의 강사 이름은 「강사」
    add_co_instructor(client, owner["access"], class_id, first["access"], display_name="보조 강사")
    add_co_instructor(client, owner["access"], class_id, second["access"], display_name="조교")

    roster = list_instructors(client, owner["access"], class_id)

    assert [(row["display_name"], row["role"], row["is_me"]) for row in roster] == [
        ("강사", "owner", True),
        ("보조 강사", "co_instructor", False),
        ("조교", "co_instructor", False),
    ]
    # 소유자는 초대를 수락해 들어온 사람이 아니다 — 수락한 때는 공동 강사에게만 있다.
    assert roster[0]["accepted_at"] is None
    assert roster[1]["accepted_at"] is not None
    assert roster[1]["accepted_at"] <= roster[2]["accepted_at"]


def test_a_co_instructor_sees_the_same_roster_with_themselves_marked(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")

    roster = list_instructors(client, co["access"], class_id)

    assert [(row["display_name"], row["role"], row["is_me"]) for row in roster] == [
        ("강사", "owner", False),
        ("보조 강사", "co_instructor", True),
    ]


# --- 대기 중인 초대 -------------------------------------------------------------------


def test_only_pending_invites_are_listed(client, db):
    start = timezone.now()
    _set_clock(start)
    owner = login(client, "owner")
    helper = login(client, "helper")
    class_id = create_class(client, owner["access"])
    expiring = create_co_instructor_invite(client, owner["access"], class_id)
    _set_clock(start + timedelta(days=2))
    accepted = create_co_instructor_invite(client, owner["access"], class_id)
    cancelled = create_co_instructor_invite(client, owner["access"], class_id)
    pending = create_co_instructor_invite(client, owner["access"], class_id)
    assert accept_co_instructor_invite(client, helper["access"], accepted["token"]).status_code == 200
    assert cancel_co_instructor_invite(client, owner["access"], class_id, cancelled["id"]).status_code == 204
    _set_clock(start + timedelta(days=7, seconds=1))  # 처음 것만 만료된다

    listed = list_pending_co_instructor_invites(client, owner["access"], class_id)

    assert [row["id"] for row in listed] == [pending["id"]]
    assert listed[0]["token"] == pending["token"]
    assert listed[0]["expires_at"] == pending["expires_at"]
    assert listed[0]["created_at"] == pending["created_at"]
    assert {expiring["id"], accepted["id"], cancelled["id"]}.isdisjoint(row["id"] for row in listed)


def test_each_pending_invite_names_who_made_it(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    by_owner = create_co_instructor_invite(client, owner["access"], class_id)
    by_co = create_co_instructor_invite(client, co["access"], class_id)

    listed = {row["id"]: row for row in list_pending_co_instructor_invites(client, co["access"], class_id)}

    assert (listed[by_owner["id"]]["created_by_name"], listed[by_owner["id"]]["created_by_me"]) == ("강사", False)
    assert (listed[by_co["id"]]["created_by_name"], listed[by_co["id"]]["created_by_me"]) == ("보조 강사", True)


# --- 취소 -----------------------------------------------------------------------------


def test_a_cancelled_invite_link_says_cancelled_and_cannot_be_accepted(client, db):
    owner = login(client, "owner")
    helper = login(client, "helper")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    assert cancel_co_instructor_invite(client, owner["access"], class_id, invite["id"]).status_code == 204

    preview = preview_co_instructor_invite(client, invite["token"]).json()
    assert preview["status"] == "cancelled"
    assert preview["status_message"].startswith("취소된 초대입니다.")
    refused = accept_co_instructor_invite(client, helper["access"], invite["token"])
    assert refused.status_code == 410
    assert refused.json()["detail"] == preview["status_message"]
    assert [row["role"] for row in list_instructors(client, owner["access"], class_id)] == ["owner"]


def test_a_co_instructor_can_cancel_an_invite_the_owner_made(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)

    response = cancel_co_instructor_invite(client, co["access"], class_id, invite["id"])

    assert response.status_code == 204, response.content
    assert list_pending_co_instructor_invites(client, owner["access"], class_id) == []


def test_cancelling_an_invite_that_is_no_longer_pending_is_409_and_changes_nothing(client, db):
    owner = login(client, "owner")
    helper = login(client, "helper")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)
    assert accept_co_instructor_invite(client, helper["access"], invite["token"]).status_code == 200

    response = cancel_co_instructor_invite(client, owner["access"], class_id, invite["id"])

    assert response.status_code == 409
    assert response.json()["detail"].startswith("이미 쓰인 초대입니다.")
    assert preview_co_instructor_invite(client, invite["token"]).json()["status"] == "accepted"


def test_another_classs_invite_and_another_persons_class_are_404(client, db):
    owner = login(client, "owner")
    stranger = login(client, "stranger")
    class_id = create_class(client, owner["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)
    strangers_class_id = create_class(client, stranger["access"], with_key=False)

    # 남의 클래스는 「없다」 — 목록도 취소도.
    assert client.get(f"{CLASSES_URL}/{class_id}/instructors", **auth_header(stranger["access"])).status_code == 404
    assert (
        client.get(f"{CLASSES_URL}/{class_id}/co-instructor-invites", **auth_header(stranger["access"])).status_code
        == 404
    )
    assert cancel_co_instructor_invite(client, stranger["access"], class_id, invite["id"]).status_code == 404
    # 자기 클래스의 주소에 남의 초대 id 를 넣어도 「없다」 — 초대는 클래스에 묶여 있다.
    assert cancel_co_instructor_invite(client, stranger["access"], strangers_class_id, invite["id"]).status_code == 404
    assert preview_co_instructor_invite(client, invite["token"]).json()["status"] == "pending"


def test_an_archived_class_still_lists_and_cancels(client, db):
    owner = login(client, "owner")
    co = login(client, "co")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"])
    invite = create_co_instructor_invite(client, owner["access"], class_id)
    archive_class(client, owner["access"], class_id)

    assert [row["role"] for row in list_instructors(client, co["access"], class_id)] == ["owner", "co_instructor"]
    assert [row["id"] for row in list_pending_co_instructor_invites(client, co["access"], class_id)] == [invite["id"]]
    assert cancel_co_instructor_invite(client, co["access"], class_id, invite["id"]).status_code == 204
    assert list_pending_co_instructor_invites(client, co["access"], class_id) == []


def test_the_giver_of_an_ownership_transfer_is_listed_as_having_handed_over_not_accepted(client, db):
    """넘긴 사람은 초대를 수락해 들어온 사람이 아니다(#565) — 그 줄의 시각은 「넘긴 때」로 읽힌다."""

    from tests.classroom_scenarios import transfer_ownership

    owner = login(client, "owner")
    co = login(client, "co")
    helper = login(client, "helper")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    add_co_instructor(client, owner["access"], class_id, helper["access"], display_name="조교")
    transfer_ownership(client, owner["access"], class_id, co["access"], recipient_name="보조 강사")

    roster = list_instructors(client, co["access"], class_id)

    assert [(row["display_name"], row["role"], row["joined_by"]) for row in roster] == [
        ("보조 강사", "owner", None),
        ("조교", "co_instructor", "invite"),
        ("강사", "co_instructor", "ownership_transfer"),
    ]
