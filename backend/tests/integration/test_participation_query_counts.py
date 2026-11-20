"""「다음 행동」과 점수·무료 공모전 화면의 쿼리 수를 못 박는다 (#1102).

이 화면들은 위 앱(채점·이의·선정·인수)의 행으로 판정한다. 그 관계를 공모전 앱이 직접 적지 않고 위 앱이 등록
자리로 올리게 뒤집었다 — 뒤집기가 select_related 하나라도 빠뜨리면 목록이 행마다 조회한다. 그래서 판정의 모든
갈래(마감 전·채점 대기·이의 대기·선정·남이 선정·무료 수상)를 한 참가자에게 심고 요청마다 쿼리 수를 센다.
행을 더 심은 뒤의 수(`_more_rows`)도 못 박는다 — 빠진 select_related 는 여기서 갈린다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from appeals.models import Appeal
from awards.models import Award
from contests.models import Category, Contest, ContestSubmission
from handovers.models import Handover
from scoring.models import Score
from submissions.models import Submission
from verification.models import Verification

ORIGIN = "http://testserver"
PW = "operator-pw-1102-query-counts"


def _login(client: Client, uid: str) -> str:
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()["access"]


def _auth(access: str) -> dict[str, str]:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _developer(user) -> DeveloperProfile:
    Verification.objects.create(
        user=user, status=Verification.Status.VERIFIED, real_name_encrypted="x", birth_date_encrypted="x"
    )
    return DeveloperProfile.objects.create(user=user)


def _contest(sponsor: SponsorProfile, category: Category, *, deadline_in: timedelta, is_free: bool = False) -> Contest:
    now = timezone.now()
    return Contest.objects.create(
        sponsor=sponsor,
        title=f"쿼리 수 {uuid4().hex[:8]}",
        category=category,
        prize=0 if is_free else 900_000,
        is_free=is_free,
        deadline_at=now + deadline_in,
        judging_ends_at=now + deadline_in + timedelta(days=7),
        status=Contest.Status.PUBLISHED if deadline_in > timedelta(0) else Contest.Status.CLOSED,
    )


def _submit(contest: Contest, developer: DeveloperProfile) -> ContestSubmission:
    return ContestSubmission.objects.create(
        user=developer.user, product=Submission.Product.CONTEST, contest=contest, developer=developer
    )


def _score(submission: ContestSubmission) -> Score:
    return Score.objects.create(
        submission=submission, percentage=80, model_version="fake", prompt="p", reasoning={}
    )


def _award(contest: Contest, submission: ContestSubmission) -> Award:
    return Award.objects.create(contest=contest, submission=submission, awarded_at=timezone.now())


def _more_rows(sponsor, category, developer, other) -> None:
    """판정 갈래마다 한 행씩 더 — 쿼리 수가 행 수를 따라 늘면 N+1 이다."""

    _submit(_contest(sponsor, category, deadline_in=timedelta(days=3)), developer)
    scored = _submit(_contest(sponsor, category, deadline_in=-timedelta(days=1)), developer)
    _score(scored)
    Appeal.objects.create(submission=scored, reason="다시 봐 주세요")
    lost = _contest(sponsor, category, deadline_in=-timedelta(days=1))
    _score(_submit(lost, developer))
    _award(lost, _submit(lost, other))


@pytest.fixture
def world(db):
    client = Client()
    uid = f"qc-dev-{uuid4().hex[:6]}"
    access = _login(client, uid)
    me = _developer(get_user_model().objects.get(email=f"{uid}@example.com"))
    other_user = get_user_model().objects.create_user(username="qc-other", email="qc-other@example.invalid")
    other = _developer(other_user)
    sponsor_user = get_user_model().objects.create_user(username="qc-sponsor", email="qc-sponsor@example.invalid")
    sponsor = SponsorProfile.objects.create(user=sponsor_user, display_name="쿼리 수 개최자")
    category = Category.objects.create(name="쿼리 수")

    # 마감 전 · 채점 대기 · 채점 끝 + 이의 대기 · 선정(인수 대기) · 남이 선정 · 무료 수상
    _submit(_contest(sponsor, category, deadline_in=timedelta(days=3)), me)
    _submit(_contest(sponsor, category, deadline_in=-timedelta(days=1)), me)
    appealed = _submit(_contest(sponsor, category, deadline_in=-timedelta(days=1)), me)
    _score(appealed)
    Appeal.objects.create(submission=appealed, reason="다시 봐 주세요")
    won_contest = _contest(sponsor, category, deadline_in=-timedelta(days=8))
    won = _submit(won_contest, me)
    _score(won)
    award = _award(won_contest, won)
    Handover.objects.create(
        award=award, status=Handover.Status.PENDING_ACCEPTANCE, release_deadline_at=timezone.now() + timedelta(days=3)
    )
    lost_contest = _contest(sponsor, category, deadline_in=-timedelta(days=1))
    _score(_submit(lost_contest, me))
    _award(lost_contest, _submit(lost_contest, other))
    free_contest = _contest(sponsor, category, deadline_in=-timedelta(days=1), is_free=True)
    _award(free_contest, _submit(free_contest, me))

    return {
        "client": client, "access": access, "me": me, "other": other, "sponsor": sponsor, "category": category,
        "appealed": appealed, "won": won, "won_contest": won_contest,
    }


def _count(fn) -> int:
    with CaptureQueriesContext(connection) as ctx:
        response = fn()
    assert response.status_code == 200, response.content
    return len(ctx.captured_queries)


def test_my_participation_query_count_does_not_grow_with_rows(world):
    client, access = world["client"], world["access"]

    def get():
        return client.get("/api/submissions/mine", **_auth(access))

    before = _count(get)
    _more_rows(world["sponsor"], world["category"], world["me"], world["other"])
    assert (before, _count(get)) == MY_PARTICIPATION


def test_my_submission_query_count(world):
    client, access = world["client"], world["access"]
    url = f"/api/contests/{world['won_contest'].id}/submissions/me"
    assert _count(lambda: client.get(url, **_auth(access))) == MY_SUBMISSION


def test_submission_detail_query_count_for_the_owner(world):
    client, access = world["client"], world["access"]
    url = f"/api/submissions/{world['won'].id}"
    assert _count(lambda: client.get(url, **_auth(access))) == SUBMISSION_DETAIL


def test_own_score_query_count(world):
    client, access = world["client"], world["access"]
    url = f"/api/submissions/{world['appealed'].id}/score"
    assert _count(lambda: client.get(url, **_auth(access))) == OWN_SCORE


def test_operator_free_contests_query_count_does_not_grow_with_rows(world):
    call_command("create_operator", "qc-operator", password=PW, superuser=True)
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": "qc-operator", "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content

    def get():
        return operator.get("/api/operator/contests/free", HTTP_ORIGIN=ORIGIN)

    before = _count(get)
    free = _contest(world["sponsor"], world["category"], deadline_in=-timedelta(days=2), is_free=True)
    _award(free, _submit(free, world["other"]))
    assert (before, _count(get)) == FREE_CONTESTS


#: 심은 행 → 행을 더 심은 뒤. 판정 갈래 셋(채점 대기 크기 보류·지급 단계·이의 창)이 행마다 한 번씩 묻는 것이
#: 뒤집기 전부터 있다(13 → 16) — 이 수가 더 늘면 뒤집기가 select_related 를 빠뜨린 것이다.
MY_PARTICIPATION = (13, 16)
MY_SUBMISSION = 14
SUBMISSION_DETAIL = 12
OWN_SCORE = 7
#: 수상자 한 줄마다 한 번 묻는 것이 뒤집기 전부터 있다(3 → 4)
FREE_CONTESTS = (3, 4)
