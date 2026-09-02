"""Withdrawal — 신원 파기, 계정 삭제가 아니다 (#100, ADR-0025).

`Withdrawal`은 계정 행을 지우지 않는다. CI·DI·전화번호·표시 이름·소개가
즉시 사라지고, 공개 프로필이 닫히고, 로그인할 수 없게 된다. 이 티켓(#100)은
거래(결제·지급) 이력이 있는 사람을 아직 통째로 막는다 — 실명을 남길 자리
(RetainedIdentity)가 없기 때문이다. 그 제한은 #101이 푼다.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from accounts.models import DeveloperProfile, PhoneContact, SponsorProfile, Withdrawal
from accounts.withdrawal import WithdrawalBlockReason
from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from payouts.models import Payout
from verification.models import Verification

WITHDRAWAL_URL = "/api/accounts/withdrawal"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
PAYOUTS_URL = "/api/payouts"


# --- 헬퍼 (test_payouts.py와 같은 관용구) ---------------------------------------


def _login(client, uid="wd-user", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _fake_token(name, birth_iso, ci, di=None, phone=None) -> str:
    di = di or f"{ci}-di"
    if phone:
        return f"{name}|{birth_iso}|{ci}|{di}|{phone}"
    return f"{name}|{birth_iso}|{ci}|{di}"


def _verify(client, access: str, *, ci: str, name="사람", birth="1995-01-01", phone=None) -> dict:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": _fake_token(name, birth, ci, phone=phone)},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content
    assert response.json()["status"] == "verified"
    return response.json()


def _verified_user(client, uid: str, ci: str, *, phone=None) -> dict:
    pair = _login(client, uid=uid)
    _verify(client, pair["access"], ci=ci, phone=phone)
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert me.status_code == 200
    return {"access": pair["access"], "user_id": me.json()["id"], "uid": uid}


def _freeze(at):
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _unfreeze():
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": None})


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _sign_payment(webhook_id: str, order_id: str, status: str) -> str:
    import hashlib
    import hmac

    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _publish_contest(
    client, *, category, deliverable_type, sponsor, deadline_at, prize=1_000_000, title=None
) -> dict:
    import uuid

    response = client.post(
        CONTESTS_URL,
        data={
            "title": title or f"{sponsor['uid']}의 공모전",
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
    assert payment_resp.status_code == 201, payment_resp.content
    payment = payment_resp.json()

    webhook_id = f"wh-{contest['id']}-{uuid.uuid4().hex}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign_payment(webhook_id, payment["order_id"], "paid")
    webhook_resp = client.post(
        f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json"
    )
    assert webhook_resp.status_code == 200, webhook_resp.content

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    contest = detail.json()
    assert contest["status"] == "published"
    return contest


def _submit(client, dev: dict, contest_id: int) -> dict:
    import uuid

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "source_object_key": f"submission:{contest_id}:{dev['user_id']}:source/{uuid.uuid4().hex}",
            "requirement_responses": [],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _close_contest(client, contest_id: int, *, deadline) -> None:
    _freeze(deadline + timedelta(minutes=1))
    tick_resp = client.post("/api/internal/tick", **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest_id).status == Contest.Status.CLOSED


def _award(client, sponsor: dict, contest_id: int, submission_id: int) -> dict:
    resp = client.post(
        f"{CONTESTS_URL}/{contest_id}/award",
        data={"submission_id": submission_id},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 200, resp.content
    return resp.json()


def _accept_handover(client, sponsor: dict, contest_id: int) -> dict:
    resp = client.post(
        f"{CONTESTS_URL}/{contest_id}/handover/accept", **_auth_header(sponsor["access"])
    )
    assert resp.status_code == 200, resp.content
    return resp.json()


def _ready_for_payout(client, category, landing_type, *, sponsor_uid, dev_uid, prize=1_000_000):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor = _verified_user(client, sponsor_uid, f"{sponsor_uid}-ci")
    sponsor["uid"] = sponsor_uid
    contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, sponsor=sponsor,
        deadline_at=deadline, prize=prize,
    )
    dev = _verified_user(client, dev_uid, f"{dev_uid}-ci")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest["id"], deadline=deadline)
    _award(client, sponsor, contest["id"], submission["id"])
    _accept_handover(client, sponsor, contest["id"])
    return sponsor, dev, contest, submission


def _request_payout(client, dev: dict, contest_id: int) -> dict:
    resp = client.post(f"{CONTESTS_URL}/{contest_id}/payout", **_auth_header(dev["access"]))
    assert resp.status_code == 201, resp.content
    return resp.json()


def _confirm_payout(client, dev: dict, idempotency_key: str):
    return client.post(
        f"{PAYOUTS_URL}/{idempotency_key}/confirm",
        data={},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )


def _submit_identity(client, dev: dict, idempotency_key: str, rrn="9001011234567"):
    return client.post(
        f"{PAYOUTS_URL}/{idempotency_key}/identity",
        data={"resident_registration_number": rrn},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )


@pytest.fixture
def category(db):
    return Category.objects.create(name="탈퇴테스트")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 인증 -----------------------------------------------------------------------


@pytest.mark.django_db
def test_withdrawal_endpoints_require_authentication(client):
    assert client.get(WITHDRAWAL_URL).status_code == 401
    assert client.post(WITHDRAWAL_URL, content_type="application/json").status_code == 401


# --- 콘솔에서 닿기 · 화면이 읽을 판정 --------------------------------------------


@pytest.mark.django_db
def test_account_with_no_history_can_withdraw_immediately(client):
    """진행 중인 거래도, 거래 이력도 없는 사람은 클릭 한 번으로 탈퇴가 끝난다."""

    pair = _login(client, uid="clean-user")
    header = _auth_header(pair["access"])

    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.status_code == 200
    assert eligibility.json() == {"can_withdraw": True, "blocking_reasons": []}

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 200, response.content
    assert response.json()["withdrawn_at"] is not None

    user = client.get("/api/accounts/me", **header)
    assert user.status_code == 401  # 방금 준 토큰도 그 자리에서 즉시 무효화된다 — 유예 없음.


@pytest.mark.django_db
def test_withdrawal_erases_ci_di_phone_display_name_and_bio_but_keeps_verification_row(client):
    pair = _login(client, uid="full-identity-user")
    header = _auth_header(pair["access"])
    _verify(client, pair["access"], ci="erase-me-ci", name="지워질사람", phone="010-1234-5678")

    profile_resp = client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "지워질닉네임", "bio": "지워질소개"},
        content_type="application/json",
        **header,
    )
    assert profile_resp.status_code == 200

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="full-identity-user")
    assert PhoneContact.objects.filter(user=user).exists()

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 200, response.content

    verification = Verification.objects.get(user=user)
    # 행은 남는다 — "신원이 파기된 계정"과 "한 번도 확인하지 않은 계정"이
    # 구별되어야 파기 이행 여부를 셀 수 있다.
    assert verification.status == Verification.Status.WITHDRAWN
    assert verification.ci_encrypted == ""
    assert verification.ci_hash == ""
    assert verification.di_encrypted == ""
    assert verification.real_name_encrypted == ""
    assert verification.birth_date_encrypted == ""

    assert not PhoneContact.objects.filter(user=user).exists()

    developer = DeveloperProfile.objects.get(user=user)
    assert developer.display_name == ""
    assert developer.bio == ""

    assert Withdrawal.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_unverified_account_withdrawal_leaves_no_verification_row(client):
    """본인확인을 한 번도 안 한 사람은 지울 신원 자체가 없다 — Verification 행이
    생기지 않는다. '신원이 파기된 계정'과 '한 번도 확인하지 않은 계정'이 이렇게
    구별된다."""

    pair = _login(client, uid="never-verified-user")
    header = _auth_header(pair["access"])

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 200, response.content

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="never-verified-user")
    assert not Verification.objects.filter(user=user).exists()


@pytest.mark.django_db
def test_withdrawal_has_no_grace_period(client):
    """신청과 동시에 실행된다 — 대기 상태가 없다."""

    pair = _login(client, uid="no-grace-user")
    header = _auth_header(pair["access"])

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 200

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="no-grace-user")
    assert user.is_active is False
    assert Withdrawal.objects.get(user=user).withdrawn_at is not None


# --- 로그인 차단 ------------------------------------------------------------------


@pytest.mark.django_db
def test_withdrawn_account_cannot_log_in_again(client):
    pair = _login(client, uid="relogin-user", email="relogin@example.com")
    header = _auth_header(pair["access"])
    client.post(WITHDRAWAL_URL, content_type="application/json", **header)

    retry = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": "relogin-user:relogin@example.com"},
        content_type="application/json",
    )
    assert retry.status_code == 403


@pytest.mark.django_db
def test_existing_access_token_is_invalidated_the_moment_withdrawal_completes(client):
    pair = _login(client, uid="live-token-user")
    header = _auth_header(pair["access"])

    before = client.get("/api/accounts/me", **header)
    assert before.status_code == 200

    client.post(WITHDRAWAL_URL, content_type="application/json", **header)

    after = client.get("/api/accounts/me", **header)
    assert after.status_code == 401


# --- 공개 프로필이 닫힌다 · 참가작은 이름 없이 남는다 -----------------------------


@pytest.mark.django_db
def test_developer_public_profile_closes_after_withdrawal(client):
    pair = _login(client, uid="public-profile-dev")
    header = _auth_header(pair["access"])
    client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "공개돼있던이름", "bio": "공개소개"},
        content_type="application/json",
        **header,
    )

    developer = DeveloperProfile.objects.get(
        user__social_accounts__provider_uid="public-profile-dev"
    )

    before = client.get(f"/api/developers/{developer.id}/profile")
    assert before.status_code == 200
    assert before.json()["display_name"] == "공개돼있던이름"

    client.post(WITHDRAWAL_URL, content_type="application/json", **header)

    after = client.get(f"/api/developers/{developer.id}/profile")
    assert after.status_code == 404
    assert "공개돼있던이름" not in after.content.decode()


@pytest.mark.django_db
def test_withdrawn_developers_submission_shows_no_name_to_sponsor(client, category, landing_type):
    """탈퇴한 Developer의 참가작은 남지만 이름은 사라진다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor = _verified_user(client, "compare-sponsor", "compare-sponsor-ci")
    sponsor["uid"] = "compare-sponsor"
    contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, sponsor=sponsor,
        deadline_at=deadline,
    )

    dev = _verified_user(client, "compare-dev", "compare-dev-ci")
    dev_header = _auth_header(dev["access"])
    client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "정든이름"},
        content_type="application/json",
        **dev_header,
    )
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest["id"], deadline=deadline)

    client.post(WITHDRAWAL_URL, content_type="application/json", **dev_header)

    resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/compare", **_auth_header(sponsor["access"])
    )
    assert resp.status_code == 200, resp.content
    body = resp.json()
    names = {s["developer_display_name"] for s in body["submissions"]}
    assert "정든이름" not in names
    assert submission["id"] in [s["submission_id"] for s in body["submissions"]]


