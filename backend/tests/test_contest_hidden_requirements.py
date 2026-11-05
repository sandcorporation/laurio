"""공모전 숨은 항목(#906, 스펙 #903) — 「제출자에게 숨기기」를 켠 Requirement 는 제출자 경로 어디에도 내용이 나가지 않고
개수·충족 수만 나간다. AI 판정·완성도에는 보통 항목처럼 들어가고, 개최자·Operator 이의 심판은 내용을 본다.
유료 공모전은 숨은 필수를 만들 수 없다(422).

유출 시험은 숨은 항목의 고유 문자열(과 id)이 제출자 토큰으로 받는 응답 본문 전체에 없음을 본다 — 마감 전·후 모두."""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from appeals.models import Appeal
from storage.adapters.fake import FakeStorageAdapter
from contests.models import Category, DeliverableType, Requirement
from scoring.models import Score, SubmissionQualityReview
from tests.test_appeals import _operator_client
from tests.test_contest_quality import CONTESTS_URL, _auth, _run_quality
from tests.test_distributions import (
    LOGIN_REQUIREMENT,
    _publish_contest,
    _run_scoring,
    _source_object_key,
    _submit,
    _verified_user,
    _zip_bytes,
)
from tests.test_source_readings import _close_contest

HIDDEN_OPTIONAL = "HIDDENOPT7f3a-숨은-선택-항목"
HIDDEN_BONUS = "HIDDENBON9c1e-숨은-가산-항목"
#: 응답 JSON 은 한글을 \u 로 내보내므로 ASCII 머리로 찾는다.
SECRETS = ("HIDDENOPT7f3a", "HIDDENBON9c1e")


def _assert_no_leak(body: bytes, hidden_ids: tuple[int, ...] = ()) -> None:
    text = body.decode()
    for secret in SECRETS:
        assert secret not in text, f"숨은 항목 문구가 샜다: {secret}"
    for hidden_id in hidden_ids:
        assert f'"requirement_id": {hidden_id}' not in text and f'"requirement_id":{hidden_id}' not in text
        assert f'"item_id": {hidden_id}' not in text and f'"item_id":{hidden_id}' not in text


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
        requirements=[
            {"text": LOGIN_REQUIREMENT, "grade": "required"},
            {"text": HIDDEN_OPTIONAL, "grade": "optional", "hidden": True},
            {"text": HIDDEN_BONUS, "grade": "bonus", "hidden": True},
        ],
    )
    # 익명 상세는 숨은 항목을 빼므로 개최자 토큰으로 다시 받는다.
    contest = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth(sponsor["access"])).json()
    required_id, hidden_optional_id, hidden_bonus_id = (r["id"] for r in contest["requirements"])
    dev = _verified_user(client, "dev-h1", "dev-h1-ci")
    # 소스에 숨은 선택 항목 문구도 넣어 흉내 채점이 그것을 「충족」으로 판정하게 한다 — 결과 요약이 1/1 이 된다.
    submission = _submit(
        client,
        dev,
        contest["id"],
        requirement_id=required_id,
        grounded=True,
        requirement_text=f"{LOGIN_REQUIREMENT} {HIDDEN_OPTIONAL}",
    )
    return {
        "sponsor": sponsor,
        "contest": contest,
        "deadline": deadline,
        "dev": dev,
        "submission_id": submission["id"],
        "required_id": required_id,
        "hidden_ids": (hidden_optional_id, hidden_bonus_id),
    }


def _get(client, url: str, access: str | None = None):
    response = client.get(url, **(_auth(access) if access else {}))
    assert response.status_code == 200, (url, response.content)
    return response


def _submitter_bodies(client, w: dict) -> list[bytes]:
    """제출자 토큰(과 익명)으로 받는 공모전 응답 전부."""

    contest_id = w["contest"]["id"]
    access = w["dev"]["access"]
    return [
        _get(client, f"{CONTESTS_URL}/{contest_id}", access).content,
        _get(client, f"{CONTESTS_URL}/{contest_id}").content,
        _get(client, CONTESTS_URL).content,
        _get(client, f"{CONTESTS_URL}/home").content,
        _get(client, f"/api/submissions/{w['submission_id']}", access).content,
        _get(client, "/api/submissions/mine", access).content,
    ]


