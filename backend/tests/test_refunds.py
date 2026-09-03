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
from policies.scope import current_policy

# 환불 스캔 둘의 등록부 이름(#140) — 예전 단일 엔드포인트가 순서대로 처리하던 두 후보 종류 그대로.
REFUND_SCAN_URLS = (
    "/api/internal/scans/payment-refund-request",
    "/api/internal/scans/payment-refund-reconcile",
)


class _ScanResponse:
    """두 스캔 응답을 예전 `/run-refunds` 의 관찰면(`count`·`results`)으로 합친 것."""

    status_code = 200

    def __init__(self, rows: list[dict]):
        self._body = {"count": len(rows), "results": rows}

    def json(self) -> dict:
        return self._body
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


def _run_refunds(client, *, simulate: str | None = None, scans=REFUND_SCAN_URLS) -> _ScanResponse:
    rows: list[dict] = []
    for url in scans:
        response = client.post(
            url,
            data={"params": {"simulate": simulate}} if simulate is not None else {},
            content_type="application/json",
            **_internal_headers(),
        )
        assert response.status_code == 200, response.content
        rows += response.json()["rows"]
    return _ScanResponse(rows)


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
    """Contest 전이 스캔 둘(마감·심사기간 종료)만 돌린다 — `/tick` 은 등록부 전부를 한 바퀴
    돌아(#137) 환불 스캔까지 같이 실행하므로, 어느 simulate 로 언제 환불되는지를 단언하는 이
    파일에서는 쓰지 않는다."""

    _freeze(at)
    for name in ("contest-close", "contest-judging-end"):
        response = client.post(f"/api/internal/scans/{name}", **_internal_headers())
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
    response = client.post(REFUND_SCAN_URLS[0])

    assert response.status_code == 401


