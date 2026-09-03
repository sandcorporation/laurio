"""결제 + Escrow 예치 + Fake PG → Contest 공개 (#9, ADR-0004, ADR-0007, ADR-0008).

Fake PG의 존재 이유는 정상 흐름이 아니라 장애 흐름이다 — 웹훅 재전송, 웹훅이 동기
승인 확인보다 먼저 도착, 타임아웃 후 실제로는 성공. 이 파일은 그 장애 흐름을
먼저 증명하고 나서 원장 불변식과 Contest 공개 시점을 확인한다.
"""

import hashlib
import hmac
import threading
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import override_settings

from contests.models import Category, Contest, DeliverableType
from payments.adapters import FakePGAdapter, PGError, PGTimeoutError, PaymentRequestResult
from payments.models import Payment
from policies.services import get_current_policy

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
LEDGER_URL = "/api/ledger"


def _login(client, uid="sponsor-1", email="sponsor@example.com"):
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _verify(client, access: str, ci: str = "sponsor-ci-1") -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"발주자|1985-06-01|{ci}|sponsor-di-1"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def _make_operator(**kwargs):
    defaults = {
        "username": "payments-operator",
        "email": "payments-operator@example.com",
        "password": "operator-pw-1234",
        "is_staff": True,
    }
    defaults.update(kwargs)
    return get_user_model().objects.create_user(**defaults)


def _login_operator(client, **kwargs):
    user = _make_operator(**kwargs)
    assert client.login(username=user.username, password="operator-pw-1234")
    return user


@pytest.fixture
def category(db):
    return Category.objects.create(name="엔터테인먼트")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _draft_contest(client, *, uid="sponsor-1", ci="sponsor-ci-1", prize=1_000_000, category=None, deliverable_type=None):
    """검증된 Sponsor로 로그인해 draft Contest를 하나 만들고 (access token, contest dict)를 돌려준다."""

    pair = _login(client, uid=uid, email=f"{uid}@example.com")
    _verify(client, pair["access"], ci=ci)

    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{uid}의 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "prize": prize,
            "deadline_at": "2030-01-01T00:00:00Z",
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.status_code == 200
    return pair["access"], response.json()


def _initiate_payment(client, access: str, contest_id: int) -> dict:
    response = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest_id},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _sign(*, webhook_id: str, order_id: str, status: str, secret: str | None = None) -> str:
    """Fake PG가 웹훅에 붙이는 서명을 그대로 재현한다(payments.webhook_security와
    같은 HMAC-SHA256 스킴). 실제 secret 대신 잘못된 값을 넣으면 위조 웹훅을
    흉내낼 수 있다."""

    key = secret if secret is not None else settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _send_webhook(
    client, *, webhook_id: str, order_id: str, status: str, signature: str | None = "__default__"
):
    body = {"webhook_id": webhook_id, "order_id": order_id, "status": status}
    if signature == "__default__":
        body["signature"] = _sign(webhook_id=webhook_id, order_id=order_id, status=status)
    elif signature is not None:
        body["signature"] = signature
    return client.post(
        f"{PAYMENTS_URL}/webhook",
        data=body,
        content_type="application/json",
    )


def _confirm(
    client,
    access: str,
    order_id: str,
    simulate: str | None = None,
    payment_key: str | None = None,
):
    body: dict = {}
    if simulate is not None:
        body["simulate"] = simulate
    if payment_key is not None:
        body["payment_key"] = payment_key
    return client.post(
        f"{PAYMENTS_URL}/{order_id}/confirm",
        data=body,
        content_type="application/json",
        **_auth_header(access),
    )


# --- 접근 제어 ---------------------------------------------------------------


