"""Submission 제출 — 소스 필수 · Evidence 연결 · 소스 비공개 · 자전거래 차단 (#10).

ADR-0014가 이 파일의 핵심 대상이다: 소스는 제출 시점에 필수로 받되 Sponsor에게는
Award 전까지(이 티켓 범위에서는 항상) 보이지 않는다. 데모·영상은 진행 중 Sponsor·
제출자 본인에게만, 마감 후 전면 공개된다. 리뷰에서 실패 경로 결함이 대부분이었다는
지적에 따라 실패 경로를 먼저, 더 두껍게 쓴다.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from submissions.models import Submission

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
SUBMISSIONS_URL = "/api/submissions"


# --- 로그인 · 본인확인 헬퍼 (test_payments.py와 같은 형식을 재사용) -------------------


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
    """소셜 로그인 + 본인확인을 마친 (access, user_id) 를 돌려준다."""

    pair = _login(client, uid=uid)
    _verify(client, pair["access"], ci=ci)
    me = client.get("/api/accounts/me", **_auth_header(pair["access"]))
    assert me.status_code == 200
    return {"access": pair["access"], "user_id": me.json()["id"]}


def _sign(*, webhook_id: str, order_id: str, status: str) -> str:
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
) -> tuple[dict, dict]:
    """검증된 Sponsor로 Contest를 만들고 결제까지 완료해 published 상태로 돌려준다.

    (sponsor dict {access, user_id}, contest json) 을 돌려준다.
    """

    sponsor = _verified_user(client, sponsor_uid, sponsor_ci)
    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))

    response = client.post(
        CONTESTS_URL,
        data={
            "title": f"{sponsor_uid}의 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [deliverable_type.id],
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
    assert payment_resp.status_code == 201
    payment = payment_resp.json()

    webhook_id = f"wh-{contest['id']}"
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


# --- object_key 헬퍼 (storage의 "<target_ref>/<32자리 hex>" 형태를 그대로 재현) -----


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _demo_video_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:demo-video/{uuid.uuid4().hex}"


def _submit(client, access: str, contest_id: int, payload: dict):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


def _edit(client, access: str, contest_id: int, payload: dict):
    return client.put(
        f"{CONTESTS_URL}/{contest_id}/submissions/me",
        data=payload,
        content_type="application/json",
        **_auth_header(access),
    )


@pytest.fixture
def category(db):
    return Category.objects.create(name="엔터테인먼트")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 소스 필수 (ADR-0014) -----------------------------------------------------


@pytest.mark.django_db
def test_submission_without_source_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(client, dev["access"], contest["id"], {"source_object_key": ""})

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_submission_with_whitespace_only_source_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(client, dev["access"], contest["id"], {"source_object_key": "   "})

    assert response.status_code == 422


@pytest.mark.django_db
def test_source_object_key_must_belong_to_callers_own_target_ref(client, category, landing_type):
    """다른 target_ref 아래에서 만든 object_key를 자기 것인 양 주장할 수 없다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    other = _verified_user(client, "dev-2", "dev-ci-2")

    stolen_key = _source_object_key(contest["id"], other["user_id"])
    response = _submit(client, dev["access"], contest["id"], {"source_object_key": stolen_key})

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_developer_can_submit_with_source_only(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])

    response = _submit(client, dev["access"], contest["id"], {"source_object_key": source_key})

    assert response.status_code == 201, response.content
    body = response.json()
    assert body["source_object_key"] == source_key
    assert body["is_owner"] is True
    assert body["completion"]["has_demo_video"] is False
    assert body["completion"]["has_demo_url"] is False
    assert body["completion"]["has_test_account"] is False