# --- 진행 중인 거래가 있으면 거부한다 ---------------------------------------------


@pytest.mark.django_db
def test_sponsor_with_published_contest_is_blocked(client, category, landing_type):
    sponsor = _verified_user(client, "blocked-sponsor", "blocked-sponsor-ci")
    header = _auth_header(sponsor["access"])
    _publish_contest(
        client, category=category, deliverable_type=landing_type,
        sponsor={**sponsor, "uid": "blocked-sponsor"},
        deadline_at=timezone.now() + timedelta(days=3),
    )

    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.status_code == 200
    body = eligibility.json()
    assert body["can_withdraw"] is False
    assert body["blocking_reasons"] == [WithdrawalBlockReason.SPONSOR_CONTEST_IN_PROGRESS.value]

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 409
    assert response.json()["blocking_reasons"] == [
        WithdrawalBlockReason.SPONSOR_CONTEST_IN_PROGRESS.value
    ]

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="blocked-sponsor")
    assert user.is_active is True  # 거부된 요청은 아무것도 바꾸지 않는다.


@pytest.mark.django_db
def test_developer_with_in_progress_payout_is_blocked(client, category, landing_type):
    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="payout-sponsor", dev_uid="payout-dev"
    )
    _request_payout(client, dev, contest["id"])

    header = _auth_header(dev["access"])
    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.json()["blocking_reasons"] == [
        WithdrawalBlockReason.DEVELOPER_PAYOUT_IN_PROGRESS.value
    ]

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 409


