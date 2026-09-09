"""제출물 단건 조회가 「다음 행동」을 싣는다 (#247).

지금까지 이 값(`NextAction`, #74·#245)은 「내 참가 현황」(`GET /submissions/mine`)
에만 있었다 — 제출 화면 자체는 마감 여부를 스스로 시각 비교로 파생했다. 그 판정기가
둘이면 언젠가 갈라진다. 이 파일은 두 가지를 고정한다:

1. `SubmissionOut.next_action`이 `MyParticipationOut.next_action`과 **같은 값**을
   낸다 — 최소 세 상태(마감 전 / 채점 대기 / 채점 완료 이후)에서.
2. 그 값은 **자기 제출물일 때만** 나온다 — 남의 제출물을 보는 경로(Sponsor, 마감 후
   공개 열람)에서는 나오지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType
from tests.test_source_readings import (
    _close_contest,
    _publish_contest,
    _run_scoring,
    _submit,
    _verified_user,
)

CONTESTS_URL = "/api/contests"
SUBMISSIONS_URL = "/api/submissions"
MY_PARTICIPATION_URL = "/api/submissions/mine"


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _seed(client, category, landing_type, *, uid: str, deadline_at):
    """Contest 를 열고 결제까지 마친 뒤 그 Developer 로 제출한다.

    `test_my_participation._seed_submission`과 같은 흐름이지만, 이 파일에서는
    마감 시각을 시나리오마다 다르게 줘야 해서 인자로 받는다.
    """

    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid=f"{uid}-sponsor",
        sponsor_ci=f"{uid}-sponsor-ci",
        deadline_at=deadline_at,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, uid, f"{uid}-ci")
    submission = _submit(
        client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"]
    )
    return {
        "access": dev["access"],
        "user_id": dev["user_id"],
        "submission_id": submission["id"],
        "contest_id": contest["id"],
        "contest": contest,
    }


def _next_action_in_my_participation(client, access: str, submission_id: int) -> str:
    response = client.get(MY_PARTICIPATION_URL, **_auth_header(access))
    assert response.status_code == 200
    (row,) = [item for item in response.json()["items"] if item["submission_id"] == submission_id]
    return row["next_action"]


# --- 세 상태에서 「내 참가 현황」과 일치한다 --------------------------------------


@pytest.mark.django_db
def test_next_action_before_deadline_matches_my_participation(client, category, landing_type):
    seeded = _seed(
        client, category, landing_type, uid="dev-before", deadline_at=timezone.now() + timedelta(hours=1)
    )

    me = client.get(
        f"{CONTESTS_URL}/{seeded['contest_id']}/submissions/me",
        **_auth_header(seeded["access"]),
    )
    assert me.status_code == 200
    body = me.json()
    assert body["next_action"] == "can_edit_submission"
    assert body["next_action"] == _next_action_in_my_participation(
        client, seeded["access"], seeded["submission_id"]
    )

    # 단건 조회(`GET /submissions/{id}`)도 같은 값을 낸다 — 본인 조회 경로가
    # 두 개(계약 하나는 contest_id 로, 하나는 submission_id 로) 있으므로 둘 다 본다.
    single = client.get(
        f"{SUBMISSIONS_URL}/{seeded['submission_id']}", **_auth_header(seeded["access"])
    )
    assert single.status_code == 200
    assert single.json()["next_action"] == "can_edit_submission"


@pytest.mark.django_db
def test_next_action_awaiting_scoring_matches_my_participation(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    seeded = _seed(client, category, landing_type, uid="dev-scoring", deadline_at=deadline)
    _close_contest(client, seeded["contest"], deadline=deadline)

    me = client.get(
        f"/api/contests/{seeded['contest_id']}/submissions/me", **_auth_header(seeded["access"])
    )
    assert me.status_code == 200
    body = me.json()
    assert body["next_action"] == "awaiting_scoring"
    assert body["next_action"] == _next_action_in_my_participation(
        client, seeded["access"], seeded["submission_id"]
    )


@pytest.mark.django_db
def test_next_action_after_scoring_matches_my_participation(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    seeded = _seed(client, category, landing_type, uid="dev-scored", deadline_at=deadline)
    _close_contest(client, seeded["contest"], deadline=deadline)
    _run_scoring(client)

    me = client.get(
        f"/api/contests/{seeded['contest_id']}/submissions/me", **_auth_header(seeded["access"])
    )
    assert me.status_code == 200
    body = me.json()
    assert body["next_action"] == "can_appeal"
    assert body["next_action"] == _next_action_in_my_participation(
        client, seeded["access"], seeded["submission_id"]
    )


# --- 자기 제출물일 때만 나온다 ----------------------------------------------------


@pytest.mark.django_db
def test_next_action_is_absent_for_sponsor_viewer(client, category, landing_type):
    """Sponsor 는 진행 중에도 (데모만) 볼 수 있지만, 「다음 행동」은 본인 것이 아니다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-visible", "dev-visible-ci")
    submission = _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"])

    response = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}", **_auth_header(sponsor["access"])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_owner"] is False
    assert body["next_action"] is None


@pytest.mark.django_db
def test_next_action_is_absent_for_anonymous_viewer_after_deadline(client, category, landing_type):
    """마감 후 전면 공개되는 조회에도 「다음 행동」은 실리지 않는다 — 본인 것이 아니다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-public", "dev-public-ci")
    submission = _submit(client, dev, contest["id"], requirement_id=contest["requirements"][0]["id"])
    _close_contest(client, contest, deadline=deadline)

    anon_response = client.get(f"{SUBMISSIONS_URL}/{submission['id']}")

    assert anon_response.status_code == 200
    body = anon_response.json()
    assert body["is_owner"] is False
    assert body["next_action"] is None

    # 그리고 본인에게는 여전히 실린다(채점 전이니 마감 후에도 "채점 대기").
    owner_response = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}", **_auth_header(dev["access"])
    )
    assert owner_response.json()["next_action"] == "awaiting_scoring"
