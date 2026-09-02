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
from policies.services import get_current_policy

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


def _extend(client, sponsor: dict, contest_id: int) -> dict:
    """유료 심사기간 연장 결제를 initiate+confirm으로 한 번에 끝낸다
    (test_judging_period_and_award.py의 같은 이름 헬퍼와 같은 형식)."""

    initiated = client.post(
        f"{CONTESTS_URL}/{contest_id}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert initiated.status_code == 201, initiated.content
    order_id = initiated.json()["order_id"]

    confirmed = client.post(
        f"{CONTESTS_URL}/{contest_id}/extend-judging-period/{order_id}/confirm",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert confirmed.status_code == 200, confirmed.content
    return confirmed.json()


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
            deadline - timedelta(hours=get_current_policy().deadline_reminder_lead_hours)
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


@pytest.mark.django_db
def test_deadline_reminder_lead_time_follows_policy_change_not_a_hardcoded_default(
    client, category, landing_type
):
    """운영자가 마감 임박 리드타임을 바꾸면 그 뒤의 알림 발송 시각이 실제로
    달라진다(#78 AC) — "정책 행에 값이 저장됐다"로 멈추지 않고 효과를 확인한다.

    기본 리드타임(24시간)이라면 마감 60시간 전은 창 밖이다(위
    test_deadline_reminder_does_not_fire_before_lead_window가 그보다도 훨씬
    이른 4일 전으로 그 경계를 이미 증명한다). 리드타임을 72시간으로 늘리면
    같은 "마감 60시간 전"이 창 안으로 들어와 알림이 나가야 한다 — 소비처
    (`notifications.lifecycle.send_due_deadline_reminders`)가 여전히 24시간을
    하드코딩하고 있다면 이 테스트가 실제로 빨개진다.
    """

    from policies.models import PlatformPolicy

    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"deadline_reminder_lead_hours": 72}
    )

    deadline = timezone.now() + timedelta(days=5)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    # `_safe_daytime_at_or_after`가 최대 24시간까지 앞으로 밀 수 있으므로,
    # 목표 시각(마감 60시간 전)에 넉넉한 여유를 둔다 — 최악의 경우(24시간
    # 밀림)에도 마감 36시간 전이라 기본 24시간 창보다는 이르고(창 밖), 새
    # 72시간 창보다는 늦다(창 안).
    _freeze(_safe_daytime_at_or_after(deadline - timedelta(hours=60)))
    result = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "deadline_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in result["results"]
    )
    assert _my_notifications(client, sponsor["access"]) != []


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
        - timedelta(hours=get_current_policy().judging_end_reminder_lead_hours)
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
    distribution_due_at = judging_ends_at + timedelta(days=get_current_policy().distribution_wait_days)

    # 구성된 경고 시각을 테스트가 독립적으로 계산한다: distribution_due_at으로부터
    # LEAD_DAYS 전, 로컬(KST) NOTIFICATION_DAYTIME_HOUR시로 고정.
    local_due = timezone.localtime(distribution_due_at, KST)
    warning_date = (local_due - timedelta(days=get_current_policy().distribution_final_warning_lead_days)).date()
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
    _freeze(judging_ends_at + timedelta(days=get_current_policy().distribution_wait_days, minutes=1))
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
            judging_ends_at + timedelta(days=get_current_policy().distribution_wait_days, minutes=1)
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
    distribution_due_at = judging_ends_at + timedelta(days=get_current_policy().distribution_wait_days)
    local_due = timezone.localtime(distribution_due_at, KST)
    warning_date = (local_due - timedelta(days=get_current_policy().distribution_final_warning_lead_days)).date()
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
        - timedelta(hours=get_current_policy().deadline_reminder_lead_hours)
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


# --- 리뷰 지적 회귀 방지 (#19) ------------------------------------------------


