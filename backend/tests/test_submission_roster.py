"""개최자의 제출 명단 — 마감 전에도 표시 이름·낸 시각만 (#956, ADR-0079).

시임은 HTTP 다 — `GET /api/contests/{id}/submissions/roster` 를 전체 요청 스택으로 친다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from accounts.tokens import issue_token_pair
from accounts.withdrawal import execute_withdrawal
from contests.models import Category, Contest, ContestSubmission
from submissions.models import Submission

ROSTER_URL = "/api/contests/{contest_id}/submissions/roster"
DETAIL_URL = "/api/submissions/{submission_id}"


def _auth(user_id: int) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {issue_token_pair(user_id).access}"}


def _user(name: str):
    return get_user_model().objects.create_user(username=name, email=f"{name}@example.invalid")


def _contest(*, is_free: bool, deadline_in: timedelta = timedelta(days=3)) -> Contest:
    sponsor = SponsorProfile.objects.create(user=_user(f"sponsor-{is_free}"), display_name="개최자")
    return Contest.objects.create(
        sponsor=sponsor,
        title="명단 공모전",
        category=Category.objects.create(name=f"분류-{is_free}"),
        prize=0 if is_free else 3_000_000,
        is_free=is_free,
        deadline_at=timezone.now() + deadline_in,
        status=Contest.Status.PUBLISHED,
    )


def _submit(contest: Contest, name: str, display_name: str) -> ContestSubmission:
    user = _user(name)
    developer = DeveloperProfile.objects.create(user=user, display_name=display_name)
    return ContestSubmission.objects.create(
        contest=contest, developer=developer, user=user, product=Submission.Product.CONTEST
    )


@pytest.mark.django_db
@pytest.mark.parametrize("is_free", [False, True], ids=["유료", "무료"])
def test_sponsor_sees_names_and_times_only_before_deadline(client, is_free):
    contest = _contest(is_free=is_free)
    first = _submit(contest, "dev-a", "가나다")
    second = _submit(contest, "dev-b", "라마바")

    response = client.get(ROSTER_URL.format(contest_id=contest.id), **_auth(contest.sponsor.user_id))

    assert response.status_code == 200, response.content
    body = response.json()
    assert set(body) == {"contest_id", "entries"}
    assert body["contest_id"] == contest.id
    # 명단 칸 밖의 필드가 없다 — 제출 id·developer id·자료·점수 어느 것도 싣지 않는다.
    assert all(set(entry) == {"display_name", "submitted_at"} for entry in body["entries"])
    assert [e["display_name"] for e in body["entries"]] == ["가나다", "라마바"]
    assert [e["submitted_at"][:19] for e in body["entries"]] == [
        s.created_at.isoformat()[:19] for s in (first, second)
    ]


@pytest.mark.django_db
def test_withdrawn_developer_is_listed_without_a_name(client):
    contest = _contest(is_free=False)
    gone = _submit(contest, "dev-gone", "떠난 사람")
    execute_withdrawal(gone.developer.user)

    response = client.get(ROSTER_URL.format(contest_id=contest.id), **_auth(contest.sponsor.user_id))

    assert response.status_code == 200, response.content
    assert [e["display_name"] for e in response.json()["entries"]] == [None]


@pytest.mark.django_db
def test_participant_and_stranger_cannot_read_the_roster(client):
    contest = _contest(is_free=False)
    participant = _submit(contest, "dev-in", "참가자")
    stranger = _user("stranger")
    url = ROSTER_URL.format(contest_id=contest.id)

    assert client.get(url).status_code == 401
    assert client.get(url, **_auth(participant.developer.user_id)).status_code == 403
    assert client.get(url, **_auth(stranger.id)).status_code == 403
    assert client.get(ROSTER_URL.format(contest_id=contest.id + 999), **_auth(stranger.id)).status_code == 404


@pytest.mark.django_db
def test_detail_before_deadline_is_unchanged_by_the_roster(client):
    """명단은 상세의 규칙을 바꾸지 않는다 — 다른 참가자에게는 여전히 404 다.

    마감 전 개최자의 단건 조회(데모·영상·스크린샷)는 지금 그대로다
    (`test_submissions.py` 의 `test_sponsor_can_view_demo_but_not_source_during_contest`).
    """

    contest = _contest(is_free=False)
    mine = _submit(contest, "dev-1", "하나")
    other = _submit(contest, "dev-2", "둘")

    response = client.get(DETAIL_URL.format(submission_id=mine.id), **_auth(other.developer.user_id))

    assert response.status_code == 404
