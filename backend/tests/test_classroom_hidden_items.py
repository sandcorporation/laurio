"""강의실 숨은 항목(#906, 스펙 #903) — 「제출자에게 숨기기」를 켠 체크리스트 항목은 참여자 경로(문제·시도 결과·본인
완성도, 강사의 「참여자로 보기」 포함)에 내용 없이 개수·충족 수만 나간다. AI 판정·통과·완성도에는 보통 항목처럼 든다.
클래스는 숨은 필수도 허용한다. 들여온 공모전 문제는 공모전의 숨김을 그대로 따른다.

판정·완성도는 기본 가짜 어댑터가 문구 유무로 정한다(`test_classroom_quality` 와 같은 세계)."""

from __future__ import annotations

import pytest

from classroom.models import ChecklistItem, ClassroomScore
from tests.classroom_scenarios import CLASSES_URL, auth_header, create_class, join_class, login, open_problem
from tests.test_classroom_contest_problems import _import
from tests.test_classroom_quality import REQUIRED, _get, _patch_problem, _run, _submit, _url, _world
from tests.test_contest_classroom_import import _host
from tests.test_free_contest_hosting import CONTESTS_URL, _auth_header, _free_brief, category, landing_type  # noqa: F401

#: 응답 JSON 은 한글을 \u 로 내보내므로 ASCII 머리로 찾는다.
HIDDEN_REQUIRED = "HIDDENREQ5b2d 숨은 필수 항목"
HIDDEN_BONUS = "HIDDENBON8e4f 숨은 가산 항목"
SECRETS = ("HIDDENREQ5b2d", "HIDDENBON8e4f")


def _assert_no_leak(body: bytes, hidden_ids: tuple[int, ...]) -> None:
    text = body.decode()
    for secret in SECRETS:
        assert secret not in text, f"숨은 항목 문구가 샜다: {secret}"
    for hidden_id in hidden_ids:
        for key in ("id", "item_id", "checklist_item_id"):
            assert f'"{key}": {hidden_id},' not in text and f'"{key}":{hidden_id},' not in text


def _add_item(client, world: dict, label: str, grade: str, *, hidden: bool) -> int:
    response = client.post(
        _url(world, "/checklist-items"),
        data={"label": label, "grade": grade, "hidden": hidden},
        content_type="application/json",
        **auth_header(world["instructor"]["access"]),
    )
    assert response.status_code == 201, response.content
    assert response.json()["hidden"] is hidden
    return response.json()["id"]


@pytest.fixture
def hidden_world(client, db):
    world = _world(client)
    world["hidden_ids"] = (
        _add_item(client, world, HIDDEN_REQUIRED, "required", hidden=True),
        _add_item(client, world, HIDDEN_BONUS, "bonus", hidden=True),
    )
    _patch_problem(client, world, {"quality_public": True})
    # 가람은 숨은 필수까지 채워 통과하고, 나래는 보이는 필수만 채워 숨은 필수에서 떨어진다.
    _submit(client, world, "p-a", f"# {REQUIRED}\n# {HIDDEN_REQUIRED}\n")
    _submit(client, world, "p-b", f"# {REQUIRED}\n")
    _submit(client, world, "instructor", f"# {REQUIRED}\n")
    _run(client, world)
    return world


def _participant_bodies(client, world: dict, who: str) -> list[bytes]:
    bodies = []
    for suffix in ("/mine", "/quality/mine"):
        response = _get(client, world, suffix, who)
        assert response.status_code == 200, (suffix, response.content)
        bodies.append(response.content)
    return bodies


def test_instructor_sees_hidden_items_and_they_count_for_pass(client, hidden_world):
    raw = _get(client, hidden_world, "").content
    # 유출 검사가 찾는 머리가 강사 응답에는 실제로 있다(검사가 헛돌지 않는다는 대조).
    assert all(secret.encode() in raw for secret in SECRETS)
    problem = _get(client, hidden_world, "").json()
    hidden = [i for i in problem["checklist_items"] if i["hidden"]]
    assert [(i["label"], i["grade"]) for i in hidden] == [(HIDDEN_REQUIRED, "required"), (HIDDEN_BONUS, "bonus")]
    # AI 는 숨은 필수를 판정한다 — 프롬프트에 있고, 통과를 가른다.
    scores = ClassroomScore.objects.filter(submission__problem_id=hidden_world["problem_id"])
    assert all(HIDDEN_REQUIRED in s.prompt for s in scores)
    board = _get(client, hidden_world, "/quality").json()
    assert [r["display_name"] for r in board["rows"]] == ["가람"]
    assert HIDDEN_REQUIRED in [i["label"] for i in board["rows"][0]["items"]]


