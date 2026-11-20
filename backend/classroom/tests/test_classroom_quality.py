"""강의실 완성도 채점(#883, ADR-0072) — 대상·재사용·체크리스트 지문·공개 스위치·실패.

판정은 기본 가짜 어댑터(`FakeClassroomScoringAdapter`)가 한다 — 항목 문구가 소스에 있으면 충족. 완성도도
같은 결로 매긴다(문구가 있으면 5, 없으면 1). 그래서 소스 내용으로 통과·완성도를 고른다.
"""

from __future__ import annotations

import json

import pytest

from tests.classroom_scenarios import (
    CLASSES_URL,
    FakeVendorResponse,
    auth_header,
    create_class,
    create_open_problem,
    force_real_scoring_adapter,
    get_class,
    join_class,
    login,
    mine,
    run_scan,
    submit_source,
    user_id,
)

REQUIRED = "테스트가 있다"
OPTIONAL = "README 가 있다"


def _url(world: dict, suffix: str = "") -> str:
    return f"{CLASSES_URL}/{world['class_id']}/problems/{world['problem_id']}{suffix}"


def _submit(client, world: dict, who: str, text: str) -> None:
    person = world[who]
    submit_source(
        client,
        person["access"],
        world["class_id"],
        world["problem_id"],
        participant_user_id=user_id(person["uid"]),
        files={"main.py": text},
    )
    run_scan(client)


def _world(client, *, with_key: bool = True) -> dict:
    instructor = login(client, uid="instructor-1")
    class_id = create_class(client, instructor["access"], with_key=with_key)
    problem = create_open_problem(
        client,
        instructor["access"],
        class_id,
        submission_formats=["source"],
        required_labels=[REQUIRED],
        optional_labels=[OPTIONAL],
        syntax_check_enabled=False,
    )
    world: dict = {"class_id": class_id, "problem_id": problem.id, "item_ids": problem.item_ids}
    world["instructor"] = {**instructor, "uid": "instructor-1"}
    for uid, name in (("p-a", "가람"), ("p-b", "나래"), ("p-c", "다솜")):
        person = login(client, uid=uid)
        join_class(client, person["access"], class_id, instructor_access=instructor["access"], display_name=name)
        world[uid] = {**person, "uid": uid}
    # 강사도 자기 클래스에 들어와 낸다 — 순위에서 빠져야 한다.
    join_class(client, instructor["access"], class_id, instructor_access=instructor["access"], display_name="강사")
    return world


def _get(client, world: dict, suffix: str, who: str = "instructor"):
    return client.get(_url(world, suffix), **auth_header(world[who]["access"]))


def _run(client, world: dict) -> dict:
    response = client.post(_url(world, "/quality/run"), content_type="application/json", **auth_header(world["instructor"]["access"]))
    assert response.status_code == 200, response.content
    return response.json()


def _board(client, world: dict) -> dict:
    response = _get(client, world, "/quality")
    assert response.status_code == 200, response.content
    return response.json()


def _estimate(client, world: dict) -> dict:
    response = _get(client, world, "/quality/estimate")
    assert response.status_code == 200, response.content
    return response.json()


def _patch_problem(client, world: dict, payload: dict) -> dict:
    response = client.patch(_url(world), data=payload, content_type="application/json", **auth_header(world["instructor"]["access"]))
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def scored(client, db):
    world = _world(client)
    _submit(client, world, "p-a", f"# {REQUIRED}\n# {OPTIONAL}\n")
    _submit(client, world, "p-b", f"# {REQUIRED}\n")
    _submit(client, world, "p-c", "# 아무것도 없다\n")
    _submit(client, world, "instructor", f"# {REQUIRED}\n# {OPTIONAL}\n")
    return world