@pytest.mark.django_db
def test_extension_clears_judging_end_reminder_flag_so_a_second_warning_can_fire(
    client, category, landing_type
):
    """Sponsor가 심사기간 종료 임박 경고를 보고 유료 연장하면, 연장된 새
    종료일이 다가올 때 다시 경고를 받아야 한다(#19 리뷰 지적 1). 이 순서(경고를
    보고 연장한다)가 REQUEST.md가 이 티켓의 존재 이유로 든 "발주자가 깜빡한다"
    를 실제로 막는 정상 경로다 — 두 번째 경고가 없으면 그 정상 경로에서조차
    Sponsor는 두 번째 종료일 앞에서 아무 경고 없이 바로 무응답 Distribution을
    맞는다.
    """

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    first_judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    # 첫 번째 경고 — 낮 시각으로 명시적으로 고정한다.
    _freeze(
        _safe_daytime_at_or_after(
            first_judging_ends_at
            - timedelta(hours=get_current_policy().judging_end_reminder_lead_hours)
        )
    )
    first_scan = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "judging_end_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in first_scan["results"]
    )
    assert Contest.objects.get(id=contest["id"]).judging_end_reminder_sent_at is not None
    first_notices = [
        n
        for n in _my_notifications(client, sponsor["access"])
        if n["notification_type"] == NotificationType.JUDGING_PERIOD_ENDING_REMINDER
    ]
    assert len(first_notices) == 1

    # Sponsor가 그 경고를 보고 유료 연장한다.
    extended = _extend(client, sponsor, contest["id"])
    assert extended["judging_extension_count"] == 1

    # 연장 직후 플래그가 비워졌다 — 재스캔해도 아직 새 종료일이 멀었으므로
    # 곧바로 다시 발송되지는 않는다(리드타임 밖).
    contest_after_extension = Contest.objects.get(id=contest["id"])
    assert contest_after_extension.judging_end_reminder_sent_at is None
    new_judging_ends_at = contest_after_extension.judging_ends_at
    assert new_judging_ends_at > first_judging_ends_at

    rescan_too_early = _run_lifecycle_scan(client)
    assert not any(
        r.get("event") == "judging_end_reminder_sent" for r in rescan_too_early["results"]
    )

    # 연장된 새 종료일이 다가오면 두 번째 경고가 실제로 나간다.
    _freeze(
        _safe_daytime_at_or_after(
            new_judging_ends_at - timedelta(hours=get_current_policy().judging_end_reminder_lead_hours)
        )
    )
    second_scan = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "judging_end_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in second_scan["results"]
    )

    second_notices = [
        n
        for n in _my_notifications(client, sponsor["access"])
        if n["notification_type"] == NotificationType.JUDGING_PERIOD_ENDING_REMINDER
    ]
    assert len(second_notices) == 2
    assert second_notices[0]["context"]["judging_ends_at"] == new_judging_ends_at.isoformat()


@pytest.mark.django_db
def test_deadline_reminder_scan_yields_to_time_budget_mid_fanout_and_recovers_next_scan(
    client, category, landing_type
):
    """#51 2차 코드리뷰 지적 2: run_due_lifecycle_notifications는 이제 그 안에서
    notifications.services.create_notification을 통해 실물 벤더에 동기 HTTP를
    낸다 — Contest 200개 × 참가자 전원을 한 요청 안에서 처리하면 gunicorn/
    Celery의 30초 타임아웃을 넘긴다. 실제 크래시(위 테스트)가 아니라 정상적인
    시간 예산 초과로도 똑같이 "이미 받은 사람은 다시 받지 않고, 완료 표시는
    남기지 않아 다음 스캔이 안전하게 마저 보낸다"가 성립해야 한다."""

    from unittest.mock import patch

    import notifications.lifecycle as lifecycle_module

    deadline = timezone.now() + timedelta(hours=2)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    devs = [_verified_user(client, f"budget-dev-{i}", f"budget-dev-{i}-ci") for i in range(3)]
    for dev in devs:
        _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _freeze(
        _safe_daytime_at_or_after(
            deadline - timedelta(hours=get_current_policy().deadline_reminder_lead_hours)
        )
    )

    # 호출 순서: ① send_due_deadline_reminders 몫의 deadline 계산,
    # ② 그 스캔의 바깥 루프(이 Contest 진입 전) 확인, ③ 첫 번째 참가자
    # 팬아웃 전 확인, ④ 두 번째 참가자 팬아웃 전 확인(여기서 예산 초과로
    # 멈춘다). 다섯 스캔이 각자 자기 차례에 deadline을 새로 계산하므로(#51
    # 3차 코드리뷰 지적 4), 이어지는 네 스캔도 각자 한 번씩 자기 몫의
    # deadline을 계산한다(⑤~⑧) — 이 시나리오에서는 그 네 스캔 모두 대상
    # Contest/행이 없어 그 이상은 monotonic()을 부르지 않는다.
    with patch.object(
        lifecycle_module.time_module,
        "monotonic",
        side_effect=[0.0, 0.0, 0.0, 100.0, 100.0, 100.0, 100.0, 100.0],
    ):
        budget_exceeded_scan = _run_lifecycle_scan(client)

    # 예산 초과로 멈췄으므로 이 Contest는 "완료"로 보고되지 않는다.
    assert not any(
        r.get("event") == "deadline_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in budget_exceeded_scan["results"]
    )
    assert Contest.objects.get(id=contest["id"]).deadline_reminder_sent_at is None

    notified_count = sum(
        1
        for dev in devs
        if any(
            n["notification_type"] == NotificationType.DEADLINE_REMINDER
            for n in _my_notifications(client, dev["access"])
        )
    )
    assert notified_count == 1

    # 다음 스캔(시간 제약 없이)이 나머지 수신자만 안전하게 마저 보낸다.
    recovery_scan = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "deadline_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in recovery_scan["results"]
    )
    assert Contest.objects.get(id=contest["id"]).deadline_reminder_sent_at is not None

    for dev in devs:
        matching = [
            n
            for n in _my_notifications(client, dev["access"])
            if n["notification_type"] == NotificationType.DEADLINE_REMINDER
        ]
        # 이미 받은 1명은 중복으로 다시 받지 않고, 나머지 2명은 정확히 한 번 받는다.
        assert len(matching) == 1


