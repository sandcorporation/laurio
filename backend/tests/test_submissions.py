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
from submissions.models import Submission, SubmissionAsset
from tests.submission_assets import assets_of, first_value, demo_account_of
# 신원 파기(EXPIRED) 시나리오(#250)를 만드는 데 쓰는 내부 스캔 호출 헬퍼 — 이 파일이
# 다시 구현하는 대신 그 스캔을 처음 세운 파일(#102)의 것을 그대로 쓴다(이 저장소의
# 관용구, 예: test_contest_metrics.py가 test_source_readings.py를 그대로 쓰는 것과 같다).
from tests.test_withdrawal import DORMANCY_SCAN_URL, _freeze, _internal_headers, _unfreeze

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

    response = _submit(client, dev["access"], contest["id"], {"assets": []})

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_submission_with_whitespace_only_source_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": "   "}]})

    assert response.status_code == 422


@pytest.mark.django_db
def test_source_object_key_must_belong_to_callers_own_target_ref(client, category, landing_type):
    """다른 target_ref 아래에서 만든 object_key를 자기 것인 양 주장할 수 없다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    other = _verified_user(client, "dev-2", "dev-ci-2")

    stolen_key = _source_object_key(contest["id"], other["user_id"])
    response = _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": stolen_key}]})

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_developer_can_submit_with_source_only(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])

    response = _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]})

    assert response.status_code == 201, response.content
    body = response.json()
    assert first_value(body, "source") == source_key
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}, {"kind": "demo_url", "value": "https://example.invalid/oversized", "test_account": "x" * 5000}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}], "requirement_responses": [
                {"requirement_id": requirement_id, "is_met": True, "note": "x" * 5000}
            ]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], 999)}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], 999)}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
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

    created = _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]})
    assert created.status_code == 201

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )

    new_key = _source_object_key(contest["id"], dev["user_id"])
    response = _edit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": new_key}]})

    assert response.status_code == 403
    # 마감 후 수정이 거부되었으니 소스는 원래 값 그대로여야 한다.
    submission = Submission.objects.get(contest_id=contest["id"])
    assert [a.value for a in submission.assets.filter(kind="source")] == [source_key]


@pytest.mark.django_db
def test_developer_can_edit_before_deadline(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    first_key = _source_object_key(contest["id"], dev["user_id"])
    created = _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": first_key}]})
    assert created.status_code == 201

    second_key = _source_object_key(contest["id"], dev["user_id"])
    response = _edit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": second_key}, {"kind": "demo_url", "value": "https://example.com/demo"}]},
    )

    assert response.status_code == 200
    body = response.json()
    assert first_value(body, "source") == second_key
    assert first_value(body, "demo_url") == "https://example.com/demo"
    assert body["completion"]["has_demo_url"] is True


@pytest.mark.django_db
def test_editing_a_submission_that_does_not_exist_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _edit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_submitting_twice_without_editing_is_rejected(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    payload = {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]}

    first = _submit(client, dev["access"], contest["id"], payload)
    assert first.status_code == 201

    second = _submit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(draft_contest["id"], dev["user_id"])}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(
                contest["id"], same_person_other_account["user_id"]
            )}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], me.json()["id"])}]},
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
            {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
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
            {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}], "requirement_responses": [
                {"requirement_id": requirement_ids[0], "is_met": True, "evidence": []},
                {
                    "requirement_id": requirement_ids[1],
                    "is_met": True,
                    "evidence": [{"kind": "video_timestamp", "value": "00:01:23"}],
                },
            ]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}], "requirement_responses": [
                {"requirement_id": requirement_id, "is_met": True, "evidence": []}
            ]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}], "requirement_responses": [
                {"requirement_id": foreign_requirement_id, "is_met": True, "evidence": []}
            ]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}], "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "smell", "value": "x"}],
                }
            ]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
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
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}, {"kind": "demo_video", "value": demo_key}, {"kind": "demo_url", "value": "https://example.com/demo", "test_account": "id/pw"}]},
    )
    submission_id = created.json()["id"]

    response = client.get(f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(sponsor["access"]))

    assert response.status_code == 200
    body = response.json()
    assert assets_of(body, "source") == []
    assert first_value(body, "demo_video") == demo_key
    assert first_value(body, "demo_url") == "https://example.com/demo"
    assert demo_account_of(body) == "id/pw"
    assert body["is_owner"] is False


@pytest.mark.django_db
def test_owner_can_view_own_source(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    created = _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]})
    submission_id = created.json()["id"]

    response = client.get(f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(dev["access"]))

    assert response.status_code == 200
    assert first_value(response.json(), "source") == source_key


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
        {"assets": [{"kind": "source", "value": source_key}, {"kind": "demo_video", "value": demo_key}, {"kind": "demo_url", "value": "https://example.invalid/after-deadline-demo", "test_account": "demo-login/demo-password"}]},
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
    assert first_value(body, "demo_video") == demo_key
    assert assets_of(body, "source") == []
    assert demo_account_of(body) == ""

    anon_response = client.get(f"{SUBMISSIONS_URL}/{submission_id}")
    assert anon_response.status_code == 200
    anon_body = anon_response.json()
    assert assets_of(anon_body, "source") == []
    assert demo_account_of(anon_body) == ""
    assert first_value(anon_body, "demo_video") == demo_key

    # Owner와 Sponsor는 마감 후에도 test_account를 계속 볼 수 있다 — 숨기는 대상은
    # "낯선 사람"이지 정당한 당사자가 아니다.
    owner_response = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(dev["access"])
    )
    assert demo_account_of(owner_response.json()) == "demo-login/demo-password"

    sponsor_response = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(sponsor["access"])
    )
    assert demo_account_of(sponsor_response.json()) == "demo-login/demo-password"


# --- 스크린샷 (#264, ADR-0036) -----------------------------------------------


def _screenshot_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:screenshot/{uuid.uuid4().hex}"


@pytest.mark.django_db
def test_screenshot_is_accepted_and_public_after_deadline_like_demo_video(
    client, category, landing_type
):
    """스크린샷은 데모·영상과 같은 모양이다 — 마감 전 비공개, 마감 후 전면 공개
    (ADR-0036). 이미지 content-type이면 받아들여진다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    screenshot_key = _screenshot_object_key(contest["id"], dev["user_id"])

    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": source_key},
                {
                    "kind": "screenshot",
                    "value": screenshot_key,
                    "content_type": "image/png",
                    "label": "메인 화면",
                },
            ]
        },
    )
    assert created.status_code == 201, created.content
    submission_id = created.json()["id"]

    # 마감 전에는 낯선 사람에게 통째로 안 보인다(#10) — Submission 자체가 404다.
    stranger = _login(client, uid="anyone")
    before = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(stranger["access"])
    )
    assert before.status_code == 404

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )

    after = client.get(f"{SUBMISSIONS_URL}/{submission_id}")
    assert after.status_code == 200
    assert first_value(after.json(), "screenshot") == screenshot_key


