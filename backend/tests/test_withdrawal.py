"""Withdrawal — 신원 파기, 계정 삭제가 아니다 (#100, #101, ADR-0025).

`Withdrawal`은 계정 행을 지우지 않는다. CI·DI·전화번호·표시 이름·소개가
즉시 사라지고, 공개 프로필이 닫히고, 로그인할 수 없게 된다. 거래(결제·지급)
이력이 있는 사람은 실명·생년월일이 `RetainedIdentity`로 옮겨져 남고(#101),
없었던 사람은 전부 즉시 파기된다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from accounts.models import DeveloperProfile, PhoneContact, SponsorProfile, Withdrawal
from accounts.withdrawal import WithdrawalBlockReason
from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from payouts.models import Payout
from verification.models import RetainedIdentity, Verification

WITHDRAWAL_URL = "/api/accounts/withdrawal"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
PAYOUTS_URL = "/api/payouts"
DORMANCY_SCAN_URL = "/api/internal/scans/identity-dormancy-purge"
RETAINED_SCAN_URL = "/api/internal/scans/retained-identity-purge"


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
def test_sponsor_who_already_paid_can_withdraw_and_real_name_is_retained(
    client, category, landing_type
):
    """진행 중인 거래는 이제 없다(Contest가 AWARDED로 끝났다) — 결제 이력이 있는
    Sponsor도 #101부터는 탈퇴할 수 있다. 실명·생년월일은 RetainedIdentity로
    옮겨지고, 원래 자리(Verification)에서는 사라진다(#101 AC)."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="retained-sponsor", dev_uid="retained-dev-1"
    )

    header = _auth_header(sponsor["access"])
    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.json() == {"can_withdraw": True, "blocking_reasons": []}

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 200, response.content

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="retained-sponsor")

    verification = Verification.objects.get(user=user)
    assert verification.status == Verification.Status.WITHDRAWN
    # CI·DI·전화번호는 거래 이력과 무관하게 여전히 즉시 파기된다.
    assert verification.ci_encrypted == ""
    assert verification.di_encrypted == ""
    # 실명·생년월일은 원래 자리에서 사라졌다 — RetainedIdentity로 옮겨졌다.
    assert verification.real_name_encrypted == ""
    assert verification.birth_date_encrypted == ""

    retained = RetainedIdentity.objects.get(user=user)
    assert retained.reason == RetainedIdentity.Reason.SPONSOR_PAID_CONTEST
    assert retained.retained_because_id == contest["id"]
    assert retained.real_name == "사람"  # _verified_user의 기본 실명
    assert retained.birth_date == date(1995, 1, 1)
    assert retained.retained_until > timezone.now()
    # 원문이 평문으로 저장되지 않는다 — Verification과 같은 암호화 방식이다.
    assert "사람" not in retained.real_name_encrypted


@pytest.mark.django_db
def test_developer_with_a_confirmed_payout_can_withdraw_and_real_name_is_retained(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="retained-sponsor-2", dev_uid="retained-dev-2"
    )
    requested = _request_payout(client, dev, contest["id"])
    _confirm_payout(client, dev, requested["idempotency_key"])
    identity_resp = _submit_identity(client, dev, requested["idempotency_key"])
    assert identity_resp.status_code == 200
    payout = Payout.objects.get(idempotency_key=requested["idempotency_key"])
    assert payout.status == Payout.Status.CONFIRMED

    header = _auth_header(dev["access"])
    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.json() == {"can_withdraw": True, "blocking_reasons": []}

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 200, response.content

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="retained-dev-2")
    retained = RetainedIdentity.objects.get(user=user)
    assert retained.reason == RetainedIdentity.Reason.DEVELOPER_CONFIRMED_PAYOUT
    assert retained.retained_because_id == payout.id


