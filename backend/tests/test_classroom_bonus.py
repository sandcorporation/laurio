"""강의실 가산(#905, 스펙 #903, ADR-0073) — AI 는 가산을 판정·완성도 채점하지 않고, 강사·공동 강사가 그 참여자의
**지금 완성도 대상 시도**에 0~5 와 한 줄 메모를 매긴다. 대상 시도가 바뀌면 0점이 되고 「가산 다시 매김 필요」가 뜬다.

판정·완성도는 기본 가짜 어댑터가 문구 유무로 정한다(`test_classroom_quality` 와 같은 세계).
"""

from __future__ import annotations

import pytest

from tests.classroom_scenarios import add_co_instructor, auth_header, login
from tests.test_classroom_quality import (
    OPTIONAL,
    REQUIRED,
    _board,
    _get,
    _patch_problem,
    _run,
    _submit,
    _url,
    _world,
)

BONUS = "가산-화면이-아름답다"


def _add_bonus(client, world: dict, *, points: int = 3) -> int:
    response = client.post(
        _url(world, "/checklist-items"),
        data={"label": BONUS, "grade": "bonus", "points": points},
        content_type="application/json",
        **auth_header(world["instructor"]["access"]),
    )
    assert response.status_code == 201, response.content
    body = response.json()
    assert (body["grade"], body["required"], body["points"]) == ("bonus", False, points)
    return body["id"]


def _rate(client, world: dict, submission_id: int, item_id: int, score: int, memo: str = "", who: str = "instructor"):
    return client.put(
        _url(world, f"/quality/bonus/{submission_id}/{item_id}"),
        data={"score": score, "memo": memo},
        content_type="application/json",
        **auth_header(world[who]["access"]),
    )


def _row(board: dict, name: str) -> dict:
    return next(r for r in board["rows"] if r["display_name"] == name)


@pytest.fixture
def bonus_world(client, db):
    world = _world(client)
    # 가산 문구를 소스에 넣어도 AI 가 매기지 않아야 한다 — 가짜 어댑터는 문구가 있으면 충족·5점이다.
    world["bonus_id"] = _add_bonus(client, world)
    _submit(client, world, "p-a", f"# {REQUIRED}\n# {OPTIONAL}\n# {BONUS}\n")
    _submit(client, world, "p-b", f"# {REQUIRED}\n")
    _submit(client, world, "p-c", "# 아무것도 없다\n")
    _run(client, world)
    return world


def test_bonus_is_not_in_the_ai_prompts_and_scores_or_pass_do_not_change(client, bonus_world):
    from classroom.models import ClassroomQualityReview, ClassroomScore

    scores = list(ClassroomScore.objects.filter(submission__problem_id=bonus_world["problem_id"]))
    assert scores
    for score in scores:
        assert BONUS not in score.prompt.split("체크리스트:")[1].split("제출된 소스")[0]
        assert bonus_world["bonus_id"] not in [r.get("checklist_item_id") for r in score.reasoning]
    reviews = list(ClassroomQualityReview.objects.all())
    assert len(reviews) == 2
    for review in reviews:
        assert f"item_id={bonus_world['bonus_id']}" not in review.prompt
        assert bonus_world["bonus_id"] not in [i["item_id"] for i in review.items]

    board = _board(client, bonus_world)
    # 통과는 필수만 센다 — 가산을 더해도 대상(통과한 사람)은 그대로 둘이다.
    assert board["target_count"] == 2
    garam = _row(board, "가람")
    # 매기기 전 가산은 0점, 만점에는 든다: 가람 5×2 + 5×1 + 0×3 = 15, 만점 2+1+3 = 6.
    assert (garam["raw_total"], garam["max_total"]) == (15, 6)
    bonus_item = garam["items"][-1]
    assert (bonus_item["label"], bonus_item["bonus"], bonus_item["rated"], bonus_item["score"]) == (BONUS, True, False, 0)