@pytest.mark.django_db
def test_screenshot_with_disallowed_content_type_is_rejected(client, category, landing_type):
    """ADR-0036: ContestImage와 같은 MIME 허용목록(png/jpeg/webp/gif)이다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])},
                {
                    "kind": "screenshot",
                    "value": _screenshot_object_key(contest["id"], dev["user_id"]),
                    "content_type": "application/zip",
                },
            ]
        },
    )

    assert response.status_code == 422
    assert "png/jpeg/webp/gif" in response.json()["detail"]
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_screenshot_without_a_content_type_is_rejected(client, category, landing_type):
    """content-type을 아예 안 실은 것도 거절한다 — 빈 값으로 허용목록 검사를
    건너뛸 수 없다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])},
                {
                    "kind": "screenshot",
                    "value": _screenshot_object_key(contest["id"], dev["user_id"]),
                },
            ]
        },
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_screenshot_count_cap_comes_from_the_policy(client, category, landing_type):
    from policies.services import get_current_policy

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    policy = get_current_policy()
    policy.max_screenshot_assets = 1
    policy.save(update_fields=["max_screenshot_assets"])

    assets = [
        {"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])},
        {
            "kind": "screenshot",
            "value": _screenshot_object_key(contest["id"], dev["user_id"]),
            "content_type": "image/png",
        },
        {
            "kind": "screenshot",
            "value": _screenshot_object_key(contest["id"], dev["user_id"]),
            "content_type": "image/png",
        },
    ]
    rejected = _submit(client, dev["access"], contest["id"], {"assets": assets})
    assert rejected.status_code == 422

    policy.max_screenshot_assets = 2
    policy.save(update_fields=["max_screenshot_assets"])
    accepted = _submit(client, dev["access"], contest["id"], {"assets": assets})
    assert accepted.status_code == 201, accepted.content


@pytest.mark.django_db
def test_evidence_can_point_at_a_screenshot_asset(client, category, landing_type):
    """Evidence.asset은 종류를 가리지 않는다 — 스크린샷도 가리킬 수 있어야
    「어느 자료의 근거인가」 선택에 스크린샷이 나온다(#264 AC)."""

    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "온보딩 화면", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    screenshot_key = _screenshot_object_key(contest["id"], dev["user_id"])

    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])},
                {
                    "kind": "screenshot",
                    "value": screenshot_key,
                    "content_type": "image/png",
                },
            ]
        },
    )
    assert created.status_code == 201, created.content
    screenshot_asset_id = next(
        a["id"] for a in created.json()["assets"] if a["kind"] == "screenshot"
    )

    edited = _edit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": created.json()["assets"],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "note": "화면 참고",
                    "evidence": [
                        {"kind": "screenshot", "value": "온보딩 1단계", "asset_id": screenshot_asset_id}
                    ],
                }
            ],
        },
    )
    assert edited.status_code == 200, edited.content
    evidence = edited.json()["requirement_responses"][0]["evidence"][0]
    assert evidence["asset_id"] == screenshot_asset_id


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
    _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]})

    response = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )

    assert response.status_code == 200
    assert first_value(response.json(), "source") == source_key