@pytest.mark.django_db
def test_award_result_notice_recovery_is_not_starved_when_an_earlier_scan_exhausts_its_own_share(
    client, category, landing_type
):
    """#51 3차 코드리뷰 지적 4: 다섯 스캔이 마감시각 하나를 고정 순서로
    공유하던 버전에서는, 첫 스캔(마감 임박 팬아웃)이 예산을 다 쓸 때마다
    마지막 두 복구 스캔(Award/Distribution 결과 알림 복구)이 매번 첫
    iteration에서 멈췄다 — 즉시 경로가 죽은 Award 결과 알림이 영원히
    복구되지 않는다는 뜻이다. 이 테스트는 그 시나리오를 그대로 재현한다 —
    마감 임박 스캔은(mock으로) 자기 몫을 다 쓰게 만들고, 동시에 Award 하나가
    복구를 기다리고 있다. 다섯 스캔이 각자 새로 몫을 받으므로, 첫 스캔이
    중단돼도 Award 복구 스캔은 정상적으로 실행돼야 한다."""

    from unittest.mock import patch

    import notifications.lifecycle as lifecycle_module
    from awards.models import Award

    # 두 Contest를 만들고 제출까지 전부 "지금"(고정 시각 없음) 끝내 둔다 —
    # 아래에서 Award 시나리오를 완성하려고 시계를 앞으로 넘기면, 그 뒤에
    # 만드는 Contest의 deadline_at 계산이 이미 지나간 시각이 될 수 있다.
    award_deadline = timezone.now() + timedelta(hours=1)
    award_sponsor, award_contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=award_deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    award_requirement_id = award_contest["requirements"][0]["id"]
    award_dev = _verified_user(client, "budget-award-dev", "budget-award-dev-ci")
    award_submission = _submit(
        client, award_dev, award_contest["id"], requirement_id=award_requirement_id, grounded=True
    )

    reminder_deadline = timezone.now() + timedelta(hours=2)
    _reminder_sponsor, reminder_contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=reminder_deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    reminder_requirement_id = reminder_contest["requirements"][0]["id"]
    reminder_devs = [
        _verified_user(client, f"budget-reminder-dev-{i}", f"budget-reminder-dev-{i}-ci")
        for i in range(2)
    ]
    for dev in reminder_devs:
        _submit(
            client, dev, reminder_contest["id"], requirement_id=reminder_requirement_id, grounded=True
        )

    # --- Award 하나를 "즉시 알림이 죽어서 복구를 기다리는" 상태로 만든다 ---
    _close_contest(client, award_contest, deadline=award_deadline)
    _run_scoring(client)
    _freeze(_safe_daytime_at_or_after(award_deadline + timedelta(minutes=1)))
    with patch.object(
        lifecycle_module,
        "_safe_notify",
        side_effect=RuntimeError("simulated crash before completion"),
    ):
        award_resp = client.post(
            f"{AWARDS_URL}/{award_contest['id']}/award",
            data={"submission_id": award_submission["id"]},
            content_type="application/json",
            **_auth_header(award_sponsor["access"]),
        )
    assert award_resp.status_code == 200, award_resp.content
    award = Award.objects.get(contest_id=award_contest["id"])
    assert award.result_notice_sent_at is None

    # 마감 임박 알림이 밀려 있는 시각으로 다시 맞춘다 — reminder_contest는
    # 이미 제출까지 끝나 있으므로 이 시계 이동에 영향받지 않는다.
    _freeze(
        _safe_daytime_at_or_after(
            reminder_deadline
            - timedelta(hours=get_current_policy().deadline_reminder_lead_hours)
        )
    )

    # monotonic()을 처음 네 번(마감 임박 스캔의 deadline 계산 + 바깥 루프 진입 +
    # 참가자 둘의 팬아웃 확인)만 정밀 제어해 그 스캔이 자기 몫을 다 쓰고
    # 중단되게 만든다. 그 이후(다른 네 스캔이 각자 새로 받는 deadline과 그
    # 이후 점검들)는 실제로 몇 번 호출되는지 미리 셀 필요가 없도록, 아주
    # 작은 간격(0.001초)만 계속 흘려보낸다 — 각 스캔이 자기 몫으로 새로
    # 받는 2.4초짜리 창을 그 정도로는 절대 넘기지 못한다.
    call_count = {"n": 0}
    fanout_exhausted_at = 100.0

    def _monotonic_side_effect():
        call_count["n"] += 1
        n = call_count["n"]
        if n <= 3:
            return 0.0
        if n == 4:
            return fanout_exhausted_at
        return fanout_exhausted_at + (n - 4) * 0.001

    with patch.object(
        lifecycle_module.time_module, "monotonic", side_effect=_monotonic_side_effect
    ):
        combined_scan = _run_lifecycle_scan(client)

    # 마감 임박 스캔은 예산을 넘겨 중단됐다 — 이 Contest는 "완료"로 보고되지
    # 않는다(이 테스트가 실제로 그 경로를 탔다는 확인).
    assert not any(
        r.get("event") == "deadline_reminder_sent" and r.get("contest_id") == reminder_contest["id"]
        for r in combined_scan["results"]
    )
    assert Contest.objects.get(id=reminder_contest["id"]).deadline_reminder_sent_at is None

    # 그런데도 Award 결과 알림 복구는 굶지 않고 실제로 실행됐다 — 다섯
    # 스캔이 더는 마감시각 하나를 고정 순서로 공유하지 않기 때문이다.
    assert any(
        r.get("event") == "award_result_notice_recovered" and r.get("award_id") == award.id
        for r in combined_scan["results"]
    )
    award.refresh_from_db()
    assert award.result_notice_sent_at is not None
    result_notices = [
        n
        for n in _my_notifications(client, award_dev["access"])
        if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]
    assert len(result_notices) == 1