@pytest.mark.django_db
def test_never_transacted_vs_transacted_withdrawal_differ_in_what_is_retained(
    client, category, landing_type
):
    """이 스펙의 핵심 대비다 — 거래가 있었던 사람은 실명이 남고, 없었던 사람은
    전부 즉시 파기된다(#101 AC). 같은 테스트에서 둘을 대비시킨다."""

    # 거래가 전혀 없는 사람 — 본인확인만 했다.
    never_pair = _login(client, uid="never-transacted-user")
    never_header = _auth_header(never_pair["access"])
    _verify(client, never_pair["access"], ci="never-transacted-ci", name="한번도안한사람")

    # 거래(결제된 Contest)가 있는 Sponsor.
    transacted_sponsor, _dev, _contest, _submission = _ready_for_payout(
        client, category, landing_type,
        sponsor_uid="differ-sponsor", dev_uid="differ-dev",
    )

    client.post(WITHDRAWAL_URL, content_type="application/json", **never_header)
    client.post(
        WITHDRAWAL_URL, content_type="application/json", **_auth_header(transacted_sponsor["access"])
    )

    from django.contrib.auth import get_user_model

    User = get_user_model()
    never_user = User.objects.get(social_accounts__provider_uid="never-transacted-user")
    transacted_user = User.objects.get(social_accounts__provider_uid="differ-sponsor")

    # 거래가 없었던 사람 — RetainedIdentity 행 자체가 생기지 않는다.
    assert not RetainedIdentity.objects.filter(user=never_user).exists()
    assert Verification.objects.get(user=never_user).real_name_encrypted == ""

    # 거래가 있었던 사람 — RetainedIdentity가 실명을 들고 남는다.
    assert RetainedIdentity.objects.filter(user=transacted_user).exists()
    assert Verification.objects.get(user=transacted_user).real_name_encrypted == ""


@pytest.mark.django_db
def test_retained_identity_has_no_ci_di_or_phone_columns():
    """CI·DI·전화번호는 RetainedIdentity에 들어갈 칼럼 자체가 없다(#101 AC) —
    자리가 없어야 나중에 채워 넣는 실수를 막는다."""

    field_names = {f.name for f in RetainedIdentity._meta.get_fields()}
    assert "ci_encrypted" not in field_names
    assert "ci_hash" not in field_names
    assert "di_encrypted" not in field_names
    assert "phone_number_encrypted" not in field_names


@pytest.mark.django_db
def test_retained_identity_lives_in_its_own_table_separate_from_verification():
    """살아 있는 신원과 다른 자리(별도 테이블)에 있다 — 같은 테이블에 칼럼만
    늘리지 않았다."""

    assert RetainedIdentity._meta.db_table != Verification._meta.db_table


@pytest.mark.django_db
def test_retained_identity_never_appears_in_any_public_response(client, category, landing_type):
    """RetainedIdentity의 내용이 어떤 공개 API 응답에도 실리지 않는다 — 있는지가
    아니라 없는지를 단언한다(#101 AC)."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="leak-check-sponsor", dev_uid="leak-check-dev"
    )
    client.post(
        WITHDRAWAL_URL, content_type="application/json", **_auth_header(sponsor["access"])
    )

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="leak-check-sponsor")
    retained = RetainedIdentity.objects.get(user=user)
    real_name = retained.real_name

    # 이 Sponsor가 개최한 Contest의 공개 상세 — 실명이 실릴 자리가 없어야 한다.
    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 200
    assert real_name not in detail.content.decode()

    listing = client.get(CONTESTS_URL)
    assert listing.status_code == 200
    assert real_name not in listing.content.decode()


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


# --- #102: 2년 미이용 신원 파기 · 보존 기간 만료 스캔 ------------------------------


def _backdate_activity(user_id: int, verification_id: int, *, to) -> None:
    """휴면 스캔의 후보 쿼리가 보는 두 신호(가입 시각·본인확인 갱신 시각)를 과거로
    되돌린다. `.update()`로 직접 쓴다 — `auto_now`/`auto_now_add`는 `.save()` 호출
    시점에만 개입하므로 이 방법이 유일하게 값을 강제로 앉힌다."""

    from django.contrib.auth import get_user_model

    get_user_model().objects.filter(id=user_id).update(date_joined=to)
    Verification.objects.filter(id=verification_id).update(updated_at=to)


@pytest.mark.django_db
def test_dormant_verified_account_has_identity_purged_but_account_and_submission_remain(
    client,
):
    """2년간 행위가 없던 계정의 신원이 파기되지만, 계정·프로필은 그대로 남는다
    (#102 AC) — Withdrawal과 달리 로그인도 그대로 된다."""

    pair = _login(client, uid="dormant-user")
    header = _auth_header(pair["access"])
    _verify(client, pair["access"], ci="dormant-ci", name="오래안온사람", phone="010-2222-3333")
    client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "오래된닉네임"},
        content_type="application/json",
        **header,
    )

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="dormant-user")
    verification = Verification.objects.get(user=user)
    long_ago = timezone.now() - timedelta(days=365 * 3)
    _backdate_activity(user.id, verification.id, to=long_ago)

    _freeze(timezone.now())
    resp = client.post(DORMANCY_SCAN_URL, **_internal_headers())
    assert resp.status_code == 200, resp.content
    body = resp.json()
    assert body["count"] == 1
    assert [r["user_id"] for r in body["rows"]] == [user.id]

    verification.refresh_from_db()
    assert verification.status == Verification.Status.EXPIRED
    assert verification.ci_encrypted == ""
    assert verification.di_encrypted == ""
    assert verification.real_name_encrypted == ""
    assert verification.birth_date_encrypted == ""
    assert not PhoneContact.objects.filter(user=user).exists()

    # 계정·프로필·로그인은 그대로다.
    user.refresh_from_db()
    assert user.is_active is True
    developer = DeveloperProfile.objects.get(user=user)
    assert developer.display_name == "오래된닉네임"  # Withdrawal과 달리 지워지지 않는다.

    me = client.get("/api/accounts/me", **header)
    assert me.status_code == 200  # 이미 발급된 토큰으로도 여전히 로그인 상태다.