# --- 신원 파기(EXPIRED) 뒤에도 읽기는 열려 있다 (#250, ADR-0025) ------------------
#
# `Verification.Status.EXPIRED`는 2년간 행위가 없을 때 스캔이 신원만 파기하고
# 남기는 상태다(#102) — 계정은 비활성화되지 않고 로그인도 그대로 되며, 다음
# 개최·제출 시도에서만 본인확인을 다시 요구받는다. ADR-0025가 지우는 것은
# 실명·생년월일·CI/DI·전화번호 같은 신원 정보이지 그 사람이 낸 제출물이 아니다
# — 그런데 예전 화면은 `verified`가 아니면 조회 자체를 시도하지 않아, 신원이
# 파기된 본인에게 자기 제출물이 통째로 사라진 것처럼 보였다. 아래는 그 경계가
# 서버(HTTP)에서 실제로 어디 있는지 고정한다: 읽기(GET .../submissions/me)는
# 세 상태(본인확인 없음·`expired`·`verified`) 어디서도 열려 있고, 쓰기(생성·
# 수정)는 `verified`가 아니면 여전히 거부된다.


def _expire_identity_via_dormancy_scan(client) -> None:
    """지금 시점에 살아 있는 모든 `Verification`을 2년 미이용으로 판정해 스캔이
    신원을 파기하게 만든다.

    백데이트(`tests.test_withdrawal._backdate_activity`)로 `User.date_joined`
    ·`Verification.updated_at`만 과거로 되돌리는 방식은 이 파일과 맞지 않는다
    — 최근 행위 판정(`accounts.dormancy._dormant_verifications`)이
    `Submission.created_at`도 함께 보는데, 이 파일의 제출 픽스처들은 방금
    만든 Submission을 곧바로 쓴다. 그래서 여기서는 반대로 시계를 2년+1일
    앞으로 밀어 "방금"을 "2년 전"으로 만든다. 스캔이 끝나면 시계를 원래대로
    돌려놓는다 — 안 그러면 뒤이은 호출이 전부 마감을 훌쩍 넘긴 시점으로
    보여 `_reject_if_past_deadline`이 엉뚱한 이유로 먼저 걸린다.
    """

    from accounts.dormancy import DORMANCY_PERIOD

    _freeze(timezone.now() + DORMANCY_PERIOD + timedelta(days=1))
    try:
        resp = client.post(DORMANCY_SCAN_URL, **_internal_headers())
        assert resp.status_code == 200, resp.content
    finally:
        _unfreeze()


@pytest.mark.django_db
def test_owner_can_still_read_submission_after_identity_is_purged(client, category, landing_type):
    """신원이 파기(EXPIRED)돼도 이미 낸 제출물은 그대로 읽힌다(#250 AC).

    **`next_action`도 함께 고정한다.** 그 값이 이 화면군의 유일한 판정처다
    (`submissions.participation.next_action_for`) — 읽기가 되는 것만 보고
    `next_action`이 여전히 `can_edit_submission`(마감 전이라는 이유만으로)을
    돌려주면, 「내 참여」와 제출 화면은 "수정할 수 있습니다"라고 말하고
    실제 PUT은 403으로 거절해 화면이 시킨 대로 한 사용자를 배신한다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dormant-dev", "dormant-dev-ci")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    submit_resp = _submit(
        client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]}
    )
    assert submit_resp.status_code == 201, submit_resp.content

    _expire_identity_via_dormancy_scan(client)

    from verification.models import Verification

    verification = Verification.objects.get(user_id=dev["user_id"])
    assert verification.status == Verification.Status.EXPIRED

    response = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )

    assert response.status_code == 200
    body = response.json()
    assert first_value(body, "source") == source_key
    assert body["next_action"] == "needs_reverification"

    # 「내 참여」(`GET /submissions/mine`)도 같은 판정기를 쓴다 — 두 화면이
    # 다른 말을 하지 않는다.
    mine_response = client.get(f"{SUBMISSIONS_URL}/mine", **_auth_header(dev["access"]))
    assert mine_response.status_code == 200
    mine_body = mine_response.json()
    assert len(mine_body["items"]) == 1
    assert mine_body["items"][0]["next_action"] == "needs_reverification"


@pytest.mark.django_db
def test_write_is_still_rejected_after_identity_is_purged(client, category, landing_type):
    """읽기는 열려도 새로 내거나 고치는 것은 여전히 막힌다(#250 AC) — 화면이
    막는 것과 서버가 거절하는 것은 둘 다 필요하다(#67과 같은 원칙)."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dormant-dev-2", "dormant-dev-2-ci")
    submit_resp = _submit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
    )
    assert submit_resp.status_code == 201, submit_resp.content

    _expire_identity_via_dormancy_scan(client)

    edit_resp = _edit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}]},
    )
    assert edit_resp.status_code == 403
    assert "본인확인" in edit_resp.json()["detail"]

    # 새 Contest에 첫 제출을 시도하는 것도 같은 이유로 막힌다 — `create_submission`
    # 도 `update_submission`과 같은 게이트(`_require_verification`)를 먼저 통과해야
    # 한다.
    _, another_contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid="dormant-sponsor-2",
        sponsor_ci="dormant-sponsor-2-ci",
    )
    create_resp = _submit(
        client,
        dev["access"],
        another_contest["id"],
        {
            "assets": [
                {"kind": "source", "value": _source_object_key(another_contest["id"], dev["user_id"])}
            ]
        },
    )
    assert create_resp.status_code == 403
    assert "본인확인" in create_resp.json()["detail"]