@pytest.mark.django_db
def test_run_refunds_rejects_wrong_token(client):
    response = client.post(REFUND_SCAN_URLS[0], **{"HTTP_X_INTERNAL_TOKEN": "wrong-token"})

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
        {
            "payment_id": Payment.objects.get(order_id=order_id).id,
            "contest_id": contest["id"],
            "status": "refunded",
            # 이 스캔이 직접 선점해 환불했다는 뜻이다 — 남이 시작한 환불을
            # 확인만 한 경우와 구분된다(#48).
            "claimed": True,
        }
    ]

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refund_journal_entry_id is not None

    balance = _ledger_balance(client, closed.ledger_id)
    assert balance["balance"] == 0
    assert balance["is_balanced"] is True

    listing_fee = current_policy().contest_listing_fee
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
    """두 스캔이 같은 PAID Payment 를 **동시에 선점하려 할 때** 정확히 하나만 이긴다.

    `request_refund` 의 조건부 UPDATE(WHERE status='paid')가 최후의 방어선으로
    동작하는지를 본다.

    **이 테스트는 두 번 고쳐졌다(#48).**

    처음에는 `sum(count) == 1` 을 단언했다. 그런데 `count` 는 "이번 스캔이 처리한
    행 수"이지 "환불한 건수"가 아니다 — 경합이 진짜로 일어나면 합계가 2가 되므로,
    그 단언은 **경합이 실제로 일어날 때만 실패**했다. 제 일을 할 때만 빨개지는
    테스트였다.

    단언을 고친 뒤에는 더 불편한 사실이 드러났다: `threading.Barrier` 로 두 요청을
    같은 순간에 쏴도 **12번 중 한 번도 겹치지 않았다.** 한 스레드가 스캔을 통째로
    끝낸 뒤에야 다른 스레드가 시작하므로, 뒤늦은 스캔은 후보 집합에서 이미 사라진
    Payment 를 아예 보지 못한다. 겹치지 않은 실행은 조건부 UPDATE 에 대해 아무것도
    증명하지 않는다.

    그래서 경합을 **우연에 맡기지 않고 만든다.** 두 스레드가 각자 후보를 고른 뒤
    선점 직전에서 만나도록 `request_refund` 를 감싼다 — 그 지점이 정확히 이
    테스트가 지키려는 곳이다. HTTP 시임 밖으로 나가는 예외지만(CLAUDE.md), 두
    요청의 내부 인터리빙은 시임 위에서는 만들어낼 수 없다 — `test_ledger.py` 의
    매니저 레벨 테스트가 같은 이유로 둔 예외와 같은 성격이다.
    """

    from unittest.mock import patch

    from django.db import connections
    from django.test import Client

    from payments import services as payment_services

    with django_db_blocker.unblock():
        setup_client = Client()
        deadline = timezone.now() + timedelta(hours=1)
        _sponsor, contest = _publish_contest(
            setup_client, category=category, deliverable_type=landing_type, deadline_at=deadline
        )
        payment = Payment.objects.get(contest_id=contest["id"])
        _close_via_tick(setup_client, at=deadline + timedelta(minutes=1))

        real_request_refund = payment_services.request_refund
        claim_barrier = threading.Barrier(2)
        claim_lock = threading.Lock()
        claim_outcomes: list = []

        def racing_request_refund(order_id):
            # 두 스레드가 각자 후보를 고른 상태로 여기 모인다 — 둘 다 이 Payment 를
            # PAID 로 보고 있다. 그 다음 동시에 조건부 UPDATE 로 들어간다.
            claim_barrier.wait(timeout=15)
            claimed = real_request_refund(order_id)
            with claim_lock:
                claim_outcomes.append(claimed)
            return claimed

        responses: list = []

        def worker():
            try:
                with django_db_blocker.unblock():
                    local_client = Client()
                    responses.append(
                        local_client.post(
                            REFUND_SCAN_URLS[0],
                            data={},
                            content_type="application/json",
                            **_internal_headers(),
                        )
                    )
            finally:
                connections.close_all()

        with patch.object(payment_services, "request_refund", racing_request_refund):
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=30)
            assert not any(t.is_alive() for t in threads), "스레드가 끝나지 않았다"

        assert len(responses) == 2
        for response in responses:
            assert response.status_code == 200, response.content

        # --- 경합이 실제로 일어났는가 -----------------------------------------
        #
        # 둘 다 이 Payment 를 PAID 로 보고 선점을 시도했다는 뜻이다. 이게 아니면
        # 아래 단언들은 조건부 UPDATE 에 대해 아무것도 말하지 않는다.
        assert len(claim_outcomes) == 2, (
            f"두 스캔이 동시에 선점을 시도하지 않았다({len(claim_outcomes)}회) — "
            "이 테스트는 아무것도 증명하지 못했다."
        )

        # --- 그리고 정확히 하나만 이겼는가 -------------------------------------
        winners = [c for c in claim_outcomes if c is not None]
        assert len(winners) == 1, f"선점이 {len(winners)}번 성공했다 — 조건부 UPDATE 가 샜다"

        rows = [
            row
            for response in responses
            for row in response.json()["rows"]
            if row["payment_id"] == payment.id
        ]
        assert [row["claimed"] for row in rows] == [True], (
            f"환불을 수행했다고 보고한 스캔이 정확히 하나가 아니다: {rows}"
        )

        refreshed = Payment.objects.get(pk=payment.pk)
        assert refreshed.status == Payment.Status.REFUNDED

        ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
        entries = _ledger_entries(setup_client, ledger_id)
        reversing = [e for e in entries if e["reverses_id"] is not None]
        assert len(reversing) == 1, f"반대 분개가 {len(reversing)}개다 — 이중 환불"


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
def test_refund_failure_after_timeout_is_terminal_and_never_auto_retried(
    client, category, landing_type
):
    """환불이 (타임아웃 후 확정된) 실패로 끝나면 REFUND_FAILED로 종결되고 원장은
    손대지 않는다. mark_failed(Payment.FAILED)와 같은 성격의 종결 상태라 이
    스캔은 REFUND_FAILED를 자동으로 다시 집지 않는다 — PAID로 되돌리면(과거
    버전의 버그) 재전송된 실패 웹훅이 그 사이 시작된 다른 시도를 잘못 취소시켜
    이중 환불로 이어진다(리뷰 지적 1)."""

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
    assert payment.status == Payment.Status.REFUND_FAILED
    assert payment.refund_journal_entry_id is None

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    entries = _ledger_entries(client, ledger_id)
    assert len(entries) == 1  # 원장은 아직 예치 분개 하나뿐 — 환불 분개 없음.

    # 다음 스캔이 자동으로 REFUND_FAILED를 다시 집지 않는다 — PAID만 새 후보다.
    second = _run_refunds(client)
    assert second.status_code == 200
    assert second.json()["count"] == 0

    payment.refresh_from_db()
    assert payment.status == Payment.Status.REFUND_FAILED

    entries = _ledger_entries(client, ledger_id)
    assert len(entries) == 1  # 여전히 예치 분개 하나뿐.