def test_button_flow_scores_the_latest_passed_attempt_of_each_participant_only(client, scored):
    estimate = _estimate(client, scored)
    assert (estimate["new_count"], estimate["reuse_count"], estimate["blocked_reason"]) == (2, 0, None)

    assert _run(client, scored) == {"queued_count": 2}

    board = _board(client, scored)
    assert (board["target_count"], board["queued_count"], board["failed_count"]) == (2, 0, 0)
    rows = board["rows"]
    assert [(r["rank"], r["display_name"], r["weighted_score"]) for r in rows] == [(1, "가람", 15), (2, "나래", 11)]
    assert rows[0]["completeness"] == 100
    assert rows[1]["completeness"] == pytest.approx(11 / 15 * 100)
    assert [(i["label"], i["required"], i["score"]) for i in rows[1]["items"]] == [(REQUIRED, True, 5), (OPTIONAL, False, 1)]
    assert all(i["reasoning"] for i in rows[1]["items"])


def test_rerun_reuses_unchanged_attempts_and_scores_only_the_changed_person(client, scored):
    _run(client, scored)
    assert _estimate(client, scored)["new_count"] == 0
    assert _run(client, scored) == {"queued_count": 0}

    # 마지막 시도가 실패여도 대상은 그 앞의 통과 시도 그대로다.
    _submit(client, scored, "p-b", "# 깨졌다\n")
    assert _estimate(client, scored)["new_count"] == 0

    # 새로 통과하면 그 사람만 다시 매긴다.
    _submit(client, scored, "p-b", f"# {REQUIRED}\n# {OPTIONAL}\n")
    assert _estimate(client, scored) | {"cost_krw": None} == {
        "new_count": 1,
        "reuse_count": 1,
        "cost_krw": None,
        "blocked_reason": None,
    }
    assert _run(client, scored) == {"queued_count": 1}
    rows = _board(client, scored)["rows"]
    assert [(r["rank"], r["display_name"], r["attempt_number"]) for r in rows] == [(1, "가람", 1), (1, "나래", 3)]


def test_editing_the_checklist_rescores_everyone(client, scored):
    _run(client, scored)
    optional_id = scored["item_ids"][1]
    response = client.patch(
        _url(scored, f"/checklist-items/{optional_id}"),
        data={"label": "README 를 썼다"},
        content_type="application/json",
        **auth_header(scored["instructor"]["access"]),
    )
    assert response.status_code == 200, response.content

    assert _estimate(client, scored)["new_count"] == 2
    assert _board(client, scored)["rows"] == []
    assert _run(client, scored) == {"queued_count": 2}
    labels = {i["label"] for r in _board(client, scored)["rows"] for i in r["items"]}
    assert labels == {REQUIRED, "README 를 썼다"}


def test_participants_see_nothing_until_public_and_then_only_their_own(client, scored):
    _run(client, scored)

    assert _get(client, scored, "/quality/mine", who="p-b").status_code == 404
    assert "quality" not in json.dumps(mine(client, scored["p-b"]["access"], scored["class_id"], scored["problem_id"]))

    assert _patch_problem(client, scored, {"quality_public": True})["quality_public"] is True

    response = _get(client, scored, "/quality/mine", who="p-b")
    assert response.status_code == 200, response.content
    body = response.json()
    assert (body["rank"], body["total"]) == (2, 2)
    assert body["completeness"] == pytest.approx(11 / 15 * 100)
    assert [i["score"] for i in body["items"]] == [5, 1]
    assert "가람" not in response.content.decode()
    # 통과하지 못한 사람은 순위에 없다.
    assert _get(client, scored, "/quality/mine", who="p-c").status_code == 404
    # 참여자는 강사용 순위를 읽지 못한다.
    assert _get(client, scored, "/quality", who="p-a").status_code == 404


def test_without_a_scoring_connection_the_button_is_blocked(client, db):
    world = _world(client, with_key=False)
    assert _estimate(client, world)["blocked_reason"] == "no_api_key"
    response = client.post(_url(world, "/quality/run"), content_type="application/json", **auth_header(world["instructor"]["access"]))
    assert response.status_code == 409


def _quality_body(scores: list[dict], *, total_tokens: int = 0) -> dict:
    body: dict = {
        "model": "gpt-4o-mini-2024-07-18",
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps({"scores": scores})}}],
    }
    if total_tokens:
        body["usage"] = {"prompt_tokens": total_tokens, "completion_tokens": 0, "total_tokens": total_tokens}
    return body