def test_owner_sees_hidden_items_and_others_see_only_the_count(client, world):
    contest_id = world["contest"]["id"]
    # 개최자가 만든 응답(만들기)에는 숨은 항목이 실려 있다.
    assert [r["hidden"] for r in world["contest"]["requirements"]] == [False, True, True]

    owner_raw = _get(client, f"{CONTESTS_URL}/{contest_id}", world["sponsor"]["access"]).content
    # 유출 검사가 찾는 머리가 개최자 응답에는 실제로 있다(검사가 헛돌지 않는다는 대조).
    assert all(secret.encode() in owner_raw for secret in SECRETS)
    owner = _get(client, f"{CONTESTS_URL}/{contest_id}", world["sponsor"]["access"]).json()
    assert [r["text"] for r in owner["requirements"]] == [LOGIN_REQUIREMENT, HIDDEN_OPTIONAL, HIDDEN_BONUS]
    assert owner["hidden_requirement_count"] == 2

    public = _get(client, f"{CONTESTS_URL}/{contest_id}", world["dev"]["access"]).json()
    assert [r["text"] for r in public["requirements"]] == [LOGIN_REQUIREMENT]
    assert public["hidden_requirement_count"] == 2
    listed = next(c for c in _get(client, CONTESTS_URL).json()["items"] if c["id"] == contest_id)
    assert [r["text"] for r in listed["requirements"]] == [LOGIN_REQUIREMENT]
    assert listed["hidden_requirement_count"] == 2


def test_submitter_paths_do_not_leak_before_the_deadline(client, world):
    for body in _submitter_bodies(client, world):
        _assert_no_leak(body, world["hidden_ids"])
    # 채움률은 숨은 항목을 세지 않는다 — 보이는 항목 하나뿐이다.
    own = _get(client, f"/api/submissions/{world['submission_id']}", world["dev"]["access"]).json()
    assert [r["requirement_id"] for r in own["requirement_responses"]] == [world["required_id"]]


@pytest.mark.parametrize("which", [0, 1])
def test_response_to_a_hidden_item_is_rejected(client, world, which):
    hidden_id = world["hidden_ids"][which]
    dev = _verified_user(client, "dev-h2", "dev-h2-ci")
    source_key = _source_object_key(world["contest"]["id"], dev["user_id"])
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": "print('x')\n"}))
    response = client.post(
        f"{CONTESTS_URL}/{world['contest']['id']}/submissions",
        data={
            "assets": [{"kind": "source", "value": source_key}],
            "requirement_responses": [{"requirement_id": hidden_id, "is_met": True, "evidence": []}],
        },
        content_type="application/json",
        **_auth(dev["access"]),
    )
    assert response.status_code == 422
    # 숨은 항목 id 와 남의 공모전 항목 id 는 같은 문장으로 거절된다 — 떠보는 길이 되지 않는다.
    assert response.json()["detail"] == "이 제출 대상에 속하지 않은 요구사항입니다."