@pytest.mark.django_db
def test_immediate_pg_failure_is_terminal_and_does_not_touch_ledger(client, category, landing_type):
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
    assert payment.status == Payment.Status.REFUND_FAILED
    assert payment.refund_journal_entry_id is None


# --- 리뷰 지적 1: 실패 웹훅 재전송이 이미 종결된 시도를 다시 건드리지 않는다 --------


@pytest.mark.django_db
def test_redelivered_refund_failed_webhook_on_an_already_failed_payment_is_a_noop(
    client, category, landing_type
):
    """가장 단순한 재전송 형태 — 같은 refund_failed 웹훅이 REFUND_FAILED에
    이미 도달한 뒤 다시 와도 아무 일도 일어나지 않는다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    _run_refunds(client, simulate="failed")
    assert Payment.objects.get(order_id=order_id).status == Payment.Status.REFUND_FAILED

    for _ in range(2):
        webhook_id = f"wh-redelivered-{uuid.uuid4().hex}"
        response = _send_webhook(
            client, webhook_id=webhook_id, order_id=str(order_id), status="refund_failed"
        )
        assert response.status_code == 200

    assert Payment.objects.get(order_id=order_id).status == Payment.Status.REFUND_FAILED


# --- 리뷰 지적 2: query_refund_status 자체의 실패가 배치를 죽이지 않는다 --------


@pytest.mark.django_db
def test_query_refund_status_error_after_timeout_does_not_500_and_leaves_row_retryable(
    client, category, landing_type
):
    """confirm과 달리, 타임아웃 뒤의 재확인 호출(query_refund_status) 자체가
    PG 쪽 오류로 실패할 수 있다. 이 오류가 스캔 엔드포인트를 500으로 죽이면
    안 되고, 나머지 배치도 계속 처리되어야 한다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor_a, contest_a = _publish_contest(
        client, category=category, deliverable_type=landing_type, sponsor_uid="sponsor-a",
        deadline_at=deadline,
    )
    sponsor_b, contest_b = _publish_contest(
        client, category=category, deliverable_type=landing_type, sponsor_uid="sponsor-b",
        deadline_at=deadline,
    )
    order_id_a = Payment.objects.get(contest_id=contest_a["id"]).order_id
    order_id_b = Payment.objects.get(contest_id=contest_b["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    # 두 Contest 모두 같은 스캔 실행 안에서 같은 simulate로 처리된다 — a는
    # query_refund_status 자체가 에러를 내는 시나리오, b는 이 테스트에서는
    # 같은 시나리오를 쓰지만 배치가 죽지 않는다는 것만 확인하면 충분하다. 재확인
    # 스캔은 돌리지 않는다 — 방금 선점된 두 행을 곧바로 다시 집어 행 수를 두 배로 보고한다.
    response = _run_refunds(client, simulate="timeout_then_query_error", scans=REFUND_SCAN_URLS[:1])
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    statuses = {r["payment_id"]: r["status"] for r in body["results"]}
    payment_a = Payment.objects.get(order_id=order_id_a)
    payment_b = Payment.objects.get(order_id=order_id_b)
    assert statuses[payment_a.id] == "pending"
    assert statuses[payment_b.id] == "pending"

    # 둘 다 REFUND_REQUESTED로 남아 다음 스캔이 재시도할 수 있다 — 영원히 갇히지
    # 않는다.
    assert payment_a.status == Payment.Status.REFUND_REQUESTED
    assert payment_b.status == Payment.Status.REFUND_REQUESTED


# --- 리뷰 지적 3: pending으로 남은 시도를 다음 스캔이 재확인해 끝낸다 -----------


@pytest.mark.django_db
def test_pending_refund_is_reconciled_by_a_later_scan_without_calling_refund_again(
    client, category, landing_type
):
    """adapter.refund()가 예외 없이 곧바로 "pending"을 돌려주면(비동기 PG) 이
    Payment는 REFUND_REQUESTED로 남는다. 다음 스캔은 새 refund()를 다시
    부르지 않고(중복 요청 방지) query_refund_status로만 재확인해야 하고, PG가
    그 사이 실제로 확정했다면(Fake의 테스트 전용 훅으로 흉내낸다) 그 결과를
    끝내 반영해야 한다."""

    from payments.adapters import FakePGAdapter

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    first = _run_refunds(client, simulate="pending")
    assert first.status_code == 200
    assert first.json()["results"][0]["status"] == "pending"
    assert Payment.objects.get(order_id=order_id).status == Payment.Status.REFUND_REQUESTED

    # 다음 스캔이 (아직 PG가 확정하지 못했다면) 계속 pending으로 재확인만 하고
    # 새 refund()를 또 부르지 않는다는 것을 확인한다.
    second = _run_refunds(client)
    assert second.status_code == 200
    assert second.json()["count"] == 1
    assert second.json()["results"][0]["status"] == "pending"
    assert Payment.objects.get(order_id=order_id).status == Payment.Status.REFUND_REQUESTED

    # PG가 그 사이 실제로 환불을 확정했다 — Fake의 테스트 전용 훅으로 흉내낸다
    # (ClockOverride로 시간을 앞당기는 것과 같은 성격의 인프라 상태 준비).
    FakePGAdapter.resolve_pending_refund_for_testing(str(order_id), "refunded")

    third = _run_refunds(client)
    assert third.status_code == 200
    assert third.json()["count"] == 1
    assert third.json()["results"][0]["status"] == "refunded"

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refund_journal_entry_id is not None

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    balance = client.get(f"{LEDGER_URL}/contests/{ledger_id}/balance")
    _as_operator(client)
    balance = client.get(f"{LEDGER_URL}/contests/{ledger_id}/balance").json()
    assert balance["balance"] == 0
    assert balance["is_balanced"] is True


# --- 리뷰 지적 4: 배치 크기가 무제한이 아니다 ------------------------------------


@pytest.mark.django_db
def test_refund_scan_is_bounded_by_batch_size(client, category, landing_type):
    """한 스캔이 처리하는 후보 수가 배치 상한으로 제한된다 — 무제한 스캔은
    백로그가 쌓였을 때 이 엔드포인트를 호출하는 HTTP 요청 자체를 타임아웃으로
    몰아넣는다."""

    from core.scans import SCAN_REGISTRY

    REFUND_BATCH_SIZE = SCAN_REGISTRY["payment-refund-request"].batch_size
    assert REFUND_BATCH_SIZE > 0

    total = REFUND_BATCH_SIZE + 3
    deadline = timezone.now() + timedelta(hours=1)
    order_ids = []
    for i in range(total):
        sponsor, contest = _publish_contest(
            client,
            category=category,
            deliverable_type=landing_type,
            sponsor_uid=f"batch-sponsor-{i}",
            deadline_at=deadline,
        )
        order_ids.append(Payment.objects.get(contest_id=contest["id"]).order_id)

    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    response = _run_refunds(client)
    assert response.status_code == 200
    assert response.json()["count"] == REFUND_BATCH_SIZE

    refunded = Payment.objects.filter(
        order_id__in=order_ids, status=Payment.Status.REFUNDED
    ).count()
    still_paid = Payment.objects.filter(order_id__in=order_ids, status=Payment.Status.PAID).count()
    assert refunded == REFUND_BATCH_SIZE
    assert still_paid == total - REFUND_BATCH_SIZE

    # 다음 스캔이 남은 잔여분을 마저 처리한다.
    second = _run_refunds(client)
    assert second.status_code == 200
    assert second.json()["count"] == total - REFUND_BATCH_SIZE

    refunded_after = Payment.objects.filter(
        order_id__in=order_ids, status=Payment.Status.REFUNDED
    ).count()
    assert refunded_after == total


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
def test_refund_webhook_for_payment_still_paid_is_honored(client, category, landing_type):
    """스캔이 아직 이 Payment를 집지 않았는데(REFUND_REQUESTED가 아님) 서명이
    유효한 환불 웹훅이 먼저 오면(PG 콘솔에서 직접 환불했거나 차지백이 들어온
    경우), 조용히 버리지 않고 그대로 반영해야 한다.

    서명 검증(`verify_webhook_signature`)이 이미 위조를 걸러내므로, 여기 남는
    건 "우리 스캔이 아직 request_refund로 선점하지 않은 PAID Payment"뿐이다 —
    이 신호를 버리면 PG가 이미 실제로 환불한 돈이 원장에는 여전히 예치금으로
    남아, 나중에 Award/Payout이 이미 돌려준 돈을 또 지급하는 사고로 이어진다.
    웹훅 핸들러가 PAID -> REFUND_REQUESTED로 먼저 선점한 뒤 확정하므로, 반대
    분개가 정확히 한 번 남는다."""

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
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refund_journal_entry_id is not None



# --- 코디네이터 리뷰 회귀 방지: 새 상태(JUDGING_ENDED)·refund_disabled·재시도 --------


def _end_judging_period_via_tick(client, contest_id: int) -> None:
    """CLOSED -> JUDGING_ENDED로 옮긴다 — 스케줄러가 judging_ends_at이 지나면
    Award 여부와 무관하게 무조건 이 전이를 시킨다(core.transitions 레지스트리).
    """

    judging_ends_at = Contest.objects.get(id=contest_id).judging_ends_at
    assert judging_ends_at is not None
    _close_via_tick(client, at=judging_ends_at + timedelta(minutes=1))
    assert Contest.objects.get(id=contest_id).status == Contest.Status.JUDGING_ENDED


@pytest.mark.django_db
def test_zero_submission_contest_stuck_at_judging_ended_is_still_refunded(
    client, category, landing_type
):
    """참여자 0명인 Contest가 환불 스캔이 따라잡기 전에 CLOSED -> JUDGING_ENDED로
    자동 전이돼도(스케줄러는 Award 여부와 무관하게 judging_ends_at이 지나면
    무조건 옮긴다) 여전히 환불 대상이어야 한다.

    이전에는 run_pending_refunds의 후보 쿼리가 status=CLOSED만 봐서, 이 시점
    이후로는 Payment가 PAID에 영원히 갇혔다(코디네이터 리뷰 결함 1)."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id

    _close_via_tick(client, at=deadline + timedelta(minutes=1))
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    # 환불 스캔을 아직 돌리지 않은 채로 심사기간 종료 시각까지 시간을 더 흘려
    # JUDGING_ENDED로 넘어가게 한다.
    _end_judging_period_via_tick(client, contest["id"])

    resp = _run_refunds(client)
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert any(r["payment_id"] == Payment.objects.get(order_id=order_id).id for r in body["results"])

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refund_journal_entry_id is not None


@pytest.mark.django_db
def test_refund_disabled_contest_is_never_refunded_even_with_zero_submissions(
    client, category, landing_type
):
    """REQUEST.md: 유료 연장 2회 이상이면 환불 불가로 영구 확정된다. 참여자가
    0명이어도 refund_disabled인 Contest는 이 스캔이 절대 건드리면 안 된다
    (코디네이터 리뷰 결함 5 — #13이 만든 refund_disabled의 유일한 소비처인데
    소비하지 않고 있었다)."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    # 실제 연장 결제 두 번을 거치는 대신, 그 결과 상태(refund_disabled=True)만
    # 직접 준비한다 — 이 테스트의 대상은 연장 로직이 아니라 환불 스캔의 필터다.
    Contest.objects.filter(id=contest["id"]).update(refund_disabled=True)

    resp = _run_refunds(client)
    assert resp.status_code == 200, resp.content

    payment = Payment.objects.get(order_id=order_id)
    assert payment.status == Payment.Status.PAID
    assert payment.refund_journal_entry_id is None


@pytest.mark.django_db
def test_unexpected_adapter_exception_leaves_refund_retryable_not_terminal(
    client, category, landing_type
):
    """PG가 명시적으로 거부한 것(PGError)과 예기치 못한 예외는 다르다 — 후자는
    REFUND_FAILED(재시도 경로 없는 종결 상태)로 굳히면 안 된다(코디네이터 리뷰
    결함 3). 어댑터가 알 수 없는 예외를 던져도 Payment는 REFUND_REQUESTED로
    남아 다음 스캔이 재확인할 수 있어야 한다."""

    from unittest.mock import patch

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    order_id = Payment.objects.get(contest_id=contest["id"]).order_id
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    with patch(
        "payments.adapters.FakePGAdapter.refund",
        side_effect=RuntimeError("예기치 못한 어댑터 버그"),
    ):
        resp = _run_refunds(client)
        assert resp.status_code == 200, resp.content

    payment = Payment.objects.get(order_id=order_id)
    # REFUND_FAILED(종결)가 아니라 REFUND_REQUESTED(재시도 대상)로 남아야 한다.
    assert payment.status == Payment.Status.REFUND_REQUESTED
    assert payment.refund_journal_entry_id is None

    # PG는 실제로는 그 사이 환불을 완료했다(FakePGAdapter의 테스트 전용
    # 훅으로 주입한다 — payments.adapters.FakePGAdapter.resolve_pending_refund_
    # for_testing과 같은 성격, ClockOverride로 시각을 앞당기는 것과 같은
    # 원칙). 다음 스캔의 재확인이 마저 확정한다 — REFUND_FAILED로 굳었다면
    # candidate 쿼리 밖으로 영원히 빠져 이 재시도 경로 자체가 없었을 것이다.
    from payments.adapters import FakePGAdapter

    FakePGAdapter.resolve_pending_refund_for_testing(str(order_id), "refunded")

    resp2 = _run_refunds(client)
    assert resp2.status_code == 200, resp2.content
    payment.refresh_from_db()
    assert payment.status == Payment.Status.REFUNDED
    assert payment.refund_journal_entry_id is not None


@pytest.mark.django_db
def test_run_refunds_accepts_body_less_request(client, category, landing_type):
    """`core.tasks.call_scheduler_tick`처럼 Celery beat는 `requests.post(url,
    headers=..., timeout=30)`로 본문 없이(길이 0) POST한다 — Django 테스트
    클라이언트의 기본 `client.post(url)`은 이것과 다르다: `data=`를 생략해도
    multipart 경계 문자열이 채워진 **비어 있지 않은** 본문을 보내므로, 실제
    운영 호출을 재현하려면 `generic()`으로 길이 0인 본문을 직접 보내야 한다.

    이 스캔도 본문 없는 호출을 받아들여야 실제로 스케줄에 걸린다(코디네이터
    리뷰 결함 8). 이전에는 본문 스키마에 기본값이 없어 본문 없는 요청이 400으로
    거부됐다 — 지금은 `/scans/{name}` 이 본문을 선택으로 읽는다(#140)."""

    response = client.generic(
        "POST", REFUND_SCAN_URLS[0], data=b"", content_type="application/json", **_internal_headers()
    )
    assert response.status_code == 200, response.content
