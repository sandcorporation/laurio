"""마감 전이 + 데모·영상 전면 공개 + 포트폴리오 아카이브 (#11, ADR-0003/0005/0014).

핵심 대상: 스케줄러 틱이 `Contest`를 PUBLISHED -> CLOSED 로 조건부 UPDATE 하는지,
그 전이가 두 번 쏴도 한 번만 일어나는지. 데모·영상 전면 공개·소스 비공개
자체는 이미 #10(submissions.resolvers)이 `deadline_at`을 직접 비교해 구현해
두었으므로(틱을 기다리지 않는다), 여기서는 그 계약을 다시 한번 못박고
"Developer 공개 프로필에 나타난다"는 #11의 새 AC만 새로 증명한다.
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

TICK_URL = "/api/internal/tick"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
SUBMISSIONS_URL = "/api/submissions"


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
    assert detail.status_code == 200
    contest = detail.json()
    assert contest["status"] == "published"

    return sponsor, contest


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _demo_video_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:demo-video/{uuid.uuid4().hex}"


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 마감 전이 자체 (ADR-0003) ------------------------------------------------


@pytest.mark.django_db
def test_tick_closes_contest_past_its_deadline(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    _freeze(deadline + timedelta(minutes=1))
    response = client.post(TICK_URL, **_internal_headers())

    assert response.status_code == 200
    body = response.json()
    matching = [t for t in body["transitioned"] if t["model"] == "Contest" and t["pk"] == contest["id"]]
    assert matching == [
        {"model": "Contest", "pk": contest["id"], "from_state": "published", "to_state": "closed"}
    ]

    closed = Contest.objects.get(id=contest["id"])
    assert closed.status == Contest.Status.CLOSED


@pytest.mark.django_db
def test_contest_not_yet_past_deadline_stays_published(client, category, landing_type):
    deadline = timezone.now() + timedelta(days=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    response = client.post(TICK_URL, **_internal_headers())
    assert response.status_code == 200

    still_published = Contest.objects.get(id=contest["id"])
    assert still_published.status == Contest.Status.PUBLISHED


@pytest.mark.django_db
def test_firing_tick_twice_closes_contest_only_once(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _freeze(deadline + timedelta(minutes=1))

    first = client.post(TICK_URL, **_internal_headers())
    second = client.post(TICK_URL, **_internal_headers())

    assert first.status_code == 200
    assert second.status_code == 200

    first_matches = [t for t in first.json()["transitioned"] if t["pk"] == contest["id"]]
    second_matches = [t for t in second.json()["transitioned"] if t["pk"] == contest["id"]]
    assert len(first_matches) == 1
    assert second_matches == []

    closed = Contest.objects.get(id=contest["id"])
    assert closed.status == Contest.Status.CLOSED


@pytest.mark.django_db
def test_draft_contest_is_never_closed_by_the_tick(client, category, landing_type):
    """전이 규칙은 from_state='published' 만 잡는다 — draft는 결제 미완료라 손대면 안 된다."""
    sponsor = _verified_user(client, "sponsor-draft", "sponsor-draft-ci")
    response = client.post(
        CONTESTS_URL,
        data={
            "title": "미결제 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() - timedelta(hours=1)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert response.status_code == 200
    contest = response.json()
    assert contest["status"] == "draft"

    client.post(TICK_URL, **_internal_headers())

    draft_contest = Contest.objects.get(id=contest["id"])
    assert draft_contest.status == Contest.Status.DRAFT


# --- 마감 후 전면 공개 · 소스 비공개 (ADR-0005, ADR-0014 — #10 계약의 재확인) -----


@pytest.mark.django_db
def test_after_tick_closes_contest_demo_is_public_but_source_stays_hidden(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    source_key = _source_object_key(contest["id"], dev["user_id"])
    demo_key = _demo_video_object_key(contest["id"], dev["user_id"])
    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "demo_video_object_key": demo_key,
            "test_account": "demo-id/demo-pw",
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert submit_resp.status_code == 201
    submission_id = submit_resp.json()["id"]

    _freeze(deadline + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    # 비로그인 상태로도 데모·영상이 조회된다.
    anon_resp = client.get(f"{SUBMISSIONS_URL}/{submission_id}")
    assert anon_resp.status_code == 200
    body = anon_resp.json()
    assert body["demo_video_object_key"] == demo_key

    # 소스는 마감 후에도, Sponsor에게도, 누구에게도 공개되지 않는다.
    assert body["source_object_key"] is None
    assert body["test_account"] is None

    sponsor_resp = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(sponsor["access"])
    )
    assert sponsor_resp.status_code == 200
    sponsor_body = sponsor_resp.json()
    assert sponsor_body["source_object_key"] is None
    # test_account는 owner+sponsor에게만 계속 열려 있다.
    assert sponsor_body["test_account"] == "demo-id/demo-pw"

    owner_resp = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(dev["access"])
    )
    assert owner_resp.json()["source_object_key"] == source_key


@pytest.mark.django_db
def test_no_storage_bytes_move_object_keys_are_unchanged_by_the_deadline(
    client, category, landing_type
):
    """공개 전환은 DB 상태 판정일 뿐이다 — object_key 자체가 바뀌지 않는다는 것으로
    "객체를 옮기거나 복사하지 않는다"(ADR-0005)를 증명한다."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")

    source_key = _source_object_key(contest["id"], dev["user_id"])
    demo_key = _demo_video_object_key(contest["id"], dev["user_id"])
    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={"source_object_key": source_key, "demo_video_object_key": demo_key},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert submit_resp.status_code == 201
    submission_id = submit_resp.json()["id"]

    from submissions.models import Submission

    before = Submission.objects.get(id=submission_id)
    assert before.source_object_key == source_key
    assert before.demo_video_object_key == demo_key

    _freeze(deadline + timedelta(minutes=1))
    client.post(TICK_URL, **_internal_headers())

    after = Submission.objects.get(id=submission_id)
    assert after.source_object_key == source_key
    assert after.demo_video_object_key == demo_key


