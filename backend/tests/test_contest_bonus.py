"""공모전 가산(#905, 스펙 #903, ADR-0073) — AI 는 가산을 판정·완성도 채점하지 않고, 개최자가 **마감 뒤** 제출작마다
0~5 와 한 줄 메모를 매긴다. 완성도 합계에만 들고 Score·달성률·Distribution 은 그대로다."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType
from scoring.models import Score, SubmissionBonusScore, SubmissionQualityReview
from tests.test_contest_quality import CONTESTS_URL, REQUIREMENTS, _auth, _run_quality
from tests.test_distributions import _publish_contest, _run_scoring, _submit, _verified_user
from tests.test_source_readings import _close_contest

BONUS = "가산-발표-영상이-훌륭하다"


@pytest.fixture
def world(client, db):
    category = Category.objects.create(name="게임")
    landing_type = DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[*REQUIREMENTS, {"text": BONUS, "grade": "bonus", "points": 3}],
    )
    required_id, optional_id, bonus_id = (r["id"] for r in contest["requirements"])
    assert [r["grade"] for r in contest["requirements"]] == ["required", "optional", "bonus"]
    dev_a = _verified_user(client, "dev-ba", "dev-ba-ci")
    dev_b = _verified_user(client, "dev-bb", "dev-bb-ci")
    sub_a = _submit(client, dev_a, contest["id"], requirement_id=required_id, grounded=True)
    sub_b = _submit(client, dev_b, contest["id"], requirement_id=required_id, grounded=False)
    return {
        "sponsor": sponsor,
        "contest": contest,
        "deadline": deadline,
        "dev_a": dev_a,
        "a": sub_a["id"],
        "b": sub_b["id"],
        "required_id": required_id,
        "optional_id": optional_id,
        "bonus_id": bonus_id,
    }


def _rate(client, w: dict, submission_id: int, requirement_id: int, score: int, memo: str = "", who: str = "sponsor"):
    return client.put(
        f"{CONTESTS_URL}/{w['contest']['id']}/submissions/{submission_id}/bonus/{requirement_id}",
        data={"score": score, "memo": memo},
        content_type="application/json",
        **_auth(w[who]["access"]),
    )


def _compare(client, w: dict) -> dict:
    response = client.get(f"{CONTESTS_URL}/{w['contest']['id']}/submissions/compare", **_auth(w["sponsor"]["access"]))
    assert response.status_code == 200, response.content
    return {s["submission_id"]: s for s in response.json()["submissions"]}


def _close_and_score(client, w: dict) -> None:
    _close_contest(client, w["contest"], deadline=w["deadline"])
    _run_scoring(client)
    _run_quality(client)


def test_bonus_is_rejected_before_the_deadline(client, world):
    response = _rate(client, world, world["a"], world["bonus_id"], 5)
    assert response.status_code == 409
    assert not SubmissionBonusScore.objects.exists()


def test_bonus_is_not_in_the_ai_prompts_and_score_does_not_count_it(client, world):
    _close_and_score(client, world)

    for score in Score.objects.all():
        assert BONUS not in score.prompt
        assert world["bonus_id"] not in [r["requirement_id"] for r in score.reasoning]
    for review in SubmissionQualityReview.objects.all():
        assert BONUS not in review.prompt
        assert [i["item_id"] for i in review.items] == [world["required_id"], world["optional_id"]]
    # 달성률은 필수만 센다 — 근거가 있는 a 는 필수를 채웠고 b 는 못 채웠다(가산이 없을 때와 같다).
    percentages = {s.submission_id: s.percentage for s in Score.objects.all()}
    assert percentages[world["a"]] > percentages[world["b"]]

    compare = _compare(client, world)
    for sid in (world["a"], world["b"]):
        quality = compare[sid]["quality"]
        # 만점 2+1+3 = 6, 매기기 전 가산은 0점.
        assert quality["max_total"] == 6
        assert (quality["items"][-1]["label"], quality["items"][-1]["bonus"], quality["items"][-1]["rated"]) == (
            BONUS,
            True,
            False,
        )
        assert compare[sid]["bonus_scores"] == [
            {"requirement_id": world["bonus_id"], "score": 0, "memo": "", "rated": False}
        ]


def test_sponsor_rates_after_the_deadline_and_it_moves_only_the_quality(client, world):
    _close_and_score(client, world)
    scores_before = {s.submission_id: (s.percentage, s.reasoning) for s in Score.objects.all()}
    before = _compare(client, world)

    response = _rate(client, world, world["b"], world["bonus_id"], 5, "  영상이 좋다 ")
    assert response.status_code == 200, response.content
    assert response.json() == {"requirement_id": world["bonus_id"], "score": 5, "memo": "영상이 좋다", "rated": True}
    # 덮어쓰기.
    assert _rate(client, world, world["b"], world["bonus_id"], 4, "한 줄").status_code == 200
    assert SubmissionBonusScore.objects.count() == 1

    after = _compare(client, world)
    quality_b = after[world["b"]]["quality"]
    assert quality_b["raw_total"] == before[world["b"]]["quality"]["raw_total"] + 4 * 3
    assert (quality_b["items"][-1]["score"], quality_b["items"][-1]["reasoning"]) == (4, "한 줄")
    assert after[world["b"]]["bonus_scores"][0] == {
        "requirement_id": world["bonus_id"],
        "score": 4,
        "memo": "한 줄",
        "rated": True,
    }
    # Score·달성률은 그대로다.
    assert {s.submission_id: (s.percentage, s.reasoning) for s in Score.objects.all()} == scores_before

    # 제출자 본인 결과에 가산이 자기 완성도 항목으로 보인다(남의 것은 아니다).
    own = client.get(f"/api/submissions/{world['b']}/score", **_auth(world["dev_a"]["access"]))
    assert own.status_code in (403, 404)
    own_a = client.get(f"/api/submissions/{world['a']}/score", **_auth(world["dev_a"]["access"]))
    assert own_a.status_code == 200, own_a.content
    item = own_a.json()["quality"]["items"][-1]
    assert (item["label"], item["bonus"], item["score"], item["rated"]) == (BONUS, True, 0, False)


def test_only_the_sponsor_rates_and_only_bonus_requirements(client, world):
    _close_and_score(client, world)
    # 제출자(개최자 아님)는 403.
    assert _rate(client, world, world["a"], world["bonus_id"], 5, who="dev_a").status_code == 403
    # 가산이 아닌 Requirement 는 404.
    assert _rate(client, world, world["a"], world["required_id"], 5).status_code == 404
    # 0~5 밖은 422.
    for bad in (-1, 6):
        assert _rate(client, world, world["a"], world["bonus_id"], bad).status_code == 422
    # 메모는 한 줄(200자).
    assert _rate(client, world, world["a"], world["bonus_id"], 1, "가" * 201).status_code == 422
    assert not SubmissionBonusScore.objects.exists()
