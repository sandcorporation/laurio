"""상대편 행동 뒤 열어 둔 화면을 맞추는 재조회 신호 (#1447 10-1·10-2, ADR-0046).

- `instructors-changed` — 초대 만들기·취소·수락, 강사 이름, 떠나기·내보내기, 소유권 이전 요청·취소·
  거절·수락. 그 클래스 강사에게만 간다(방금 빠진 사람은 함께).
- `participation-changed` — 문제 열기·숨김·다시 열기, 클래스 보관·되돌리기는 그 클래스의 살아 있는
  참여자 전원에게(보관·되돌리기는 강사에게도 `instructors-changed` 로), 내보내기는 내보내진 그 사람에게만 간다.
- 참여자 구성·집계 대상이 바뀌는 일 — 새 참여(가입), 내보내기, 문제 열기·숨김·다시 열기 — 은 그 클래스 강사에게
  `instructors-changed` 로 간다(#1471 ⑦ 후속). 다른 탭·다른 강사가 열어 둔 클래스 머리·참여자 격자·문제 목록의
  참여자 수·n/N·달성률이 그것으로 다시 읽는다.

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


def _body_is(kind: str, payload: dict, class_id: int) -> bool:
    """강사 쪽 신호는 `class_id` 에 변경 번호 `rev` 하나만, 참여 신호는 `class_id` 하나만 싣는다(#1484 ④)."""

    if kind == INSTRUCTORS_CHANGED:
        return set(payload) == {"class_id", "rev"} and payload["class_id"] == class_id and isinstance(payload["rev"], int)
    return payload == {"class_id": class_id}


def _assert_only(kind: str, class_id: int, receivers: set[str]) -> None:
    everyone = {"owner", "co", "alice", "bob", "outsider-owner", "outsider"}
    for uid in everyone:
        got = _signals(uid, kind)
        if uid in receivers:
            assert got and all(_body_is(kind, p, class_id) for p in got), (uid, got)
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
    assert [p["class_id"] for p in _signals("newcomer", INSTRUCTORS_CHANGED)] == [s["class_id"]]
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


def test_hiding_a_problem_signals_the_live_participants_and_the_instructors(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, s["owner"]["access"], f"{s['class_id']}/problems/{s['problem'].id}/hide")
    assert response.status_code == 200, response.content

    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"alice", "bob"})
    # 열린 문제 수(n/N 의 N·달성률)가 바뀐다 — 다른 강사가 열어 둔 격자·문제 목록도 다시 읽는다(#1471 ⑦ 후속).
    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})


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


def test_expelling_signals_the_expelled_participant_and_the_instructors(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    members = client.get(f"{CLASSES_URL}/{s['class_id']}/members", **auth_header(s["owner"]["access"])).json()
    alice_id = next(m["id"] for m in members if m["display_name"] == "앨리스")
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, s["owner"]["access"], f"{s['class_id']}/members/{alice_id}/expel")
    assert response.status_code == 200, response.content

    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"alice"})
    # 격자의 그 행·달성률 분모가 바뀐다 — 강사의 열린 화면이 다시 읽는다(#1471 ⑦ 후속). 내보내진 사람은 강사 신호를
    # 받지 않는다(강사가 아니다).
    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})

    # 내보내진 사람은 그 뒤의 숨김 신호를 받지 않는다.
    _clear()
    with django_capture_on_commit_callbacks(execute=True):
        _post(client, s["owner"]["access"], f"{s['class_id']}/problems/{s['problem'].id}/hide")
    _assert_only(PARTICIPATION_CHANGED, s["class_id"], {"bob"})


def test_joining_signals_the_class_instructors_only(client, db, django_capture_on_commit_callbacks):
    """새 참여자는 격자의 새 행이고 달성률 분모다 — 강사의 열린 화면이 다시 읽는다(#1471 ⑦ 후속).
    다른 참여자·바깥 사람은 받지 않는다."""

    s = _scene(client)
    newcomer = login(client, uid="newcomer")
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        join_class(client, newcomer["access"], s["class_id"], instructor_access=s["owner"]["access"], display_name="새내기")

    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], {"owner", "co"})
    assert _signals("newcomer", INSTRUCTORS_CHANGED) == []
    _assert_only(PARTICIPATION_CHANGED, s["class_id"], set())


def test_joining_again_sends_no_signal(client, db, django_capture_on_commit_callbacks):
    """이미 참여자면 행이 그대로다 — 바뀐 것이 없으니 신호도 없다."""

    s = _scene(client)
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        join_class(client, s["alice"]["access"], s["class_id"], instructor_access=s["owner"]["access"], display_name="앨리스")

    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], set())


def test_expelling_twice_signals_only_once(client, db, django_capture_on_commit_callbacks):
    s = _scene(client)
    members = client.get(f"{CLASSES_URL}/{s['class_id']}/members", **auth_header(s["owner"]["access"])).json()
    alice_id = next(m["id"] for m in members if m["display_name"] == "앨리스")
    _post(client, s["owner"]["access"], f"{s['class_id']}/members/{alice_id}/expel")
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        _post(client, s["owner"]["access"], f"{s['class_id']}/members/{alice_id}/expel")

    _assert_only(INSTRUCTORS_CHANGED, s["class_id"], set())


# --- #1484 ④ 변경 번호 ----------------------------------------------------------------


def _class_rev(client, access: str, class_id: int) -> int:
    response = client.get(f"{CLASSES_URL}/{class_id}", **auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()["signal_rev"]


def test_each_instructor_change_carries_a_higher_rev_that_the_class_response_reports(
    client, db, django_capture_on_commit_callbacks
):
    s = _scene(client)
    owner, class_id = s["owner"]["access"], s["class_id"]
    _clear()

    with django_capture_on_commit_callbacks(execute=True):
        create_co_instructor_invite(client, owner, class_id)
    first = _signals("owner", INSTRUCTORS_CHANGED)
    assert len(first) == 1
    # 신호의 번호와 그 뒤 클래스 응답의 번호가 같다 — 화면이 이 응답으로 그 신호를 이미 반영했음을 안다.
    assert _class_rev(client, owner, class_id) == first[0]["rev"]

    with django_capture_on_commit_callbacks(execute=True):
        create_co_instructor_invite(client, owner, class_id)
    second = _signals("owner", INSTRUCTORS_CHANGED)
    assert [p["rev"] for p in second] == [first[0]["rev"], first[0]["rev"] + 1]
    # 같은 변경의 두 수신자는 같은 번호를 받는다.
    assert _signals("co", INSTRUCTORS_CHANGED)[-1]["rev"] == second[-1]["rev"]
    assert _class_rev(client, owner, class_id) == second[-1]["rev"]


def test_a_stale_class_instance_saving_does_not_rewind_the_rev(client, db, django_capture_on_commit_callbacks):
    from classroom.models import Class

    s = _scene(client)
    owner, class_id = s["owner"]["access"], s["class_id"]
    stale = Class.objects.get(pk=class_id)
    with django_capture_on_commit_callbacks(execute=True):
        create_co_instructor_invite(client, owner, class_id)
    bumped = _class_rev(client, owner, class_id)
    assert bumped > stale.signal_rev

    stale.name = "바뀐 이름"
    stale.save()

    assert _class_rev(client, owner, class_id) == bumped