@pytest.mark.django_db
def test_unauthenticated_cannot_initiate_payment(client, category, landing_type):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)

    response = client.post(
        PAYMENTS_URL, data={"contest_id": contest["id"]}, content_type="application/json"
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_stranger_cannot_pay_for_someone_elses_contest(client, category, landing_type):
    _owner_access, contest = _draft_contest(
        client, uid="owner", ci="owner-ci", category=category, deliverable_type=landing_type
    )

    stranger_pair = _login(client, uid="stranger", email="stranger@example.com")

    response = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(stranger_pair["access"]),
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_already_published_contest_cannot_be_paid_again(client, category, landing_type):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])
    webhook = _send_webhook(
        client, webhook_id="wh-1", order_id=payment["order_id"], status="paid"
    )
    assert webhook.status_code == 200

    response = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 409


# --- Contest 공개 시점 --------------------------------------------------------


@pytest.mark.django_db
def test_contest_not_visible_anonymously_before_payment(client, category, landing_type):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    _initiate_payment(client, access, contest["id"])

    listing = client.get(CONTESTS_URL).json()
    assert all(c["id"] != contest["id"] for c in listing["items"])

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 404


@pytest.mark.django_db
def test_contest_visible_anonymously_immediately_after_payment_success(
    client, category, landing_type
):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    webhook = _send_webhook(
        client, webhook_id="wh-visible-1", order_id=payment["order_id"], status="paid"
    )
    assert webhook.status_code == 200

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 200
    assert detail.json()["status"] == "published"

    listing = client.get(CONTESTS_URL).json()
    assert any(c["id"] == contest["id"] for c in listing["items"])


@pytest.mark.django_db
def test_failed_payment_leaves_contest_draft_and_no_ledger_entries(
    client, category, landing_type
):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    response = _confirm(client, access, payment["order_id"], simulate="failed")
    assert response.status_code == 200
    assert response.json()["status"] == "failed"

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 404  # 여전히 draft — 공개되지 않았다

    # ledger_id는 ContestOut에 노출되지 않으므로 DB에서 직접 가져온다.
    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries")
    assert entries.status_code == 200
    assert entries.json() == []


# --- 원장 불변식 --------------------------------------------------------------


@pytest.mark.django_db
def test_escrow_deposit_posts_balanced_ledger_entry(client, category, landing_type):
    access, contest = _draft_contest(
        client, prize=1_000_000, category=category, deliverable_type=landing_type
    )
    payment = _initiate_payment(client, access, contest["id"])

    webhook = _send_webhook(
        client, webhook_id="wh-balance-1", order_id=payment["order_id"], status="paid"
    )
    assert webhook.status_code == 200

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id

    _login_operator(client)
    balance = client.get(f"{LEDGER_URL}/contests/{ledger_id}/balance")
    assert balance.status_code == 200
    body = balance.json()
    assert body["is_balanced"] is True
    assert body["balance"] == 0  # 모든 분개가 그 자체로 균형이면 순합계는 항상 0이다.

    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert len(entries) == 1
    entry = entries[0]

    listing_fee = get_current_policy().contest_listing_fee
    lines_by_account = {line["account"]: (line["side"], line["amount"]) for line in entry["lines"]}
    assert lines_by_account["sponsor_deposit"] == ("debit", 1_000_000 + listing_fee)
    assert lines_by_account["developer_payable"] == ("credit", 1_000_000)
    assert lines_by_account["platform_fee_revenue"] == ("credit", listing_fee)

    debit_total = sum(amt for side, amt in lines_by_account.values() if side == "debit")
    credit_total = sum(amt for side, amt in lines_by_account.values() if side == "credit")
    assert debit_total == credit_total == 1_000_000 + listing_fee


# --- 돈이 새는 경로 (Fake PG 주입) --------------------------------------------