def test_instructor_rates_the_target_attempt_and_it_adds_to_the_total_and_rank(client, bonus_world):
    board = _board(client, bonus_world)
    narae = _row(board, "나래")
    # 나래 5×2 + 1×1 = 11 < 가람 15 — 가산 5×3 = 15 를 받으면 26 으로 앞선다.
    response = _rate(client, bonus_world, narae["submission_id"], bonus_world["bonus_id"], 5, "  화면이 깔끔하다  ")
    assert response.status_code == 200, response.content
    assert response.json() == {
        "submission_id": narae["submission_id"],
        "item_id": bonus_world["bonus_id"],
        "score": 5,
        "memo": "화면이 깔끔하다",
    }
    # 덮어쓰기.
    assert _rate(client, bonus_world, narae["submission_id"], bonus_world["bonus_id"], 4, "한 줄").status_code == 200

    board = _board(client, bonus_world)
    assert [(r["rank"], r["display_name"], r["raw_total"]) for r in board["rows"]] == [(1, "나래", 23), (2, "가람", 15)]
    narae = _row(board, "나래")
    assert narae["total"] == pytest.approx(4.6)
    assert (narae["items"][-1]["score"], narae["items"][-1]["reasoning"], narae["items"][-1]["rated"]) == (4, "한 줄", True)
    assert narae["bonus_needs_rerate"] is False

    # 참여자 본인 완성도에도 가산 항목이 점수로 보인다(공개를 켠 뒤).
    _patch_problem(client, bonus_world, {"quality_public": True})
    mine = _get(client, bonus_world, "/quality/mine", who="p-b").json()
    assert mine["rank"] == 1
    assert (mine["items"][-1]["label"], mine["items"][-1]["score"], mine["items"][-1]["bonus"]) == (BONUS, 4, True)
    assert "bonus_needs_rerate" not in mine


def test_only_instructors_rate_and_only_the_current_target_attempt(client, bonus_world):
    from classroom.models import ClassroomBonusScore, ClassroomSubmission

    garam = _row(_board(client, bonus_world), "가람")
    bonus_id = bonus_world["bonus_id"]
    # 참여자는 매기지 못한다(강사 범위 밖 — 404).
    assert _rate(client, bonus_world, garam["submission_id"], bonus_id, 5, who="p-a").status_code == 404
    # 0~5 밖은 422.
    for bad in (-1, 6):
        assert _rate(client, bonus_world, garam["submission_id"], bonus_id, bad).status_code == 422
    # 가산이 아닌 항목에는 매기지 못한다.
    required_id, _optional_id = bonus_world["item_ids"]
    assert _rate(client, bonus_world, garam["submission_id"], required_id, 5).status_code == 409
    # 통과하지 못한 시도(대상 아님)에는 매기지 못한다.
    dasom = ClassroomSubmission.objects.get(problem_id=bonus_world["problem_id"], member__display_name="다솜")
    response = _rate(client, bonus_world, dasom.id, bonus_id, 5)
    assert response.status_code == 409
    assert "대상 시도" in response.json()["detail"]
    assert not ClassroomBonusScore.objects.exists()

    # 공동 강사는 매긴다.
    co = login(client, uid="co-1")
    add_co_instructor(client, bonus_world["instructor"]["access"], bonus_world["class_id"], co["access"])
    bonus_world["co"] = co
    assert _rate(client, bonus_world, garam["submission_id"], bonus_id, 2, who="co").status_code == 200


def test_new_target_attempt_resets_bonus_to_zero_and_asks_to_rerate(client, bonus_world):
    from classroom.models import ClassroomBonusScore

    first = _row(_board(client, bonus_world), "나래")
    assert _rate(client, bonus_world, first["submission_id"], bonus_world["bonus_id"], 5).status_code == 200

    # 나래가 다시 통과하면 대상 시도가 바뀐다 — 새 시도에는 가산이 없어 0점, 「다시 매김 필요」.
    _submit(client, bonus_world, "p-b", f"# {REQUIRED}\n# {OPTIONAL}\n")
    _run(client, bonus_world)
    narae = _row(_board(client, bonus_world), "나래")
    assert narae["submission_id"] != first["submission_id"]
    assert (narae["items"][-1]["score"], narae["items"][-1]["rated"]) == (0, False)
    assert narae["bonus_needs_rerate"] is True
    assert _row(_board(client, bonus_world), "가람")["bonus_needs_rerate"] is False
    # 지난 대상 시도에는 더 매기지 못한다.
    assert _rate(client, bonus_world, first["submission_id"], bonus_world["bonus_id"], 1).status_code == 409
    # 지난 점수는 지우지 않는다(시도에 붙어 있다).
    assert ClassroomBonusScore.objects.filter(submission_id=first["submission_id"]).count() == 1

    assert _rate(client, bonus_world, narae["submission_id"], bonus_world["bonus_id"], 3).status_code == 200
    narae = _row(_board(client, bonus_world), "나래")
    assert (narae["items"][-1]["score"], narae["bonus_needs_rerate"]) == (3, False)