@pytest.mark.django_db
def test_reading_without_ever_verifying_is_a_plain_404_not_a_verification_error(
    client, category, landing_type
):
    """조회 경로 자체는 본인확인을 요구하지 않는다는 것을 뒤집어서도 보인다 —
    한 번도 본인확인하지 않은 사람이 자기 제출물을 찾을 때(있을 리 없다)
    "아직 안 냈다"(404)와 "본인확인이 필요하다"(403, 쓰기 경로의 메시지)가
    같은 응답으로 뭉개지지 않는다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    pair = _login(client, uid="never-verified-dev")

    response = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(pair["access"])
    )

    assert response.status_code == 404
    assert "본인확인" not in response.json()["detail"]


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

    _submit(client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": object_key}]})

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


# --- 다운로드 파일명 (#241) ---------------------------------------------------
#
# 확장자 없는 32자리 hex object_key가 그대로 파일명으로 떨어지던 결함(#241)의
# 재현·수정 확인. 업로드 발급 시점에 받은 content-type을 자산(SubmissionAsset)에
# 남기고, 다운로드 시점에 그 값으로 파일명을 만든다 — 원본 파일명은 절대 쓰지
# 않는다(RFC 5987 이스케이프가 필요한 자리를 새로 만들지 않으려는 결정).


@pytest.mark.django_db
def test_download_filename_gets_extension_from_stored_content_type(
    client, category, landing_type
):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    upload = client.post(
        "/api/storage/uploads",
        data={
            "target_ref": f"submission:{contest['id']}:{dev['user_id']}:source",
            "content_type": "application/zip",
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert upload.status_code == 200
    object_key = upload.json()["object_key"]

    submit = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": object_key, "content_type": "application/zip"}
            ]
        },
    )
    assert submit.status_code == 201, submit.content

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
    assert 'filename="download.zip"' in download.json()["download_url"]


@pytest.mark.django_db
def test_editing_an_unchanged_asset_does_not_erase_its_stored_content_type(
    client, category, landing_type
):
    """`SubmissionAssetOut`은 content_type을 내주지 않으므로(#241), 편집 화면이
    기존 자료를 그대로 재전송할 때 이 필드를 알 도리가 없어 빈 문자열로 보낸다.
    value(object_key)가 같다는 것은 같은 파일을 가리킨다는 뜻이라 그 형식도
    바뀔 수 없다 — `_merge_assets`가 "kept" 자료의 content_type을 건드리지 않아야
    이런 재전송이 이미 알려진 확장자를 조용히 지우지 않는다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])

    submit = _submit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": source_key, "content_type": "application/zip"}]},
    )
    assert submit.status_code == 201, submit.content

    # 편집 UI는 content_type을 모른 채(응답에 없다) 같은 value를 그대로 되돌려 보낸다.
    edit = _edit(
        client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]}
    )
    assert edit.status_code == 200, edit.content

    download = client.post(
        "/api/storage/downloads",
        data={
            "target_ref": f"submission:{contest['id']}:{dev['user_id']}:source",
            "object_key": source_key,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert download.status_code == 200
    assert 'filename="download.zip"' in download.json()["download_url"]


@pytest.mark.django_db
def test_download_filename_has_no_extension_when_content_type_is_unknown(
    client, category, landing_type
):
    """content-type을 안 보냈어도(기존에 올라간 자산과 같은 상황) 다운로드가
    실패하지 않고, 확장자 없는 이름이 그대로 붙는다(#241 AC — 마이그레이션이
    기존 데이터를 깨지 않는다는 것과 같은 자리다)."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])

    submit = _submit(
        client, dev["access"], contest["id"], {"assets": [{"kind": "source", "value": source_key}]}
    )
    assert submit.status_code == 201, submit.content

    download = client.post(
        "/api/storage/downloads",
        data={
            "target_ref": f"submission:{contest['id']}:{dev['user_id']}:source",
            "object_key": source_key,
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert download.status_code == 200
    body = download.json()
    assert 'filename="download"' in body["download_url"]
    assert ".zip" not in body["download_url"].split('filename="download"')[1][:5]


@pytest.mark.django_db
def test_content_type_on_a_url_kind_asset_is_ignored(client, category, landing_type):
    """소스가 아니라 데모 URL 같은 종류에 content_type을 실어 보내도 조용히
    버려진다 — 그 자료는 storage를 거치지 않아 다운로드 파일명이라는 개념 자체가
    없다(#241)."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])

    submit = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": source_key},
                {
                    "kind": "demo_url",
                    "value": "https://example.com/demo",
                    "content_type": "text/html",
                },
            ]
        },
    )
    assert submit.status_code == 201, submit.content

    demo_asset = SubmissionAsset.objects.get(
        submission_id=submit.json()["id"], kind="demo_url"
    )
    assert demo_asset.content_type == ""


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
def test_demo_video_download_ttl_is_longer_than_the_default(client, category, landing_type):
    """시연 영상은 화면 안에서 재생해야 해서 다른 종류보다 서명 수명이 길다
    (#265, ADR-0036) — 그 값은 PlatformPolicy가 아니라 설정 상수다."""

    from datetime import datetime, timezone as dt_timezone

    from django.conf import settings

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    def _expires_delta(target_ref: str) -> float:
        object_key = f"{target_ref}/{uuid.uuid4().hex}"
        response = client.post(
            "/api/storage/downloads",
            data={"target_ref": target_ref, "object_key": object_key},
            content_type="application/json",
            **_auth_header(dev["access"]),
        )
        assert response.status_code == 200, response.content
        expires_at = datetime.fromisoformat(response.json()["expires_at"])
        return (expires_at - datetime.now(dt_timezone.utc)).total_seconds()

    source_delta = _expires_delta(f"submission:{contest['id']}:{dev['user_id']}:source")
    video_delta = _expires_delta(f"submission:{contest['id']}:{dev['user_id']}:demo-video")

    assert source_delta <= settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS
    assert video_delta > settings.STORAGE_DOWNLOAD_URL_TTL_SECONDS
    assert (
        settings.STORAGE_VIDEO_DOWNLOAD_URL_TTL_SECONDS - 5
        <= video_delta
        <= settings.STORAGE_VIDEO_DOWNLOAD_URL_TTL_SECONDS
    )


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


