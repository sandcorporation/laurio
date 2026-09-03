"""Charge(CONTEXT.md)의 확정 경로가 종류와 무관하게 같은 규율을 지키는지 — Prize 결제와
심사 연장비를 같은 시나리오 표로 친다 (#127, #118).

두 종류가 같은 `payments.charges.settle_charge` 를 타므로 시나리오는 한 번만 적고
종류만 parametrize 한다. 웹훅 선행·이중 웹훅은 Prize 결제에만 웹훅이 있어
`test_payments.py` 에 남는다. HTTP 가 유일한 시임이다(CLAUDE.md).
"""

from __future__ import annotations

import threading
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.db import connections
from django.db import transaction as db_transaction
from django.test import Client
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType, JudgingExtensionPayment
from payments.adapters import FakePGAdapter
from payments.models import Payment
from tests import test_judging_period_and_award as ext
from tests import test_payments as prize


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


class PrizeCharge:
    """Sponsor 의 Prize + 개최비 결제 — Contest 는 DRAFT 에서 시작하고, 확정되면 공개된다."""

    name = "prize"
    model = Payment

    @staticmethod
    def setup(client, category, landing_type):
        access, contest = prize._draft_contest(
            client, category=category, deliverable_type=landing_type
        )
        return {"access": access, "contest_id": contest["id"]}

    @staticmethod
    def initiate(client, ctx) -> str:
        return prize._initiate_payment(client, ctx["access"], ctx["contest_id"])["order_id"]

    @staticmethod
    def initiate_raw(client, ctx):
        return client.post(
            prize.PAYMENTS_URL,
            data={"contest_id": ctx["contest_id"]},
            content_type="application/json",
            **prize._auth_header(ctx["access"]),
        )

    @staticmethod
    def confirm(client, ctx, order_id, *, simulate=None):
        return prize._confirm(client, ctx["access"], order_id, simulate=simulate)

    @staticmethod
    def applied(ctx) -> bool:
        return Contest.objects.get(id=ctx["contest_id"]).status == Contest.Status.PUBLISHED


class ExtensionCharge:
    """심사 연장비 — Contest 는 CLOSED(심사 중)에서 시작하고, 확정되면 심사기간이 늘어난다."""

    name = "extension"
    model = JudgingExtensionPayment

    @staticmethod
    def setup(client, category, landing_type):
        deadline = timezone.now() + timedelta(hours=1)
        sponsor, contest = ext._publish_contest(
            client, category=category, deliverable_type=landing_type, deadline_at=deadline
        )
        ext._close_contest(client, contest, deadline=deadline)
        return {"access": sponsor["access"], "sponsor": sponsor, "contest_id": contest["id"]}

    @staticmethod
    def initiate(client, ctx) -> str:
        return ext._initiate_extension(client, ctx["sponsor"], ctx["contest_id"])["order_id"]

    @staticmethod
    def initiate_raw(client, ctx):
        return client.post(
            f"{ext.CONTESTS_URL}/{ctx['contest_id']}/extend-judging-period",
            data={},
            content_type="application/json",
            **ext._auth_header(ctx["access"]),
        )

    @staticmethod
    def confirm(client, ctx, order_id, *, simulate=None):
        return ext._confirm_extension(
            client, ctx["sponsor"], ctx["contest_id"], order_id, simulate=simulate
        )

    @staticmethod
    def applied(ctx) -> bool:
        return Contest.objects.get(id=ctx["contest_id"]).judging_extension_count == 1


KINDS = [PrizeCharge, ExtensionCharge]
KIND_IDS = [k.name for k in KINDS]