@pytest.mark.django_db
def test_duplicate_webhook_is_applied_to_ledger_exactly_once(client, category, landing_type):
    """같은 웹훅이 PG 재전송으로 두 번 와도 원장 분개는 한 번만 남는다."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    first = _send_webhook(
        client, webhook_id="wh-dup-1", order_id=payment["order_id"], status="paid"
    )
    second = _send_webhook(
        client, webhook_id="wh-dup-1", order_id=payment["order_id"], status="paid"
    )

    assert first.status_code == 200
    assert second.status_code == 200

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert len(entries) == 1

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.PUBLISHED

    payment_row = Payment.objects.get(order_id=payment["order_id"])
    assert payment_row.status == Payment.Status.PAID


@pytest.mark.django_db
def test_webhook_arriving_before_confirm_response_still_lands_correct_state(
    client, category, landing_type
):
    """웹훅이 동기 승인 확인보다 먼저 도착해도 최종 상태가 어긋나지 않는다."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    # 웹훅이 먼저 도착한다(PG 쪽 비동기 통지가 우리 서버의 동기 confirm 호출보다 빠르다).
    webhook = _send_webhook(
        client, webhook_id="wh-order-1", order_id=payment["order_id"], status="paid"
    )
    assert webhook.status_code == 200

    # 뒤늦게 confirm이 도착한다 — 이미 확정되어 있으므로 조용히 같은 결과를 돌려줘야 한다.
    confirm = _confirm(client, access, payment["order_id"])
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "paid"

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert len(entries) == 1  # 두 채널이 경합해도 분개는 한 번만.

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.PUBLISHED


