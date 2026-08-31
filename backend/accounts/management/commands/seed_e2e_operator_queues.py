"""운영자 앱 07(#65) e2e 전용 — 「할 일」 세 큐에 각각 한 건씩 심는다.

「할 일」 홈은 세 가지를 센다: 심판 대기 이의(appeals?status=pending), 신원 대기
지급(payouts?blocked_on=identity), Seller 대기 지급(payouts?blocked_on=seller).
그 숫자가 맞는지 e2e로 확인하려면 실제로 그 상태에 있는 데이터가 있어야 하고,
그 상태들은 손으로 ORM 행을 조립해서는 안전하게 재현되지 않는다 — 원장 분개·
Escrow 해제·Seller 등록 같은 불변식이 서비스 계층 여러 곳에 걸쳐 있다
(ADR-0003·ADR-0004·ADR-0020). 그래서 `backend/tests/test_appeals.py`·
`backend/tests/test_payouts.py`가 이미 검증해 둔 것과 **같은 HTTP 흐름**을
`django.test.Client`(pytest 없이도 쓸 수 있는 일반 Django 유틸리티)로 그대로
반복한다 — appeals·payouts 앱의 소스를 고치지 않고, 이미 있는 공개 API만 부른다.

멱등하지 않다 — 부를 때마다 새 Contest·Submission·Appeal·Payout이 생긴다(부제·
UID에 타임스탬프를 섞어 충돌을 피한다). 그래서 이 명령을 쓰는 e2e 스펙은 절대
카운트를 고정값으로 단언하지 않고, "부르기 전 baseline 대비 정확히 1씩 늘었다"는
증분으로 검증해야 한다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
PAYOUTS_URL = "/api/payouts"
TICK_URL = "/api/internal/tick"
SCORING_RUN_PENDING_URL = "/api/internal/scoring/run-pending"

# 이 명령이 심은 Contest 는 전부 이 접두어로 시작한다(코드리뷰 지적) — clear_queues()가
# "이 명령이 만든 것"만 골라 지우려면 다른 시드·실사용 데이터와 구별할 표식이
# 필요하다(frontend/e2e/lib/seed.ts, contests/management/commands/
# seed_e2e_contests.py의 title__startswith 관용구와 같은 원칙).
TITLE_PREFIX = "[e2e-op-queue] "


def _internal_headers() -> dict:
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _login(client: Client, uid: str) -> dict:
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{uid}@example.test"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _verify(client: Client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"사람|1995-01-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _verified_user(client: Client, uid: str) -> dict:
    pair = _login(client, uid)
    _verify(client, pair["access"], ci=f"{uid}-ci")
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert me.status_code == 200, me.content
    return {"access": pair["access"], "user_id": me.json()["id"]}


def _sign_payment(*, webhook_id: str, order_id: str, status: str) -> str:
    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _freeze(at) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _unfreeze() -> None:
    # 이 명령은 매번 새 프로세스로 실행되지만 ClockOverride는 DB 행이라 프로세스
    # 경계를 넘어 남는다 — 얼린 채로 끝내면 다음에 이 명령을 부르거나(다른 seed_*
    # 함수가 실시간 기준 마감일을 계산하다 "이미 지났다"로 거부되는 것을 직접
    # 재현했다) 같은 DB를 보는 다른 e2e 스펙까지 조용히 오작동시킨다. 마감을
    # 지나치게 만드는 용도로만 잠깐 얼리고, 쓰자마자 바로 되돌린다.
    ClockOverride.objects.filter(pk=1).delete()


def _category() -> Category:
    category, _ = Category.objects.get_or_create(name="E2E 운영자 큐")
    return category


def _deliverable_type() -> DeliverableType:
    dtype, _ = DeliverableType.objects.get_or_create(
        name="E2E 운영자 큐용 웹서비스", defaults={"minimum_prize": 500_000}
    )
    return dtype


def _publish_contest(client: Client, *, sponsor_uid: str, deadline_at, requirements=None) -> tuple[dict, dict]:
    sponsor = _verified_user(client, sponsor_uid)
    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{TITLE_PREFIX}{sponsor_uid}의 공모전",
            "category_id": _category().id,
            "deliverable_type_ids": [_deliverable_type().id],
            "prize": 1_000_000,
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
    assert payment_resp.status_code == 201, payment_resp.content
    payment = payment_resp.json()

    webhook_id = f"wh-{contest['id']}-{uuid.uuid4().hex}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign_payment(webhook_id=webhook_id, order_id=payment["order_id"], status="paid")
    webhook_resp = client.post(f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json")
    assert webhook_resp.status_code == 200, webhook_resp.content

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    contest = detail.json()
    assert contest["status"] == "published", contest
    return sponsor, contest


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client: Client, dev: dict, contest_id: int, *, requirement_id: int | None = None) -> dict:
    from storage.adapters.fake import FakeStorageAdapter

    source_key = _source_object_key(contest_id, dev["user_id"])
    FakeStorageAdapter().write_object(source_key, b"print('e2e queue seed')\n")

    responses = []
    if requirement_id is not None:
        responses.append({"requirement_id": requirement_id, "is_met": True, "evidence": []})

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={"source_object_key": source_key, "requirement_responses": responses},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _close_contest(client: Client, contest: dict, *, deadline) -> None:
    _freeze(deadline + timedelta(minutes=1))
    try:
        tick_resp = client.post(TICK_URL, **_internal_headers())
        assert tick_resp.status_code == 200, tick_resp.content
        assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED
    finally:
        # 마감을 지나치게 만드는 용도로만 잠깐 얼렸다 — 이후 단계(채점·Award·
        # Handover·지급)는 실시간 기준으로 진행돼야 하고, 이 프로세스가 끝난 뒤에도
        # DB에 남아 다른 e2e 스펙까지 오작동시키면 안 된다(_unfreeze 주석 참고).
        _unfreeze()


def seed_pending_appeal() -> dict:
    """채점까지 끝난 Submission에 이의를 하나 걸어둔다 — /operator/appeals?status=pending에서 보인다."""

    client = Client()
    uid = uuid.uuid4().hex[:8]
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        sponsor_uid=f"e2e-appeal-sponsor-{uid}",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, f"e2e-appeal-dev-{uid}")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id)
    _close_contest(client, contest, deadline=deadline)

    scoring_resp = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
    assert scoring_resp.status_code == 200, scoring_resp.content

    appeal_resp = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": "e2e 큐 시드 — AI가 놓친 근거가 실제로 소스에 있습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert appeal_resp.status_code == 201, appeal_resp.content
    return {"appeal_id": appeal_resp.json()["id"], "contest_id": contest["id"]}


def _ready_for_payout(uid: str) -> tuple[Client, dict, dict, dict]:
    client = Client()
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(client, sponsor_uid=f"e2e-payout-sponsor-{uid}", deadline_at=deadline)
    dev = _verified_user(client, f"e2e-payout-dev-{uid}")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    award_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert award_resp.status_code == 200, award_resp.content

    handover_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(sponsor["access"])
    )
    assert handover_resp.status_code == 200, handover_resp.content

    return client, sponsor, dev, contest


def _request_and_confirm_payout(client: Client, dev: dict, contest_id: int, *, seller_simulate: str | None) -> dict:
    requested = client.post(f"{CONTESTS_URL}/{contest_id}/payout", **_auth_header(dev["access"]))
    assert requested.status_code == 201, requested.content
    idempotency_key = requested.json()["idempotency_key"]

    body: dict = {}
    if seller_simulate is not None:
        body["seller_simulate"] = seller_simulate
    confirm_resp = client.post(
        f"{PAYOUTS_URL}/{idempotency_key}/confirm",
        data=body,
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert confirm_resp.status_code == 200, confirm_resp.content
    return confirm_resp.json()


def seed_identity_pending_payout() -> dict:
    """확정됐지만 신원(주민등록번호) 대기 — /operator/payouts?blocked_on=identity에서 보인다."""

    uid = uuid.uuid4().hex[:8]
    client, _sponsor, dev, contest = _ready_for_payout(uid)
    result = _request_and_confirm_payout(client, dev, contest["id"], seller_simulate=None)
    assert result["status"] == "confirmed_identity_pending", result
    return {"idempotency_key": result["idempotency_key"], "contest_id": contest["id"]}


def seed_seller_pending_payout() -> dict:
    """확정됐지만 Seller 등록 대기 — /operator/payouts?blocked_on=seller에서 보인다."""

    uid = uuid.uuid4().hex[:8]
    client, _sponsor, dev, contest = _ready_for_payout(uid)
    result = _request_and_confirm_payout(client, dev, contest["id"], seller_simulate="review_required")
    assert result["status"] == "confirmed_seller_pending", result
    return {"idempotency_key": result["idempotency_key"], "contest_id": contest["id"]}


def clear_queues() -> dict:
    """세 큐를 이 명령이 심은 데이터에 한해서만 빈 상태로 되돌린다 — "0건은
    0건이라고 명시적으로 말한다"는 인수조건(#65)을 e2e로 확인하려면 실제로 0인
    상태가 필요하다.

    **삭제 범위는 이 명령이 만든 Contest(TITLE_PREFIX)로만 좁힌다**(코드리뷰
    지적) — 애초의 "status가 pending/대기 상태인 건 전부"는 다른 시드나 실제
    운영 데이터까지 함께 지울 수 있는 너무 넓은 조건이었다. `manage.py
    seed_dev_data`가 만든 Appeal·Payout이나, 이 명령을 모르는 다른 체인의 e2e
    데이터는 절대 건드리지 않는다.

    Payout을 지우면 TaxIdentity·PayoutWebhookDelivery가 CASCADE로 함께 지워진다
    (payouts/models.py) — 원장 분개(journal_entry_id)는 FK가 아니라 그대로 남지만,
    이 명령이 만든 Contest·Payout에 한정된 삭제라 감사 기록 보존을 신경 쓸
    대상이 아니다.
    """
    from appeals.models import Appeal
    from payouts.models import Payout

    appeals_deleted, _ = Appeal.objects.filter(
        status="pending", submission__contest__title__startswith=TITLE_PREFIX
    ).delete()
    payouts_deleted, _ = Payout.objects.filter(
        status__in=[Payout.Status.CONFIRMED_IDENTITY_PENDING, Payout.Status.CONFIRMED_SELLER_PENDING],
        handover__award__contest__title__startswith=TITLE_PREFIX,
    ).delete()
    return {"appeals_deleted": appeals_deleted, "payouts_deleted": payouts_deleted}


def _refuse_in_deployed_environment() -> None:
    # 이 명령은 실제 Contest·Payment·Payout을 만들고(--clear는 그것도 모자라
    # 지운다) 운영 이미지에 그대로 들어간다 — ADR-0019가 Django admin을 내린
    # 이유(행을 직접 편집·삭제할 수 있으면 감사 추적에 우회로가 남는다)가 여기도
    # 그대로 적용된다. dev·CI(IS_DEPLOYED_ENVIRONMENT가 아닌 곳)에서만 돈다 —
    # config/settings.py의 다른 배포 가드들과 같은 판정 기준이다.
    if settings.IS_DEPLOYED_ENVIRONMENT:
        raise CommandError(
            f"LAURIO_DEPLOYMENT_TARGET={settings.LAURIO_DEPLOYMENT_TARGET} 인데 "
            "이 명령을 실행하려 했다 — seed_e2e_operator_queues 는 e2e 전용이라 "
            "배포 환경에서 실행할 수 없다(실제 데이터를 만들거나 지운다)."
        )


class Command(BaseCommand):
    help = "운영자 앱 「할 일」 세 큐(심판 대기 이의·신원 대기 지급·Seller 대기 지급)에 한 건씩 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--only",
            choices=["appeal", "identity", "seller"],
            default=None,
            help="지정하면 그 하나만 심는다. 생략하면 셋 다 심는다.",
        )
        parser.add_argument(
            "--clear",
            action="store_true",
            help="심지 않고 이 명령이 심은 데이터만 빈 상태로 되돌린다(다른 옵션과 함께 쓰지 않는다).",
        )

    def handle(self, *args, **options) -> None:
        _refuse_in_deployed_environment()

        if options.get("clear"):
            result = clear_queues()
            self.stdout.write(json.dumps(result))
            return

        only = options.get("only")
        result: dict = {}

        if only in (None, "appeal"):
            result["appeal"] = seed_pending_appeal()
        if only in (None, "identity"):
            result["identity_pending_payout"] = seed_identity_pending_payout()
        if only in (None, "seller"):
            result["seller_pending_payout"] = seed_seller_pending_payout()

        # 명령이 마지막 줄에 JSON 한 덩어리만 찍는다 — 다른 seed_e2e_* 명령과 같은 관용구.
        self.stdout.write(json.dumps(result))