def _charge(kind, order_id):
    return kind.model.objects.get(order_id=order_id)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_timeout_then_success_is_settled_via_query_and_posts_one_entry(
    client, category, landing_type, kind
):
    ctx = kind.setup(client, category, landing_type)
    order_id = kind.initiate(client, ctx)

    resp = kind.confirm(client, ctx, order_id, simulate="timeout_then_success")
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "paid"

    charge = _charge(kind, order_id)
    assert charge.journal_entry_id is not None
    assert kind.applied(ctx)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_timeout_then_failed_settles_as_failed_with_no_entry(client, category, landing_type, kind):
    ctx = kind.setup(client, category, landing_type)
    order_id = kind.initiate(client, ctx)

    resp = kind.confirm(client, ctx, order_id, simulate="timeout_then_failed")
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "failed"

    assert _charge(kind, order_id).journal_entry_id is None
    assert not kind.applied(ctx)


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_timeout_then_query_failure_leaves_charge_requested_not_500(
    client, category, landing_type, kind
):
    """재확인 자체가 죽으면 실패로 단정하지 않는다 — 미확정으로 남아 웹훅·재시도가 확정한다
    (#87 지적 3·4, #125)."""

    ctx = kind.setup(client, category, landing_type)
    order_id = kind.initiate(client, ctx)

    real_query = FakePGAdapter.query_status

    def _boom(self, *, order_id):
        raise RuntimeError("PG 조회 API 가 500 을 냈다")

    with patch.object(FakePGAdapter, "query_status", _boom):
        resp = kind.confirm(client, ctx, order_id, simulate="timeout_then_success")
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "requested"
    assert _charge(kind, order_id).journal_entry_id is None
    assert not kind.applied(ctx)

    # 다음 확인이 마저 확정한다.
    FakePGAdapter.query_status = real_query
    resp = kind.confirm(client, ctx, order_id)
    assert resp.status_code == 200
    assert resp.json()["status"] == "paid"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_vendor_decline_settles_as_failed_and_can_be_retried(client, category, landing_type, kind):
    ctx = kind.setup(client, category, landing_type)
    order_id = kind.initiate(client, ctx)

    resp = kind.confirm(client, ctx, order_id, simulate="failed")
    assert resp.status_code == 200, resp.content
    assert resp.json()["status"] == "failed"
    assert not kind.applied(ctx)

    # 실패한 시도는 실패인 채로 남고, 새 시도는 새 order_id 를 받는다.
    retry_order_id = kind.initiate(client, ctx)
    assert retry_order_id != order_id
    assert _charge(kind, order_id).status == "failed"


@pytest.mark.django_db
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_vendor_error_is_502_and_charge_stays_requested(client, category, landing_type, kind):
    """벤더의 명시적 거절(PGError)은 이 Charge 의 문제가 아니라 이 배포의 문제일 수 있다 —
    종결시키지 않고 502 로 드러낸다."""

    ctx = kind.setup(client, category, landing_type)
    order_id = kind.initiate(client, ctx)

    resp = kind.confirm(client, ctx, order_id, simulate="__no_such_scenario__")
    assert resp.status_code == 502, resp.content
    assert _charge(kind, order_id).status == "requested"


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_initiate_calls_pg_outside_the_contest_lock(client, category, landing_type, kind):
    """PG 등록은 Contest 행 잠금을 쥔 atomic 밖에서 부른다 — 벤더가 느리면 그 Contest 의
    모든 쓰기가 멈추고 DB 커넥션을 물고 있게 된다(#57 5차 지적 7, #126, #127).
    `transaction=True` 라야 `in_atomic_block` 이 엔드포인트가 연 블록만을 말한다."""

    ctx = kind.setup(client, category, landing_type)

    seen: list[bool] = []
    real_request_payment = FakePGAdapter.request_payment

    def _observe(self, *, order_id, amount):
        seen.append(db_transaction.get_connection().in_atomic_block)
        return real_request_payment(self, order_id=order_id, amount=amount)

    with patch.object(FakePGAdapter, "request_payment", _observe):
        kind.initiate(client, ctx)
        kind.initiate(client, ctx)  # 재요청(기존 행 재사용 경로)도 마찬가지다.

    assert seen == [False, False], seen


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("kind", KINDS, ids=KIND_IDS)
def test_concurrent_initiate_creates_only_one_active_charge(
    django_db_blocker, category, landing_type, kind
):
    """두 요청이 동시에 같은 Contest 의 결제를 시작해도 활성 Charge 는 하나 — 행 잠금과 부분
    유니크 제약이 함께 막는다. 스레드 둘이 각자 커넥션으로 진짜 커밋을 주고받는다."""

    with django_db_blocker.unblock():
        ctx = kind.setup(Client(), category, landing_type)

        results: list = []
        barrier = threading.Barrier(2)

        def worker():
            try:
                with django_db_blocker.unblock():
                    barrier.wait()
                    results.append(kind.initiate_raw(Client(), ctx))
            finally:
                connections.close_all()

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert [r.status_code for r in results] == [201, 201], [r.content for r in results]
        assert len({r.json()["order_id"] for r in results}) == 1
        assert kind.model.objects.filter(contest_id=ctx["contest_id"], status="requested").count() == 1
