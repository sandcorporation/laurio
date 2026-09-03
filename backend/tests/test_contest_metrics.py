"""Sponsor 지표 화면 — 일자별 누적 참가작 수 (#107, 부모 #105).

지금까지 Sponsor 가 자기 Contest 상태를 아는 수단은 제출을 하나씩 열어보는
것뿐이었다. 이 티켓은 그 화면의 첫 지표 — **일자별 누적 Submission 수** — 를
`GET /api/contests/{id}/metrics` 로 낸다.

시임은 언제나 HTTP 다(CLAUDE.md). Requirement 충족 분포·완성도 분포(#108)는
이 파일이 다루지 않는다 — 다음 티켓의 몫이다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType
from submissions.models import Submission

from tests.test_source_readings import _publish_contest, _submit, _verified_user

METRICS_URL = "/api/contests/{contest_id}/metrics"


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


def _metrics(client, access: str, contest_id: int):
    return client.get(METRICS_URL.format(contest_id=contest_id), **_auth_header(access))


# --- 인증·소유권 -------------------------------------------------------------


@pytest.mark.django_db
def test_metrics_requires_authentication(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    response = client.get(METRICS_URL.format(contest_id=contest["id"]))

    assert response.status_code == 401


@pytest.mark.django_db
def test_metrics_for_nonexistent_contest_is_404(client, category, landing_type):
    sponsor, _contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    response = _metrics(client, sponsor["access"], 999_999)

    assert response.status_code == 404


@pytest.mark.django_db
def test_a_sponsor_cannot_reach_another_sponsors_metrics(client, category, landing_type):
    """자기 Contest 에만 열린다 — **있는지가 아니라 없는지**로 단언한다."""

    _owner, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor_uid="sponsor-owner", sponsor_ci="ci-owner",
    )
    other = _verified_user(client, "sponsor-intruder", "ci-intruder")

    response = _metrics(client, other["access"], contest["id"])

    assert response.status_code == 403
    # 남의 Contest 로는 지표 데이터에 조금도 닿지 않는다 — 403 본문에 집계가
    # 실려 있으면 안 된다.
    assert "daily_participation" not in response.json()


# --- 마감 전에도 보인다 -------------------------------------------------------


@pytest.mark.django_db
def test_metrics_are_visible_before_the_deadline(client, category, landing_type):
    """Sponsor 는 마감 전에도 개별 Submission 을 볼 수 있으므로, 집계도 마감 전에
    보여야 새로 알려주는 것이 없다 — `compare_submissions` 와 달리 게이트가
    없다."""

    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=timezone.now() + timedelta(days=3),
    )

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200, response.content
    assert response.json()["contest_id"] == contest["id"]


# --- 빈 상태 -------------------------------------------------------------------


@pytest.mark.django_db
def test_a_contest_with_no_submissions_reports_an_empty_but_valid_state(
    client, category, landing_type
):
    """참가작이 하나도 없어도 화면이 깨지지 않고 그렇게 말한다 — 빈 상태와 오류가
    구별된다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200
    body = response.json()
    assert body["total_submission_count"] == 0
    assert body["daily_participation"] == []


# --- 일자별 누적치가 실제 Submission 과 일치한다 -------------------------------


@pytest.mark.django_db
def test_daily_participation_matches_actual_submissions_seeded_and_counted_together(
    client, category, landing_type
):
    """심고 세는 것을 같은 테스트에서 대비시킨다 — 참가작 수가 실제 Submission
    수와 일치한다."""

    deadline = timezone.now() + timedelta(days=10)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev_a = _verified_user(client, "dev-metrics-a", "ci-metrics-a")
    dev_b = _verified_user(client, "dev-metrics-b", "ci-metrics-b")
    dev_c = _verified_user(client, "dev-metrics-c", "ci-metrics-c")

    sub_a = _submit(client, dev_a, contest["id"], requirement_id=requirement_id)
    sub_b = _submit(client, dev_b, contest["id"], requirement_id=requirement_id)
    sub_c = _submit(client, dev_c, contest["id"], requirement_id=requirement_id)

    # 실제로 심어진 날짜를 흩뿌린다 — a·b는 D-2, c는 D-1. `created_at`은
    # auto_now_add라 API로는 지정할 수 없으므로 심고 난 뒤 시각만 옮긴다(시나리오
    # 재현이지 시임 우회가 아니다 — 관찰은 여전히 HTTP 응답으로 한다).
    two_days_ago = timezone.now() - timedelta(days=2)
    one_day_ago = timezone.now() - timedelta(days=1)
    Submission.objects.filter(id__in=[sub_a["id"], sub_b["id"]]).update(created_at=two_days_ago)
    Submission.objects.filter(id=sub_c["id"]).update(created_at=one_day_ago)

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["total_submission_count"] == 3

    daily = body["daily_participation"]
    assert len(daily) == 2
    # 누적이어야 한다 — 둘째 날은 셋째까지 합쳐 3이지, 그날 하루의 1이 아니다.
    assert daily[0]["cumulative_count"] == 2
    assert daily[1]["cumulative_count"] == 3
    # 날짜 순서로 나온다.
    assert daily[0]["date"] < daily[1]["date"]


@pytest.mark.django_db
def test_daily_participation_is_ordered_by_date_regardless_of_creation_order(
    client, category, landing_type
):
    """언제 순서로 제출됐든, 응답은 날짜순으로 정렬돼 나온다."""

    deadline = timezone.now() + timedelta(days=10)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "다크모드", "grade": "optional"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-metrics-order", "ci-metrics-order")
    sub = _submit(client, dev, contest["id"], requirement_id=requirement_id)

    long_ago = timezone.now() - timedelta(days=5)
    Submission.objects.filter(id=sub["id"]).update(created_at=long_ago)

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200
    daily = response.json()["daily_participation"]
    assert len(daily) == 1
    assert daily[0]["cumulative_count"] == 1