@pytest.mark.django_db
def test_oversized_test_account_is_rejected_with_422_not_500(client, category, landing_type):
    """스키마가 model의 CharField 길이를 그대로 반영하지 않으면 DB CHECK가 대신
    걸려 422 대신 500(DataError)이 난다(#10 리뷰 지적 재현: varchar(500) 초과)."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "test_account": "x" * 5000,
        },
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_oversized_requirement_note_is_rejected_with_422_not_500(client, category, landing_type):
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "로그인 기능", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "requirement_responses": [
                {"requirement_id": requirement_id, "is_met": True, "note": "x" * 5000}
            ],
        },
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


# --- Verification 필요 (ADR-0011) ---------------------------------------------


@pytest.mark.django_db
def test_submission_without_verification_is_rejected_with_reason(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    pair = _login(client, uid="unverified-dev")

    response = _submit(
        client,
        pair["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], 999)},
    )

    assert response.status_code == 403
    assert "본인확인" in response.json()["detail"]
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_underage_developer_cannot_submit(client, category, landing_type):
    """만 19세 미만은 verify 자체가 verified에 도달하지 못한다(ADR-0011) — 그 결과로
    제출도 막힌다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    pair = _login(client, uid="minor-dev")
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"미성년|{timezone.now().year - 10}-01-01|minor-ci|minor-di"},
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert response.json()["status"] == "underage"

    submit_response = _submit(
        client,
        pair["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], 999)},
    )

    assert submit_response.status_code == 403


# --- 마감 (Clock 기반, #11이 뒤집을 규칙) --------------------------------------


@pytest.mark.django_db
def test_submission_after_deadline_is_rejected(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
    )

    assert response.status_code == 403
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_edit_after_deadline_is_rejected(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])

    created = _submit(client, dev["access"], contest["id"], {"source_object_key": source_key})
    assert created.status_code == 201

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )

    new_key = _source_object_key(contest["id"], dev["user_id"])
    response = _edit(client, dev["access"], contest["id"], {"source_object_key": new_key})

    assert response.status_code == 403
    # 마감 후 수정이 거부되었으니 소스는 원래 값 그대로여야 한다.
    submission = Submission.objects.get(contest_id=contest["id"])
    assert submission.source_object_key == source_key