def test_invalid_ai_scores_fail_only_that_attempt_and_the_next_press_retries(client, scored, monkeypatch):
    required_id, optional_id = scored["item_ids"]
    sent: list[dict] = []

    def _bad(*args, **kwargs):
        sent.append(kwargs["json"])
        return FakeVendorResponse(200, _quality_body([{"requirement_id": required_id, "score": 7, "reasoning": "r"}]))

    with force_real_scoring_adapter():
        monkeypatch.setattr("core.llm_scoring.requests.post", _bad)
        assert _run(client, scored) == {"queued_count": 2}
    board = _board(client, scored)
    assert (board["failed_count"], board["rows"]) == (2, [])
    assert sorted(board["failed_names"]) == ["가람", "나래"]
    assert sent[0]["response_format"]["json_schema"]["name"] == "quality_review"

    before = get_class(client, scored["instructor"]["access"], scored["class_id"])["token_usage_total"]

    def _good(*args, **kwargs):
        return FakeVendorResponse(
            200,
            _quality_body(
                [
                    {"requirement_id": required_id, "score": 4, "reasoning": "필수 근거"},
                    {"requirement_id": optional_id, "score": 2, "reasoning": "선택 근거"},
                ],
                total_tokens=100,
            ),
        )

    assert _estimate(client, scored)["new_count"] == 2
    with force_real_scoring_adapter():
        monkeypatch.setattr("core.llm_scoring.requests.post", _good)
        assert _run(client, scored) == {"queued_count": 2}
    board = _board(client, scored)
    assert board["failed_count"] == 0
    assert [(r["rank"], r["weighted_score"]) for r in board["rows"]] == [(1, 10), (1, 10)]
    after = get_class(client, scored["instructor"]["access"], scored["class_id"])["token_usage_total"]
    assert after - before == 200


@pytest.mark.django_db(transaction=True)
def test_the_grader_picks_quality_jobs_sharing_the_per_connection_limit(settings, monkeypatch):
    """상주 grader 의 비동기 길 — 버튼은 큐에 넣기만 하고, grader 가 판정과 같은 연결당 상한 아래에서 집는다."""

    from django.test import Client

    from classroom import grader as classroom_grader
    from classroom.scoring import FakeClassroomScoringAdapter

    client = Client()
    world = _world(client)
    _submit(client, world, "p-a", f"# {REQUIRED}\n# {OPTIONAL}\n")
    _submit(client, world, "p-b", f"# {REQUIRED}\n")

    settings.CLASSROOM_GRADER_INLINE = False
    assert _run(client, world) == {"queued_count": 2}
    assert _board(client, world)["queued_count"] == 2
    # 이미 큐에 있는 사람은 다시 누르면 새로 넣지 않는다.
    assert _estimate(client, world)["new_count"] == 0

    in_flight = 0
    peak = 0
    real = FakeClassroomScoringAdapter.review_quality_async

    async def _counting(self, quality_input):
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        try:
            import asyncio

            await asyncio.sleep(0.02)
            return await real(self, quality_input)
        finally:
            in_flight -= 1

    monkeypatch.setattr(FakeClassroomScoringAdapter, "review_quality_async", _counting)
    results = classroom_grader.run_round(global_limit=4, per_connection_limit=1, poll_seconds=0.01)

    assert sorted(r["status"] for r in results) == ["quality_reviewed", "quality_reviewed"]
    assert peak == 1
    board = _board(client, world)
    assert (board["queued_count"], len(board["rows"])) == (0, 2)


def _patch_item(client, world: dict, item_id: int, payload: dict) -> dict:
    response = client.patch(
        _url(world, f"/checklist-items/{item_id}"),
        data=payload,
        content_type="application/json",
        **auth_header(world["instructor"]["access"]),
    )
    assert response.status_code == 200, response.content
    return response.json()


def _passing_members(world: dict) -> set[int]:
    from classroom.models import ClassroomSubmission, Problem

    problem = Problem.objects.get(id=world["problem_id"])
    return {
        s.member_id
        for s in ClassroomSubmission.objects.filter(problem=problem).select_related("classroom_score")
        if problem.is_score_passed(getattr(s, "classroom_score", None))
    }


