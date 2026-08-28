"""Distribution — 무응답 14일 + Score 컷라인 1/N 배분 (#16, ADR-0003/0004/0006).

핵심 대상:

- 심사기간 종료(JUDGING_ENDED) 후 DISTRIBUTION_WAIT_DAYS(기본 14일)가 지나야
  스캔이 Distribution을 실행한다 — 그 전에는 아무 일도 일어나지 않는다.
- Score 컷라인을 통과한 Submission만 배분 대상이 되고, 컷라인은 DB 조정 가능한
  운영 파라미터다.
- 스캔을 두 번 돌려도 Distribution은 한 번만 만들어진다.
- 1/N 나머지는 단수처리 분개로 명시되고, Contest 원장 합계는 여전히 0이다.
- 배분 중 일부만 성공하면 성공분만 원장에 반영되고 나머지는 재시도 대상으로
  남는다.
- 참여자가 있는데 아무도 컷라인을 넘지 못해도 Prize는 Sponsor에게 돌아가지
  않는다(REQUEST.md "핵심 원칙").
- 기존 payouts 경로(get_or_create_payout/mark_confirmed/mark_failed)를 그대로
  재사용한다 — Payout이 실제로 수수료·원천징수 분개를 남긴다.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from distributions.models import Distribution, DistributionCutline, DistributionShare
from ledger.services import contest_balance, contest_entries
from payouts.models import Payout
from storage.adapters.fake import FakeStorageAdapter

TICK_URL = "/api/internal/tick"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
SCORING_RUN_PENDING_URL = "/api/internal/scoring/run-pending"
DISTRIBUTIONS_RUN_DUE_URL = "/api/internal/distributions/run-due"


# --- 헬퍼 (test_scoring.py/test_handover.py와 같은 형식) ------------------------


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


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


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _submit(
    client, dev: dict, contest_id: int, *, requirement_id: int, grounded: bool
) -> dict:
    """Evidence가 소스에서 실제로 확인되는지(grounded)로 결정적으로 충족/미달을
    만든다(FakeLLMScoringAdapter, ADR-0014).
    """

    source_key = _source_object_key(contest_id, dev["user_id"])
    marker = f"MARKER_{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(
        source_key, _zip_bytes({"app.py": f"# {marker}\n" if grounded else "print('x')\n"})
    )

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
    """CLOSED -> JUDGING_ENDED로 옮긴다(Award 없이 무응답).

    judging_ends_at은 이 Contest 자신의 필드에서 읽는다(#13 관용구) — 스캔
    주기가 아니라 이 행의 실제 값을 근거로 삼는다.
    """

    judging_ends_at = Contest.objects.get(id=contest_id).judging_ends_at
    assert judging_ends_at is not None
    _freeze(judging_ends_at + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest_id).status == Contest.Status.JUDGING_ENDED


def _advance_past_distribution_wait(contest_id: int) -> None:
    judging_ends_at = Contest.objects.get(id=contest_id).judging_ends_at
    _freeze(
        judging_ends_at
        + timedelta(days=settings.DISTRIBUTION_WAIT_DAYS, minutes=1)
    )


def _run_due_distributions(client, *, fail_submission_ids: list[int] | None = None) -> dict:
    response = client.post(
        DISTRIBUTIONS_RUN_DUE_URL,
        data={"fail_submission_ids": fail_submission_ids or []},
        content_type="application/json",
        **_internal_headers(),
    )
    assert response.status_code == 200, response.content
    return response.json()


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


@pytest.fixture(autouse=True)
def _default_cutline(db):
    """모든 테스트가 같은 기본 컷라인(60%)에서 출발하게 한다."""

    DistributionCutline.objects.update_or_create(pk=1, defaults={"minimum_percentage": Decimal("60.00")})


# --- 무응답 14일: 그 전에는 아무 일도 없고, 지나면 배분한다 ------------------------


@pytest.mark.django_db
def test_distribution_does_not_fire_before_wait_period_elapses(client, category, landing_type):
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

    # 심사기간이 막 끝났다 — 아직 무응답 14일이 지나지 않았으므로 스캔해도
    # Distribution이 생기지 않는다.
    result = _run_due_distributions(client)
    assert result["count"] == 0
    assert not Distribution.objects.filter(contest_id=contest["id"]).exists()

    _advance_past_distribution_wait(contest["id"])
    result = _run_due_distributions(client)
    assert any(r["event"] == "distribution_created" for r in result["results"])

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.qualifying_count == 1
    assert distribution.share_amount == 900_000
    share = DistributionShare.objects.get(distribution=distribution)
    assert share.submission_id == submission["id"]


# --- 컷라인: 통과자만 배분 대상, DB로 조정 가능 -----------------------------------


@pytest.mark.django_db
def test_only_submissions_clearing_cutline_receive_shares(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=1_000_000,
    )
    requirement_id = contest["requirements"][0]["id"]

    dev_high = _verified_user(client, "dev-high", "dev-high-ci")
    dev_low = _verified_user(client, "dev-low", "dev-low-ci")
    submission_high = _submit(
        client, dev_high, contest["id"], requirement_id=requirement_id, grounded=True
    )
    submission_low = _submit(
        client, dev_low, contest["id"], requirement_id=requirement_id, grounded=False
    )

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])
    _run_due_distributions(client)

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.qualifying_count == 1
    assert distribution.cutline_waived is False
    shares = list(DistributionShare.objects.filter(distribution=distribution))
    assert len(shares) == 1
    assert shares[0].submission_id == submission_high["id"]
    assert not DistributionShare.objects.filter(submission_id=submission_low["id"]).exists()


@pytest.mark.django_db
def test_cutline_is_a_db_adjustable_operating_parameter(client, category, landing_type):
    """같은 0% 제출작이 컷라인을 낮추면 배분 대상이 된다 — 컷라인이 상수가 아니라
    DB에서 읽는 운영 파라미터라는 증거다.
    """

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=1_000_000,
    )
    requirement_id = contest["requirements"][0]["id"]

    dev_low = _verified_user(client, "dev-low", "dev-low-ci")
    submission_low = _submit(
        client, dev_low, contest["id"], requirement_id=requirement_id, grounded=False
    )

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])

    # 운영자가 admin에서 컷라인을 낮췄다고 가정한다 — DB 행을 직접 조정한다
    # (core.models.ClockOverride를 테스트가 직접 조정하는 것과 같은 관용구).
    DistributionCutline.objects.update_or_create(
        pk=1, defaults={"minimum_percentage": Decimal("0.00")}
    )

    _run_due_distributions(client)

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.qualifying_count == 1
    assert distribution.cutline_percentage == Decimal("0.00")
    assert DistributionShare.objects.filter(submission_id=submission_low["id"]).exists()


# --- 두 번 쏴도 한 번만 -----------------------------------------------------------


@pytest.mark.django_db
def test_running_scan_twice_distributes_exactly_once(client, category, landing_type):
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
    _advance_past_distribution_wait(contest["id"])

    _run_due_distributions(client)
    _run_due_distributions(client)

    assert Distribution.objects.filter(contest_id=contest["id"]).count() == 1
    assert DistributionShare.objects.filter(distribution__contest_id=contest["id"]).count() == 1
    payouts = Payout.objects.filter(distribution_share__distribution__contest_id=contest["id"])
    assert payouts.count() == 1
    assert payouts.first().status == Payout.Status.CONFIRMED_IDENTITY_PENDING


# --- 1/N 나머지는 단수처리 분개로, 원장 합계는 0 ----------------------------------


@pytest.mark.django_db
def test_remainder_is_booked_as_explicit_entry_and_ledger_stays_balanced(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=5_000_000,
    )
    requirement_id = contest["requirements"][0]["id"]

    devs = [_verified_user(client, f"dev-{i}", f"dev-{i}-ci") for i in range(3)]
    for dev in devs:
        _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])
    _run_due_distributions(client)

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.qualifying_count == 3
    assert distribution.share_amount == 1_666_666
    assert distribution.remainder_amount == 2
    assert distribution.remainder_journal_entry_id is not None

    contest_obj = Contest.objects.get(id=contest["id"])
    balance = contest_balance(contest_obj.ledger_id)
    assert balance["is_balanced"] is True

    remainder_entry = next(
        e for e in contest_entries(contest_obj.ledger_id) if e.id == distribution.remainder_journal_entry_id
    )
    lines = {(line.account, line.side): line.amount for line in remainder_entry.lines.all()}
    assert lines[("developer_payable", "debit")] == 2
    assert lines[("platform_fee_revenue", "credit")] == 2

    # 3명 모두 지급까지 자동으로 확정됐다(기본 성공 시나리오) — 원장은 여전히
    # 균형을 유지한다.
    assert (
        Payout.objects.filter(distribution_share__distribution=distribution).count() == 3
    )
    balance_after = contest_balance(contest_obj.ledger_id)
    assert balance_after["is_balanced"] is True


# --- 부분 실패: 성공분만 반영, 실패분은 재시도 대상 -------------------------------


@pytest.mark.django_db
def test_partial_payout_failure_leaves_successes_posted_and_failure_retryable(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=3_000_000,
    )
    requirement_id = contest["requirements"][0]["id"]

    devs = [_verified_user(client, f"dev-{i}", f"dev-{i}-ci") for i in range(3)]
    submissions = [
        _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)
        for dev in devs
    ]

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])

    failing_submission_id = submissions[0]["id"]
    _run_due_distributions(client, fail_submission_ids=[failing_submission_id])

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.share_amount == 1_000_000
    assert distribution.remainder_amount == 0

    failed_payout = Payout.objects.get(
        distribution_share__submission_id=failing_submission_id
    )
    assert failed_payout.status == Payout.Status.FAILED
    assert failed_payout.journal_entry_id is None

    succeeded = Payout.objects.filter(
        distribution_share__distribution=distribution
    ).exclude(distribution_share__submission_id=failing_submission_id)
    assert succeeded.count() == 2
    for payout in succeeded:
        assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
        assert payout.journal_entry_id is not None

    contest_obj = Contest.objects.get(id=contest["id"])
    assert contest_balance(contest_obj.ledger_id)["is_balanced"] is True

    # 다음 스캔이 실패분을 자동으로 재시도한다 — 이번엔 강제 실패를 주지 않는다.
    _run_due_distributions(client)

    retried_payout = Payout.objects.get(
        distribution_share__submission_id=failing_submission_id,
        status=Payout.Status.CONFIRMED_IDENTITY_PENDING,
    )
    assert retried_payout.journal_entry_id is not None
    # 원래 실패했던 시도는 그대로 FAILED로 남아 있다 — 반대 분개나 이력 수정 없이
    # 재시도가 "새 시도"로 남는다.
    assert Payout.objects.filter(
        distribution_share__submission_id=failing_submission_id
    ).count() == 2
    assert contest_balance(contest_obj.ledger_id)["is_balanced"] is True


# --- 참여자가 있으면 컷라인 미달자뿐이어도 Sponsor에게 돌아가지 않는다 -------------


@pytest.mark.django_db
def test_prize_never_returns_to_sponsor_when_nobody_clears_cutline(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=1_000_000,
    )
    requirement_id = contest["requirements"][0]["id"]

    devs = [_verified_user(client, f"dev-{i}", f"dev-{i}-ci") for i in range(2)]
    submissions = [
        _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=False)
        for dev in devs
    ]

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])
    _run_due_distributions(client)

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.cutline_waived is True
    assert distribution.qualifying_count == 2
    submission_ids = {s["id"] for s in submissions}
    share_submission_ids = set(
        DistributionShare.objects.filter(distribution=distribution).values_list(
            "submission_id", flat=True
        )
    )
    assert share_submission_ids == submission_ids

    contest_obj = Contest.objects.get(id=contest["id"])
    assert contest_obj.status == Contest.Status.JUDGING_ENDED
    # Sponsor에게 반환하는 환불류 분개(sponsor_deposit 계정 재입금)가 없다 — 전액이
    # developer_payable 안에서만 이동한다.
    entries = list(contest_entries(contest_obj.ledger_id))
    for entry in entries:
        for line in entry.lines.all():
            assert not (line.account == "sponsor_deposit" and "환불" in entry.memo)


# --- 참여자가 0명이면 이 스캔의 대상이 아니다(#17이 처리) -------------------------


@pytest.mark.django_db
def test_zero_submissions_are_not_distributed_by_this_scan(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])

    result = _run_due_distributions(client)
    assert result["count"] == 0
    assert not Distribution.objects.filter(contest_id=contest["id"]).exists()



# --- 코디네이터 리뷰 회귀 방지: Distribution Payout의 신원 제출·조회, 배치 안전성 ------


PAYOUTS_URL = "/api/payouts"


@pytest.mark.django_db
def test_developer_can_view_and_finalize_distribution_payout(client, category, landing_type):
    """Distribution으로 확정된(CONFIRMED_IDENTITY_PENDING) Payout도 Award 경로와
    똑같이 GET /contests/{id}/payout으로 조회하고 POST /payouts/{key}/identity로
    최종 확정할 수 있어야 한다.

    이전에는 `_get_owned_payout`이 `handover_id is None`인 Payout(=Distribution
    경로 전부)을 무조건 404로 숨겨서, 신원 정보를 제출할 방법 자체가 없어
    지급이 CONFIRMED_IDENTITY_PENDING에 영구히 갇혔다(코디네이터 리뷰 결함 2)."""

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
    _advance_past_distribution_wait(contest["id"])
    _run_due_distributions(client)

    payout = Payout.objects.get(distribution_share__submission_id=submission["id"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING

    get_resp = client.get(f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(dev["access"]))
    assert get_resp.status_code == 200, get_resp.content
    body = get_resp.json()
    assert body["idempotency_key"] == str(payout.idempotency_key)
    assert body["contest_id"] == contest["id"]
    assert body["status"] == "confirmed_identity_pending"
    assert body["has_identity"] is False

    identity_resp = client.post(
        f"{PAYOUTS_URL}/{payout.idempotency_key}/identity",
        data={"resident_registration_number": "9001011234567"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert identity_resp.status_code == 200, identity_resp.content
    assert identity_resp.json()["status"] == "confirmed"

    payout.refresh_from_db()
    assert payout.status == Payout.Status.CONFIRMED

    # 다른 Developer는 이 지급 요청에 접근할 수 없다(소유권 검사가 여전히 산다).
    other_dev = _verified_user(client, "dev-2", "dev-2-ci")
    forbidden = client.get(
        f"{CONTESTS_URL}/{contest['id']}/payout", **_auth_header(other_dev["access"])
    )
    assert forbidden.status_code == 404


@pytest.mark.django_db
def test_one_poisoned_share_does_not_block_other_shares_in_same_scan(
    client, category, landing_type
):
    """한 몫의 지급 시도가 예기치 못한 예외를 던져도(어댑터 버그 등) 같은 스캔
    안의 다른 몫·다른 Contest는 계속 처리돼야 한다 — order_by("id")로 스캔하는
    이상, 예외를 감싸지 않으면 그 몫이 항상 배치 맨 앞에서 다시 걸려 뒤의
    정상 건들이 영원히 처리되지 못하는 poison pill이 된다(코디네이터 리뷰
    결함 4, scoring.services.run_pending_scoring이 이미 겪고 고친 것과 같은
    사고)."""

    from unittest.mock import patch

    from payouts.adapters import FakePayoutAdapter

    deadline = timezone.now() + timedelta(hours=1)
    poison_prize = 111_111
    ok_prize = 222_222

    _, poison_contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=poison_prize,
        sponsor_uid="sponsor-poison",
    )
    poison_requirement_id = poison_contest["requirements"][0]["id"]
    dev_poison = _verified_user(client, "dev-poison", "dev-poison-ci")
    poison_submission = _submit(
        client, dev_poison, poison_contest["id"], requirement_id=poison_requirement_id, grounded=True
    )

    _, ok_contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=ok_prize,
        sponsor_uid="sponsor-ok",
    )
    ok_requirement_id = ok_contest["requirements"][0]["id"]
    dev_ok = _verified_user(client, "dev-ok", "dev-ok-ci")
    ok_submission = _submit(
        client, dev_ok, ok_contest["id"], requirement_id=ok_requirement_id, grounded=True
    )

    for contest in (poison_contest, ok_contest):
        _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    for contest in (poison_contest, ok_contest):
        _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(poison_contest["id"])
    _advance_past_distribution_wait(ok_contest["id"])

    real_request_payout = FakePayoutAdapter.request_payout

    def _maybe_poison(self, *, idempotency_key, amount):
        # amount는 net_amount(수수료·원천징수 공제 후)라 prize와 다르다 — Payout을
        # idempotency_key로 역참조해 어느 Submission의 시도인지 정확히 판별한다.
        # 이 시점에는 이미 get_or_create_payout이 Payout 행을 만들어 둔 뒤다.
        payout = Payout.objects.select_related("distribution_share").get(
            idempotency_key=idempotency_key
        )
        if payout.distribution_share.submission_id == poison_submission["id"]:
            raise RuntimeError("예기치 못한 어댑터 버그")
        return real_request_payout(self, idempotency_key=idempotency_key, amount=amount)

    with patch.object(FakePayoutAdapter, "request_payout", _maybe_poison):
        resp = _run_due_distributions(client)

    events = {r.get("submission_id"): r for r in resp["results"] if "submission_id" in r}
    assert events[poison_submission["id"]]["event"] == "payout_attempt_failed"
    # 포이즌 항목 뒤에 있는(더 큰 id) 정상 항목도 같은 스캔에서 처리됐다 —
    # 배치가 막히지 않았다는 직접적인 증거다.
    assert events[ok_submission["id"]]["event"] == "payout_attempted"
    assert events[ok_submission["id"]]["status"] == "confirmed_identity_pending"

    poison_payout = Payout.objects.get(distribution_share__submission_id=poison_submission["id"])
    assert poison_payout.status == Payout.Status.REQUESTED
    assert poison_payout.journal_entry_id is None

    ok_payout = Payout.objects.get(distribution_share__submission_id=ok_submission["id"])
    assert ok_payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
    assert ok_payout.journal_entry_id is not None

    # 다음 스캔(포이즌 없이)이 실패했던 몫도 정상적으로 마저 확정한다 —
    # 스캔이 살아 있다는 것 자체가 재시도 경로가 죽지 않았다는 증거다.
    resp2 = _run_due_distributions(client)
    assert resp2 is not None
    poison_payout.refresh_from_db()
    assert poison_payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