@pytest.mark.django_db
def test_developer_can_edit_before_deadline(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    first_key = _source_object_key(contest["id"], dev["user_id"])
    created = _submit(client, dev["access"], contest["id"], {"source_object_key": first_key})
    assert created.status_code == 201

    second_key = _source_object_key(contest["id"], dev["user_id"])
    response = _edit(
        client,
        dev["access"],
        contest["id"],
        {"source_object_key": second_key, "demo_url": "https://example.com/demo"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_object_key"] == second_key
    assert body["demo_url"] == "https://example.com/demo"
    assert body["completion"]["has_demo_url"] is True


@pytest.mark.django_db
def test_editing_a_submission_that_does_not_exist_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _edit(
        client,
        dev["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_submitting_twice_without_editing_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    payload = {"source_object_key": _source_object_key(contest["id"], dev["user_id"])}

    first = _submit(client, dev["access"], contest["id"], payload)
    assert first.status_code == 201

    second = _submit(
        client,
        dev["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
    )

    assert second.status_code == 409
    assert Submission.objects.filter(contest_id=contest["id"]).count() == 1


@pytest.mark.django_db
def test_submission_to_unpublished_contest_is_rejected(client, category, landing_type):
    sponsor = _verified_user(client, "sponsor-1", "sponsor-ci-1")
    response = client.post(
        CONTESTS_URL,
        data={
            "title": "아직 결제 안 한 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert response.status_code == 200
    draft_contest = response.json()

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submit_response = _submit(
        client,
        dev["access"],
        draft_contest["id"],
        {"source_object_key": _source_object_key(draft_contest["id"], dev["user_id"])},
    )

    assert submit_response.status_code == 404


# --- 자전거래 차단 (같은 CI) ---------------------------------------------------


@pytest.mark.django_db
def test_sponsors_own_ci_cannot_submit_to_their_own_contest(client, category, landing_type):
    shared_ci = "shared-identity-ci"
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, sponsor_ci=shared_ci
    )
    # 다른 계정(다른 소셜 로그인)이지만 같은 CI로 본인확인된 사람 — 자전거래 시도.
    same_person_other_account = _verified_user(client, "dev-1", shared_ci)

    response = _submit(
        client,
        same_person_other_account["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(
                contest["id"], same_person_other_account["user_id"]
            )
        },
    )

    assert response.status_code == 403
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_different_ci_developer_can_submit(client, category, landing_type):
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, sponsor_ci="sponsor-only-ci"
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
    )

    assert response.status_code == 201


class _NoCIVerificationAdapterForSelfDealingRegression:
    """CI를 주지 않는 벤더 응답을 흉내낸다 — `verification.adapters`의 것과 같은
    모양이지만, `_reject_self_dealing`이 있는 이 파일에서 독립적으로 검증하기
    위해 여기 따로 둔다(#84 코드리뷰 지적 4)."""

    def resolve(self, verification_token: str):
        from datetime import date

        from verification.adapters import VerificationResult

        return VerificationResult(real_name="CI없음", birth_date=date(1995, 1, 1), ci="", di="")


@pytest.mark.django_db
def test_ci_less_developer_can_never_reach_the_self_dealing_check(client, category, landing_type):
    """#84 회귀 테스트 — `_reject_self_dealing`이 실제로 걸려 있는 이 파일에서,
    CI 없는 응답으로 인증을 시도한 Developer는 애초에 VERIFIED가 되지 않으므로
    그 함수의 ci_hash 비교에 도달조차 못 한다는 것을 증명한다.

    구코드는 `Verification.set_ci("")`가 `HMAC(key, "")`라는 정상 해시를 만들어,
    CI 없는 사용자 전원(서로 남남인 Sponsor·Developer 포함)이 같은 해시를 갖고
    동일인으로 오차단됐다 — `_reject_self_dealing`의 `if not ci_hash: return`
    가드도 그 값이 falsy가 아니라서 못 걸렀다. #84 이후에는 CI 없는 응답이
    VERIFIED 행 자체를 만들 수 없으므로, 이 시나리오는 self-dealing 판정에
    도달하기 한참 전인 "본인확인 필요" 게이트에서 막힌다.
    """
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, sponsor_ci="sponsor-only-ci-2"
    )

    from django.test import override_settings

    dev_pair = _login(client, uid="ci-less-dev")
    with override_settings(
        VERIFICATION_ADAPTER_MODE=(
            "tests.test_submissions._NoCIVerificationAdapterForSelfDealingRegression"
        )
    ):
        start = client.post("/api/verification/start", **_auth_header(dev_pair["access"]))
        assert start.status_code == 200, start.content
        verify_response = client.post(
            "/api/verification/verify",
            data={"verification_token": start.json()["identity_verification_id"]},
            content_type="application/json",
            **_auth_header(dev_pair["access"]),
        )
    # CI 없는 응답은 거절된다(#84) — 이 사용자는 VERIFIED가 아니다.
    assert 400 <= verify_response.status_code < 500

    me = client.get("/api/accounts/me", **_auth_header(dev_pair["access"]))
    assert me.status_code == 200

    submit_response = _submit(
        client,
        dev_pair["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], me.json()["id"])},
    )

    # self-dealing 판정이 아니라 "본인확인이 안 됐다"는 훨씬 앞선 게이트에서
    # 막힌다 — Submission.objects.count()가 0인 것으로 어느 경로로도 생성되지
    # 않았음을 확인한다.
    assert submit_response.status_code == 403
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_submission_is_rejected_when_sponsor_has_no_verified_identity(
    client, category, landing_type, caplog
):
    """#90 회귀 — Sponsor에게 VERIFIED 신원이 없으면 자전거래 검사를 할 수 없다.
    지금까지는 비교 대상이 없으면 조용히 통과시켰다 — "검사할 수 없다"가
    "안전하다"를 뜻하지 않는다. 개최에는 본인확인이 필요하므로(ADR-0011) 이
    상태는 정상 운영에서 도달 불가능해야 하고, 그럼에도 도달했다면 fail-closed로
    막고 ERROR로 남겨야 한다.

    실제로 이 상태에 도달하는 경로 하나는 "성인으로 확인받아 개최한 Sponsor가
    재확인에서 미성년으로 내려가 CI가 지워지는 것"이다. #99(같은 CI로의
    재확인만 허용)가 생긴 뒤로는 다른 CI로 그 상태를 만들 수 없다 — 그래서 같은
    CI를 유지한 채 생년월일만 미성년으로 바꿔 재확인한다(현실의 벤더는 같은
    CI에 다른 생년월일을 주지 않지만, fake 어댑터는 이 회귀 시나리오를 직접
    구성하기 위해 그 제약이 없다).
    """
    import logging

    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_ci="sponsor-underage-later",
    )

    ten_years_ago = (timezone.now() - timedelta(days=365 * 10)).date().isoformat()
    downgrade = client.post(
        "/api/verification/verify",
        data={
            "verification_token": (
                f"사실은미성년|{ten_years_ago}|sponsor-underage-later|sponsor-underage-later-di"
            )
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert downgrade.json()["status"] == "underage"

    dev = _verified_user(client, "dev-after-downgrade", "dev-after-downgrade-ci")

    with caplog.at_level(logging.ERROR, logger="submissions.api"):
        response = _submit(
            client,
            dev["access"],
            contest["id"],
            {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
        )

    assert response.status_code == 403
    assert Submission.objects.count() == 0

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "비교 대상 없는 자전거래 검사는 ERROR 로그를 남겨야 한다"


@pytest.mark.django_db
def test_submission_is_rejected_when_sponsor_verified_but_ci_hash_is_empty(
    client, category, landing_type, caplog
):
    """코드리뷰 지적 — `_reject_self_dealing`의 Sponsor 쪽 가드가 비대칭이었다.
    `sponsor_verification is None`만 막고 "VERIFIED인데 ci_hash가 빈 문자열"은
    막지 않아서, 마지막 비교 `"" == developer_ci_hash`가 항상 False가 되어
    자전거래 검사가 조용히 통과했다 — #90이 지적한 결함의 좁은 형태가 그대로
    남아 있었다.

    이 docstring의 도달 불가 논거(VERIFIED 행은 반드시 `set_ci`를 거쳤으므로
    `ci_hash`가 빌 수 없다, #84)는 Developer뿐 아니라 Sponsor에게도 똑같이
    적용된다 — 그래서 이 상태는 HTTP로는 만들 수 없다. `set_ci`가 빈 CI를
    거부하기 때문이다. `test_set_ci_refuses_an_empty_value_so_ci_less_users_cannot_share_a_hash`
    와 같은 이유로, 여기서만 모델을 직접 손대 방어선 자체를 검증한다 — 나머지
    흐름(개최·제출)은 그대로 HTTP를 거친다.
    """
    import logging

    from verification.models import Verification

    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_ci="sponsor-empty-ci-hash",
    )

    sponsor_verification = Verification.objects.get(user_id=sponsor["user_id"])
    sponsor_verification.ci_hash = ""
    sponsor_verification.save(update_fields=["ci_hash"])

    dev = _verified_user(
        client, "dev-vs-empty-ci-hash-sponsor", "dev-vs-empty-ci-hash-sponsor-ci"
    )

    with caplog.at_level(logging.ERROR, logger="submissions.api"):
        response = _submit(
            client,
            dev["access"],
            contest["id"],
            {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
        )

    assert response.status_code == 403
    assert Submission.objects.count() == 0

    error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert error_records, "빈 ci_hash인 VERIFIED Sponsor도 ERROR 로그를 남겨야 한다"


# --- Evidence 연결 · 완성도 지표 -----------------------------------------------


@pytest.mark.django_db
def test_requirement_response_without_evidence_is_marked_unlinked(client, category, landing_type):
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[
            {"text": "로그인 기능", "grade": "required"},
            {"text": "다크모드", "grade": "optional"},
        ],
    )
    requirement_ids = [r["id"] for r in contest["requirements"]]
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "requirement_responses": [
                {"requirement_id": requirement_ids[0], "is_met": True, "evidence": []},
                {
                    "requirement_id": requirement_ids[1],
                    "is_met": True,
                    "evidence": [{"kind": "video_timestamp", "value": "00:01:23"}],
                },
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    by_id = {r["requirement_id"]: r for r in body["requirement_responses"]}
    assert by_id[requirement_ids[0]]["is_linked"] is False
    assert by_id[requirement_ids[1]]["is_linked"] is True
    assert body["completion"]["total_requirement_count"] == 2
    assert body["completion"]["linked_requirement_count"] == 1
    assert body["completion"]["unlinked_requirement_count"] == 1


@pytest.mark.django_db
def test_all_met_with_no_evidence_still_succeeds_but_stays_fully_unlinked(
    client, category, landing_type
):
    """자가 응답을 전부 '충족'으로 채우고 Evidence를 비워도 제출 자체는 성공한다 —
    거부가 아니라 미연결로 기록해 채점(#12)에서 미달로 걸러지게 한다."""

    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "핵심 기능", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "requirement_responses": [
                {"requirement_id": requirement_id, "is_met": True, "evidence": []}
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["completion"]["unlinked_requirement_count"] == 1


@pytest.mark.django_db
def test_requirement_response_for_foreign_requirement_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "로그인 기능", "grade": "required"}],
    )
    _other_sponsor, other_contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid="sponsor-2",
        sponsor_ci="sponsor-ci-2",
        requirements=[{"text": "다른 공모전 요구사항", "grade": "required"}],
    )
    foreign_requirement_id = other_contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "requirement_responses": [
                {"requirement_id": foreign_requirement_id, "is_met": True, "evidence": []}
            ],
        },
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_unknown_evidence_kind_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "로그인 기능", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "smell", "value": "x"}],
                }
            ],
        },
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