@pytest.mark.django_db
def test_deadline_reminder_recovers_remaining_developers_after_mid_fanout_crash(
    client, category, landing_type
):
    """참가자가 많은 Contest에서 마감 임박 알림 팬아웃 도중(타임아웃, 재배포로)
    죽으면, 이미 받은 사람은 다시 받지 않고 못 받은 사람만 다음 스캔이 안전하게
    마저 보낸다(#19 리뷰 지적 2). 여기서는 3명 중 1명만 알리고 죽는 상황을
    `_participating_developer_users`가 예외를 던지도록 흉내낸다 — 이 예외는
    notifications.lifecycle의 개별 알림 헬퍼(_safe_notify*)가 아니라 팬아웃
    루프 자체에서 나므로, 삼켜지지 않고 이 Contest의 "완료 표시"를 막는다.
    """

    from unittest.mock import patch

    import notifications.lifecycle as lifecycle_module

    deadline = timezone.now() + timedelta(hours=2)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    devs = [_verified_user(client, f"dev-{i}", f"dev-{i}-ci") for i in range(3)]
    for dev in devs:
        _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _freeze(
        _safe_daytime_at_or_after(
            deadline - timedelta(hours=get_current_policy().deadline_reminder_lead_hours)
        )
    )

    real_participating = lifecycle_module._participating_developer_users

    def _crash_after_first_developer(contest_arg):
        users = list(real_participating(contest_arg))

        def _gen():
            yield users[0]
            raise RuntimeError("simulated mid-fanout crash (timeout/redeploy)")

        return _gen()

    with patch.object(
        lifecycle_module,
        "_participating_developer_users",
        side_effect=_crash_after_first_developer,
    ):
        crashed_scan = _run_lifecycle_scan(client)

    # 죽었으므로 이 Contest는 "완료"로 보고되지 않는다.
    assert not any(
        r.get("event") == "deadline_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in crashed_scan["results"]
    )
    assert Contest.objects.get(id=contest["id"]).deadline_reminder_sent_at is None

    notified_count = sum(
        1
        for dev in devs
        if any(
            n["notification_type"] == NotificationType.DEADLINE_REMINDER
            for n in _my_notifications(client, dev["access"])
        )
    )
    assert notified_count == 1

    # 다음 스캔(패치 없이)이 나머지 수신자만 안전하게 마저 보낸다.
    recovery_scan = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "deadline_reminder_sent" and r.get("contest_id") == contest["id"]
        for r in recovery_scan["results"]
    )
    assert Contest.objects.get(id=contest["id"]).deadline_reminder_sent_at is not None

    for dev in devs:
        matching = [
            n
            for n in _my_notifications(client, dev["access"])
            if n["notification_type"] == NotificationType.DEADLINE_REMINDER
        ]
        # 이미 받은 1명은 중복으로 다시 받지 않고, 나머지 2명은 정확히 한 번 받는다.
        assert len(matching) == 1


