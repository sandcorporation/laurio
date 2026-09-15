"""무료 공모전 — 마감 뒤 수상작을 고르면 개최자가 소스를 보고, 돈 절차
없이 끝난다 (#417, ADR-0048).

HTTP 시임만 쓴다(CLAUDE.md). 개최·제출 헬퍼는 `tests/test_free_contest_hosting.py`
·`tests/test_free_contest_submission.py`와 같은 형식을 따른다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from awards.models import Award
from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from distributions.models import Distribution
from handovers.models import Handover
from notifications.models import Notification, NotificationType

ORIGIN = "http://testserver"
PERMISSIONS_URL = "/api/operator/hosting-permissions"
CONTESTS_URL = "/api/contests"
TICK_URL = "/api/internal/tick"
PW = "operator-pw-9942-xkcd-privacy"

pytestmark = pytest.mark.django_db


# --- 헬퍼 --------------------------------------------------------------------


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _operator_client(username, *, superuser=True):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _login(client, uid):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.com"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _hosted_user(client, uid: str) -> dict:
    pair = _login(client, uid)
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email=f"{uid}@example.com")
    return {"access": pair["access"], "user_id": user.id}


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _grant(operator_client, user_id: int, *, reason="테스트 개최 권한"):
    response = operator_client.post(
        f"{PERMISSIONS_URL}/{user_id}",
        data={"granted": True, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일-수상")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지-수상", minimum_prize=500_000)


def _free_published_contest(
    client, *, host_uid, deadline_at, category, landing_type
) -> tuple[dict, dict]:
    host = _hosted_user(client, host_uid)
    root = _operator_client(f"root-{host_uid}")
    _grant(root, host["user_id"])

    draft = client.post(
        f"{CONTESTS_URL}/free",
        data={
            "title": f"{host_uid}의 무료 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "description": "",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [{"text": "할 일을 추가·완료할 수 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(host["access"]),
    ).json()

    published = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert published.status_code == 200, published.content
    return host, published.json()


def _source_asset(contest_id: int, user_id: int) -> dict:
    return {
        "kind": "source",
        "value": f"submission:{contest_id}:{user_id}:source/{uuid4().hex}",
    }


def _submit(client, dev: dict, contest_id: int) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [_source_asset(contest_id, dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _close_contest(client, contest: dict, *, deadline) -> None:
    _freeze(deadline + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED


def _award(client, host: dict, contest_id: int, submission_id: int):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/award",
        data={"submission_id": submission_id},
        content_type="application/json",
        **_auth_header(host["access"]),
    )


# --- 마감 → 채점 → 심사종료: 무료 공모전도 같은 전이를 거친다 ------------------


@pytest.mark.django_db
def test_free_contest_closes_and_scores_like_a_paid_one(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-close", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-close-dev")
    _submit(client, dev, contest["id"])

    _close_contest(client, contest, deadline=deadline)
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED


# --- Award: Handover 없이, 알림은 그대로 -------------------------------------


@pytest.mark.django_db
def test_awarding_a_free_contest_creates_award_without_handover(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-1", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-1-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    resp = _award(client, host, contest["id"], submission["id"])
    assert resp.status_code == 200, resp.content

    assert Award.objects.filter(contest_id=contest["id"], submission_id=submission["id"]).exists()
    award = Award.objects.get(contest_id=contest["id"])
    assert not Handover.objects.filter(award=award).exists()
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.AWARDED


@pytest.mark.django_db
def test_awarded_free_contest_developer_next_action_is_awarded_not_a_payout_state(
    client, category, landing_type
):
    """수상한 developer 의 「다음 행동」은 `awarded`다 — 유료 경로처럼
    `awaiting_handover_release`/`request_payout`/`payout_complete` 로 갈리지
    않는다(#417). Score 유무와 무관해야 하므로 채점을 먼저 끝낸다
    (`next_action_for`는 Award 확인보다 Score 확인이 먼저다)."""

    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-next-action", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-next-action-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    _freeze(Contest.objects.get(id=contest["id"]).deadline_at + timedelta(hours=7))
    for _ in range(5):
        scoring_resp = client.post(
            "/api/internal/scans/submission-scoring", **_internal_headers()
        )
        assert scoring_resp.status_code == 200, scoring_resp.content

    award_resp = _award(client, host, contest["id"], submission["id"])
    assert award_resp.status_code == 200, award_resp.content

    me_resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )
    assert me_resp.status_code == 200, me_resp.content
    assert me_resp.json()["next_action"] == "awarded"


@pytest.mark.django_db
def test_award_result_notification_still_sent_for_free_contest(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-notify", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-notify-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    resp = _award(client, host, contest["id"], submission["id"])
    assert resp.status_code == 200, resp.content

    assert Notification.objects.filter(
        recipient_id=dev["user_id"], notification_type=NotificationType.RESULT_NOTICE
    ).exists()


# --- 소스 열람: Award 기준으로 열리고, 수상 못 한 제출은 닫힌 채 -----------------


@pytest.mark.django_db
def test_host_can_read_the_awarded_submissions_source_but_not_the_losers(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-source", deadline_at=deadline, category=category, landing_type=landing_type
    )
    winner = _hosted_user(client, "free-award-source-winner")
    loser = _hosted_user(client, "free-award-source-loser")
    winner_submission = _submit(client, winner, contest["id"])
    loser_submission = _submit(client, loser, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    resp = _award(client, host, contest["id"], winner_submission["id"])
    assert resp.status_code == 200, resp.content

    winner_detail = client.get(
        f"/api/submissions/{winner_submission['id']}", **_auth_header(host["access"])
    )
    assert winner_detail.status_code == 200, winner_detail.content
    winner_source_kinds = {a["kind"] for a in winner_detail.json()["assets"]}
    assert "source" in winner_source_kinds

    loser_detail = client.get(
        f"/api/submissions/{loser_submission['id']}", **_auth_header(host["access"])
    )
    assert loser_detail.status_code == 200, loser_detail.content
    loser_source_kinds = {a["kind"] for a in loser_detail.json()["assets"]}
    assert "source" not in loser_source_kinds


# --- 없는 절차: 이의제기·지급 요청·인수인계·유료 연장이 거절된다 ---------------


@pytest.mark.django_db
def test_appeal_is_rejected_for_a_free_contest(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-appeal", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-appeal-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    resp = _award(client, host, contest["id"], submission["id"])
    assert resp.status_code == 200

    appeal_resp = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": "이의를 제기합니다"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert appeal_resp.status_code == 404, appeal_resp.content


@pytest.mark.django_db
def test_payout_request_is_rejected_for_a_free_contest_award(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-payout", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-payout-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    award_resp = _award(client, host, contest["id"], submission["id"])
    assert award_resp.status_code == 200

    payout_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/payout",
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert payout_resp.status_code == 404, payout_resp.content


@pytest.mark.django_db
def test_handover_accept_is_rejected_for_a_free_contest_award(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-handover", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-handover-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    award_resp = _award(client, host, contest["id"], submission["id"])
    assert award_resp.status_code == 200

    accept_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept",
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert accept_resp.status_code == 404, accept_resp.content

    get_resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/handover", **_auth_header(host["access"])
    )
    assert get_resp.status_code == 404, get_resp.content


@pytest.mark.django_db
def test_paid_judging_extension_is_rejected_for_a_free_contest_even_with_paid_switch_on(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-extend", deadline_at=deadline, category=category, landing_type=landing_type
    )
    _close_contest(client, contest, deadline=deadline)

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert resp.status_code == 409, resp.content
    assert Contest.objects.get(id=contest["id"]).judging_extension_count == 0


# --- 심사 기간 안에 수상하지 않으면: 수상 없이 끝난다, 배분이 생기지 않는다 -----


@pytest.mark.django_db
def test_free_contest_without_an_award_ends_with_no_award_and_no_distribution(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-none", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-none-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    # 무응답 배분(#16)이 도는 기준일보다 충분히 지난 시각까지 앞당긴다 — 무료
    # 공모전이면 그래도 Distribution이 생기지 않는다는 것을 증명한다. 이
    # 시각은 채점 유예(`scoring.services.SCORING_FAILURE_GRACE`, 마감 후
    # 6시간)도 이미 지난 시점이라, 소스를 찾지 못해도(가짜 object_key라
    # 스토리지에 실제로 없다) 채점이 0%로 확정된다.
    _freeze(judging_ends_at + timedelta(days=30))

    # 실패 상한(`scoring.services.SCORING_FAILURE_LIMIT`=5)에 이를 때까지
    # 스캔을 반복한다 — 가짜 object_key라 소스를 절대 못 찾으므로
    # `source_not_found`가 5번 쌓여야(+유예 경과) 0%로 확정된다(ADR-0031).
    for _ in range(5):
        scoring_resp = client.post(
            "/api/internal/scans/submission-scoring", **_internal_headers()
        )
        assert scoring_resp.status_code == 200, scoring_resp.content

    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200

    closed = Contest.objects.get(id=contest["id"])
    assert closed.status == Contest.Status.JUDGING_ENDED
    assert not Award.objects.filter(contest_id=contest["id"]).exists()
    assert not Distribution.objects.filter(contest_id=contest["id"]).exists()

    me_resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )
    assert me_resp.status_code == 200, me_resp.content
    assert me_resp.json()["next_action"] == "not_selected"


# --- 「내 공모전」의 다음 행동(SponsorNextAction) — 개최자 쪽도 배분/인수로
# 새지 않는다 --------------------------------------------------------------


def _my_contest_row(client, access: str, contest_id: int) -> dict:
    response = client.get("/api/contests/mine", **_auth_header(access))
    assert response.status_code == 200, response.content
    (row,) = [item for item in response.json()["items"] if item["contest_id"] == contest_id]
    return row


@pytest.mark.django_db
def test_sponsor_next_action_is_complete_right_after_awarding_a_free_contest(
    client, category, landing_type
):
    """유료 공모전이라면 Award 직후 「인수 확인」이 뜬다 — 무료 공모전은
    Handover 자체가 없으므로 선정되는 순간 「완료」다(#417)."""

    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-sponsor-action", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-sponsor-action-dev")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    award_resp = _award(client, host, contest["id"], submission["id"])
    assert award_resp.status_code == 200, award_resp.content

    row = _my_contest_row(client, host["access"], contest["id"])
    assert row["next_action"] == "contest_complete"


@pytest.mark.django_db
def test_sponsor_next_action_is_complete_not_awaiting_distribution_when_free_contest_ends_unawarded(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    host, contest = _free_published_contest(
        client, host_uid="free-award-sponsor-none", deadline_at=deadline, category=category, landing_type=landing_type
    )
    dev = _hosted_user(client, "free-award-sponsor-none-dev")
    _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(judging_ends_at + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.JUDGING_ENDED

    row = _my_contest_row(client, host["access"], contest["id"])
    assert row["next_action"] == "contest_complete"


# --- 유료 공모전 회귀: 기존 수상·지급 흐름은 그대로 초록이다 -------------------


@pytest.mark.django_db
def test_paid_contest_award_still_creates_handover(client, category, landing_type):
    from verification.models import Verification

    sponsor = _hosted_user(client, "paid-award-regression-sponsor")
    verify_resp = client.post(
        "/api/verification/verify",
        data={
            "verification_token": "사람|1990-01-01|paid-award-regression-ci|paid-award-regression-ci-di"
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert verify_resp.status_code == 200

    deadline = timezone.now() + timedelta(hours=1)
    contest = client.post(
        CONTESTS_URL,
        data={
            "title": "유료 공모전 — Award 회귀",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": deadline.isoformat(),
            "requirements": [{"text": "할 일을 추가·완료할 수 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    ).json()

    payment_resp = client.post(
        "/api/payments",
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    payment = payment_resp.json()

    import hashlib
    import hmac

    webhook_id = f"wh-{contest['id']}-{uuid4().hex}"
    canonical = f"{webhook_id}:{payment['order_id']}:paid".encode("utf-8")
    signature = hmac.new(
        settings.PAYMENT_WEBHOOK_SECRET.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    webhook_resp = client.post(
        "/api/payments/webhook",
        data={
            "webhook_id": webhook_id,
            "order_id": payment["order_id"],
            "status": "paid",
            "signature": signature,
        },
        content_type="application/json",
    )
    assert webhook_resp.status_code == 200

    dev = _hosted_user(client, "paid-award-regression-dev")
    verify_dev = client.post(
        "/api/verification/verify",
        data={
            "verification_token": "사람|1995-01-01|paid-award-regression-dev-ci|paid-award-regression-dev-ci-di"
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert verify_dev.status_code == 200

    submission = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={"assets": [_source_asset(contest["id"], dev["user_id"])], "requirement_responses": []},
        content_type="application/json",
        **_auth_header(dev["access"]),
    ).json()

    _close_contest(client, contest, deadline=deadline)

    award_resp = _award(client, sponsor, contest["id"], submission["id"])
    assert award_resp.status_code == 200, award_resp.content

    award = Award.objects.get(contest_id=contest["id"])
    assert Handover.objects.filter(award=award).exists()