@pytest.mark.django_db
def test_dormancy_boundary_just_under_and_at_two_years(client):
    """경계값 — 막 2년이 된 것과 아직 안 된 것을 같은 테스트에서 대비시킨다(#102 AC)."""

    from accounts.dormancy import DORMANCY_PERIOD
    from django.contrib.auth import get_user_model

    pair = _login(client, uid="boundary-user")
    header = _auth_header(pair["access"])
    _verify(client, pair["access"], ci="boundary-ci", name="경계값사람")

    user = get_user_model().objects.get(social_accounts__provider_uid="boundary-user")
    verification = Verification.objects.get(user=user)
    last_activity = timezone.now() - timedelta(days=1)
    _backdate_activity(user.id, verification.id, to=last_activity)

    # 아직 2년이 안 됐다 — 파기되지 않는다.
    _freeze(last_activity + DORMANCY_PERIOD - timedelta(days=1))
    resp = client.post(DORMANCY_SCAN_URL, **_internal_headers())
    assert resp.status_code == 200
    assert resp.json()["count"] == 0
    verification.refresh_from_db()
    assert verification.status == Verification.Status.VERIFIED

    # 막 2년이 됐다 — 파기된다.
    _freeze(last_activity + DORMANCY_PERIOD)
    resp = client.post(DORMANCY_SCAN_URL, **_internal_headers())
    assert resp.status_code == 200
    assert resp.json()["count"] == 1
    verification.refresh_from_db()
    assert verification.status == Verification.Status.EXPIRED


@pytest.mark.django_db
def test_dormant_sponsor_with_past_transaction_retains_real_name(client, category, landing_type):
    """거래 이력이 있었던 사람이 2년 미이용으로 파기돼도, 실명은 Withdrawal과 같은
    규칙(RetainedIdentity)으로 남는다."""

    sponsor, dev, contest, submission = _ready_for_payout(
        client, category, landing_type, sponsor_uid="dormant-sponsor", dev_uid="dormant-dev"
    )

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="dormant-sponsor")
    verification = Verification.objects.get(user=user)
    long_ago = timezone.now() - timedelta(days=365 * 3)
    _backdate_activity(user.id, verification.id, to=long_ago)
    # 개최 자체도 "행위"다(휴면 후보 쿼리의 Greatest) — 그 Contest를 만든 시각도 함께
    # 되돌려야 "그 뒤로 2년간 아무 것도 안 했다"는 시나리오가 성립한다.
    Contest.objects.filter(id=contest["id"]).update(created_at=long_ago)

    _freeze(timezone.now())
    resp = client.post(DORMANCY_SCAN_URL, **_internal_headers())
    assert resp.status_code == 200
    assert resp.json()["count"] == 1

    retained = RetainedIdentity.objects.get(user=user)
    assert retained.reason == RetainedIdentity.Reason.SPONSOR_PAID_CONTEST
    assert retained.retained_because_id == contest["id"]

    verification.refresh_from_db()
    assert verification.real_name_encrypted == ""


@pytest.mark.django_db
def test_expired_retained_identity_is_purged_and_unexpired_one_remains(client):
    """보존 기간이 지난 RetainedIdentity가 사라지고, 안 지난 것은 남는다(#102 AC)."""

    from django.contrib.auth import get_user_model

    User = get_user_model()
    expired_user = User.objects.create_user(username="retained-expired", email="a@example.test")
    fresh_user = User.objects.create_user(username="retained-fresh", email="b@example.test")

    now = timezone.now()
    expired = RetainedIdentity(
        user=expired_user,
        reason=RetainedIdentity.Reason.SPONSOR_PAID_CONTEST,
        retained_because_id=1,
        retained_until=now - timedelta(days=1),
    )
    expired.real_name = "만료된사람"
    expired.birth_date = date(1990, 1, 1)
    expired.save()

    fresh = RetainedIdentity(
        user=fresh_user,
        reason=RetainedIdentity.Reason.DEVELOPER_CONFIRMED_PAYOUT,
        retained_because_id=2,
        retained_until=now + timedelta(days=1),
    )
    fresh.real_name = "아직남은사람"
    fresh.birth_date = date(1991, 1, 1)
    fresh.save()

    _freeze(now)
    resp = client.post(RETAINED_SCAN_URL, **_internal_headers())
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 1
    assert [r["retained_identity_id"] for r in body["rows"]] == [expired.id]

    assert not RetainedIdentity.objects.filter(id=expired.id).exists()
    assert RetainedIdentity.objects.filter(id=fresh.id).exists()


