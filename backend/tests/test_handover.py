"""Handover — 소스 접근 개방 + 빌드 자산 + Escrow 해제 (#14, ADR-0004/0005/0014).

핵심 대상:

- Award 즉시(추가 조치 없이) Sponsor가 그 Submission의 소스를 조회·다운로드할 수
  있다. Award되지 않은 Submission의 소스는 여전히 Sponsor에게 보이지 않는다 —
  오브젝트는 옮기지 않고 DB 상태(Award 존재 여부)만으로 판정한다(ADR-0005).
- Developer가 Award된 Submission에만 빌드 자산을 presigned URL로 업로드하고
  기록할 수 있다. Sponsor는 그걸 조회할 수 있다.
- Sponsor의 인수 확인, 또는 인수 확인 없이 정해진 기간 경과(내부 스캔)로 Escrow가
  해제되고, 원장에 분개가 남는다. 두 경로가 경합해도 분개는 한 번만 남는다.
- 실제 스토어 배포는 Handover 범위 밖임이 API 응답에 명시된다.
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
from handovers.models import Handover
from ledger.services import contest_entries

TICK_URL = "/api/internal/tick"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
SUBMISSIONS_URL = "/api/submissions"
STORAGE_URL = "/api/storage"
INTERNAL_HANDOVER_RELEASE_DUE_URL = "/api/internal/scans/handover-release"


# --- 헬퍼 (test_judging_period_and_award.py와 같은 형식) ------------------------


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
) -> tuple[dict, dict]:
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
    contest = detail.json()
    assert contest["status"] == "published"
    return sponsor, contest


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, dev: dict, contest_id: int) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "source_object_key": _source_object_key(contest_id, dev["user_id"]),
            "requirement_responses": [],
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


def _award(client, sponsor: dict, contest_id: int, submission_id: int) -> dict:
    resp = client.post(
        f"{CONTESTS_URL}/{contest_id}/award",
        data={"submission_id": submission_id},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 200, resp.content
    return resp.json()


def _publish_close_award(client, category, landing_type, *, sponsor_uid="sponsor-1", dev_uid="dev-1"):
    """Award까지 끝난 Contest 하나를 만들어 (sponsor, dev, contest, submission)를 돌려준다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid=sponsor_uid,
        deadline_at=deadline,
    )
    dev = _verified_user(client, dev_uid, f"{dev_uid}-ci")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    _award(client, sponsor, contest["id"], submission["id"])
    return sponsor, dev, contest, submission


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 소스 접근 개방 ------------------------------------------------------------


@pytest.mark.django_db
def test_award_opens_source_access_to_sponsor(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    detail = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}", **_auth_header(sponsor["access"])
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["source_object_key"] is not None
    assert body["source_object_key"] == submission["source_object_key"]


