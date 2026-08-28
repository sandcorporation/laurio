"""Contest 수명주기 알림 연결 + Sponsor 알림 이력 조회 (#19, ADR-0009/0010).

#18(notifications 기반)의 dispatch·quiet-hours·fallback 로직은 여기서 다시
검증하지 않는다(test_notifications.py의 몫이다). 이 파일은 그 기반이 실제
Contest 라이프사이클 이벤트(마감 임박·심사기간 종료 임박·Distribution 최종
경고·Award/Distribution 결과)에 올바르게 연결됐는지, 그리고 Sponsor가 자신의
발송 이력을 HTTP로 조회할 수 있는지만 다룬다.

이 프로젝트의 유일한 테스트 시임은 HTTP다 — notifications.lifecycle의 함수를
테스트에서 직접 부르지 않는다.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from contests.models import Contest
from core.models import ClockOverride
from distributions.models import Distribution
from notifications.models import Notification, NotificationType

KST = ZoneInfo("Asia/Seoul")

TICK_URL = "/api/internal/tick"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
SCORING_RUN_PENDING_URL = "/api/internal/scoring/run-pending"
DISTRIBUTIONS_RUN_DUE_URL = "/api/internal/distributions/run-due"
LIFECYCLE_RUN_DUE_URL = "/api/internal/notifications/lifecycle/run-due"
MY_NOTIFICATIONS_URL = "/api/notifications/me"


# --- 헬퍼 (test_distributions.py와 같은 형식) -----------------------------------


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _safe_daytime_at_or_after(at):
    """`at` 이후(같은 시각 포함)이면서 로컬(KST) 낮(quiet hours 밖)인 가장 가까운
    14:00을 돌려준다.

    이 파일의 헬퍼들이 만드는 `deadline`/`judging_ends_at` 등은 실제 벽시계
    `timezone.now()`에서 파생되므로, 테스트를 실행하는 실제 시각에 따라 그
    시·분이 야간(21~08시)에 우연히 걸릴 수 있다(ADR-0010은 거래성 통지도 예외
    없이 야간이면 연기한다). Notification의 최종 상태(SENT/FAILED)를 검증하는
    테스트는 이 헬퍼로 명시적으로 낮 시각을 골라 그 우연성을 제거한다.
    """

    local = timezone.localtime(at, KST)
    candidate = local.replace(hour=14, minute=0, second=0, microsecond=0)
    if candidate < local:
        candidate += timedelta(days=1)
    return candidate


def _login(client, uid="dev-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _verify(client, access: str, *, ci: str, name: str = "사람", birth: str = "1995-01-01") -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"{name}|{birth}|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def _verified_user(client, uid: str, ci: str) -> dict:
    pair = _login(client, uid=uid)
    _verify(client, pair["access"], ci=ci)
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert me.status_code == 200
    return {"access": pair["access"], "user_id": me.json()["id"]}


def _sign(*, webhook_id: str, order_id: str, status: str) -> str:
    import hashlib
    import hmac

    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _publish_contest(
    client,
    *,
    category,
    deliverable_type,
    sponsor_uid="sponsor-1",
    sponsor_ci="sponsor-ci-1",
    deadline_at=None,
    requirements=None,
    prize=900_000,
) -> tuple[dict, dict]:
    sponsor = _verified_user(client, sponsor_uid, sponsor_ci)
    deadline_at = deadline_at or (timezone.now() + timedelta(hours=1))

    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{sponsor_uid}의 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "prize": prize,
            "deadline_at": deadline_at.isoformat(),
            "requirements": requirements or [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert response.status_code == 200, response.content
    contest = response.json()

    payment_resp = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert payment_resp.status_code == 201
    payment = payment_resp.json()

    webhook_id = f"wh-{contest['id']}-{uuid.uuid4().hex}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign(webhook_id=webhook_id, order_id=payment["order_id"], status="paid")
    webhook_resp = client.post(
        f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json"
    )
    assert webhook_resp.status_code == 200

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 200
    contest = detail.json()
    assert contest["status"] == "published"

    return sponsor, contest


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, dev: dict, contest_id: int, *, requirement_id: int, grounded: bool) -> dict:
    import io
    import zipfile

    from storage.adapters.fake import FakeStorageAdapter

    source_key = _source_object_key(contest_id, dev["user_id"])
    marker = f"MARKER_{uuid.uuid4().hex}"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("app.py", f"# {marker}\n" if grounded else "print('x')\n")
    FakeStorageAdapter().write_object(source_key, buf.getvalue())

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": (
                        [{"kind": "source_location", "value": marker}] if grounded else []
                    ),
                }
            ],
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


def _run_scoring(client) -> dict:
    response = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _end_judging_period(client, contest_id: int) -> None:
    judging_ends_at = Contest.objects.get(id=contest_id).judging_ends_at
    assert judging_ends_at is not None
    _freeze(judging_ends_at + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest_id).status == Contest.Status.JUDGING_ENDED


def _run_due_distributions(client, *, fail_submission_ids: list[int] | None = None) -> dict:
    response = client.post(
        DISTRIBUTIONS_RUN_DUE_URL,
        data={"fail_submission_ids": fail_submission_ids or []},
        content_type="application/json",
        **_internal_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()


def _run_lifecycle_scan(client) -> dict:
    response = client.post(LIFECYCLE_RUN_DUE_URL, **_internal_headers())
    assert response.status_code == 200, response.content
    return response.json()


def _my_notifications(client, access: str) -> list[dict]:
    response = client.get(MY_NOTIFICATIONS_URL, **_auth_header(access))
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def category(db):
    from contests.models import Category

    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    from contests.models import DeliverableType

    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


# --- 마감 임박: Sponsor + 참가 Developer -----------------------------------------


@pytest.mark.django_db
def test_deadline_reminder_notifies_sponsor_and_participating_developer(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=2)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    # 마감 리드타임(기본 24시간) 안으로 들어왔다 — 아직 마감 전이다. 낮 시각으로
    # 명시적으로 고정해 야간 연기 여부가 이 테스트의 결과를 좌우하지 않게 한다.
    _freeze(
        _safe_daytime_at_or_after(
            deadline - timedelta(hours=settings.DEADLINE_REMINDER_LEAD_HOURS)
        )
    )
    result = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "deadline_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in result["results"]
    )

    sponsor_notifications = _my_notifications(client, sponsor["access"])
    sponsor_deadline = [
        n for n in sponsor_notifications if n["notification_type"] == NotificationType.DEADLINE_REMINDER
    ]
    assert len(sponsor_deadline) == 1
    assert sponsor_deadline[0]["context"]["contest_id"] == contest["id"]
    assert sponsor_deadline[0]["context"]["role"] == "sponsor"
    assert sponsor_deadline[0]["status"] == Notification.Status.SENT
    assert [d["channel"] for d in sponsor_deadline[0]["dispatches"]] == ["alimtalk"]

    dev_notifications = _my_notifications(client, dev["access"])
    dev_deadline = [
        n for n in dev_notifications if n["notification_type"] == NotificationType.DEADLINE_REMINDER
    ]
    assert len(dev_deadline) == 1
    assert dev_deadline[0]["context"]["role"] == "developer"

    # 스캔을 두 번 돌려도 같은 Contest에 대해 중복 발송되지 않는다.
    result_again = _run_lifecycle_scan(client)
    assert not any(
        r.get("event") == "deadline_reminder_sent" for r in result_again["results"]
    )
    assert (
        len(
            [
                n
                for n in _my_notifications(client, sponsor["access"])
                if n["notification_type"] == NotificationType.DEADLINE_REMINDER
            ]
        )
        == 1
    )


@pytest.mark.django_db
def test_deadline_reminder_does_not_fire_before_lead_window(client, category, landing_type):
    deadline = timezone.now() + timedelta(days=5)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    _freeze(deadline - timedelta(days=4))  # 리드타임(24시간)보다 훨씬 이르다.
    result = _run_lifecycle_scan(client)
    assert not any(r.get("event") == "deadline_reminder_sent" for r in result["results"])
    assert _my_notifications(client, sponsor["access"]) == []


# --- 심사기간 종료 임박: Sponsor -------------------------------------------------


@pytest.mark.django_db
def test_judging_end_reminder_notifies_sponsor(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(
        judging_ends_at
        - timedelta(hours=settings.JUDGING_END_REMINDER_LEAD_HOURS)
        + timedelta(minutes=1)
    )
    result = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "judging_end_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in result["results"]
    )

    notifications = _my_notifications(client, sponsor["access"])
    matching = [
        n
        for n in notifications
        if n["notification_type"] == NotificationType.JUDGING_PERIOD_ENDING_REMINDER
    ]
    assert len(matching) == 1
    assert matching[0]["context"]["contest_id"] == contest["id"]


# --- Distribution 최종 경고: 금액 명시 + 낮 시각 구성 ------------------------------


@pytest.mark.django_db
def test_distribution_final_warning_states_amount_and_is_sent_at_constructed_daytime_hour(
    client, category, landing_type
):
    """judging_ends_at을 일부러 새벽 시각으로 만든다 — 최종 경고가 그 원시 시각을
    그대로 물려받지 않고, 항상 낮(NOTIFICATION_DAYTIME_HOUR)으로 구성됨을 증명한다.
    """

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=1_234_000,
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    distribution_due_at = judging_ends_at + timedelta(days=settings.DISTRIBUTION_WAIT_DAYS)

    # 구성된 경고 시각을 테스트가 독립적으로 계산한다: distribution_due_at으로부터
    # LEAD_DAYS 전, 로컬(KST) NOTIFICATION_DAYTIME_HOUR시로 고정.
    local_due = timezone.localtime(distribution_due_at, KST)
    warning_date = (local_due - timedelta(days=settings.DISTRIBUTION_FINAL_WARNING_LEAD_DAYS)).date()
    expected_warning_at = datetime(
        warning_date.year,
        warning_date.month,
        warning_date.day,
        settings.NOTIFICATION_DAYTIME_HOUR,
        0,
        0,
        tzinfo=KST,
    )
    # 구성된 시각은 정의상 항상 08:00~21:00 사이(낮)여야 한다.
    assert 8 <= expected_warning_at.hour < 21

    # 아직 그 시각 전이면 경고가 나가지 않는다.
    _freeze(expected_warning_at - timedelta(minutes=1))
    early = _run_lifecycle_scan(client)
    assert not any(r.get("event") == "distribution_final_warning_sent" for r in early["results"])

    # 구성된 낮 시각이 되면(비록 judging_ends_at 자체가 새벽이었어도) 즉시 발송된다 —
    # 08~21시 밖으로 미루는 야간 연기(ADR-0010)에 기대지 않는다.
    _freeze(expected_warning_at)
    on_time = _run_lifecycle_scan(client)
    matching = [
        r for r in on_time["results"] if r.get("event") == "distribution_final_warning_sent"
    ]
    assert len(matching) == 1
    assert matching[0]["contest_id"] == contest["id"]
    assert matching[0]["amount"] == 1_234_000

    notifications = _my_notifications(client, sponsor["access"])
    warnings = [
        n
        for n in notifications
        if n["notification_type"] == NotificationType.DISTRIBUTION_FINAL_WARNING
    ]
    assert len(warnings) == 1
    warning = warnings[0]
    # 금액이 명시된다(#19 AC).
    assert warning["context"]["amount"] == 1_234_000
    # 낮 시각에 즉시 발송됐다 — 야간 연기(DEFERRED)를 거치지 않았다.
    assert warning["status"] == Notification.Status.SENT
    assert [d["channel"] for d in warning["dispatches"]] == ["alimtalk"]

    # Distribution이 아직 실행되지 않은 시점이라 경고일 뿐이다.
    assert not Distribution.objects.filter(contest_id=contest["id"]).exists()


@pytest.mark.django_db
def test_distribution_final_warning_is_not_sent_once_distribution_already_happened(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(judging_ends_at + timedelta(days=settings.DISTRIBUTION_WAIT_DAYS, minutes=1))
    _run_due_distributions(client)
    assert Distribution.objects.filter(contest_id=contest["id"]).exists()

    result = _run_lifecycle_scan(client)
    assert not any(
        r.get("event") == "distribution_final_warning_sent" for r in result["results"]
    )


# --- 결과 알림: Award / Distribution ----------------------------------------------


AWARDS_URL = "/api/contests"


@pytest.mark.django_db
def test_award_sends_result_notice_to_winning_developer(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    # 낮 시각으로 명시적으로 고정한다 — Award 결과 알림의 최종 상태(SENT)를
    # 검증하므로 야간 연기 여부가 우연에 좌우되면 안 된다.
    _freeze(_safe_daytime_at_or_after(deadline + timedelta(minutes=1)))

    award_resp = client.post(
        f"{AWARDS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert award_resp.status_code == 200, award_resp.content

    dev_notifications = _my_notifications(client, dev["access"])
    result_notices = [
        n for n in dev_notifications if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]
    assert len(result_notices) == 1
    assert result_notices[0]["context"]["contest_id"] == contest["id"]
    assert result_notices[0]["context"]["outcome"] == "awarded"
    assert result_notices[0]["status"] == Notification.Status.SENT


@pytest.mark.django_db
def test_distribution_sends_result_notice_with_amount_to_qualifying_developer(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=900_000,
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    # 낮 시각으로 명시적으로 고정한다 — 배분 결과 알림의 최종 상태(SENT)를
    # 검증하므로 야간 연기 여부가 우연에 좌우되면 안 된다.
    _freeze(
        _safe_daytime_at_or_after(
            judging_ends_at + timedelta(days=settings.DISTRIBUTION_WAIT_DAYS, minutes=1)
        )
    )
    _run_due_distributions(client)

    dev_notifications = _my_notifications(client, dev["access"])
    result_notices = [
        n for n in dev_notifications if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]
    assert len(result_notices) == 1
    assert result_notices[0]["context"]["outcome"] == "distributed"
    assert result_notices[0]["context"]["amount"] == 900_000
    assert result_notices[0]["status"] == Notification.Status.SENT


# --- 핵심: 전 채널 미도달이어도 Distribution은 예정대로 실행된다(ADR-0009) -----------


@pytest.mark.django_db
def test_distribution_still_executes_when_every_notification_channel_fails(
    client, category, landing_type
):
    """Distribution 최종 경고도, 배분 결과 알림도 전 채널(알림톡/SMS/LMS)이 전부
    실패해도 Distribution 자체(Distribution/DistributionShare/Payout 생성과
    원장 분개)는 예정대로 정확히 실행된다. 이것이 ADR-0009의 핵심 약속이고, 이
    티켓(#19)이 가장 먼저 증명해야 하는 테스트다.
    """

    from ledger.services import contest_balance
    from payouts.models import Payout

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=900_000,
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    distribution_due_at = judging_ends_at + timedelta(days=settings.DISTRIBUTION_WAIT_DAYS)
    local_due = timezone.localtime(distribution_due_at, KST)
    warning_date = (local_due - timedelta(days=settings.DISTRIBUTION_FINAL_WARNING_LEAD_DAYS)).date()
    expected_warning_at = datetime(
        warning_date.year,
        warning_date.month,
        warning_date.day,
        settings.NOTIFICATION_DAYTIME_HOUR,
        0,
        0,
        tzinfo=KST,
    )

    with override_settings(NOTIFICATION_FAKE_FAILING_CHANNELS=["alimtalk", "sms", "lms"]):
        _freeze(expected_warning_at)
        warning_scan = _run_lifecycle_scan(client)
        assert any(
            r.get("event") == "distribution_final_warning_sent" for r in warning_scan["results"]
        )

        # 낮 시각으로 명시적으로 고정한다 — 아래에서 배분 결과 알림이 FAILED로
        # 끝났는지(야간이라 DEFERRED로 남은 게 아니라 실제로 시도했다가 전부
        # 실패했는지)를 검증하므로, 우연히 야간에 걸리면 안 된다.
        _freeze(_safe_daytime_at_or_after(distribution_due_at + timedelta(minutes=1)))
        dist_result = _run_due_distributions(client)

    # Distribution 자체는 예정대로 실행됐다.
    assert any(r.get("event") == "distribution_created" for r in dist_result["results"])
    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.share_amount == 900_000
    payout = Payout.objects.get(distribution_share__submission_id=submission["id"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
    assert payout.journal_entry_id is not None

    contest_obj = Contest.objects.get(id=contest["id"])
    assert contest_balance(contest_obj.ledger_id)["is_balanced"] is True

    # Sponsor의 발송 이력에는 "시도했지만 전부 실패했다"는 증거가 그대로 남는다 —
    # 이것이 ADR-0009가 요구하는, "연락받은 적 없다"는 항의에 대한 방어선이다.
    sponsor_notifications = _my_notifications(client, sponsor["access"])
    final_warning = next(
        n
        for n in sponsor_notifications
        if n["notification_type"] == NotificationType.DISTRIBUTION_FINAL_WARNING
    )
    assert final_warning["status"] == Notification.Status.FAILED
    assert [d["channel"] for d in final_warning["dispatches"]] == ["alimtalk", "sms", "lms"]
    assert all(d["status"] == "failed" for d in final_warning["dispatches"])
    assert all(d["failure_reason"] for d in final_warning["dispatches"])

    # 배분 결과 알림도 마찬가지로 실패로 기록되지만, Developer가 실제로 받은
    # DistributionShare/Payout에는 아무 영향이 없다.
    dev_notifications = _my_notifications(client, dev["access"])
    result_notice = next(
        n for n in dev_notifications if n["notification_type"] == NotificationType.RESULT_NOTICE
    )
    assert result_notice["status"] == Notification.Status.FAILED


# --- Sponsor 알림 이력 조회: 인증·소유권 -------------------------------------------


@pytest.mark.django_db
def test_notification_history_requires_authentication(client):
    response = client.get(MY_NOTIFICATIONS_URL)
    assert response.status_code == 401


@pytest.mark.django_db
def test_notification_history_only_shows_own_notifications(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=2)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    other = _verified_user(client, "someone-else", "someone-else-ci")

    _freeze(
        deadline
        - timedelta(hours=settings.DEADLINE_REMINDER_LEAD_HOURS)
        + timedelta(minutes=1)
    )
    _run_lifecycle_scan(client)

    assert len(_my_notifications(client, sponsor["access"])) >= 1
    assert _my_notifications(client, other["access"]) == []


# --- NotificationType 등록 무결성(apps.py의 부팅 시점 검사) -----------------------


@pytest.mark.django_db
def test_new_judging_period_ending_reminder_type_is_registered_with_flags(client):
    response = client.get(
        "/api/internal/notifications/types/", **_internal_headers()
    )
    assert response.status_code == 200
    by_value = {row["value"]: row for row in response.json()}
    assert by_value[NotificationType.JUDGING_PERIOD_ENDING_REMINDER]["is_transactional"] is True
    assert by_value[NotificationType.JUDGING_PERIOD_ENDING_REMINDER]["is_promotional"] is False