@pytest.mark.django_db
def test_sponsor_who_already_paid_for_a_now_finished_contest_is_blocked_by_retention_gap(
    client, category, landing_type
):
    """진행 중인 거래는 이제 없지만(Contest가 AWARDED로 끝났다) 결제 이력이 있는
    Sponsor는 #100에서는 막힌 채로 남는다 — 실명을 남길 자리가 아직 없다. 사유는
    정확히 하나(RETENTION_NOT_YET_SUPPORTED)다."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="retained-sponsor", dev_uid="retained-dev-1"
    )

    header = _auth_header(sponsor["access"])
    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.json() == {
        "can_withdraw": False,
        "blocking_reasons": [WithdrawalBlockReason.RETENTION_NOT_YET_SUPPORTED.value],
    }

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 409
    assert response.json()["blocking_reasons"] == [
        WithdrawalBlockReason.RETENTION_NOT_YET_SUPPORTED.value
    ]


@pytest.mark.django_db
def test_developer_with_a_confirmed_payout_is_blocked_by_retention_gap(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="retained-sponsor-2", dev_uid="retained-dev-2"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])
    identity_resp = _submit_identity(client, dev, requested["idempotency_key"])
    assert identity_resp.status_code == 200
    assert Payout.objects.get(idempotency_key=requested["idempotency_key"]).status == (
        Payout.Status.CONFIRMED
    )

    header = _auth_header(dev["access"])
    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.json() == {
        "can_withdraw": False,
        "blocking_reasons": [WithdrawalBlockReason.RETENTION_NOT_YET_SUPPORTED.value],
    }


# --- 상태 목록 자체를 순회한다 ----------------------------------------------------


@pytest.mark.django_db
def test_every_contest_status_is_classified_as_blocking_or_not(client, caplog):
    """새 `Contest.Status`가 생겨도 조용히 어느 분기에도 안 걸리지 않는다 — fail-closed
    로 걸리면 최소한 ERROR 로 드러난다."""

    from accounts.withdrawal import _is_blocking_contest_status

    expected_blocking = {
        Contest.Status.DRAFT: False,
        Contest.Status.PUBLISHED: True,
        Contest.Status.CLOSED: True,
        Contest.Status.AWARDED: False,
        Contest.Status.JUDGING_ENDED: False,
    }
    assert set(expected_blocking) == set(Contest.Status)  # 이 테스트 자체가 최신 목록을 안다.

    with caplog.at_level("ERROR", logger="accounts.withdrawal"):
        for status, expected in expected_blocking.items():
            assert _is_blocking_contest_status(status) is expected, status

    assert not caplog.records


@pytest.mark.django_db
def test_every_payout_status_is_classified_as_blocking_or_not(caplog):
    from accounts.withdrawal import _is_blocking_payout_status

    expected_blocking = {
        Payout.Status.REQUESTED: True,
        Payout.Status.CONFIRMED_IDENTITY_PENDING: True,
        Payout.Status.CONFIRMED_SELLER_PENDING: True,
        Payout.Status.CONFIRMED: False,
        Payout.Status.FAILED: False,
    }
    assert set(expected_blocking) == set(Payout.Status)

    with caplog.at_level("ERROR", logger="accounts.withdrawal"):
        for status, expected in expected_blocking.items():
            assert _is_blocking_payout_status(status) is expected, status

    assert not caplog.records


@pytest.mark.django_db
def test_unknown_status_fails_closed_and_logs_error(caplog):
    """분류 함수 자체가 모르는 값을 만나면 통과시키지 않는다 — 안전한 쪽(막는다)을
    고르고 ERROR를 남긴다."""

    from accounts.withdrawal import _is_blocking_contest_status, _is_blocking_payout_status

    with caplog.at_level("ERROR", logger="accounts.withdrawal"):
        assert _is_blocking_contest_status("no-such-status") is True
        assert _is_blocking_payout_status("no-such-status") is True

    assert len(caplog.records) == 2


# --- 파기된 신원이 공개 API 응답 어디에도 실리지 않는다 ---------------------------


@pytest.mark.django_db
def test_destroyed_identity_never_appears_in_any_public_response(client):
    pair = _login(client, uid="leak-check-user")
    header = _auth_header(pair["access"])
    _verify(client, pair["access"], ci="leak-check-ci", name="흘리면안되는이름")
    client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "흘리면안되는닉네임"},
        content_type="application/json",
        **header,
    )
    developer = DeveloperProfile.objects.get(user__social_accounts__provider_uid="leak-check-user")

    client.post(WITHDRAWAL_URL, content_type="application/json", **header)

    profile_resp = client.get(f"/api/developers/{developer.id}/profile")
    assert profile_resp.status_code == 404
    assert "흘리면안되는이름" not in profile_resp.content.decode()
    assert "흘리면안되는닉네임" not in profile_resp.content.decode()