@pytest.mark.django_db
def test_resolver_wiring_keeps_assignment_demo_private_after_deadline(client, landing_type):
    """Assignment(ADR-0028, #212)는 공모전과 달리 마감 후에도 전면 공개로 돌아서지
    않는다 — InviteCode 를 아는 사람만 본다는 약속이 마감 뒤에도 이어져야 한다
    (스펙 #197). `submissions.resolvers.SubmissionTargetStateResolver` 는 원래
    `deadline_at` 하나만 보고 데모·영상 슬롯을 PUBLIC 으로 뒤집었는데, 그 판정이
    Assignment 인지 전혀 묻지 않아서 InviteCode 경계가 마감 시각에 조용히
    사라졌다 — 위 `test_resolver_wiring_opens_demo_to_everyone_after_deadline`
    (진짜 콘테스트, 여전히 공개돼야 한다)과 짝을 이룬다."""

    from django.core.management import call_command

    call_command("create_operator", "root-resolver-asgn", password="correct-horse-battery-resolver", superuser=True)
    operator = client.__class__()
    operator_login = operator.post(
        "/api/operator/login",
        data={"username": "root-resolver-asgn", "password": "correct-horse-battery-resolver"},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert operator_login.status_code == 200, operator_login.content

    sponsor_pair = _login(client, uid="asgn-resolver-sponsor")
    sponsor_me = client.get("/api/accounts/me", **_auth_header(sponsor_pair["access"]))
    grant = operator.post(
        "/api/operator/assignment-permissions/grant",
        data={"username": sponsor_me.json()["username"], "reason": "리졸버 검증"},
        content_type="application/json",
        HTTP_ORIGIN="http://testserver",
    )
    assert grant.status_code == 200, grant.content

    deadline = timezone.now() + timedelta(hours=1)
    created = client.post(
        "/api/assignments",
        data={
            "title": "리졸버 검증용 과제",
            "deliverable_type_ids": [landing_type.id],
            "description": "",
            "deadline_at": deadline.isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor_pair["access"]),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]

    opened = client.post(
        f"/api/assignments/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(sponsor_pair["access"]),
    )
    assert opened.status_code == 200, opened.content
    invite_code = opened.json()["invite_code"]

    student_pair = _login(client, uid="asgn-resolver-student")
    student_me = client.get("/api/accounts/me", **_auth_header(student_pair["access"]))
    student_id = student_me.json()["id"]

    demo_target_ref = f"submission:{assignment_id}:{student_id}:demo-video"
    demo_object_key = f"{demo_target_ref}/{uuid.uuid4().hex}"
    submit = client.post(
        f"{CONTESTS_URL}/{assignment_id}/submissions",
        data={
            "assets": [
                {"kind": "source", "value": f"submission:{assignment_id}:{student_id}:source/{uuid.uuid4().hex}"},
                {"kind": "demo_video", "value": demo_object_key},
            ],
            "invite_code": invite_code,
        },
        content_type="application/json",
        **_auth_header(student_pair["access"]),
    )
    assert submit.status_code == 201, submit.content

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )

    anon_download = client.post(
        "/api/storage/downloads",
        data={"target_ref": demo_target_ref, "object_key": demo_object_key},
        content_type="application/json",
    )
    assert anon_download.status_code == 403

    # 학생 본인과 강사는 여전히 받을 수 있다 — 잠근 대상은 "낯선 사람"이지 당사자가
    # 아니다.
    assert (
        client.post(
            "/api/storage/downloads",
            data={"target_ref": demo_target_ref, "object_key": demo_object_key},
            content_type="application/json",
            **_auth_header(student_pair["access"]),
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/storage/downloads",
            data={"target_ref": demo_target_ref, "object_key": demo_object_key},
            content_type="application/json",
            **_auth_header(sponsor_pair["access"]),
        ).status_code
        == 200
    )


# --- 자료 여럿 (#190, ADR-0027) ------------------------------------------------
#
# 여기까지의 테스트는 "종류당 하나"를 전제로 쓰였고 #190이 그 전제를 자산 목록으로
# 옮겼다. 아래는 목록이 되면서 **새로 생긴 사실들**만 고정한다.


def _repo_url(name: str) -> str:
    return f"https://github.com/laurio-test/{name}"