# --- 접근 제어: 진행 중 다른 Developer는 안 보이고, Sponsor는 데모만 본다 ------------


@pytest.mark.django_db
def test_other_developer_cannot_view_submission_during_contest(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
    )
    submission_id = created.json()["id"]

    other_dev = _verified_user(client, "dev-2", "dev-ci-2")
    response = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(other_dev["access"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_anonymous_cannot_view_submission_during_contest(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {"source_object_key": _source_object_key(contest["id"], dev["user_id"])},
    )
    submission_id = created.json()["id"]

    response = client.get(f"{SUBMISSIONS_URL}/{submission_id}")

    assert response.status_code == 404


@pytest.mark.django_db
def test_sponsor_can_view_demo_but_not_source_during_contest(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    demo_key = _demo_video_object_key(contest["id"], dev["user_id"])
    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "demo_video_object_key": demo_key,
            "demo_url": "https://example.com/demo",
            "test_account": "id/pw",
        },
    )
    submission_id = created.json()["id"]

    response = client.get(f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(sponsor["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["source_object_key"] is None
    assert body["demo_video_object_key"] == demo_key
    assert body["demo_url"] == "https://example.com/demo"
    assert body["test_account"] == "id/pw"
    assert body["is_owner"] is False


@pytest.mark.django_db
def test_owner_can_view_own_source(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    created = _submit(client, dev["access"], contest["id"], {"source_object_key": source_key})
    submission_id = created.json()["id"]

    response = client.get(f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(dev["access"]))

    assert response.status_code == 200
    assert response.json()["source_object_key"] == source_key


@pytest.mark.django_db
def test_after_deadline_demo_is_public_but_source_and_test_account_stay_hidden(
    client, category, landing_type
):
    """ADR-0014: 마감 후 데모·영상은 전면 공개되지만 소스는 계속 비공개다.

    test_account는 데모·영상에 딸린 로그인 정보다 — ADR-0014의 "마감 후 공개" 칸에는
    데모·영상만 있고 test_account는 없다. 이걸 함께 공개하면 데모를 잠가둔 의미가
    없어진다(#10 리뷰 지적).
    """

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    demo_key = _demo_video_object_key(contest["id"], dev["user_id"])
    source_key = _source_object_key(contest["id"], dev["user_id"])
    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "source_object_key": source_key,
            "demo_video_object_key": demo_key,
            "test_account": "demo-login/demo-password",
        },
    )
    submission_id = created.json()["id"]

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )

    stranger = _login(client, uid="anyone")
    response = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(stranger["access"])
    )

    assert response.status_code == 200
    body = response.json()
    assert body["demo_video_object_key"] == demo_key
    assert body["source_object_key"] is None
    assert body["test_account"] is None

    anon_response = client.get(f"{SUBMISSIONS_URL}/{submission_id}")
    assert anon_response.status_code == 200
    anon_body = anon_response.json()
    assert anon_body["source_object_key"] is None
    assert anon_body["test_account"] is None
    assert anon_body["demo_video_object_key"] == demo_key

    # Owner와 Sponsor는 마감 후에도 test_account를 계속 볼 수 있다 — 숨기는 대상은
    # "낯선 사람"이지 정당한 당사자가 아니다.
    owner_response = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(dev["access"])
    )
    assert owner_response.json()["test_account"] == "demo-login/demo-password"

    sponsor_response = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(sponsor["access"])
    )
    assert sponsor_response.json()["test_account"] == "demo-login/demo-password"


