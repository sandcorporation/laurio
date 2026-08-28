"""유찰 재개최 — 복제 + source_contest_id (#22, ADR-0001).

참여자 0명으로 유찰(#17이 전액 환불)된 Contest를 Sponsor가 복제해 Prize와 마감만
새로 지정한다. 요구사항·DeliverableType·Category·제목·설명은 원본에서 그대로
복제되고, 새 Contest는 `source_contest_id`로 원본을 가리키는 별개의 행이라 결제·
제출·원장 이력이 원본과 절대 섞이지 않는다. 실패 경로(아직 마감 전, 참여자가 있어
환불되지 않음, 소유자가 아님, 본인확인 실패)를 먼저 두껍게 증명한다.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType, Requirement
from core.models import ClockOverride
from payments.models import Payment
from verification.models import Verification

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
        "username": "reopen-operator",
        "email": "reopen-operator@example.com",
        "password": "operator-pw-1234",
        "is_staff": True,
    }
    defaults.update(kwargs)
    return get_user_model().objects.create_user(**defaults)


def _login_operator(client, **kwargs):
    user = _make_operator(**kwargs)
    assert client.login(username=user.username, password="operator-pw-1234")
    return user


def _as_operator(client) -> None:
    _login_operator(client, username=f"op-{uuid.uuid4().hex[:8]}", email=f"{uuid.uuid4().hex[:8]}@example.com")


def _ledger_entries(client, ledger_id) -> list:
    _as_operator(client)
    response = client.get(f"{LEDGER_URL}/contests/{ledger_id}/entries")
    assert response.status_code == 200
    return response.json()


def _sign(*, webhook_id: str, order_id: str, status: str) -> str:
    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _send_webhook(client, *, webhook_id: str, order_id: str, status: str):
    body = {
        "webhook_id": webhook_id,
        "order_id": order_id,
        "status": status,
        "signature": _sign(webhook_id=webhook_id, order_id=order_id, status=status),
    }
    return client.post(f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json")


def _run_refunds(client, *, simulate: str | None = None):
    return client.post(
        RUN_REFUNDS_URL,
        data={"simulate": simulate} if simulate is not None else {},
        content_type="application/json",
        **_internal_headers(),
    )


# --- Contest 개최 · 결제 · 마감 · 유찰(환불) 헬퍼 -------------------------------


def _create_draft_contest(
    client,
    sponsor,
    *,
    category,
    deliverable_type,
    deadline_at,
    title="원본 공모전",
    description="원본 설명",
    prize=1_000_000,
    requirements=None,
) -> dict:
    response = client.post(
        CONTESTS_URL,
        data={
            "title": title,
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
            "description": description,
            "prize": prize,
            "deadline_at": deadline_at.isoformat(),
            "requirements": requirements or [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert response.status_code == 200, response.content
    return response.json()


def _pay_and_publish(client, sponsor, contest_id: int) -> dict:
    payment_resp = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest_id},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert payment_resp.status_code == 201
    payment = payment_resp.json()

    webhook_id = f"wh-{contest_id}-{uuid.uuid4().hex}"
    webhook_resp = _send_webhook(
        client, webhook_id=webhook_id, order_id=payment["order_id"], status="paid"
    )
    assert webhook_resp.status_code == 200
    return payment


def _close_via_tick(client, *, at) -> None:
    _freeze(at)
    response = client.post(TICK_URL, **_internal_headers())
    assert response.status_code == 200


def _lapsed_contest(
    client,
    *,
    category,
    deliverable_type,
    sponsor_uid="sponsor-1",
    sponsor_ci="sponsor-ci-1",
    title="원본 공모전",
    description="원본 설명",
    prize=1_000_000,
    requirements=None,
) -> tuple[dict, dict]:
    """참여자 0명으로 유찰(마감 + 전액 환불)된 Contest를 만들어 (sponsor, contest)로
    돌려준다."""

    sponsor = _verified_user(client, sponsor_uid, sponsor_ci)
    deadline = timezone.now() + timedelta(hours=1)
    contest = _create_draft_contest(
        client,
        sponsor,
        category=category,
        deliverable_type=deliverable_type,
        deadline_at=deadline,
        title=title,
        description=description,
        prize=prize,
        requirements=requirements,
    )
    _pay_and_publish(client, sponsor, contest["id"])
    _close_via_tick(client, at=deadline + timedelta(minutes=1))

    scan = _run_refunds(client)
    assert scan.json()["count"] == 1

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}", **_auth_header(sponsor["access"]))
    assert detail.status_code == 200
    contest = detail.json()
    assert contest["status"] == "closed"

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


def _reopen(client, access: str, contest_id: int, *, prize: int, deadline_at):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/reopen",
        data={"prize": prize, "deadline_at": deadline_at.isoformat()},
        content_type="application/json",
        **_auth_header(access),
    )


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 핵심 경로 -----------------------------------------------------------------


@pytest.mark.django_db
def test_lapsed_contest_can_be_reopened_with_new_prize_and_deadline(client, category, landing_type):
    sponsor, original = _lapsed_contest(client, category=category, deliverable_type=landing_type)
    new_deadline = timezone.now() + timedelta(days=14)

    response = _reopen(client, sponsor["access"], original["id"], prize=2_000_000, deadline_at=new_deadline)

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["id"] != original["id"]
    assert body["source_contest_id"] == original["id"]
    assert body["prize"] == 2_000_000
    assert body["status"] == "draft"


@pytest.mark.django_db
def test_reopened_contest_copies_requirements_deliverable_types_category_and_text(
    client, category, landing_type
):
    requirements = [
        {"text": "로그인 기능이 있어야 한다", "grade": "required"},
        {"text": "다크모드를 지원하면 좋다", "grade": "optional"},
    ]
    sponsor, original = _lapsed_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        title="원본 제목",
        description="원본 설명입니다",
        requirements=requirements,
    )
    new_deadline = timezone.now() + timedelta(days=14)

    response = _reopen(client, sponsor["access"], original["id"], prize=1_500_000, deadline_at=new_deadline)
    assert response.status_code == 200, response.content
    body = response.json()

    assert body["title"] == "원본 제목"
    assert body["description"] == "원본 설명입니다"
    assert body["category"]["id"] == category.id
    assert [dt["id"] for dt in body["deliverable_types"]] == [landing_type.id]

    copied = [(r["text"], r["grade"], r["order"]) for r in body["requirements"]]
    assert copied == [
        ("로그인 기능이 있어야 한다", "required", 0),
        ("다크모드를 지원하면 좋다", "optional", 1),
    ]

    # 새 Requirement 행은 원본과 완전히 다른 pk를 가진 별개의 레코드다.
    original_requirement_ids = set(
        Requirement.objects.filter(contest_id=original["id"]).values_list("id", flat=True)
    )
    new_requirement_ids = {r["id"] for r in body["requirements"]}
    assert original_requirement_ids.isdisjoint(new_requirement_ids)


@pytest.mark.django_db
def test_reopened_contest_is_visible_via_get_with_source_contest_id(client, category, landing_type):
    sponsor, original = _lapsed_contest(client, category=category, deliverable_type=landing_type)
    new_deadline = timezone.now() + timedelta(days=14)

    reopen_resp = _reopen(client, sponsor["access"], original["id"], prize=1_000_000, deadline_at=new_deadline)
    new_id = reopen_resp.json()["id"]

    detail = client.get(f"{CONTESTS_URL}/{new_id}", **_auth_header(sponsor["access"]))
    assert detail.status_code == 200
    assert detail.json()["source_contest_id"] == original["id"]


# --- 실패 경로 -----------------------------------------------------------------


@pytest.mark.django_db
def test_reopen_requires_authentication(client, category, landing_type):
    sponsor, original = _lapsed_contest(client, category=category, deliverable_type=landing_type)
    new_deadline = timezone.now() + timedelta(days=14)

    response = client.post(
        f"{CONTESTS_URL}/{original['id']}/reopen",
        data={"prize": 1_000_000, "deadline_at": new_deadline.isoformat()},
        content_type="application/json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_stranger_cannot_reopen_someone_elses_contest(client, category, landing_type):
    sponsor, original = _lapsed_contest(client, category=category, deliverable_type=landing_type)
    stranger = _verified_user(client, "stranger-1", "stranger-ci-1")
    new_deadline = timezone.now() + timedelta(days=14)

    response = _reopen(client, stranger["access"], original["id"], prize=1_000_000, deadline_at=new_deadline)

    assert response.status_code == 403


@pytest.mark.django_db
def test_reopening_nonexistent_contest_is_404(client, category, landing_type):
    sponsor = _verified_user(client, "sponsor-404", "sponsor-404-ci")
    new_deadline = timezone.now() + timedelta(days=14)

    response = _reopen(client, sponsor["access"], 999_999, prize=1_000_000, deadline_at=new_deadline)

    assert response.status_code == 404


@pytest.mark.django_db
def test_still_published_contest_cannot_be_reopened(client, category, landing_type):
    sponsor = _verified_user(client, "sponsor-pub", "sponsor-pub-ci")
    deadline = timezone.now() + timedelta(days=7)
    contest = _create_draft_contest(
        client, sponsor, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _pay_and_publish(client, sponsor, contest["id"])
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.PUBLISHED

    response = _reopen(
        client, sponsor["access"], contest["id"], prize=1_000_000, deadline_at=timezone.now() + timedelta(days=14)
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_draft_contest_that_was_never_published_cannot_be_reopened(client, category, landing_type):
    sponsor = _verified_user(client, "sponsor-draft", "sponsor-draft-ci")
    deadline = timezone.now() + timedelta(days=7)
    contest = _create_draft_contest(
        client, sponsor, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.DRAFT

    response = _reopen(
        client, sponsor["access"], contest["id"], prize=1_000_000, deadline_at=timezone.now() + timedelta(days=14)
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_closed_contest_with_a_submission_was_never_refunded_and_cannot_be_reopened(
    client, category, landing_type
):
    sponsor = _verified_user(client, "sponsor-won", "sponsor-won-ci")
    deadline = timezone.now() + timedelta(hours=1)
    contest = _create_draft_contest(
        client, sponsor, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _pay_and_publish(client, sponsor, contest["id"])

    dev = _verified_user(client, "dev-won", "dev-won-ci")
    _submit(client, dev["access"], contest["id"])

    _close_via_tick(client, at=deadline + timedelta(minutes=1))
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    # 참여자가 있으므로 환불 스캔은 이 Contest를 건드리지 않는다(#17).
    scan = _run_refunds(client)
    assert scan.json()["count"] == 0
    assert Payment.objects.get(contest_id=contest["id"]).status == Payment.Status.PAID

    response = _reopen(
        client, sponsor["access"], contest["id"], prize=1_000_000, deadline_at=timezone.now() + timedelta(days=14)
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_reopen_rejects_non_positive_prize(client, category, landing_type):
    sponsor, original = _lapsed_contest(client, category=category, deliverable_type=landing_type)

    response = _reopen(
        client, sponsor["access"], original["id"], prize=0, deadline_at=timezone.now() + timedelta(days=14)
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_reopen_requires_verification_even_for_the_original_owner(client, category, landing_type):
    """본인확인 상태가 그 사이 더 이상 유효하지 않게 됐다면(예: 재확인 실패로
    underage 판정) 원래 소유자라도 재개최를 거부한다 — create_contest와 같은
    관문을 재사용한다."""

    sponsor, original = _lapsed_contest(client, category=category, deliverable_type=landing_type)
    Verification.objects.filter(user_id=sponsor["user_id"]).update(
        status=Verification.Status.UNDERAGE
    )

    response = _reopen(
        client, sponsor["access"], original["id"], prize=1_000_000, deadline_at=timezone.now() + timedelta(days=14)
    )

    assert response.status_code == 403


# --- 이력 분리 -----------------------------------------------------------------


@pytest.mark.django_db
def test_original_and_reopened_contest_histories_never_mix(client, category, landing_type):
    sponsor, original = _lapsed_contest(client, category=category, deliverable_type=landing_type, prize=1_000_000)
    new_deadline = timezone.now() + timedelta(days=14)

    reopen_resp = _reopen(
        client, sponsor["access"], original["id"], prize=3_000_000, deadline_at=new_deadline
    )
    assert reopen_resp.status_code == 200
    new_contest = reopen_resp.json()

    # 새 Contest는 원본과 다른 ledger_id를 받는다 — 원장 이력이 물리적으로 분리된다.
    original_ledger_id = Contest.objects.get(id=original["id"]).ledger_id
    new_ledger_id = Contest.objects.get(id=new_contest["id"]).ledger_id
    assert original_ledger_id != new_ledger_id

    # 새 Contest에 결제를 새로 걸어도 원본의 원장·Payment는 그대로다.
    _pay_and_publish(client, sponsor, new_contest["id"])

    original_entries = _ledger_entries(client, original_ledger_id)
    assert len(original_entries) == 2  # 원본 예치 + 환불 반대 분개, 그 이상 늘지 않는다.

    new_entries = _ledger_entries(client, new_ledger_id)
    assert len(new_entries) == 1  # 새 Contest의 예치 분개 하나뿐.

    assert Payment.objects.filter(contest_id=original["id"]).count() == 1
    assert Payment.objects.filter(contest_id=new_contest["id"]).count() == 1
    assert (
        Payment.objects.get(contest_id=original["id"]).order_id
        != Payment.objects.get(contest_id=new_contest["id"]).order_id
    )