def test_default_points_keep_the_old_ranking(client, scored):
    """기존 데이터(필수 2·선택 1)는 옛 가중 점수 그대로라 순위가 바뀌지 않는다(#904, ADR-0073)."""

    _run(client, scored)
    rows = _board(client, scored)["rows"]
    assert [(r["rank"], r["display_name"], r["raw_total"], r["max_total"]) for r in rows] == [
        (1, "가람", 15, 3),
        (2, "나래", 11, 3),
    ]
    assert [r["total"] for r in rows] == [pytest.approx(3.0), pytest.approx(2.2)]
    assert [(i["points"], i["item_points"]) for i in rows[1]["items"]] == [(2, 2.0), (1, pytest.approx(0.2))]


def test_points_change_recomputes_rank_without_rescoring_and_keeps_pass(client, scored):
    """배점을 고치면 AI 를 다시 부르지 않고(새 기록·새 대상 없음) 지금 배점으로 다시 계산한다. 통과는 그대로다."""

    from classroom.models import ClassroomQualityReview

    _run(client, scored)
    reviews_before = ClassroomQualityReview.objects.count()
    passing_before = _passing_members(scored)
    required_id, optional_id = scored["item_ids"]

    saved = _patch_item(client, scored, optional_id, {"points": 10})
    assert (saved["grade"], saved["required"], saved["points"]) == ("optional", False, 10)
    _patch_item(client, scored, required_id, {"points": 1})

    assert _estimate(client, scored)["new_count"] == 0
    assert _run(client, scored) == {"queued_count": 0}
    assert ClassroomQualityReview.objects.count() == reviews_before
    rows = _board(client, scored)["rows"]
    # 가람 5×1 + 5×10 = 55, 나래 5×1 + 1×10 = 15 — 만점 11.
    assert [(r["display_name"], r["raw_total"], r["max_total"]) for r in rows] == [("가람", 55, 11), ("나래", 15, 11)]
    assert rows[1]["total"] == pytest.approx(3.0)
    assert _passing_members(scored) == passing_before


def test_points_must_be_1_to_10(client, scored):
    _required_id, optional_id = scored["item_ids"]
    for bad in (0, 11):
        response = client.patch(
            _url(scored, f"/checklist-items/{optional_id}"),
            data={"points": bad},
            content_type="application/json",
            **auth_header(scored["instructor"]["access"]),
        )
        assert response.status_code == 422


def test_grade_input_wins_over_required_and_bonus_is_open(client, scored):
    _required_id, optional_id = scored["item_ids"]
    assert _patch_item(client, scored, optional_id, {"grade": "required"})["required"] is True
    assert _patch_item(client, scored, optional_id, {"required": False})["grade"] == "optional"
    # 가산은 #905 부터 연다 — 강사가 사람 점수로 매긴다(`test_classroom_bonus`).
    saved = _patch_item(client, scored, optional_id, {"grade": "bonus"})
    assert (saved["grade"], saved["required"]) == ("bonus", False)


def test_migration_rekeys_existing_reviews_so_they_are_reused_without_rescoring(client, scored):
    """0037 이 옛 지문(id·라벨·필수 여부)의 기록을 새 지문(AI 대상 항목의 id·라벨)으로 다시 센다 — 그대로 두면
    배포 뒤 강사가 다시 돈을 내고 채점해야 한다(#904, ADR-0073)."""

    import hashlib
    import importlib

    from django.apps import apps as django_apps

    from classroom.models import ClassroomQualityReview

    _run(client, scored)
    old = [
        hashlib.sha256(
            json.dumps(
                sorted([i["item_id"], i["label"], i["required"]] for i in r.items),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode()
        ).hexdigest()
        for r in ClassroomQualityReview.objects.order_by("id")
    ]
    for review, fingerprint in zip(ClassroomQualityReview.objects.order_by("id"), old, strict=True):
        ClassroomQualityReview.objects.filter(id=review.id).update(checklist_fingerprint=fingerprint)
    assert _estimate(client, scored)["new_count"] == 2  # 옛 지문이면 지금의 기록을 못 찾는다.

    migration = importlib.import_module("classroom.migrations.0037_checklist_grade_and_points")
    migration.refingerprint_quality_reviews(django_apps, None)

    assert _estimate(client, scored)["new_count"] == 0
    assert [r["raw_total"] for r in _board(client, scored)["rows"]] == [15, 11]