@pytest.mark.django_db
def test_viewing_a_nonexistent_submission_is_404(client):
    response = client.get(f"{SUBMISSIONS_URL}/999999")

    assert response.status_code == 404


# --- 소유자의 GET /contests/{id}/submissions/me ---------------------------------


@pytest.mark.django_db
def test_get_my_submission_before_creating_one_is_404(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_get_my_submission_after_creating_one_returns_it_with_source(
    client, category, landing_type
):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    _submit(client, dev["access"], contest["id"], {"source_object_key": source_key})

    response = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )

    assert response.status_code == 200
    assert response.json()["source_object_key"] == source_key


# --- STORAGE_TARGET_RESOLVER 실배선 (실제 presigned URL 발급까지) ------------------
#
# 위 테스트들은 Submission API 자체의 가시성 판정(파이썬 레벨)을 검증한다. 아래는
# 그와 별개로 storage 앱의 presigned 업로드·다운로드 엔드포인트가 실제로
# `submissions.resolvers.SubmissionTargetStateResolver`를 통해 같은 결론에
# 도달하는지 — 즉 STORAGE_TARGET_RESOLVER 배선 자체가 살아있는지 — 확인한다.
#
# storage.policy는 이 플랫폼의 다른 모든 API와 같은 인증(JWT, `Authorization:
# Bearer`)을 쓴다(#10 리뷰 지적 — Django 세션은 이 플랫폼 어디에서도 만들어지지
# 않으므로 `force_login`은 실제 클라이언트가 밟을 수 없는 경로였다). 그래서 여기서도
# `_verified_user`가 이미 돌려주는 access token을 그대로 storage 호출에 싣는다.