# --- Developer 공개 프로필 아카이브 (#11 새 AC) ---------------------------------


@pytest.mark.django_db
def test_closed_submission_appears_on_developer_public_profile(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    client.post(
        "/api/accounts/developer-profile",
        data={"display_name": "포트폴리오 개발자", "bio": "안녕하세요"},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )

    demo_key = _demo_video_object_key(contest["id"], dev["user_id"])
    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": _source_object_key(contest["id"], dev["user_id"]),
            "demo_video_object_key": demo_key,
            "demo_url": "https://example.com/demo",
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert submit_resp.status_code == 201
    submission_id = submit_resp.json()["id"]

    from accounts.models import DeveloperProfile

    developer_id = DeveloperProfile.objects.get(user_id=dev["user_id"]).id

    # 마감 전에는 아카이브에 나타나지 않는다.
    before = client.get(f"/api/developers/{developer_id}/profile")
    assert before.status_code == 200
    assert before.json()["submissions"] == []

    _freeze(deadline + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200

    # 비로그인 상태로도 공개 프로필과 그 안의 아카이브가 조회된다.
    after = client.get(f"/api/developers/{developer_id}/profile")
    assert after.status_code == 200
    after_body = after.json()
    assert after_body["display_name"] == "포트폴리오 개발자"
    assert after_body["submissions"] == [
        {
            "submission_id": submission_id,
            "contest_id": contest["id"],
            "contest_title": contest["title"],
            "demo_video_object_key": demo_key,
            "demo_url": "https://example.com/demo",
            "created_at": after_body["submissions"][0]["created_at"],
        }
    ]
    # 소스·test_account는 공개 프로필 스키마 자체에 없다.
    assert "source_object_key" not in after_body["submissions"][0]
    assert "test_account" not in after_body["submissions"][0]


@pytest.mark.django_db
def test_public_profile_for_unknown_developer_is_404(client):
    response = client.get(f"/api/developers/999999/profile")
    assert response.status_code == 404
