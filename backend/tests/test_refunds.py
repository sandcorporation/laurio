"""참여자 0명 전액 환불 (#17, ADR-0004, ADR-0003, ADR-0007).

마감(#11) 시점에 `Submission`이 0건이면 `Prize`와 개최 등록비가 전액 환불되고
원장이 0으로 닫힌다 — 이것이 환불이 허용되는 유일한 경로다(Escrow: "참가자가 한
명이라도 있으면 Sponsor에게 되돌아가지 않는다"). 실패 경로가 대부분의 결함을
품는다는 지적(리뷰 69건 중 대다수)에 따라 실패 경로를 먼저, 더 두껍게 쓴다:
PG 타임아웃, 웹훅 재전송, 동시 스캔, Submission이 있어 환불이 절대 일어나면 안
되는 경로를 모두 증명한다.
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from payments.models import Payment

TICK_URL = "/api/internal/tick"
RUN_REFUNDS_URL = "/api/internal/payments/run-refunds"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
LEDGER_URL = "/api/ledger"


# --- 로그인 · 본인확인 · 내부 인증 헬퍼 ----------------------------------------


def _login(client, uid="user-1", email=None):
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


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _make_operator(**kwargs):
    defaults = {
        "username": "refunds-operator",
        "email": "refunds-operator@example.com",
        "password": "operator-pw-1234",
        "is_staff": True,
    }
    defaults.update(kwargs)
    return get_user_model().objects.create_user(**defaults)


def _login_operator(client, **kwargs):
    user = _make_operator(**kwargs)
    assert client.login(username=user.username, password="operator-pw-1234")
    return user


def _run_refunds(client, *, simulate: str | None = None):
    return client.post(
        RUN_REFUNDS_URL,
        data={"simulate": simulate} if simulate is not None else {},
        content_type="application/json",
        **_internal_headers(),
    )


def _sign(*, webhook_id: str, order_id: str, status: str, secret: str | None = None) -> str:
    key = secret if secret is not None else settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _send_webhook(client, *, webhook_id: str, order_id: str, status: str, signature="__default__"):
    body = {"webhook_id": webhook_id, "order_id": order_id, "status": status}
    if signature == "__default__":
        body["signature"] = _sign(webhook_id=webhook_id, order_id=order_id, status=status)
    elif signature is not None:
        body["signature"] = signature
    return client.post(f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json")


# --- Contest 개최 · 결제 · 마감 헬퍼 -------------------------------------------


def _publish_contest(
    client,
    *,
    category,
    deliverable_type,
    sponsor_uid="sponsor-1",
    sponsor_ci="sponsor-ci-1",
    deadline_at=None,
    prize=1_000_000,
) -> tuple[dict, dict]:
    """검증된 Sponsor로 Contest를 만들고 결제까지 완료해 published 상태로 돌려준다."""

    sponsor = _verified_user(client, sponsor_uid, sponsor_ci)
    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))

    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{sponsor_uid}의 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "prize": prize,
            "deadline_at": deadline_at.isoformat(),
            "requirements": [],
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
    webhook_resp = _send_webhook(
        client, webhook_id=webhook_id, order_id=payment["order_id"], status="paid"
    )
    assert webhook_resp.status_code == 200

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 200
    contest = detail.json()
    assert contest["status"] == "published"

    return sponsor, contest


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, access: str, contest_id: int) -> None:
    me = client.get("/api/accounts/me", **_auth_header(access))
    assert me.status_code == 200
    developer_user_id = me.json()["id"]
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={"source_object_key": _source_object_key(contest_id, developer_user_id)},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content


def _close_via_tick(client, *, at) -> None:
    _freeze(at)
    response = client.post(TICK_URL, **_internal_headers())
    assert response.status_code == 200


def _as_operator(client) -> None:
    """이 client 세션을 운영자로 로그인시킨다(원장 조회 엔드포인트는 operator 전용).

    같은 client에 이미 developer/sponsor 세션이 붙어 있어도 Django 세션 로그인은
    덮어써도 무방하다 — 이 헬퍼를 부르는 시점 이후로는 원장 조회 목적으로만 쓴다.
    """

    _login_operator(client, username=f"op-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@example.com")


def _ledger_balance(client, ledger_id) -> dict:
    _as_operator(client)
    response = client.get(f"{LEDGER_URL}/contests/{ledger_id}/balance")
    assert response.status_code == 200
    return response.json()


def _ledger_entries(client, ledger_id) -> list:
    _as_operator(client)
    response = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries")
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 접근 제어 ---------------------------------------------------------------


@pytest.mark.django_db
def test_run_refunds_rejects_request_without_internal_auth(client):
    response = client.post(RUN_REFUNDS_URL)

    assert response.status_code == 401


@pytest.mark.django_db
def test_run_refunds_rejects_wrong_token(client):
    response = client.post(RUN_REFUNDS_URL, **{"HTTP_X_INTERNAL_TOKEN": "wrong-token"})

    assert response.status_code == 401


# --- 핵심 경로: 참여자 0명 전액 환불 ---------------------------------------------


@pytest.mark.django_db
def test_zero_submissions_after_close_gets_fully_refunded_and_ledger_balances_to_zero(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline, prize=1_000_000
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id

    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    closed = Contest.objects.get(id=contest["id"])
    assert closed.status == Contest.Status.CLOSED

    response = _run_refunds(client)
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert body["results"] == [
        {"payment_id": Payment.objects.get(order_id=order_id).id, "contest_id": contest["id"], "status": "refunded"}
    ]

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refund_journal_entry_id is not None

    balance = _ledger_balance(client, closed.ledger_id)
    assert balance["balance"] == 0
    assert balance["is_balanced"] is True

    listing_fee = settings.CONTEST_LISTING_FEE
    entries = _ledger_entries(client, closed.ledger_id)
    lines = entries[1]["lines"]
    lines_by_account = {line["account"]: (line["side"], line["amount"]) for line in lines}
    assert lines_by_account["sponsor_deposit"] == ("credit", 1_000_000 + listing_fee)
    assert lines_by_account["developer_payable"] == ("debit", 1_000_000)
    assert lines_by_account["platform_fee_revenue"] == ("debit", listing_fee)


@pytest.mark.django_db
def test_firing_refund_scan_twice_refunds_only_once(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    first = _run_refunds(client)
    second = _run_refunds(client)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["count"] == 1
    assert second.json()["count"] == 0

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    entries = _ledger_entries(client, ledger_id)
    # 2번째 스캔이 아무 것도 하지 않았으므로 반대 분개는 정확히 하나뿐이다
    # (원본 예치 분개 + 환불 반대 분개 = 2건).
    assert len([e for e in entries if e["reverses_id"] is not None]) == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_refund_scans_refund_only_once(django_db_blocker, category, landing_type):
    """두 워커가 동시에 같은 스캔을 돌려도 환불은 한 번만 일어나야 한다.

    request_refund의 조건부 UPDATE(WHERE status='paid')가 실제 동시 경합에서도
    막아주는지는 순차 이중 호출로는 증명되지 않는다 — 스레드 두 개로 실제 경합을
    만든다(test_payments.py의 동시 결제 시작 테스트와 같은 방식).
    """

    from django.db import connections
    from django.test import Client

    with django_db_blocker.unblock():
        setup_client = Client()
        deadline = timezone.now() + timedelta(hours=1)
        sponsor, contest = _publish_contest(
            setup_client, category=category, deliverable_type=landing_type, deadline_at=deadline
        )
        order_id = Payment.objects.get(contest_id=contest["id"]).order_id
        _close_via_tick(setup_client, at=deadline + timedelta(minutes=1))

        results: list = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                with django_db_blocker.unblock():
                    local_client = Client()
                    barrier.wait()
                    response = local_client.post(
                        RUN_REFUNDS_URL,
                        data={},
                        content_type="application/json",
                        **_internal_headers(),
                    )
                    results.append(response)
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        for response in results:
            assert response.status_code == 200

        total_refunded = sum(r.json()["count"] for r in results)
        assert total_refunded == 1

        payment = Payment.objects.get(order_id=order_id)
        assert payment.status == Payment.Status.REFUNDED

        ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
        entries = _ledger_entries(setup_client, ledger_id)
        assert len([e for e in entries if e["reverses_id"] is not None]) == 1


# --- Submission이 있으면 절대 환불되지 않는다 ------------------------------------


@pytest.mark.django_db
def test_contest_with_one_submission_is_never_refunded(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _submit(client, dev["access"], contest["id"])

    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    response = _run_refunds(client)
    assert response.status_code == 200
    assert response.json()["count"] == 0

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.PAID
    assert payment.refund_journal_entry_id is None

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    balance = _ledger_balance(client, ledger_id)
    # 환불되지 않았으므로 예치금은 여전히 Escrow에 남아 있다 — 순합계는 0이
    # 아니다(발주자 예치금 차변만 있고, 상금·수수료로 이미 대변에 분산됐으므로
    # net_balance는 0이지만 is_balanced로 "분개 자체는 여전히 하나뿐"임을 함께
    # 확인한다).
    assert balance["is_balanced"] is True

    entries = _ledger_entries(client, ledger_id)
    assert len(entries) == 1  # 예치 분개 하나뿐 — 반대 분개가 없다.


@pytest.mark.django_db
def test_still_published_contest_is_not_refunded_before_close(client, category, landing_type):
    """마감(CLOSED 전이) 전에는 Submission이 0건이라도 환불 스캔이 손대지 않는다."""

    deadline = timezone.now() + timedelta(days=7)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id

    response = _run_refunds(client)
    assert response.status_code == 200
    assert response.json()["count"] == 0

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.PAID


# --- Fake PG 장애 흐름 주입 ----------------------------------------------------


@pytest.mark.django_db
def test_refund_survives_pg_timeout_then_success(client, category, landing_type):
    """confirm과 같은 규율 — 환불 호출이 타임아웃해도 실제로 성공했으면
    query_refund_status로 확정해 REFUNDED로 끝나야 한다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    response = _run_refunds(client, simulate="timeout_then_success")
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "refunded"

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refund_journal_entry_id is not None

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    balance = _ledger_balance(client, ledger_id)
    assert balance["balance"] == 0
    assert balance["is_balanced"] is True