@pytest.mark.django_db
def test_award_result_notice_is_recovered_after_crash_before_completion(
    client, category, landing_type
):
    """Award 커밋 직후 알림 시도가 프로세스 강제종료 등으로 끝까지 완료되지
    못하면(`Award.result_notice_sent_at`이 비어 있으면), 복구 스캔이 다시 찾아
    마저 보낸다(#19 리뷰 지적 3) — "발송하고 잊어버리는" 방식이 아니라 언젠가
    누군가 실제로 재시도한다는 보장이 있어야 ADR-0009의 발송 이력이 아예
    비어버리는 사고를 막는다.
    """

    from unittest.mock import patch

    import notifications.lifecycle as lifecycle_module
    from awards.models import Award

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
    _freeze(_safe_daytime_at_or_after(deadline + timedelta(minutes=1)))

    with patch.object(
        lifecycle_module,
        "_safe_notify",
        side_effect=RuntimeError("simulated crash before completion"),
    ):
        award_resp = client.post(
            f"{AWARDS_URL}/{contest['id']}/award",
            data={"submission_id": submission["id"]},
            content_type="application/json",
            **_auth_header(sponsor["access"]),
        )
    # Award 자체는 알림 실패로 절대 막히지 않는다(#19 AC).
    assert award_resp.status_code == 200, award_resp.content

    award = Award.objects.get(contest_id=contest["id"])
    assert award.result_notice_sent_at is None
    # **결과 알림이** 아직 없다는 것이 이 테스트의 주장이다 — "알림이 하나도
    # 없다" 가 아니다. 채점 완료 알림(#74)이 생긴 뒤로 후자는 거짓이 됐고, 그건
    # 이 테스트가 원래 물으려던 것과 무관하다.
    assert not [
        n
        for n in _my_notifications(client, dev["access"])
        if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]

    recovery = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "award_result_notice_recovered" and r.get("award_id") == award.id
        for r in recovery["results"]
    )

    award.refresh_from_db()
    assert award.result_notice_sent_at is not None
    result_notices = [
        n for n in _my_notifications(client, dev["access"]) if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]
    assert len(result_notices) == 1

    # 복구 스캔을 한 번 더 돌려도 중복 발송되지 않는다.
    rescan = _run_lifecycle_scan(client)
    assert not any(r.get("event") == "award_result_notice_recovered" for r in rescan["results"])
    result_notices_again = [
        n for n in _my_notifications(client, dev["access"]) if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]
    assert len(result_notices_again) == 1