@pytest.mark.django_db
def test_confirm_timeout_but_actually_succeeded_reconciles_via_query_not_double_charge(
    client, category, landing_type
):
    """confirm 호출이 타임아웃돼도, 실제로는 PG 쪽에서 성공했다면 조회로 확정하고
    중복 반영하지 않는다."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    confirm = _confirm(client, access, payment["order_id"], simulate="timeout_then_success")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "paid"

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.PUBLISHED

    # 나중에 같은 결제에 대해 웹훅까지 도착해도(실제로 PG가 결국 웹훅도 보냈다고
    # 가정) 원장에는 여전히 한 번만 반영되어야 한다.
    webhook = _send_webhook(
        client, webhook_id="wh-timeout-1", order_id=payment["order_id"], status="paid"
    )
    assert webhook.status_code == 200

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert len(entries) == 1


@pytest.mark.django_db
def test_confirm_timeout_but_actually_failed_does_not_publish_or_post_ledger(
    client, category, landing_type
):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    confirm = _confirm(client, access, payment["order_id"], simulate="timeout_then_failed")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "failed"

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.DRAFT

    ledger_id = contest_row.ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert entries == []


@pytest.mark.django_db
def test_confirm_forwards_payment_key_to_adapter(client, category, landing_type):
    """브라우저가 보낸 결제 건 식별자가 PG 어댑터의 confirm까지 도달한다 (#86, spec #82).

    실물 PG(토스)는 결제 승인에 결제 건 식별자(payment key)를 요구하는데, 그
    값은 브라우저 위젯이 성공했을 때만 생긴다. FakePGAdapter는 이 값을 그냥
    무시해도(기존 동작 불변) 계약에는 그 값을 나를 자리가 있어야 하고, 실제로
    확인 요청 → 어댑터까지 전달돼야 한다 — #87이 실물 어댑터로 갈아끼울 때 그
    자리에 값을 지어내지 않고 그대로 넘길 수 있어야 하기 때문이다.

    FakePGAdapter는 이 값을 어디에도 남기지 않으므로(무시하는 것 자체가
    인수조건), 도달 여부를 스파이로 관찰한다 — 여전히 HTTP 엔드포인트를 통해
    구동되고, 스파이는 관찰 지점일 뿐 시임을 바꾸지 않는다.
    """

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    received: dict[str, str | int | None] = {}
    original_confirm = FakePGAdapter.confirm

    def spy_confirm(self, *, order_id, simulate=None, payment_key=None, amount=None):
        received["payment_key"] = payment_key
        received["amount"] = amount
        return original_confirm(self, order_id=order_id, simulate=simulate)

    with patch.object(FakePGAdapter, "confirm", spy_confirm):
        response = _confirm(
            client, access, payment["order_id"], payment_key="fake-widget-key-abc123"
        )

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    assert received["payment_key"] == "fake-widget-key-abc123"
    # amount도 payment_key와 같은 이유로 계약에 있다(#87) — 토스 결제 승인
    # API가 위·변조 방지를 위해 요구하는 값이라, 호출부가 DB의 실제 결제 금액을
    # 그대로 넘기는지 확인한다.
    assert received["amount"] == payment["total_amount"]


@pytest.mark.django_db
def test_confirm_survives_query_status_failure_after_timeout(client, category, landing_type):
    """confirm이 타임아웃돼 query_status로 재확인하는데 그 재확인마저 실패하면
    (#87 코드리뷰 지적 3) — 500이 되면 안 된다. FakePGAdapter는 query_status에서
    절대 예외를 던지지 않아 이 경로가 기존 테스트에서 한 번도 밟힌 적이 없었다
    (실물 어댑터는 네트워크 문제로 재확인 자체도 실패할 수 있다). 재확인조차
    실패했다는 것은 "실패했다"가 아니라 "아직 모른다"이므로, Payment는 강제로
    종결되지 않고 REQUESTED로 남아야 한다."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    def broken_confirm(self, *, order_id, simulate=None, payment_key=None, amount=None):
        raise PGTimeoutError("fake network blip on confirm")

    def broken_query_status(self, *, order_id):
        raise PGError("fake network blip on query_status")

    with patch.object(FakePGAdapter, "confirm", broken_confirm), patch.object(
        FakePGAdapter, "query_status", broken_query_status
    ):
        response = _confirm(client, access, payment["order_id"], payment_key="k")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "requested"

    # 기존 동작 불변 — payment_key를 안 보내도(기존 호출부와 동일) 여전히 정상
    # 승인된다.
    access2, contest2 = _draft_contest(
        client, uid="sponsor-payment-key-omitted", category=category, deliverable_type=landing_type
    )
    payment2 = _initiate_payment(client, access2, contest2["id"])
    response2 = _confirm(client, access2, payment2["order_id"])
    assert response2.status_code == 200
    assert response2.json()["status"] == "paid"


@pytest.mark.django_db
def test_webhook_for_unknown_order_id_is_rejected(client):
    response = _send_webhook(
        client, webhook_id="wh-unknown-1", order_id=str(uuid4()), status="paid"
    )
    assert response.status_code == 404


@pytest.mark.django_db
def test_initiating_payment_twice_is_idempotent(client, category, landing_type):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)

    first = _initiate_payment(client, access, contest["id"])
    second = _initiate_payment(client, access, contest["id"])

    assert first["order_id"] == second["order_id"]
    assert Payment.objects.filter(contest_id=contest["id"]).count() == 1


# --- 웹훅 서명 검증 (#9 리뷰 지적 2) -------------------------------------------


@pytest.mark.django_db
def test_unsigned_webhook_is_rejected_and_ledger_untouched(client, category, landing_type):
    """서명이 없으면(빈 문자열) Sponsor가 자기 order_id로 "paid"를 위조해도
    원장에는 아무 것도 남지 않는다."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    forged = _send_webhook(
        client,
        webhook_id="wh-forged-1",
        order_id=payment["order_id"],
        status="paid",
        signature="",
    )
    assert forged.status_code == 401

    payment_row = Payment.objects.get(order_id=payment["order_id"])
    assert payment_row.status == Payment.Status.REQUESTED

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.DRAFT

    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{contest_row.ledger_id}/entries").json()
    assert entries == []


@pytest.mark.django_db
def test_wrongly_signed_webhook_is_rejected_and_ledger_untouched(client, category, landing_type):
    """서명이 있어도 비밀키를 모르고 만든 값이면 여전히 거부된다."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    forged = _send_webhook(
        client,
        webhook_id="wh-forged-2",
        order_id=payment["order_id"],
        status="paid",
        signature="not-the-real-signature",
    )
    assert forged.status_code == 401

    payment_row = Payment.objects.get(order_id=payment["order_id"])
    assert payment_row.status == Payment.Status.REQUESTED

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.DRAFT

    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{contest_row.ledger_id}/entries").json()
    assert entries == []

    # 정상 서명을 붙이면(이번엔 실제로 결제가 확정된다) 그대로 확정 경로를 탄다
    # — 서명 검증 자체가 정상 흐름을 막지 않는다는 것도 함께 증명한다.
    genuine = _send_webhook(
        client, webhook_id="wh-forged-2-retry", order_id=payment["order_id"], status="paid"
    )
    assert genuine.status_code == 200

    contest_row.refresh_from_db()
    assert contest_row.status == Contest.Status.PUBLISHED