@pytest.mark.django_db
def test_a_submission_can_carry_several_sources_videos_demos_and_repositories(
    client, category, landing_type
):
    """Contest가 산출물 종류 여럿을 요구할 수 있는데(`Contest.deliverable_types`가
    M2M이다) 자료가 종류당 하나면 참가자는 자기가 만든 것의 일부만 낼 수 있었다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    web_source = _source_object_key(contest["id"], dev["user_id"])
    app_source = _source_object_key(contest["id"], dev["user_id"])
    video = _demo_video_object_key(contest["id"], dev["user_id"])

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": web_source, "label": "웹"},
                {"kind": "source", "value": app_source, "label": "모바일 앱"},
                {"kind": "demo_video", "value": video},
                {
                    "kind": "demo_url",
                    "value": "https://example.invalid/web",
                    "test_account": "web-id/web-pw",
                },
                {
                    "kind": "demo_url",
                    "value": "https://example.invalid/app",
                    "test_account": "app-id/app-pw",
                },
                {"kind": "repository", "value": _repo_url("web")},
            ]
        },
    )

    assert response.status_code == 201, response.content
    body = response.json()
    assert sorted(a["value"] for a in assets_of(body, "source")) == sorted(
        [web_source, app_source]
    )
    assert len(assets_of(body, "demo_url")) == 2
    assert demo_account_of(body, "https://example.invalid/app") == "app-id/app-pw"

    completion = body["completion"]
    # boolean은 "하나라도 있는가"로 그대로 살고, 개수가 옆에 따로 온다.
    assert completion["has_demo_url"] is True
    assert completion["source_count"] == 2
    assert completion["demo_url_count"] == 2
    assert completion["repository_count"] == 1


@pytest.mark.django_db
def test_editing_keeps_assets_sent_with_their_id_and_drops_the_omitted_ones(
    client, category, landing_type
):
    """자료만 id로 병합된다 — 그 병합이 없으면 저장할 때마다 같은 파일이 새 행이
    되어 "언제 올렸는가"가 전부 마지막 수정 시각으로 뭉갠다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    kept_key = _source_object_key(contest["id"], dev["user_id"])
    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": kept_key},
                {"kind": "demo_url", "value": "https://example.invalid/gone"},
            ]
        },
    )
    assert created.status_code == 201
    kept = assets_of(created.json(), "source")[0]

    edited = _edit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                # id를 실어 보낸 것은 그 행 그대로 살아남는다.
                {"kind": "source", "value": kept_key, "id": kept["id"], "label": "웹"},
                # id 없이 보낸 것은 새로 생긴다.
                {"kind": "demo_url", "value": "https://example.invalid/new"},
            ]
        },
    )

    assert edited.status_code == 200, edited.content
    body = edited.json()
    surviving = assets_of(body, "source")[0]
    assert surviving["id"] == kept["id"]
    assert surviving["label"] == "웹"
    # 페이로드에 없던 데모는 사라지고 새 것만 남는다.
    assert [a["value"] for a in assets_of(body, "demo_url")] == [
        "https://example.invalid/new"
    ]


@pytest.mark.django_db
def test_another_developers_asset_id_cannot_be_claimed(client, category, landing_type):
    """id 병합이 이 API에 처음 들여온 부분 갱신 의미론이다 — 소유권 검사가 없으면
    남의 행을 자기 제출작으로 옮길 수 있다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    victim = _verified_user(client, "dev-1", "dev-ci-1")
    attacker = _verified_user(client, "dev-2", "dev-ci-2")

    victim_submission = _submit(
        client,
        victim["access"],
        contest["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], victim["user_id"]),
                }
            ]
        },
    )
    assert victim_submission.status_code == 201
    victim_asset_id = assets_of(victim_submission.json(), "source")[0]["id"]

    attacker_key = _source_object_key(contest["id"], attacker["user_id"])
    _submit(
        client,
        attacker["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": attacker_key}]},
    )

    stolen = _edit(
        client,
        attacker["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": attacker_key, "id": victim_asset_id}]},
    )

    assert stolen.status_code == 422
    # 피해자의 자료는 그대로 자기 제출작에 남아 있다.
    victim_after = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(victim["access"])
    )
    assert assets_of(victim_after.json(), "source")[0]["id"] == victim_asset_id


@pytest.mark.django_db
def test_first_submission_cannot_carry_asset_ids(client, category, landing_type):
    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], dev["user_id"]),
                    "id": 1,
                }
            ]
        },
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_repository_must_be_a_github_url(client, category, landing_type):
    """임의의 git URL을 받으면 플랫폼 서버가 참가자가 지정한 주소로 나가게 된다
    (SSRF) — 저장소를 실제로 clone하는 것은 #193이지만 받아들일 수 있는 값만
    지금부터 저장한다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source = {"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}

    for bad in [
        "http://169.254.169.254/latest/meta-data",
        "https://gitlab.com/owner/repo",
        "https://github.com/owner",
        "https://github.com.evil.invalid/owner/repo",
        "git@github.com:owner/repo.git",
    ]:
        response = _submit(
            client,
            dev["access"],
            contest["id"],
            {"assets": [source, {"kind": "repository", "value": bad}]},
        )
        assert response.status_code == 422, f"허용되면 안 되는 값: {bad}"

    ok = _submit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [source, {"kind": "repository", "value": _repo_url("ok")}]},
    )
    assert ok.status_code == 201, ok.content


