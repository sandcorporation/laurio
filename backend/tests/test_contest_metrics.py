"""Sponsor 지표 화면 — 일자별 누적 참가작 수(#107), Requirement 충족 분포·제출
채움률 분포(#108), 부모 #105.

지금까지 Sponsor 가 자기 Contest 상태를 아는 수단은 제출을 하나씩 열어보는
것뿐이었다. `GET /api/contests/{id}/metrics` 가 그 자리에 세 지표를 낸다:

- 일자별 누적 Submission 수 (#107)
- Requirement 별로 몇 명이 충족했는가 — 필수·선택 구별, 분모는 전체 Submission
  수 (#108)
- 제출 채움률 분포 — 데모·영상·테스트 계정이 붙은 비율 (#108)

시임은 언제나 HTTP 다(CLAUDE.md).
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Category, DeliverableType
from storage.adapters.fake import FakeStorageAdapter
from submissions.models import Submission
from contests.submission_target_refs import demo_video_target_ref, source_target_ref

from tests.test_source_readings import _publish_contest, _submit, _verified_user

METRICS_URL = "/api/contests/{contest_id}/metrics"
SUBMISSIONS_URL = "/api/contests/{contest_id}/submissions"
CONTESTS_URL = "/api/contests"


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _submit_full(
    client,
    dev: dict,
    contest_id: int,
    *,
    responses: list[dict],
    demo_video: bool = False,
    demo_url: str = "",
    test_account: str = "",
) -> dict:
    """`_submit`(test_source_readings)보다 유연한 버전 — 여러 Requirement 응답과
    채움률 필드(데모 영상·URL·테스트 계정)를 함께 제어한다. #108 의 분포
    테스트는 응답이 갈리는 Submission 을 여러 건 심어야 한다."""

    source_key = f"{source_target_ref(contest_id, dev['user_id'])}/{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(source_key, b"fake source zip bytes")

    assets = [{"kind": "source", "value": source_key}]
    # 테스트 계정은 데모 URL 자료에 붙는다(#190) — 계정만 주고 데모를 안 주면
    # 붙일 곳이 없으므로 데모 하나를 만들어 준다.
    url = demo_url or ("https://example.invalid/acct" if test_account else "")
    if url:
        assets.append({"kind": "demo_url", "value": url, "test_account": test_account})
    if demo_video:
        video_key = f"{demo_video_target_ref(contest_id, dev['user_id'])}/{uuid.uuid4().hex}"
        FakeStorageAdapter().write_object(video_key, b"fake video bytes")
        assets.append({"kind": "demo_video", "value": video_key})

    payload = {"assets": assets, "requirement_responses": responses}

    response = client.post(
        SUBMISSIONS_URL.format(contest_id=contest_id),
        data=payload,
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


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


# --- #108: Requirement 별 충족 분포 --------------------------------------------


@pytest.mark.django_db
def test_requirement_fulfillment_matches_actual_responses_seeded_and_counted_together(
    client, category, landing_type
):
    """일부만 충족한 Submission 을 심어 숫자가 갈리는 것을 본다 — 필수와 선택이
    구별된다."""

    deadline = timezone.now() + timedelta(days=10)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "다크모드가 있다", "grade": "optional"},
        ],
    )
    required_id = contest["requirements"][0]["id"]
    optional_id = contest["requirements"][1]["id"]

    dev_a = _verified_user(client, "dev-fulfillment-a", "ci-fulfillment-a")
    dev_b = _verified_user(client, "dev-fulfillment-b", "ci-fulfillment-b")
    dev_c = _verified_user(client, "dev-fulfillment-c", "ci-fulfillment-c")

    # A: 둘 다 충족. B: 필수만 충족, 선택은 미충족. C: 필수 응답 자체가 없다
    # (자가 응답을 안 남긴 것도 "충족하지 못함"으로 세야 한다).
    _submit_full(
        client, dev_a, contest["id"],
        responses=[
            {"requirement_id": required_id, "is_met": True},
            {"requirement_id": optional_id, "is_met": True},
        ],
    )
    _submit_full(
        client, dev_b, contest["id"],
        responses=[
            {"requirement_id": required_id, "is_met": True},
            {"requirement_id": optional_id, "is_met": False},
        ],
    )
    _submit_full(client, dev_c, contest["id"], responses=[])

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["total_submission_count"] == 3

    fulfillment_by_id = {r["requirement_id"]: r for r in body["requirement_fulfillment"]}
    required_row = fulfillment_by_id[required_id]
    optional_row = fulfillment_by_id[optional_id]

    assert required_row["grade"] == "required"
    assert required_row["met_count"] == 2
    assert required_row["total_submission_count"] == 3

    assert optional_row["grade"] == "optional"
    assert optional_row["met_count"] == 1
    assert optional_row["total_submission_count"] == 3


@pytest.mark.django_db
def test_a_requirement_nobody_met_is_reported_as_zero(client, category, landing_type):
    """아무도 충족하지 못한 Requirement 도 0 으로 정확히 나온다 — 화면이 그것을
    눈에 띄게 만드는 재료다."""

    deadline = timezone.now() + timedelta(days=10)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "과한 요구사항", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-fulfillment-zero", "ci-fulfillment-zero")
    _submit_full(
        client, dev, contest["id"],
        responses=[{"requirement_id": requirement_id, "is_met": False}],
    )

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200
    row = response.json()["requirement_fulfillment"][0]
    assert row["met_count"] == 0
    assert row["total_submission_count"] == 1


@pytest.mark.django_db
def test_a_contest_with_no_requirements_reports_an_empty_fulfillment_list(
    client, category, landing_type
):
    """Requirement 응답이 없어도(이 경우 Requirement 자체가 없어도) 화면이
    깨지지 않고 그렇게 말한다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200
    assert response.json()["requirement_fulfillment"] == []