# --- 동시 결제 시작 (#9 리뷰 지적 3) --------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_concurrent_initiate_payment_creates_only_one_active_payment(
    django_db_blocker, category, landing_type
):
    """두 요청이 동시에 같은 Contest에 결제를 시작해도 활성 Payment는 하나만
    남아야 한다 — Contest 행 잠금(select_for_update)과
    unique_active_payment_per_contest 부분 유니크 제약이 함께 막는다.

    `test_initiating_payment_twice_is_idempotent`는 순차 호출만 검증하므로
    이 테스트는 실제 스레드 두 개로 동시에 쏴서 락 없이는 재현되지 않는 경합을
    직접 만든다. `transaction=True`라야 각 스레드가 자기 DB 커넥션으로 진짜
    커밋을 주고받아 select_for_update가 실제로 대기·직렬화한다.
    """

    from django.db import connections
    from django.test import Client

    with django_db_blocker.unblock():
        setup_client = Client()
        access, contest = _draft_contest(
            setup_client, category=category, deliverable_type=landing_type
        )

        results: list = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                with django_db_blocker.unblock():
                    local_client = Client()
                    barrier.wait()
                    response = local_client.post(
                        PAYMENTS_URL,
                        data={"contest_id": contest["id"]},
                        content_type="application/json",
                        **_auth_header(access),
                    )
                    results.append(response)
            finally:
                # 스레드마다 독립된 DB 커넥션을 새로 여는데, 스레드가 끝나도 그
                # 커넥션은 Django가 자동으로 닫아주지 않는다 — 닫지 않으면
                # 테스트 DB 정리(DROP DATABASE) 시점에 "다른 세션이 접속 중"
                # 경고·경합이 남는다.
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 2
        for response in results:
            assert response.status_code == 201, response.content

        order_ids = {response.json()["order_id"] for response in results}
        assert len(order_ids) == 1  # 둘 다 같은 결제를 가리켜야 한다.

        active = Payment.objects.filter(
            contest_id=contest["id"], status__in=[Payment.Status.REQUESTED, Payment.Status.PAID]
        )
        assert active.count() == 1


# --- 위젯 vs 즉시 확정 — PG 어댑터 모드가 가른다, 클라이언트 키가 아니다 (#112) ---