@pytest.mark.django_db
def test_award_opens_source_download_url_to_sponsor(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    download_resp = client.post(
        f"{STORAGE_URL}/downloads",
        data={
            "target_ref": f"submission:{contest['id']}:{dev['user_id']}:source",
            "object_key": submission["source_object_key"],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert download_resp.status_code == 200, download_resp.content
    assert "download_url" in download_resp.json()


@pytest.mark.django_db
def test_non_awarded_submission_source_stays_hidden_from_sponsor(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev_awarded = _verified_user(client, "dev-awarded", "dev-awarded-ci")
    dev_other = _verified_user(client, "dev-other", "dev-other-ci")
    submission_awarded = _submit(client, dev_awarded, contest["id"])
    submission_other = _submit(client, dev_other, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    _award(client, sponsor, contest["id"], submission_awarded["id"])

    # 다른 Developer의 Submission은 Award되지 않았으므로 여전히 숨겨진다.
    other_detail = client.get(
        f"{SUBMISSIONS_URL}/{submission_other['id']}", **_auth_header(sponsor["access"])
    )
    assert other_detail.status_code == 200
    assert other_detail.json()["source_object_key"] is None

    download_resp = client.post(
        f"{STORAGE_URL}/downloads",
        data={
            "target_ref": f"submission:{contest['id']}:{dev_other['user_id']}:source",
            "object_key": submission_other["source_object_key"],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert download_resp.status_code == 403


@pytest.mark.django_db
def test_developer_source_still_visible_to_self(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    own_detail = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}", **_auth_header(dev["access"])
    )
    assert own_detail.status_code == 200
    assert own_detail.json()["source_object_key"] == submission["source_object_key"]


# --- 빌드 자산 -----------------------------------------------------------------


@pytest.mark.django_db
def test_developer_can_upload_and_sponsor_can_list_build_asset(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    upload_resp = client.post(
        f"{STORAGE_URL}/uploads",
        data={"target_ref": f"submission:{contest['id']}:{dev['user_id']}:build-asset"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert upload_resp.status_code == 200, upload_resp.content
    object_key = upload_resp.json()["object_key"]

    record_resp = client.post(
        f"{SUBMISSIONS_URL}/{submission['id']}/build-assets",
        data={"kind": "build_config", "object_key": object_key, "label": "release.yaml"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert record_resp.status_code == 201, record_resp.content
    asset = record_resp.json()
    assert asset["object_key"] == object_key
    assert asset["kind"] == "build_config"

    sponsor_list = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}/build-assets", **_auth_header(sponsor["access"])
    )
    assert sponsor_list.status_code == 200
    kinds = [a["kind"] for a in sponsor_list.json()]
    assert "build_config" in kinds

    stranger = _verified_user(client, "stranger-1", "stranger-ci-1")
    stranger_list = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}/build-assets", **_auth_header(stranger["access"])
    )
    assert stranger_list.status_code == 403


@pytest.mark.django_db
def test_build_asset_label_over_200_chars_is_rejected_with_422_not_500(
    client, category, landing_type
):
    """BuildAsset.label은 CharField(max_length=200)이다 — 스키마가 막지 않으면
    Postgres DataError가 500으로 샌다(리뷰 지적 3)."""

    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    upload_resp = client.post(
        f"{STORAGE_URL}/uploads",
        data={"target_ref": f"submission:{contest['id']}:{dev['user_id']}:build-asset"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert upload_resp.status_code == 200
    object_key = upload_resp.json()["object_key"]

    record_resp = client.post(
        f"{SUBMISSIONS_URL}/{submission['id']}/build-assets",
        data={"kind": "build_config", "object_key": object_key, "label": "a" * 201},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert record_resp.status_code == 422


@pytest.mark.django_db
def test_developer_cannot_upload_build_asset_for_non_awarded_submission(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-1-ci")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    # Award하지 않는다.

    record_resp = client.post(
        f"{SUBMISSIONS_URL}/{submission['id']}/build-assets",
        data={"kind": "build_config", "object_key": "irrelevant", "label": ""},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert record_resp.status_code == 409


@pytest.mark.django_db
def test_other_developer_cannot_upload_build_asset_for_someone_elses_awarded_submission(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)
    stranger = _verified_user(client, "stranger-2", "stranger-ci-2")

    record_resp = client.post(
        f"{SUBMISSIONS_URL}/{submission['id']}/build-assets",
        data={"kind": "build_config", "object_key": "irrelevant", "label": ""},
        content_type="application/json",
        **_auth_header(stranger["access"]),
    )
    assert record_resp.status_code == 403


# --- Handover 조회 · 스토어 배포 범위 밖 안내 ------------------------------------


@pytest.mark.django_db
def test_handover_status_visible_to_sponsor_and_developer_only(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    sponsor_view = client.get(
        f"{CONTESTS_URL}/{contest['id']}/handover", **_auth_header(sponsor["access"])
    )
    assert sponsor_view.status_code == 200
    body = sponsor_view.json()
    assert body["status"] == "pending_acceptance"
    assert "스토어 배포" in body["note"]

    dev_view = client.get(
        f"{CONTESTS_URL}/{contest['id']}/handover", **_auth_header(dev["access"])
    )
    assert dev_view.status_code == 200

    stranger = _verified_user(client, "stranger-3", "stranger-ci-3")
    stranger_view = client.get(
        f"{CONTESTS_URL}/{contest['id']}/handover", **_auth_header(stranger["access"])
    )
    assert stranger_view.status_code == 403


# --- Escrow 해제 — Sponsor 인수 확인 --------------------------------------------


@pytest.mark.django_db
def test_sponsor_acceptance_releases_escrow_and_posts_balanced_ledger_entry(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    accept_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(sponsor["access"])
    )
    assert accept_resp.status_code == 200, accept_resp.content
    body = accept_resp.json()
    assert body["status"] == "released"
    assert body["released_via"] == "sponsor_accepted"

    handover = Handover.objects.get(award__contest_id=contest["id"])
    assert handover.status == Handover.Status.RELEASED
    assert handover.escrow_release_journal_entry_id is not None

    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == handover.escrow_release_journal_entry_id
    ]
    assert len(entries) == 1
    entry = entries[0]
    debit_total = sum(line.amount for line in entry.lines.all() if line.side == "debit")
    credit_total = sum(line.amount for line in entry.lines.all() if line.side == "credit")
    assert debit_total == credit_total
    assert debit_total == contest["prize"]


@pytest.mark.django_db
def test_only_sponsor_can_accept_handover(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    dev_accept = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(dev["access"])
    )
    assert dev_accept.status_code == 403


@pytest.mark.django_db
def test_double_accept_is_idempotent_and_posts_ledger_entry_once(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)

    first = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(sponsor["access"])
    )
    second = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(sponsor["access"])
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["status"] == "released"
    assert second.json()["status"] == "released"

    handover = Handover.objects.get(award__contest_id=contest["id"])
    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == handover.escrow_release_journal_entry_id
    ]
    assert len(entries) == 1


# --- Escrow 해제 — 인수 확인 없이 정해진 기간 경과 -------------------------------


@pytest.mark.django_db
def test_timeout_releases_escrow_without_sponsor_acceptance(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)
    handover = Handover.objects.get(award__contest_id=contest["id"])
    assert handover.status == Handover.Status.PENDING_ACCEPTANCE

    _freeze(handover.release_deadline_at + timedelta(minutes=1))
    scan_resp = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())
    assert scan_resp.status_code == 200
    assert scan_resp.json()["count"] == 1

    handover.refresh_from_db()
    assert handover.status == Handover.Status.RELEASED
    assert handover.released_via == Handover.ReleasedVia.TIMEOUT
    assert handover.escrow_release_journal_entry_id is not None


@pytest.mark.django_db
def test_release_due_scan_is_idempotent_when_run_twice(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)
    handover = Handover.objects.get(award__contest_id=contest["id"])

    _freeze(handover.release_deadline_at + timedelta(minutes=1))
    first = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())
    second = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())

    assert first.json()["count"] == 1
    assert second.json()["count"] == 0

    handover.refresh_from_db()
    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == handover.escrow_release_journal_entry_id
    ]
    assert len(entries) == 1


@pytest.mark.django_db
def test_release_due_scan_is_bounded_by_batch_size(client, category, landing_type, monkeypatch):
    """무제한 스캔은 백로그가 쌓였을 때 요청 자체를 타임아웃으로 몰아넣는다
    (scoring.services.BATCH_SIZE와 같은 이유, 리뷰 지적 5) — 배치를 넘는 잔여
    분량은 다음 스캔이 마저 처리해야 한다."""

    from dataclasses import replace

    from core import scans

    spec = scans.SCAN_REGISTRY["handover-release"]
    monkeypatch.setitem(scans.SCAN_REGISTRY, "handover-release", replace(spec, batch_size=2))

    handovers = []
    for i in range(3):
        # 이전 반복의 _close_contest가 시계를 미래로 얼려 놓았다 — 그대로 두면
        # 다음 반복이 만드는 Contest의 deadline_at(실제 현재 시각 기준)이 이미
        # 지난 것으로 보여 제출 자체가 403으로 막힌다. 각 반복 시작 시 실제
        # 시각으로 되돌린다.
        ClockOverride.objects.filter(pk=1).delete()
        _sponsor, _dev, contest, _submission = _publish_close_award(
            client, category, landing_type, sponsor_uid=f"batch-sponsor-{i}", dev_uid=f"batch-dev-{i}"
        )
        handovers.append(Handover.objects.get(award__contest_id=contest["id"]))

    latest_deadline = max(h.release_deadline_at for h in handovers)
    _freeze(latest_deadline + timedelta(minutes=1))

    first = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())
    assert first.status_code == 200
    assert first.json()["count"] == 2

    second = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())
    assert second.status_code == 200
    assert second.json()["count"] == 1

    third = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())
    assert third.json()["count"] == 0

    for h in handovers:
        h.refresh_from_db()
        assert h.status == Handover.Status.RELEASED
        assert h.escrow_release_journal_entry_id is not None


@pytest.mark.django_db
def test_release_scan_isolates_a_handover_whose_release_raises(client, category, landing_type):
    """행 하나의 예외가 배치를 막지 않는다(#138) — 그 Handover 는 `failed` 에 남고 뒤의
    Handover 는 같은 실행에서 해제된다. 격리가 없으면 id 순 스캔에서 그 행이 매번 맨 앞에서
    다시 걸려 뒤가 영원히 막힌다."""

    from unittest.mock import patch

    import handovers.scans as handover_scans

    handovers = []
    for i in range(2):
        ClockOverride.objects.filter(pk=1).delete()
        _sponsor, _dev, contest, _submission = _publish_close_award(
            client, category, landing_type, sponsor_uid=f"poison-sponsor-{i}", dev_uid=f"poison-dev-{i}"
        )
        handovers.append(Handover.objects.get(award__contest_id=contest["id"]))
    poison, healthy = handovers
    _freeze(max(h.release_deadline_at for h in handovers) + timedelta(minutes=1))

    real_release = handover_scans.release_escrow

    def _release(handover, **kwargs):
        if handover.pk == poison.pk:
            raise RuntimeError("원장 분개 중 예기치 못한 버그")
        return real_release(handover, **kwargs)

    with patch.object(handover_scans, "release_escrow", _release):
        resp = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())

    assert resp.status_code == 200
    body = resp.json()
    assert [f["pk"] for f in body["failed"]] == [poison.pk]
    assert [r["handover_id"] for r in body["rows"]] == [healthy.pk]
    poison.refresh_from_db()
    healthy.refresh_from_db()
    assert poison.status == Handover.Status.PENDING_ACCEPTANCE
    assert healthy.status == Handover.Status.RELEASED


@pytest.mark.django_db
def test_scan_does_not_release_handover_before_deadline(client, category, landing_type):
    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)
    handover = Handover.objects.get(award__contest_id=contest["id"])

    # 아직 release_deadline_at 전이다 — 스캔해도 아무 것도 풀리지 않는다.
    scan_resp = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())
    assert scan_resp.status_code == 200
    assert scan_resp.json()["count"] == 0

    handover.refresh_from_db()
    assert handover.status == Handover.Status.PENDING_ACCEPTANCE


@pytest.mark.django_db
def test_sponsor_acceptance_after_timeout_scan_does_not_double_release(
    client, category, landing_type
):
    """타임아웃 스캔이 먼저 해제한 뒤 Sponsor가 뒤늦게 인수 확인을 눌러도 분개가
    다시 남지 않는다 — 두 경로 모두 같은 조건부 UPDATE 관문을 지난다."""

    sponsor, dev, contest, submission = _publish_close_award(client, category, landing_type)
    handover = Handover.objects.get(award__contest_id=contest["id"])

    _freeze(handover.release_deadline_at + timedelta(minutes=1))
    scan_resp = client.post(INTERNAL_HANDOVER_RELEASE_DUE_URL, **_internal_headers())
    assert scan_resp.json()["count"] == 1

    late_accept = client.post(
        f"{CONTESTS_URL}/{contest['id']}/handover/accept", **_auth_header(sponsor["access"])
    )
    assert late_accept.status_code == 200
    assert late_accept.json()["released_via"] == "timeout"

    handover.refresh_from_db()
    entries = [
        e
        for e in contest_entries(Contest.objects.get(id=contest["id"]).ledger_id)
        if e.id == handover.escrow_release_journal_entry_id
    ]
    assert len(entries) == 1
