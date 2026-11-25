"""상대편 행동 뒤 열어 둔 화면을 맞추는 재조회 신호 (#1447 10-1·10-2, ADR-0046).

- `instructors-changed` — 초대 만들기·취소·수락, 강사 이름, 떠나기·내보내기, 소유권 이전 요청·취소·
  거절·수락. 그 클래스 강사에게만 간다(방금 빠진 사람은 함께).
- `participation-changed` — 문제 열기·숨김·다시 열기, 클래스 보관·되돌리기는 그 클래스의 살아 있는
  참여자 전원에게(보관·되돌리기는 강사에게도 `instructors-changed` 로), 내보내기는 내보내진 그 사람에게만 간다.

두 신호 모두 본문은 `class_id` 하나다 — 이름·소스 같은 것을 싣지 않는다. 준비는 마운트된 HTTP API
(`tests.classroom_scenarios`), 신호는 fake 이벤트 버스의 수신자별 큐로 본다.
"""

from __future__ import annotations

from core.events import FakeEventBus
from tests.classroom_scenarios import (
    CLASSES_URL,
    accept_co_instructor_invite,
    add_co_instructor,
    archive_class,
    auth_header,
    co_instructor_id_of,
    create_class,
    create_co_instructor_invite,
    create_open_problem,
    decline_ownership_transfer,
    accept_ownership_transfer,
    join_class,
    login,
    request_ownership_transfer,
    user_id,
)

INSTRUCTORS_CHANGED = "instructors-changed"
PARTICIPATION_CHANGED = "participation-changed"


def _signals(uid: str, kind: str) -> list[dict]:
    return [e.payload for e in FakeEventBus._queues.get(user_id(uid), []) if e.kind == kind]


def _clear() -> None:
    FakeEventBus._queues.clear()


def _post(client, access: str, path: str, data: dict | None = None):
    return client.post(
        f"{CLASSES_URL}/{path}", data=data or {}, content_type="application/json", **auth_header(access)
    )


def _scene(client):
    """소유자·공동 강사·참여자 둘이 있는 클래스와, 바깥 사람(다른 클래스의 강사·참여자)."""

    owner = login(client, uid="owner")
    co = login(client, uid="co")
    alice = login(client, uid="alice")
    bob = login(client, uid="bob")
    class_id = create_class(client, owner["access"])
    add_co_instructor(client, owner["access"], class_id, co["access"], display_name="보조 강사")
    problem = create_open_problem(client, owner["access"], class_id)
    join_class(client, alice["access"], class_id, instructor_access=owner["access"], display_name="앨리스")
    join_class(client, bob["access"], class_id, instructor_access=owner["access"], display_name="밥")

    outsider_owner = login(client, uid="outsider-owner")
    outsider = login(client, uid="outsider")
    other_class = create_class(client, outsider_owner["access"], name="다른 클래스", with_key=False)
    create_open_problem(client, outsider_owner["access"], other_class)
    join_class(client, outsider["access"], other_class, instructor_access=outsider_owner["access"])
    return {"owner": owner, "co": co, "alice": alice, "bob": bob, "class_id": class_id, "problem": problem}


def _assert_only(kind: str, class_id: int, receivers: set[str]) -> None:
    everyone = {"owner", "co", "alice", "bob", "outsider-owner", "outsider"}
    for uid in everyone:
        got = _signals(uid, kind)
        if uid in receivers:
            assert got and all(p == {"class_id": class_id} for p in got), (uid, got)
        else:
            assert got == [], (uid, got)


# --- 10-1 강사 탭 ----------------------------------------------------------------


def test_accepting_an_invite_signals_the_class_instructors_only(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    newcomer = login(client, uid="newcomer")
    token = create_co_instructor_invite(client, s["owner"]["access"], s["class_id"])["token"]
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = accept_co_instructor_invite(client, newcomer["access"], token, display_name="새 강사")
    assert response.status_code == 200, response.content

    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})
    assert _signals("newcomer", INSTRUCTORS_CHANGED) == [{"class_id": s["class_id"]}]
    _assert_only(PARTICIPATION_CHANGED, s["class_id"], set())


def test_declining_a_transfer_signals_the_requesting_owner(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    co_id = co_instructor_id_of(client, s["owner"]["access"], s["class_id"], "보조 강사")
    transfer_id = request_ownership_transfer(client, s["owner"]["access"], s["class_id"], co_id).json()["id"]
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = decline_ownership_transfer(client, s["co"]["access"], s["class_id"], transfer_id)
    assert response.status_code == 204, response.content

    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})


def test_accepting_a_transfer_signals_the_old_and_new_owner(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    co_id = co_instructor_id_of(client, s["owner"]["access"], s["class_id"], "보조 강사")
    transfer_id = request_ownership_transfer(client, s["owner"]["access"], s["class_id"], co_id).json()["id"]
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = accept_ownership_transfer(client, s["co"]["access"], s["class_id"], transfer_id)
    assert response.status_code == 200, response.content

    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})


def test_removing_a_co_instructor_signals_the_removed_one_too(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    co_id = co_instructor_id_of(client, s["owner"]["access"], s["class_id"], "보조 강사")
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, s["owner"]["access"], f"{s['class_id']}/co-instructors/{co_id}/remove")
    assert response.status_code in (200, 204), response.content

    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})


# --- 10-2 제출 화면 --------------------------------------------------------------


def test_hiding_a_problem_signals_the_live_participants_only(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, s["owner"]["access"], f"{s['class_id']}/problems/{s['problem'].id}/hide")
    assert response.status_code == 200, response.content

    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"alice", "bob"})
    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], set())


def test_archiving_a_class_signals_the_live_participants_and_the_instructors(
    client, db, django_capture_on_commit_callbacks
):
    s = _scene(client)
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        archive_class(client, s["owner"]["access"], s["class_id"])

    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"alice", "bob"})
    # 참여자 행이 없는 강사의 학생 화면·다른 탭도 보관을 읽는다(#1471).
    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})


def test_unarchiving_a_class_signals_the_live_participants_and_the_instructors(
    client, db, django_capture_on_commit_callbacks
):
    s = _scene(client)
    archive_class(client, s["owner"]["access"], s["class_id"])
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, s["owner"]["access"], f"{s['class_id']}/unarchive")
    assert response.status_code == 200, response.content

    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"alice", "bob"})
    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})


def test_archiving_skips_the_expelled_and_unrelated_users(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    members = client.get(f"{CLASSES_URL}/{s['class_id']}/members", **auth_header(s["owner"]["access"])).json()
    alice_id = next(m["id"] for m in members if m["display_name"] == "앨리스")
    _post(client, s["owner"]["access"], f"{s['class_id']}/members/{alice_id}/expel")
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        archive_class(client, s["owner"]["access"], s["class_id"])

    # alice(내보내짐)와 바깥 클래스 사람은 어느 신호도 받지 않는다.
    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"bob"})
    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})


def test_expelling_signals_only_the_expelled_participant(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    members = client.get(f"{CLASSES_URL}/{s['class_id']}/members", **auth_header(s["owner"]["access"])).json()
    alice_id = next(m["id"] for m in members if m["display_name"] == "앨리스")
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, s["owner"]["access"], f"{s['class_id']}/members/{alice_id}/expel")
    assert response.status_code == 200, response.content

    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"alice"})

    # 내보내진 사람은 그 뒤의 숨김 신호를 받지 않는다.
    _clear()
    with django_capture_on_commit_callbacks(execute=True):
        _post(client, s["owner"]["access"], f"{s['class_id']}/problems/{s['problem'].id}/hide")
    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"bob"})
