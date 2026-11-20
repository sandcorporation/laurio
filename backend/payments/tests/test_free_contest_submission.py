"""무료 공모전 제출 — 누구나 본인확인 없이 소스 열람에 동의하고 낸다
(#416, ADR-0048).

HTTP 시임만 쓴다(CLAUDE.md). 개최는 `tests/test_free_contest_hosting.py`가
이미 검증한 흐름(개최 권한 → 무료 개최 → 공개)을 그대로 재사용한다.
"""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from contests.models import Category, Contest, ContestSubmission, DeliverableType

ORIGIN = "http://testserver"
PERMISSIONS_URL = "/api/operator/hosting-permissions"
CONTESTS_URL = "/api/contests"
PW = "operator-pw-9942-xkcd-privacy"

pytestmark = pytest.mark.django_db


# --- 헬퍼 --------------------------------------------------------------------


def _operator_client(username, *, superuser=True):
    call_command("create_operator", username, password=PW, superuser=superuser)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": PW},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _login(client, uid="dev-1", email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _hosted_user(client, uid: str) -> dict:
    pair = _login(client, uid=uid)
    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(email=f"{uid}@example.com")
    # 표시 이름이 없으면 공개(무료)·결제 시작(유료)이 422로 막힌다(#447) —
    # 이 파일은 개최자·참가자 양쪽에 이 헬퍼를 함께 쓰므로 항상 채워 둔다.
    profile_resp = client.post(
        "/api/accounts/sponsor-profile",
        data={"display_name": f"{uid} 개최자"},
        content_type="application/json",
        **{"HTTP_AUTHORIZATION": f"Bearer {pair['access']}"},
    )
    assert profile_resp.status_code == 200, profile_resp.content
    return {"access": pair["access"], "user_id": user.id}


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _grant(operator_client, user_id: int, *, reason="테스트 개최 권한"):
    response = operator_client.post(
        f"{PERMISSIONS_URL}/{user_id}",
        data={"granted": True, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=ORIGIN,
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일-제출")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지-제출", minimum_prize=500_000)


def _free_published_contest(
    client,
    *,
    host_uid="free-sub-host",
    deadline_at=None,
    category,
    landing_type,
    require_demo_video=False,
    require_screenshot=False,
) -> tuple[dict, dict]:
    host = _hosted_user(client, host_uid)
    root = _operator_client(f"root-{host_uid}")
    _grant(root, host["user_id"])

    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))
    draft = client.post(
        f"{CONTESTS_URL}/free",
        data={
            "title": f"{host_uid}의 무료 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "require_demo_video": require_demo_video,
            "require_screenshot": require_screenshot,
            "description": "",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [{"text": "할 일을 추가·완료할 수 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(host["access"]),
    ).json()

    published = client.post(
        f"{CONTESTS_URL}/{draft['id']}/publish",
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert published.status_code == 200, published.content

    return host, published.json()


def _source_asset(contest_id: int, user_id: int) -> dict:
    return {
        "kind": "source",
        "value": f"submission:{contest_id}:{user_id}:source/{uuid4().hex}",
    }


# --- 제출: 본인확인 없이, 동의가 필요하다 --------------------------------------


def test_unverified_user_submits_to_a_free_contest_with_consent(client, category, landing_type):
    _host, contest = _free_published_contest(client, category=category, landing_type=landing_type)
    dev = _hosted_user(client, "free-sub-dev-1")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["source_access_consent_at"] is not None

    stored = ContestSubmission.objects.get(id=body["id"])
    assert stored.source_access_consent_at is not None


def test_submission_is_rejected_when_required_screenshot_is_missing(client, category, landing_type):
    _host, contest = _free_published_contest(
        client,
        category=category,
        landing_type=landing_type,
        host_uid="free-required-screenshot",
        require_screenshot=True,
    )
    assert contest["require_screenshot"] is True
    dev = _hosted_user(client, "free-required-screenshot-dev")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 422, response.content
    assert "스크린샷" in response.json()["detail"]
    assert not ContestSubmission.objects.filter(contest_id=contest["id"]).exists()


def test_submitting_without_consent_is_422(client, category, landing_type):
    _host, contest = _free_published_contest(client, category=category, landing_type=landing_type)
    dev = _hosted_user(client, "free-sub-dev-noconsent")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": False,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 422, response.content
    assert ContestSubmission.objects.filter(contest_id=contest["id"]).count() == 0


def test_submitting_with_consent_omitted_defaults_to_false_and_is_rejected(
    client, category, landing_type
):
    _host, contest = _free_published_contest(client, category=category, landing_type=landing_type)
    dev = _hosted_user(client, "free-sub-dev-omitted")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 422, response.content


def test_updating_a_free_submission_requires_consent_again(client, category, landing_type):
    _host, contest = _free_published_contest(client, category=category, landing_type=landing_type)
    dev = _hosted_user(client, "free-sub-dev-update")

    create_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert create_resp.status_code == 201
    first_consent_at = create_resp.json()["source_access_consent_at"]

    reject_resp = client.put(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": False,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert reject_resp.status_code == 422, reject_resp.content

    update_resp = client.put(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert update_resp.status_code == 200, update_resp.content
    assert update_resp.json()["source_access_consent_at"] is not None
    # 동의 시각은 매 제출/수정마다 새로 찍힌다.
    assert update_resp.json()["source_access_consent_at"] != first_consent_at


def test_free_contest_submission_does_not_require_verification_endpoint_at_all(
    client, category, landing_type
):
    """참가자가 `/api/verification/*`를 한 번도 부르지 않아도 낼 수 있다는 것을
    직접 증명한다 — Verification 행 자체가 없다."""

    _host, contest = _free_published_contest(client, category=category, landing_type=landing_type)
    dev = _hosted_user(client, "free-sub-dev-no-verification-call")

    from verification.models import Verification

    assert not Verification.objects.filter(user_id=dev["user_id"]).exists()

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    assert not Verification.objects.filter(user_id=dev["user_id"]).exists()


def test_host_can_also_submit_without_self_dealing_check_since_free_has_no_ci(
    client, category, landing_type
):
    """무료 공모전은 본인확인(CI) 자체가 없어 자전거래 검사가 성립하지 않는다
    — 개최자 본인이 제출해도(설계상 막을 이유가 없다, 유료의 CI 비교와
    달리 이 검사가 아예 걸리지 않는다는 것만 확인한다) 500이 아니라
    정상적으로 처리된다."""

    host, contest = _free_published_contest(client, category=category, landing_type=landing_type)

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], host["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(host["access"]),
    )
    assert response.status_code == 201, response.content


# --- 유료 공모전 회귀: 제출은 여전히 본인확인을 요구한다 -----------------------


def _verified_paid_contest(client, category, landing_type):
    sponsor = _hosted_user(client, "paid-sub-sponsor")
    verify_resp = client.post(
        "/api/verification/verify",
        data={"verification_token": "사람|1990-01-01|paid-sub-sponsor-ci|paid-sub-sponsor-ci-di"},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert verify_resp.status_code == 200

    create_resp = client.post(
        CONTESTS_URL,
        data={
            "title": "유료 공모전 — 제출 회귀",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [{"text": "할 일을 추가·완료할 수 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    ).json()

    payment_resp = client.post(
        "/api/payments",
        data={"contest_id": create_resp["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert payment_resp.status_code == 201
    payment = payment_resp.json()

    import hashlib
    import hmac

    from django.conf import settings

    webhook_id = f"wh-{create_resp['id']}-{uuid4().hex}"
    canonical = f"{webhook_id}:{payment['order_id']}:paid".encode("utf-8")
    signature = hmac.new(
        settings.PAYMENT_WEBHOOK_SECRET.encode("utf-8"), canonical, hashlib.sha256
    ).hexdigest()
    webhook_resp = client.post(
        "/api/payments/webhook",
        data={
            "webhook_id": webhook_id,
            "order_id": payment["order_id"],
            "status": "paid",
            "signature": signature,
        },
        content_type="application/json",
    )
    assert webhook_resp.status_code == 200

    detail = client.get(f"{CONTESTS_URL}/{create_resp['id']}")
    assert detail.json()["status"] == "published"
    return detail.json()


def test_paid_contest_submission_still_requires_verification(client, category, landing_type):
    contest = _verified_paid_contest(client, category, landing_type)
    dev = _hosted_user(client, "paid-sub-unverified-dev")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 403, response.content


def test_paid_contest_submission_ignores_source_access_consent_field(
    client, category, landing_type
):
    """유료 공모전은 `source_access_consent`가 없어도(또는 False여도) 본인확인만
    통과하면 제출된다 — 이 필드는 무료 공모전 전용이다."""

    contest = _verified_paid_contest(client, category, landing_type)
    dev = _hosted_user(client, "paid-sub-verified-dev")
    verify_resp = client.post(
        "/api/verification/verify",
        data={"verification_token": "사람|1995-01-01|paid-sub-verified-dev-ci|paid-sub-verified-dev-ci-di"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert verify_resp.status_code == 200

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": False,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 201, response.content
    assert response.json()["source_access_consent_at"] is None


# --- 상세: 무료 여부가 실린다(안내 문구는 화면 몫, #415가 이미 검증) -----------


def test_free_contest_detail_flags_is_free_for_submit_screen(client, category, landing_type):
    _host, contest = _free_published_contest(client, category=category, landing_type=landing_type)

    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 200
    assert detail.json()["is_free"] is True


# --- 마감 전 재확인 회귀(next_action) — 무료 공모전은 NEEDS_REVERIFICATION 이
# 뜨지 않는다(본인확인 자체를 요구하지 않으므로) ------------------------------


def test_free_submission_before_deadline_can_still_be_edited_without_verification(
    client, category, landing_type
):
    deadline_at = timezone.now() + timedelta(days=7)
    _host, contest = _free_published_contest(
        client, category=category, landing_type=landing_type, deadline_at=deadline_at
    )
    dev = _hosted_user(client, "free-sub-dev-next-action")

    client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [_source_asset(contest["id"], dev["user_id"])],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    me_resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )
    assert me_resp.status_code == 200, me_resp.content
    assert me_resp.json()["next_action"] == "can_edit_submission"


def test_a_repository_url_is_stored_without_its_trailing_git_or_slash(client, category, landing_type):
    _host, contest = _free_published_contest(client, category=category, landing_type=landing_type)
    dev = _hosted_user(client, "free-sub-dev-dotgit")

    response = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [{"kind": "repository", "value": "https://github.com/me/todo.git/"}],
            "requirement_responses": [],
            "source_access_consent": True,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    assert response.status_code == 201, response.content
    assert [a["value"] for a in response.json()["assets"]] == ["https://github.com/me/todo"]