@pytest.mark.parametrize("who", ["p-a", "p-b"])
def test_participant_paths_do_not_leak(client, hidden_world, who):
    if who == "p-b":
        # 나래는 완성도 대상이 아니라 /quality/mine 이 404 다 — /mine 만 본다.
        response = _get(client, hidden_world, "/mine", who)
        assert response.status_code == 200
        _assert_no_leak(response.content, hidden_world["hidden_ids"])
        attempt = response.json()["submissions"][0]
        assert attempt["passed"] is False
        assert attempt["score"]["hidden_summary"] == {"total": 1, "met": 0}
        return
    for body in _participant_bodies(client, hidden_world, who):
        _assert_no_leak(body, hidden_world["hidden_ids"])
    mine = _get(client, hidden_world, "/mine", who).json()
    assert mine["problem"]["hidden_checklist_item_count"] == 2
    assert all(not i["hidden"] for i in mine["problem"]["checklist_items"])
    attempt = mine["submissions"][0]
    assert attempt["passed"] is True
    assert attempt["score"]["hidden_summary"] == {"total": 1, "met": 1}
    quality = _get(client, hidden_world, "/quality/mine", who).json()
    hidden_items = [i for i in quality["items"] if i["hidden"]]
    assert [i["label"] for i in hidden_items] == ["숨은 항목 1", "숨은 항목 2"]
    assert all(i["reasoning"] == "" and i["item_id"] < 0 for i in hidden_items)


def test_instructor_viewing_as_participant_sees_the_same_filtered_problem(client, hidden_world):
    response = _get(client, hidden_world, "/mine", "instructor")
    assert response.status_code == 200
    assert response.json()["viewing_as_instructor"] is True
    _assert_no_leak(response.content, hidden_world["hidden_ids"])


def test_copy_carries_the_hidden_flag(client, hidden_world):
    access = hidden_world["instructor"]["access"]
    other_class = create_class(client, access)
    response = client.post(
        _url(hidden_world, "/copy"),
        data={"target_class_id": other_class},
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 201, response.content
    copied = {i["label"]: i["hidden"] for i in response.json()["checklist_items"]}
    assert copied[HIDDEN_REQUIRED] is True and copied[REQUIRED] is False


# --- 들여온 공모전 문제 ------------------------------------------------------------------


def test_imported_contest_problem_keeps_the_contest_hidden_items_from_participants(client, db, category, landing_type):
    host = _host(client, "hid-host")
    payload = _free_brief(category, landing_type, title="숨은 항목 공모전")
    payload["requirements"] = [
        {"text": "할 일을 추가할 수 있다", "grade": "required"},
        # 무료 공모전은 숨은 필수도 된다.
        {"text": HIDDEN_REQUIRED, "grade": "required", "hidden": True},
    ]
    payload["allows_classroom_import"] = True
    created = client.post(f"{CONTESTS_URL}/free", data=payload, content_type="application/json", **_auth_header(host["access"]))
    assert created.status_code == 200, created.content
    contest_id = created.json()["id"]
    published = client.post(f"{CONTESTS_URL}/{contest_id}/publish", content_type="application/json", **_auth_header(host["access"]))
    assert published.status_code == 200, published.content
    assert [r["hidden"] for r in published.json()["requirements"]] == [False, True]

    instructor = login(client, uid="hid-instructor")
    class_id = create_class(client, instructor["access"])
    problem = _import(client, instructor["access"], class_id, contest_id)
    assert [(i["label"], i["hidden"]) for i in problem["checklist_items"]][1] == (HIDDEN_REQUIRED, True)
    hidden_ids = tuple(ChecklistItem.objects.filter(problem_id=problem["id"], hidden=True).values_list("id", flat=True))
    open_problem(client, instructor["access"], class_id, problem["id"])

    participant = login(client, uid="hid-participant")
    join_class(client, participant["access"], class_id, instructor_access=instructor["access"], display_name="가람")
    base = f"{CLASSES_URL}/{class_id}/problems/{problem['id']}"
    for suffix in ("/mine", "/contest-entry"):
        response = client.get(base + suffix, **auth_header(participant["access"]))
        assert response.status_code == 200, (suffix, response.content)
        _assert_no_leak(response.content, hidden_ids)
    # 공모전 쪽 공개 상세도 참여자 토큰으로는 개수만.
    detail = client.get(f"{CONTESTS_URL}/{contest_id}", **_auth_header(participant["access"]))
    _assert_no_leak(detail.content, ())
    assert detail.json()["hidden_requirement_count"] == 1