@pytest.mark.django_db
def test_a_repository_is_hidden_from_the_sponsor_like_the_source_is(
    client, category, landing_type
):
    """공개 레포라도 플랫폼이 Sponsor에게 코드로 가는 길을 먼저 열어주지는
    않는다(ADR-0027) — 검색해서 찾아내는 것까지 막을 수는 없어도 떠먹이지는 않는다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submitted = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], dev["user_id"]),
                },
                {"kind": "repository", "value": _repo_url("hidden")},
                {"kind": "demo_url", "value": "https://example.invalid/demo"},
            ]
        },
    )
    assert submitted.status_code == 201
    submission_id = submitted.json()["id"]

    sponsor_view = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(sponsor["access"])
    )
    assert assets_of(sponsor_view.json(), "repository") == []
    assert assets_of(sponsor_view.json(), "source") == []
    # 데모는 보인다 — 감추는 것은 코드로 가는 길뿐이다.
    assert first_value(sponsor_view.json(), "demo_url") == "https://example.invalid/demo"

    # 마감이 지나도 저장소는 전면 공개되지 않는다 — ADR-0014가 명시한
    # "탈락작의 소스는 마감 후에도 공개되지 않는다"가 저장소에도 적용된다.
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )
    anon_view = client.get(f"{SUBMISSIONS_URL}/{submission_id}")
    assert assets_of(anon_view.json(), "repository") == []
    assert first_value(anon_view.json(), "demo_url") == "https://example.invalid/demo"

    # 본인에게는 언제나 보인다.
    own_view = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(dev["access"])
    )
    assert first_value(own_view.json(), "repository") == _repo_url("hidden")


@pytest.mark.django_db
def test_scoring_input_limit_counts_sources_and_repositories_together(
    client, category, landing_type
):
    """소스와 저장소는 같은 채점 예산을 나눠 쓴다 — 종류별 상한만으로는 막을 수
    없다. 상한이 없으면 채점 예산이 잘게 쪼개져 사실상 무의미한 채점이 되고,
    모델 컨텍스트를 넘기면 그 실패가 permanent로 잡혀 소스를 많이 낸 참가자가
    오히려 Score 없이 배분 컷라인에서 탈락한다."""

    from policies.services import get_current_policy

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    policy = get_current_policy()
    assert policy.max_scoring_input_assets == 8
    assert policy.max_source_assets == 5

    # 소스 5 + 저장소 4 = 9 > 8. 종류별 상한(5, 8)에는 각각 걸리지 않는다.
    assets = [
        {"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])}
        for _ in range(5)
    ] + [{"kind": "repository", "value": _repo_url(f"r{i}")} for i in range(4)]

    response = _submit(client, dev["access"], contest["id"], {"assets": assets})

    assert response.status_code == 422
    assert "8" in response.json()["detail"]
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_per_kind_limit_comes_from_the_policy_not_from_code(client, category, landing_type):
    """상한은 사업이 정하는 값이라 배포 없이 운영자가 조정할 수 있어야 한다
    (ADR-0023) — 정책 행을 바꾸면 API의 판정도 함께 바뀐다."""

    from policies.services import get_current_policy

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    policy = get_current_policy()
    policy.max_demo_url_assets = 1
    policy.save(update_fields=["max_demo_url_assets"])

    assets = [
        {"kind": "source", "value": _source_object_key(contest["id"], dev["user_id"])},
        {"kind": "demo_url", "value": "https://example.invalid/a"},
        {"kind": "demo_url", "value": "https://example.invalid/b"},
    ]
    rejected = _submit(client, dev["access"], contest["id"], {"assets": assets})
    assert rejected.status_code == 422

    policy.max_demo_url_assets = 2
    policy.save(update_fields=["max_demo_url_assets"])
    accepted = _submit(client, dev["access"], contest["id"], {"assets": assets})
    assert accepted.status_code == 201, accepted.content


@pytest.mark.django_db
def test_the_same_value_cannot_be_listed_twice(client, category, landing_type):
    """UniqueConstraint가 대신 걸리면 422가 아니라 500(IntegrityError)이 난다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    key = _source_object_key(contest["id"], dev["user_id"])

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {"assets": [{"kind": "source", "value": key}, {"kind": "source", "value": key}]},
    )

    assert response.status_code == 422
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_a_test_account_cannot_hang_on_a_source_or_repository(client, category, landing_type):
    """"이 소스를 열어보는 로그인 정보"라는 것은 존재하지 않는다. 모델의
    CheckConstraint가 최후의 방어선이지만 그것이 걸리면 500이다."""

    _sponsor, contest = _publish_contest(client, category=category, deliverable_type=landing_type)
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    response = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], dev["user_id"]),
                    "test_account": "id/pw",
                }
            ]
        },
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_evidence_can_point_at_one_asset_and_dies_with_it(client, category, landing_type):
    """데모·영상이 여럿이 되는 순간 "데모 내 경로"가 어느 대상의 것인지 알 수
    없어진다. 자료를 지우면 그것을 가리키던 근거도 함께 사라진다 — 가리킬 곳이
    없는 근거는 근거가 아니다."""

    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "주문 목록", "grade": "required"}],
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])

    created = _submit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": source_key},
                {"kind": "demo_url", "value": "https://example.invalid/app", "label": "앱"},
            ]
        },
    )
    assert created.status_code == 201
    demo = assets_of(created.json(), "demo_url")[0]
    requirement_id = contest["requirements"][0]["id"]

    linked = _edit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": source_key},
                {
                    "kind": "demo_url",
                    "value": "https://example.invalid/app",
                    "label": "앱",
                    "id": demo["id"],
                },
            ],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [
                        {"kind": "demo_path", "value": "/orders", "asset_id": demo["id"]}
                    ],
                }
            ],
        },
    )
    assert linked.status_code == 200, linked.content
    evidence = linked.json()["requirement_responses"][0]["evidence"][0]
    assert evidence["asset_id"] == demo["id"]

    # **그 데모를 지우면서 그것을 가리키는 근거를 그대로 보내도 거부되지 않는다**
    # (#195). 서버가 병합 뒤의 자산을 이미 알고 있으므로 서버가 연결을 푼다 —
    # 클라이언트가 `_merge_assets` 의 정체성 규칙을 흉내 내어 미리 풀어 보낼
    # 이유가 없다. 그 미러링은 실제로 두 번 틀렸다(#192).
    #
    # 근거 자체는 사라지지 않는다 — 대상을 특정하지 않은 근거도 여전히 유효하다
    # (다중화 이전의 모든 근거가 그 모양이다).
    unlinked = _edit(
        client,
        dev["access"],
        contest["id"],
        {
            "assets": [{"kind": "source", "value": source_key}],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [
                        {"kind": "demo_path", "value": "/orders", "asset_id": demo["id"]}
                    ],
                }
            ],
        },
    )

    assert unlinked.status_code == 200, unlinked.content
    body = unlinked.json()
    evidence = body["requirement_responses"][0]["evidence"][0]
    # 값과 종류는 그대로고 연결만 풀렸다 — 화면은 보낸 값과 돌아온 값을 견주어
    # 「연결이 해제되었습니다」를 말할 수 있다.
    assert evidence["value"] == "/orders"
    assert evidence["asset_id"] is None
    assert assets_of(body, "demo_url") == []