def test_after_the_deadline_hidden_items_are_judged_but_the_result_shows_only_counts(client, world):
    _close_contest(client, world["contest"], deadline=world["deadline"])
    _run_scoring(client)
    _run_quality(client)

    hidden_optional_id, hidden_bonus_id = world["hidden_ids"]
    # AI 는 숨은 선택 항목을 보통 항목처럼 판정하고(가산은 #905 대로 빠진다), 완성도도 매긴다.
    score = Score.objects.get(submission_id=world["submission_id"])
    assert HIDDEN_OPTIONAL in score.prompt
    assert hidden_optional_id in [r["requirement_id"] for r in score.reasoning]
    review = SubmissionQualityReview.objects.get(submission_id=world["submission_id"])
    assert hidden_optional_id in [i["item_id"] for i in review.items]

    for body in _submitter_bodies(client, world):
        _assert_no_leak(body, world["hidden_ids"])
    own_score = _get(client, f"/api/submissions/{world['submission_id']}/score", world["dev"]["access"])
    _assert_no_leak(own_score.content, world["hidden_ids"])
    payload = own_score.json()
    assert [r["requirement_id"] for r in payload["reasoning"]] == [world["required_id"]]
    assert payload["hidden_summary"] == {"total": 1, "met": 1}
    hidden_items = [i for i in payload["quality"]["items"] if i["hidden"]]
    assert [i["label"] for i in hidden_items] == ["숨은 항목 1", "숨은 항목 2"]
    assert all(i["reasoning"] == "" and i["item_id"] < 0 for i in hidden_items)
    # 합계는 숨은 항목까지 센다 — 가리는 것은 내용이지 점수가 아니다.
    assert payload["quality"]["max_total"] == 2 + 1 + 1

    # 개최자 비교 화면은 내용을 본다.
    compare = _get(client, f"{CONTESTS_URL}/{world['contest']['id']}/submissions/compare", world["sponsor"]["access"])
    compared = {r["requirement_id"]: r["text"] for r in compare.json()["requirements"]}
    assert compared[hidden_optional_id] == HIDDEN_OPTIONAL and compared[hidden_bonus_id] == HIDDEN_BONUS


def test_operator_appeal_detail_shows_the_hidden_item_contents(client, world):
    operator_client = _operator_client()
    _close_contest(client, world["contest"], deadline=world["deadline"])
    _run_scoring(client)
    appeal = Appeal.objects.create(submission_id=world["submission_id"], reason="숨은 항목 판정이 이상합니다")
    detail = operator_client.get(f"/api/operator/appeals/{appeal.id}")
    assert detail.status_code == 200, detail.content
    by_id = {r["id"]: r for r in detail.json()["requirements"]}
    assert by_id[world["hidden_ids"][0]] == {
        "id": world["hidden_ids"][0],
        "text": HIDDEN_OPTIONAL,
        "grade": "optional",
        "hidden": True,
    }


# --- 유료 공모전의 숨은 필수 ------------------------------------------------------------


def _requirement_url(w: dict, requirement_id: int | None = None) -> str:
    base = f"{CONTESTS_URL}/{w['contest']['id']}/requirements"
    return base if requirement_id is None else f"{base}/{requirement_id}"


def test_paid_contest_rejects_hidden_required_on_create(client, db):
    category = Category.objects.create(name="게임")
    landing_type = DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)
    sponsor = _verified_user(client, "sponsor-hr", "sponsor-hr-ci")
    response = client.post(
        CONTESTS_URL,
        data={
            "title": "유료",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 900_000,
            "deadline_at": (timezone.now() + timedelta(days=1)).isoformat(),
            "requirements": [{"text": "숨은 필수", "grade": "required", "hidden": True}],
        },
        content_type="application/json",
        **_auth(sponsor["access"]),
    )
    assert response.status_code == 422
    assert "숨길 수 없습니다" in response.json()["detail"]


def test_paid_contest_rejects_hidden_required_on_add_and_update(client, world):
    access = world["sponsor"]["access"]
    added = client.post(
        _requirement_url(world),
        data={"text": "숨은 필수", "grade": "required", "hidden": True},
        content_type="application/json",
        **_auth(access),
    )
    assert added.status_code == 422

    # 숨긴 선택 항목을 필수로 바꾸기도, 필수를 숨기기도 같은 거절이다.
    to_required = client.patch(
        _requirement_url(world, world["hidden_ids"][0]),
        data={"grade": "required"},
        content_type="application/json",
        **_auth(access),
    )
    assert to_required.status_code == 422
    hide_required = client.patch(
        _requirement_url(world, world["required_id"]),
        data={"hidden": True},
        content_type="application/json",
        **_auth(access),
    )
    assert hide_required.status_code == 422
    assert not Requirement.objects.filter(contest_id=world["contest"]["id"], grade="required", hidden=True).exists()

    # 숨긴 선택 항목을 드러내는 것은 된다.
    reveal = client.patch(
        _requirement_url(world, world["hidden_ids"][0]),
        data={"hidden": False},
        content_type="application/json",
        **_auth(access),
    )
    assert reveal.status_code == 200, reveal.content
    assert reveal.json()["hidden"] is False