@pytest.mark.django_db
def test_purge_scan_is_idempotent(client):
    """스캔이 두 번 돌아도 같은 결과다 — 이미 파기된 것을 다시 파기하려 하지
    않는다(#102 AC)."""

    pair = _login(client, uid="idempotent-user")
    header = _auth_header(pair["access"])
    _verify(client, pair["access"], ci="idempotent-ci", name="두번스캔사람")

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="idempotent-user")
    verification = Verification.objects.get(user=user)
    long_ago = timezone.now() - timedelta(days=365 * 3)
    _backdate_activity(user.id, verification.id, to=long_ago)

    _freeze(timezone.now())
    first = client.post(DORMANCY_SCAN_URL, **_internal_headers())
    assert first.status_code == 200
    assert first.json()["count"] == 1

    second = client.post(DORMANCY_SCAN_URL, **_internal_headers())
    assert second.status_code == 200
    assert second.json()["count"] == 0
    assert client.post(RETAINED_SCAN_URL, **_internal_headers()).json()["count"] == 0


@pytest.mark.django_db
def test_dormancy_scan_isolates_an_account_whose_purge_raises(client):
    """행 하나의 예외가 배치를 막지 않는다(#138) — 그 계정은 `failed` 에 남고(트랜잭션은
    되돌아가 신원이 그대로다) 뒤의 계정은 같은 실행에서 파기된다."""

    from unittest.mock import patch

    from django.contrib.auth import get_user_model

    import accounts.dormancy as dormancy_module

    users = []
    for i in range(2):
        pair = _login(client, uid=f"poison-dormant-{i}")
        _verify(client, pair["access"], ci=f"poison-dormant-{i}-ci", name=f"독약{i}")
        user = get_user_model().objects.get(social_accounts__provider_uid=f"poison-dormant-{i}")
        verification = Verification.objects.get(user=user)
        _backdate_activity(user.id, verification.id, to=timezone.now() - timedelta(days=365 * 3))
        users.append((user, verification))
    (poison_user, poison_verification), (healthy_user, healthy_verification) = users
    _freeze(timezone.now())

    real_basis = dormancy_module._transaction_basis

    def _basis(user):
        if user.id == poison_user.id:
            raise RuntimeError("거래 근거 조회 중 예기치 못한 버그")
        return real_basis(user)

    with patch.object(dormancy_module, "_transaction_basis", _basis):
        resp = client.post(DORMANCY_SCAN_URL, **_internal_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert [f["pk"] for f in body["failed"]] == [poison_verification.id]
    assert [r["user_id"] for r in body["rows"]] == [healthy_user.id]
    poison_verification.refresh_from_db()
    healthy_verification.refresh_from_db()
    assert poison_verification.status == Verification.Status.VERIFIED
    assert poison_verification.ci_encrypted != ""
    assert healthy_verification.status == Verification.Status.EXPIRED


@pytest.mark.django_db
def test_returning_dormant_user_must_reverify_to_host_a_contest(client, category, landing_type):
    """돌아온 사람이 개최를 하려 할 때 본인확인을 다시 요구받는다(#102 AC) — 왜
    다시 하는지 알 수 있는 이유가 함께 온다."""

    pair = _login(client, uid="returning-sponsor")
    header = _auth_header(pair["access"])
    _verify(client, pair["access"], ci="returning-ci", name="돌아온사람")

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(social_accounts__provider_uid="returning-sponsor")
    verification = Verification.objects.get(user=user)
    long_ago = timezone.now() - timedelta(days=365 * 3)
    _backdate_activity(user.id, verification.id, to=long_ago)

    _freeze(timezone.now())
    client.post(DORMANCY_SCAN_URL, **_internal_headers())

    resp = client.post(
        CONTESTS_URL,
        data={
            "title": "돌아와서 여는 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **header,
    )
    assert resp.status_code == 403
    assert "본인확인" in resp.json()["detail"]