# --- #108: 제출 채움률 분포 -----------------------------------------------------


@pytest.mark.django_db
def test_completion_distribution_matches_actual_submissions(client, category, landing_type):
    deadline = timezone.now() + timedelta(days=10)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "요구사항", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev_a = _verified_user(client, "dev-completion-a", "ci-completion-a")
    dev_b = _verified_user(client, "dev-completion-b", "ci-completion-b")

    # A: 데모 영상·URL·테스트 계정 전부. B: 아무것도 없음.
    _submit_full(
        client, dev_a, contest["id"],
        responses=[{"requirement_id": requirement_id, "is_met": True}],
        demo_video=True,
        demo_url="https://example.invalid/demo-a",
        test_account="id:pw",
    )
    _submit_full(
        client, dev_b, contest["id"],
        responses=[{"requirement_id": requirement_id, "is_met": False}],
    )

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200, response.content
    completion = response.json()["completion_distribution"]
    assert completion["total_submission_count"] == 2
    assert completion["demo_video_count"] == 1
    assert completion["demo_url_count"] == 1
    assert completion["test_account_count"] == 1


@pytest.mark.django_db
def test_completion_distribution_is_all_zero_when_there_are_no_submissions(
    client, category, landing_type
):
    """참가작이 하나도 없어도 화면이 깨지지 않고 그렇게 말한다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200
    completion = response.json()["completion_distribution"]
    assert completion == {
        "total_submission_count": 0,
        "demo_video_count": 0,
        "demo_url_count": 0,
        "test_account_count": 0,
        "repository_count": 0,
    }


# --- #108: 사람이 아니라 일에 대한 정보다 — Score·개별 Submission 이 없다 -------


@pytest.mark.django_db
def test_metrics_response_never_mentions_score_or_developer_identity(
    client, category, landing_type
):
    """Score 는 이 화면 어디에도 없다(ADR-0006/0014) — 집계로 우회하지 않는다.
    개별 Submission 도 새로 노출하지 않는다 — 응답에 developer 식별자가 없다.

    **있는지가 아니라 없는지**를 단언한다 — 응답 본문 전체(직렬화된 JSON
    텍스트)에 그 문자열이 조금도 없어야 한다."""

    deadline = timezone.now() + timedelta(days=10)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "요구사항", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-no-score-leak", "ci-no-score-leak")
    _submit_full(
        client, dev, contest["id"],
        responses=[{"requirement_id": requirement_id, "is_met": True}],
        demo_video=True,
        demo_url="https://example.invalid/demo",
        test_account="id:pw",
    )

    # 이 Contest 를 마감·채점까지 돌려 Score 가 실제로 존재하게 만든다 — "코드
    # 경로가 아예 없어서" 안전한 게 아니라 "있는데도 안 새는지" 를 증명해야
    # 한다(judge/page.tsx·compare_submissions 테스트와 같은 원칙).
    from tests.test_source_readings import _close_contest, _run_scoring

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    response = _metrics(client, sponsor["access"], contest["id"])

    assert response.status_code == 200, response.content
    raw = response.content.decode("utf-8")
    assert "score" not in raw.lower()
    assert "percentage" not in raw.lower()
    assert "developer" not in raw.lower()
    assert "prompt" not in raw.lower()


# --- #109: ContestView — 조회수와 전환율 -------------------------------------
#
# `CONTEXT.md`의 `ContestView` 정의: 사건을 저장하지 않는다. 날짜별 고유 수만
# 남고, 같은 사람이 같은 날 여러 번 열어도 하나다. 서버 렌더는 세지 않는다 —
# 브라우저가 마운트된 뒤에 `POST /api/contests/{id}/views`로 알린다.

CONTEST_DETAIL_URL = "/api/contests/{contest_id}"
VIEWS_URL = "/api/contests/{contest_id}/views"
FLUSH_VIEWS_URL = "/api/internal/scans/contest-view-flush"


def _record_view(client, contest_id: int, *, access: str | None = None, **extra):
    headers = _auth_header(access) if access else {}
    headers.update(extra)
    return client.post(VIEWS_URL.format(contest_id=contest_id), **headers)


def _flush_views(client) -> dict:
    """조회수 옮기기 스캔을 한 번 돌린다(#446) — 지표 화면·공개 목록·큐레이션은
    Redis 를 직접 읽지 않고 이 스캔이 옮긴 `Contest.view_count`(DB)를 읽으므로,
    조회를 기록한 뒤 그 값을 확인하려면 먼저 이 스캔을 거쳐야 한다."""

    from django.conf import settings

    response = client.post(FLUSH_VIEWS_URL, HTTP_X_INTERNAL_TOKEN=settings.INTERNAL_API_TOKEN)
    assert response.status_code == 200, response.content
    return response.json()


def _view_metrics(client, access: str, contest_id: int) -> dict:
    _flush_views(client)
    response = _metrics(client, access, contest_id)
    assert response.status_code == 200, response.content
    return response.json()["view_metrics"]


@pytest.mark.django_db
def test_recording_a_view_for_a_missing_contest_is_404(client):
    response = _record_view(client, 999_999)

    assert response.status_code == 404


@pytest.mark.django_db
def test_a_person_opening_the_contest_detail_counts_as_one_view(
    client, category, landing_type
):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-view-1", "ci-view-1")

    response = _record_view(client, contest["id"], access=dev["access"])
    assert response.status_code == 200, response.content

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 1


@pytest.mark.django_db
def test_the_same_person_opening_it_twice_in_a_day_still_counts_as_one(
    client, category, landing_type
):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-view-dup", "ci-view-dup")

    _record_view(client, contest["id"], access=dev["access"])
    _record_view(client, contest["id"], access=dev["access"])
    _record_view(client, contest["id"], access=dev["access"])

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 1


@pytest.mark.django_db
def test_moving_the_clock_a_day_forward_counts_again(client, category, landing_type):
    """중복 판별에 쓰는 날짜는 주입된 시계에서 온다(ADR-0003) — 시계를 하루 밀면
    다시 세진다."""

    from core.models import ClockOverride

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-view-clock", "ci-view-clock")

    day_one = timezone.now()
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": day_one})
    _record_view(client, contest["id"], access=dev["access"])

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 1

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": day_one + timedelta(days=1)}
    )
    _record_view(client, contest["id"], access=dev["access"])

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 2


@pytest.mark.django_db
def test_a_different_person_opening_it_makes_the_count_two(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev_a = _verified_user(client, "dev-view-a", "ci-view-a")
    dev_b = _verified_user(client, "dev-view-b", "ci-view-b")

    _record_view(client, contest["id"], access=dev_a["access"])
    _record_view(client, contest["id"], access=dev_b["access"])

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 2


@pytest.mark.django_db
def test_two_anonymous_visitors_with_different_ips_both_count(client, category, landing_type):
    """로그인하지 않은 방문자도 조회로 잡힌다 — IP+User-Agent 로 구별한다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    _record_view(
        client, contest["id"],
        REMOTE_ADDR="203.0.113.5", HTTP_USER_AGENT="anon-browser-a",
    )
    _record_view(
        client, contest["id"],
        REMOTE_ADDR="203.0.113.9", HTTP_USER_AGENT="anon-browser-b",
    )

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 2


@pytest.mark.django_db
def test_the_sponsors_own_view_of_their_contest_is_not_counted(client, category, landing_type):
    """자기가 새로고침한 것이 자기 지표를 부풀리면 그 지표는 쓸모가 없다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    _record_view(client, contest["id"], access=sponsor["access"])
    _record_view(client, contest["id"], access=sponsor["access"])

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 0


@pytest.mark.django_db
def test_rendering_the_public_detail_twice_does_not_count_a_view(client, category, landing_type):
    """서버 렌더가 조회를 세지 않는다 — `GET /contests/{id}`(SSR 이 읽는 공개
    상세)를 두 번 쳐도 조회수는 그대로다. 세는 것은 브라우저가 연 뒤 알리는
    `POST /contests/{id}/views` 뿐이다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    detail_url = CONTEST_DETAIL_URL.format(contest_id=contest["id"])
    assert client.get(detail_url).status_code == 200
    assert client.get(detail_url).status_code == 200

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 0


@pytest.mark.django_db
def test_conversion_rate_is_none_when_there_are_no_views(client, category, landing_type):
    """조회가 0 이어도 전환율 자리가 깨지지 않는다 — 0 으로 나누지 않는다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 0
    assert metrics["conversion_rate"] is None


@pytest.mark.django_db
def test_conversion_rate_matches_submission_count_over_view_count(
    client, category, landing_type
):
    """전환율이 참가작 수와 조회수에서 일관되게 나온다."""

    deadline = timezone.now() + timedelta(days=10)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "요구사항", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev_a = _verified_user(client, "dev-conv-a", "ci-conv-a")
    dev_b = _verified_user(client, "dev-conv-b", "ci-conv-b")
    dev_c = _verified_user(client, "dev-conv-c", "ci-conv-c")

    for dev in (dev_a, dev_b, dev_c):
        _record_view(client, contest["id"], access=dev["access"])

    _submit_full(
        client, dev_a, contest["id"],
        responses=[{"requirement_id": requirement_id, "is_met": True}],
    )

    metrics = _view_metrics(client, sponsor["access"], contest["id"])
    assert metrics["view_count"] == 3
    assert metrics["conversion_rate"] == pytest.approx(1 / 3)


@pytest.mark.django_db
def test_view_count_is_public_but_view_metrics_and_conversion_rate_are_not(
    client, category, landing_type
):
    """#446 — 누적 조회수(`view_count`)는 이제 공개 목록·상세 응답에도 실린다
    (`ContestOut`을 세 엔드포인트가 함께 쓴다). 다만 「본 사람 대비 낸 사람」을
    해석하는 `view_metrics`(전환율 포함, Sponsor 전용 집계)는 여전히 공개 표면
    어디에도 없다 — 공개되는 것은 DB 값 하나뿐이다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-view-public-leak", "ci-view-public-leak")
    _record_view(client, contest["id"], access=dev["access"])
    _flush_views(client)

    detail_response = client.get(CONTEST_DETAIL_URL.format(contest_id=contest["id"]))
    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["view_count"] == 1
    assert "view_metrics" not in detail_body
    assert "conversion_rate" not in detail_body

    list_response = client.get(CONTESTS_URL)
    assert list_response.status_code == 200
    listed = next(
        item for item in list_response.json()["items"] if item["id"] == contest["id"]
    )
    assert listed["view_count"] == 1
    assert "view_metrics" not in listed
    assert "conversion_rate" not in listed


@pytest.mark.django_db
def test_view_metrics_response_carries_no_visitor_identifying_value(
    client, category, landing_type
):
    """조회 집계 어디에도 방문자를 식별할 값이 남지 않는다 — **있는지가 아니라
    없는지**를 단언한다. 응답 전체(직렬화된 JSON 텍스트)에 방문자를 가리키는
    원문(사용자 id, IP, User-Agent)이 조금도 없어야 한다 — 남는 것은 Contest
    별 집계 숫자뿐이다."""

    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-view-no-identity-leak", "ci-view-no-identity-leak")

    view_response = _record_view(
        client, contest["id"], access=dev["access"],
        HTTP_USER_AGENT="marker-user-agent-should-not-leak",
    )
    assert view_response.status_code == 200
    assert "marker-user-agent-should-not-leak" not in view_response.content.decode("utf-8")

    _flush_views(client)
    metrics_response = _metrics(client, sponsor["access"], contest["id"])
    assert metrics_response.status_code == 200
    metrics_raw = metrics_response.content.decode("utf-8")
    assert str(dev["user_id"]) not in metrics_raw
    assert "marker-user-agent-should-not-leak" not in metrics_raw

    view_metrics = metrics_response.json()["view_metrics"]
    assert set(view_metrics.keys()) == {"view_count", "conversion_rate"}