@pytest.mark.django_db
def test_checkout_flow_is_direct_for_fake_adapter_mode(client, category, landing_type):
    """dev/test 기본값(PAYMENT_ADAPTER_MODE=fake)에서는 브라우저가 위젯 없이
    곧바로 확정한다 — 기존 e2e가 그 경로로 끝까지 걸어야 한다(#112 인수조건)."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)

    payment = _initiate_payment(client, access, contest["id"])

    assert payment["checkout_flow"] == "direct"


@pytest.mark.django_db
def test_checkout_flow_is_widget_for_a_real_adapter_mode(client, category, landing_type):
    """PAYMENT_ADAPTER_MODE가 dotted path(=fake가 아닌)를 가리키면 브라우저가
    위젯을 거쳐야 한다는 신호를 받는다 — **클라이언트 키의 유무가 아니라
    이 설정값 자체**가 가른다(#112 인수조건). `_DottedPathTestPGAdapter`는
    `FakePGAdapter`를 상속해 동작은 fake와 같지만 클래스명이 "Fake"로
    시작하지 않으므로 `is_fake_adapter_binding`이 이 값을 fake로 보지
    않는다 — #83이 이미 이 구분을 위해 쓰는 것과 같은 더블이다."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)

    with override_settings(
        PAYMENT_ADAPTER_MODE="tests.test_payments._DottedPathTestPGAdapter"
    ):
        payment = _initiate_payment(client, access, contest["id"])

    assert payment["checkout_flow"] == "widget"


# --- 확정 금액은 브라우저가 아니라 Payment 행에서 온다 (#112) ------------------


@pytest.mark.django_db
def test_confirm_ignores_amount_claimed_by_the_browser(client, category, landing_type):
    """브라우저가 confirm 요청 본문에 실제와 다른 amount를 실어 보내도 결과가
    달라지지 않는다 — 확정에 쓰이는 금액은 언제나 이 Payment 행의
    `total_amount`다(#112 인수조건). `ConfirmPaymentIn`에는 애초에 `amount`
    필드가 없으므로 이 값은 스키마 파싱 단계에서부터 버려진다 — 이 테스트는
    "필드가 없다"는 사실이 아니라 "그 값을 실어 보내도 원장·상태가 정확한
    금액으로만 남는다"는 관찰 가능한 결과를 고정한다."""

    access, contest = _draft_contest(
        client, prize=1_000_000, category=category, deliverable_type=landing_type
    )
    payment = _initiate_payment(client, access, contest["id"])

    forged_amount = payment["total_amount"] + 999_000_000
    response = client.post(
        f"{PAYMENTS_URL}/{payment['order_id']}/confirm",
        data={"payment_key": "widget-key-forged-amount", "amount": forged_amount},
        content_type="application/json",
        **_auth_header(access),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "paid"
    assert response.json()["total_amount"] == payment["total_amount"]

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert len(entries) == 1
    lines_by_account = {
        line["account"]: (line["side"], line["amount"]) for line in entries[0]["lines"]
    }
    listing_fee = get_current_policy().contest_listing_fee
    # forged_amount가 아니라 실제 총액(prize + 개최 등록비)만 원장에 남는다.
    assert lines_by_account["sponsor_deposit"] == ("debit", 1_000_000 + listing_fee)


# --- 확정 경로가 둘이어도 한 번만 반영된다 — 순서를 뒤집어도 (#114) ------------


@pytest.mark.django_db
def test_confirm_arriving_first_then_webhook_still_lands_paid_with_single_ledger_entry(
    client, category, landing_type
):
    """리다이렉트(동기 confirm)가 먼저 도착하고, 그 뒤 웹훅이 같은 order_id로
    다시 통지해도 원장에는 한 번만 반영된다 — 웹훅이 먼저 오는 경우
    (`test_webhook_arriving_before_confirm_response_still_lands_correct_state`)
    는 이미 있으니, 순서를 뒤집은 이 경우도 같은 자리로 수렴한다는 것을
    고정한다(#114 인수조건 — "웹훅이 먼저 와도, 리다이렉트가 먼저 와도
    최종 상태가 같다")."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    confirm = _confirm(client, access, payment["order_id"], payment_key="widget-key-order-1")
    assert confirm.status_code == 200
    assert confirm.json()["status"] == "paid"

    webhook = _send_webhook(
        client, webhook_id="wh-confirm-first-1", order_id=payment["order_id"], status="paid"
    )
    assert webhook.status_code == 200

    ledger_id = Contest.objects.get(id=contest["id"]).ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert len(entries) == 1  # 두 채널이 경합해도 분개는 한 번만.

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.PUBLISHED

    payment_row = Payment.objects.get(order_id=payment["order_id"])
    assert payment_row.status == Payment.Status.PAID


# --- 실패 웹훅도 같은 자리로 수렴한다 — 리다이렉트 없이 웹훅만 (#114) ----------


@pytest.mark.django_db
def test_failed_webhook_alone_leaves_contest_draft_with_no_ledger_entries(
    client, category, landing_type
):
    """리다이렉트가 전혀 오지 않아도(사용자가 결제 직후 브라우저를 닫았거나
    애초에 위젯에서 실패해 우리 화면으로 돌아오지 못한 경우) 실패 웹훅만으로
    Payment가 종결되고 Contest는 draft에 머문다 — "돈은 안 들어왔는데
    공모전은 공개돼 있다" 같은 어긋난 상태가 남지 않는다(#114 인수조건)."""

    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)
    payment = _initiate_payment(client, access, contest["id"])

    webhook = _send_webhook(
        client, webhook_id="wh-failed-alone-1", order_id=payment["order_id"], status="failed"
    )
    assert webhook.status_code == 200
    assert webhook.json()["status"] == "failed"

    payment_row = Payment.objects.get(order_id=payment["order_id"])
    assert payment_row.status == Payment.Status.FAILED

    contest_row = Contest.objects.get(id=contest["id"])
    assert contest_row.status == Contest.Status.DRAFT

    ledger_id = contest_row.ledger_id
    _login_operator(client)
    entries = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries").json()
    assert entries == []

    # 실패로 종결된 뒤에도 같은 Contest로 결제를 다시 시작할 수 있다 — 새
    # Payment(새 order_id)가 만들어진다.
    retry = _initiate_payment(client, access, contest["id"])
    assert retry["order_id"] != payment["order_id"]


# --- admin (#9 리뷰 지적 6) ----------------------------------------------------


# admin 의 Payment 추가 폼이 NOT NULL 위반 500 을 내지 않는지 지키던 테스트가 여기
# 있었다. #46 이 admin 을 내리면서 그 폼 자체가 존재하지 않게 됐다 — 막으려던 실패
# 방식이 도달 불가능해졌으므로 함께 지운다.


# --- 어댑터 선택이 resolve_adapter를 쓴다 (#83) --------------------------------


class _DottedPathTestPGAdapter(FakePGAdapter):
    """`PAYMENT_ADAPTER_MODE`에 dotted path로 지목됐을 때 실제로 이 클래스가
    쓰인다는 것을 증명하기 위한 테스트 전용 더블(#83).

    나머지 동작(confirm/refund 등)은 `FakePGAdapter`를 그대로 물려받고,
    `request_payment`의 checkout_url에만 이 클래스만 낼 수 있는 마커를 남긴다 —
    `PAYMENT_ADAPTER_MODE="fake"`였다면 절대 나올 수 없는 값이므로, HTTP 응답
    본문만으로 `resolve_adapter`가 "fake" 별칭이 아니라 이 dotted path를 실제로
    import해 썼다는 것을 확인할 수 있다.
    """

    def request_payment(self, *, order_id: str, amount: int) -> PaymentRequestResult:
        return PaymentRequestResult(
            order_id=order_id,
            checkout_url=f"https://dotted-path-marker.test/checkout/{order_id}",
        )


@pytest.mark.django_db
def test_payment_adapter_mode_resolves_a_dotted_path_to_a_real_class(
    client, category, landing_type
):
    access, contest = _draft_contest(client, category=category, deliverable_type=landing_type)

    with override_settings(
        PAYMENT_ADAPTER_MODE="tests.test_payments._DottedPathTestPGAdapter"
    ):
        payment = _initiate_payment(client, access, contest["id"])

    assert payment["checkout_url"] == (
        f"https://dotted-path-marker.test/checkout/{payment['order_id']}"
    )