@pytest.mark.django_db
def test_refund_reverts_to_paid_on_pg_timeout_then_failure_and_retries_succeed(
    client, category, landing_type
):
    """환불이 (타임아웃 후 확정된) 실패로 끝나면 PAID로 되돌아가 재시도 가능해야
    하고, 원장은 아직 손대지 않아야 한다. 다음 스캔이 성공하면 그제서야 환불된다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    first = _run_refunds(client, simulate="timeout_then_failed")
    assert first.status_code == 200
    assert first.json()["results"][0]["status"] == "failed"

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.PAID
    assert payment.refund_journal_entry_id is None

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    entries = _ledger_entries(client, ledger_id)
    assert len(entries) == 1  # 원장은 아직 예치 분개 하나뿐 — 환불 분개 없음.

    second = _run_refunds(client)
    assert second.status_code == 200
    assert second.json()["results"][0]["status"] == "refunded"

    payment.refresh_from_db()
    assert payment.status == Payment.Status.REFUNDED

    balance = client.get(f"{LEDGER_URL}/contests/{ledger_id}/balance").json()
    assert balance["balance"] == 0
    assert balance["is_balanced"] is True


@pytest.mark.django_db
def test_immediate_pg_failure_reverts_to_paid_without_touching_ledger(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    response = _run_refunds(client, simulate="failed")
    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "failed"

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.PAID


# --- 웹훅 재전송 --------------------------------------------------------------


@pytest.mark.django_db
def test_duplicate_refund_webhook_after_scan_already_refunded_is_applied_exactly_once(
    client, category, landing_type
):
    """스캔이 동기적으로 이미 환불을 확정한 뒤, PG가 같은 결과를 웹훅으로 뒤늦게
    (그리고 두 번) 통지해도 반대 분개는 정확히 하나만 남아야 한다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    scan = _run_refunds(client)
    assert scan.json()["count"] == 1

    for _ in range(2):
        webhook_id = f"wh-refund-{uuid.uuid4().hex}"
        webhook_resp = _send_webhook(
            client, webhook_id=webhook_id, order_id=str(order_id), status="refunded"
        )
        assert webhook_resp.status_code == 200
        assert webhook_resp.json()["status"] == "refunded"

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    entries = _ledger_entries(client, ledger_id)
    assert len(entries) == 2  # 예치 분개 + 환불 반대 분개, 그 이상은 없다.

    balance = client.get(f"{LEDGER_URL}/contests/{ledger_id}/balance").json()
    assert balance["balance"] == 0
    assert balance["is_balanced"] is True