@pytest.mark.django_db
def test_resolver_wiring_grants_source_download_to_owner_only(client, category, landing_type):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    # 실제 presigned 업로드 흐름 그대로: 소유자 본인만 업로드 URL을 받을 수 있다
    # (#10 리뷰 지적 — authorize_upload가 리졸버로 소유권을 확인한다).
    upload = client.post(
        "/api/storage/uploads",
        data={"target_ref": f"submission:{contest['id']}:{dev['user_id']}:source"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert upload.status_code == 200
    object_key = upload.json()["object_key"]

    _submit(client, dev["access"], contest["id"], {"source_object_key": object_key})

    # 소유자 본인은 다운로드 URL을 받을 수 있다.
    download = client.post(
        "/api/storage/downloads",
        data={
            "target_ref": f"submission:{contest['id']}:{dev['user_id']}:source",
            "object_key": object_key,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert download.status_code == 200

    # Sponsor는 같은 소스를 절대 받을 수 없다 — Award 전까지(이 티켓 범위에서는 항상).
    sponsor_download = client.post(
        "/api/storage/downloads",
        data={
            "target_ref": f"submission:{contest['id']}:{dev['user_id']}:source",
            "object_key": object_key,
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert sponsor_download.status_code == 403


@pytest.mark.django_db
def test_stranger_cannot_upload_into_someone_elses_submission_namespace(
    client, category, landing_type
):
    """로그인했다고 아무 target_ref에나 업로드할 수 있는 게 아니다(#10 리뷰 지적) —
    그렇지 않으면 남의 namespace에 파일을 심어, 그게 나중에(마감 후) 공개로 바뀌는
    슬롯이라면 공격자의 파일이 그대로 공개 다운로드된다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    attacker = _verified_user(client, "dev-2", "dev-ci-2")

    response = client.post(
        "/api/storage/uploads",
        data={"target_ref": f"submission:{contest['id']}:{dev['user_id']}:demo-video"},
        content_type="application/json",
        **_auth_header(attacker["access"]),
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_resolver_wiring_lets_sponsor_but_not_other_developer_download_demo_before_deadline(
    client, category, landing_type
):
    sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    other_dev = _verified_user(client, "dev-2", "dev-ci-2")

    demo_target_ref = f"submission:{contest['id']}:{dev['user_id']}:demo-video"
    demo_object_key = f"{demo_target_ref}/{uuid.uuid4().hex}"

    def _download_as(access):
        return client.post(
            "/api/storage/downloads",
            data={"target_ref": demo_target_ref, "object_key": demo_object_key},
            content_type="application/json",
            **_auth_header(access),
        )

    assert _download_as(dev["access"]).status_code == 200
    assert _download_as(sponsor["access"]).status_code == 200
    assert _download_as(other_dev["access"]).status_code == 403


@pytest.mark.django_db
def test_resolver_wiring_opens_demo_to_everyone_after_deadline(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    demo_target_ref = f"submission:{contest['id']}:{dev['user_id']}:demo-video"
    demo_object_key = f"{demo_target_ref}/{uuid.uuid4().hex}"

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )

    response = client.post(
        "/api/storage/downloads",
        data={"target_ref": demo_target_ref, "object_key": demo_object_key},
        content_type="application/json",
    )

    assert response.status_code == 200