@pytest.mark.django_db
def test_evidence_cannot_point_at_another_submissions_asset(client, category, landing_type):
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "주문 목록", "grade": "required"}],
    )
    victim = _verified_user(client, "dev-1", "dev-ci-1")
    attacker = _verified_user(client, "dev-2", "dev-ci-2")

    victim_submission = _submit(
        client,
        victim["access"],
        contest["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], victim["user_id"]),
                }
            ]
        },
    )
    victim_asset_id = assets_of(victim_submission.json(), "source")[0]["id"]

    response = _submit(
        client,
        attacker["access"],
        contest["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], attacker["user_id"]),
                }
            ],
            "requirement_responses": [
                {
                    "requirement_id": contest["requirements"][0]["id"],
                    "is_met": True,
                    "evidence": [
                        {
                            "kind": "source_location",
                            "value": "src/x.ts",
                            "asset_id": victim_asset_id,
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 422


@pytest.mark.django_db
def test_removing_an_asset_does_not_open_a_path_to_another_submissions_asset(
    client, category, landing_type
):
    """#195 가 「이번 요청이 지운 자료」를 조용히 풀도록 열었는데, 그 분기가 「남의
    자료」까지 함께 뭉개면 #190 의 방어가 사라진다.

    기존 `test_evidence_cannot_point_at_another_submissions_asset` 은 POST 만 걷는다 —
    첫 제출에는 지울 자료가 없어 `removed_asset_ids` 가 항상 비어 있으므로 그 테스트는
    새 분기를 한 번도 지나지 않는다. 여기서는 **같은 요청에서 자기 자료를 지우면서**
    남의 자료 id 를 근거로 지정한다.
    """

    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "주문 목록", "grade": "required"}],
    )
    victim = _verified_user(client, "dev-1", "dev-ci-1")
    attacker = _verified_user(client, "dev-2", "dev-ci-2")
    requirement_id = contest["requirements"][0]["id"]

    victim_submission = _submit(
        client,
        victim["access"],
        contest["id"],
        {
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], victim["user_id"]),
                }
            ]
        },
    )
    assert victim_submission.status_code == 201
    victim_asset_id = assets_of(victim_submission.json(), "source")[0]["id"]

    attacker_source = _source_object_key(contest["id"], attacker["user_id"])
    created = _submit(
        client,
        attacker["access"],
        contest["id"],
        {
            "assets": [
                {"kind": "source", "value": attacker_source},
                {"kind": "demo_url", "value": "https://example.invalid/gone"},
            ]
        },
    )
    assert created.status_code == 201

    # 자기 데모를 지우면서(= removed_asset_ids 가 비어 있지 않은 요청) 남의 자료를
    # 근거로 지정한다. 지운 자료의 연결은 풀어주지만 남의 것은 여전히 거부다.
    response = _edit(
        client,
        attacker["access"],
        contest["id"],
        {
            "assets": [{"kind": "source", "value": attacker_source}],
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [
                        {
                            "kind": "source_location",
                            "value": "src/x.ts",
                            "asset_id": victim_asset_id,
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 422
    # 거부됐으니 공격자의 데모도 그대로 남아 있어야 한다(트랜잭션이 통째로 되돌아간다).
    still_there = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(attacker["access"])
    )
    assert len(assets_of(still_there.json(), "demo_url")) == 1