@pytest.mark.django_db
def test_unsigned_refund_webhook_is_rejected_and_payment_untouched(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))
    _run_refunds(client)

    response = _send_webhook(
        client,
        webhook_id="wh-forged",
        order_id=str(order_id),
        status="refund_failed",
        signature="not-a-real-signature",
    )
    assert response.status_code == 401

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED  # 위조 웹훅이 되돌리지 못했다.


@pytest.mark.django_db
def test_refund_webhook_for_payment_still_paid_is_a_noop(client, category, landing_type):
    """스캔이 아직 이 Payment를 집지 않았는데(REFUND_REQUESTED가 아님) 환불
    웹훅이 먼저 오면, mark_refunded는 조건부 UPDATE의 rowcount가 0이라 원장에
    아무 것도 남기지 않아야 한다 — 위조든 시점 경합이든 이겨선 안 된다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))
    # 스캔을 아직 돌리지 않았다 — Payment는 여전히 PAID다.

    webhook_id = f"wh-early-{uuid.uuid4().hex}"
    response = _send_webhook(
        client, webhook_id=webhook_id, order_id=str(order_id), status="refunded"
    )
    assert response.status_code == 200

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.PAID  # refunded로 넘어가지 않았다.
    assert payment.refund_journal_entry_id is None