@pytest.mark.django_db
def test_distribution_result_notice_is_recovered_after_crash_before_completion(
    client, category, landing_type
):
    """Distribution 생성 직후 결과 알림 시도가 프로세스 강제종료 등으로 끝까지
    완료되지 못하면(`DistributionShare.result_notice_sent_at`이 비어 있으면),
    복구 스캔이 다시 찾아 마저 보낸다(#19 리뷰 지적 3). Distribution 자체
    (Payout·원장 반영)는 알림 시도의 성패와 무관하게 이미 완전히 끝나 있다."""

    from unittest.mock import patch

    import notifications.lifecycle as lifecycle_module
    from distributions.models import DistributionShare

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
    _freeze(
        _safe_daytime_at_or_after(
            judging_ends_at + timedelta(days=get_current_policy().distribution_wait_days, minutes=1)
        )
    )

    with patch.object(
        lifecycle_module,
        "_safe_notify",
        side_effect=RuntimeError("simulated crash before completion"),
    ):
        dist_result = _run_due_distributions(client)

    # Distribution 자체는 알림 시도의 성패와 무관하게 예정대로 완전히 실행됐다.
    assert any(r.get("event") == "distribution_created" for r in dist_result["results"])
    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.share_amount == 900_000

    share = DistributionShare.objects.get(submission_id=submission["id"])
    assert share.result_notice_sent_at is None
    # **결과 알림이** 아직 없다는 것이 이 테스트의 주장이다 — "알림이 하나도
    # 없다" 가 아니다. 채점 완료 알림(#74)이 생긴 뒤로 후자는 거짓이 됐고, 그건
    # 이 테스트가 원래 물으려던 것과 무관하다.
    assert not [
        n
        for n in _my_notifications(client, dev["access"])
        if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]

    recovery = _run_lifecycle_scan(client)
    assert any(
        r.get("event") == "distribution_result_notice_recovered"
        and r.get("submission_id") == submission["id"]
        for r in recovery["results"]
    )

    share.refresh_from_db()
    assert share.result_notice_sent_at is not None
    result_notices = [
        n for n in _my_notifications(client, dev["access"]) if n["notification_type"] == NotificationType.RESULT_NOTICE
    ]
    assert len(result_notices) == 1


@pytest.mark.django_db
def test_distribution_final_warning_query_does_not_get_crowded_out_by_not_yet_due_contests(
    client, category, landing_type
):
    """시각 조건이 쿼리 밖(파이썬)에만 있으면, 아직 한참 멀었지만 개수가 많은
    후보(낮은 id, 먼저 처리됨)가 작은 배치를 다 채워 실제로 마감된 경고(높은
    id)를 이번 스캔에서 밀어낼 수 있다(#19 리뷰 지적 4) — 특히 유료 연장으로
    id 순서와 judging_ends_at 순서가 어긋나기 시작하면 실제로 벌어진다. 여기서는
    BATCH_SIZE를 2로 줄이고, 먼저 만든 '아직 멀었다' Contest 2개 뒤에 나중에
    만든 '이미 도래했다' Contest 1개를 두어 재현한다.
    """

    from unittest.mock import patch

    import notifications.lifecycle as lifecycle_module

    anchor = datetime(2026, 2, 1, 10, 0, tzinfo=KST)

    # "아직 멀었다" — judging_ends_at이 anchor 한 시간 전이라, 경고까지는
    # (WAIT_DAYS - LEAD_DAYS)일 가까이 남았다.
    recent_judging_ends_at = anchor - timedelta(hours=1)
    recent_deadline = recent_judging_ends_at - timedelta(days=get_current_policy().judging_period_days)

    # "이미 도래했다" — 경고 시각이 정확히 anchor가 되도록 역산한다(3시간 여유를
    # 둬 로컬 날짜 경계를 확실히 넘긴다).
    due_judging_ends_at = anchor - timedelta(
        days=get_current_policy().distribution_wait_days - get_current_policy().distribution_final_warning_lead_days,
        hours=3,
    )
    due_deadline = due_judging_ends_at - timedelta(days=get_current_policy().judging_period_days)

    contests = []
    for i, deadline_at in enumerate([recent_deadline, recent_deadline, due_deadline]):
        _, contest = _publish_contest(
            client,
            category=category,
            deliverable_type=landing_type,
            deadline_at=deadline_at,
            sponsor_uid=f"sponsor-crowd-{i}",
        )
        contests.append(contest)
        _close_contest(client, contest, deadline=deadline_at)
        contest_judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
        _freeze(contest_judging_ends_at + timedelta(minutes=1))
        tick_resp = client.post(TICK_URL, **_internal_headers())
        assert tick_resp.status_code == 200
        assert Contest.objects.get(id=contest["id"]).status == Contest.Status.JUDGING_ENDED

    due_contest = contests[2]
    assert due_contest["id"] > contests[0]["id"]
    assert due_contest["id"] > contests[1]["id"]

    _freeze(anchor)
    with patch.object(lifecycle_module, "BATCH_SIZE", 2):
        result = _run_lifecycle_scan(client)

    assert any(
        r.get("event") == "distribution_final_warning_sent"
        and r.get("contest_id") == due_contest["id"]
        for r in result["results"]
    )
