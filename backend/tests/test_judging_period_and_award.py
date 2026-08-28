"""심사기간 + Award + 유료 연장 (#13, ADR-0003, ADR-0006/0014).

핵심 대상:

- 마감 후 7일의 심사기간이 core.transitions 레지스트리에 등록된 두 번째 전이
  (CLOSED -> JUDGING_ENDED)로 스캔된다. 두 번 쏴도 한 번만 통과한다.
- Sponsor가 Requirement 체크리스트를 축으로 Submission들을 나란히 비교한다.
- Sponsor 본인만, 심사기간 중에만, 딱 하나의 Submission을 Award할 수 있다. Score는
  이 판단에 전혀 관여하지 않는다(ADR-0006/0014 — Award는 Sponsor 자신의 판단).
- 유료 연장은 judging_ends_at 컬럼만 갱신한다 — core.transitions 레지스트리에 새
  규칙을 추가하거나 기존 규칙을 다시 등록하지 않는다. 2회 이상 연장되면
  refund_disabled가 영구히 True로 확정된다.
- 심사기간이 지나면 Award가 거부된다 — Contest.status가 아직 스캔되지 않은 경우
  (스캔 주기 지연)에도 judging_ends_at 시각으로 한 번 더 막는다.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from awards.models import Award
from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from core.transitions import TRANSITION_REGISTRY

TICK_URL = "/api/internal/tick"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
SUBMISSIONS_URL = "/api/submissions"


# --- 헬퍼 (test_contest_deadline_transition.py / test_scoring.py와 같은 형식) -------


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
    requirements=None,
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


def _submit(client, dev: dict, contest_id: int, *, requirement_responses=None) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "source_object_key": _source_object_key(contest_id, dev["user_id"]),
            "requirement_responses": requirement_responses or [],
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


@pytest.fixture
def category(db):
    return Category.objects.create(name="라이프스타일")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


# --- 심사기간 시작 · 종료 전이 (ADR-0003) --------------------------------------


@pytest.mark.django_db
def test_judging_period_starts_at_close_and_scanned_by_scheduled_transition(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    close_at = deadline + timedelta(minutes=1)
    _freeze(close_at)
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200

    closed = Contest.objects.get(id=contest["id"])
    assert closed.status == Contest.Status.CLOSED
    expected_judging_ends_at = close_at + timedelta(days=settings.JUDGING_PERIOD_DAYS)
    assert closed.judging_ends_at == expected_judging_ends_at

    # 아직 심사기간 중이므로 틱을 쏴도 JUDGING_ENDED로 넘어가지 않는다.
    client.post(TICK_URL, **_internal_headers())
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    # 심사기간이 지나면 스케줄러 틱이 JUDGING_ENDED로 옮긴다.
    _freeze(expected_judging_ends_at + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    matching = [
        t for t in tick_resp.json()["transitioned"] if t["model"] == "Contest" and t["pk"] == contest["id"]
    ]
    assert matching == [
        {"model": "Contest", "pk": contest["id"], "from_state": "closed", "to_state": "judging_ended"}
    ]
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.JUDGING_ENDED


@pytest.mark.django_db
def test_firing_tick_twice_ends_judging_period_only_once(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    _freeze(judging_ends_at + timedelta(minutes=1))
    first = client.post(TICK_URL, **_internal_headers())
    second = client.post(TICK_URL, **_internal_headers())

    assert first.status_code == 200
    assert second.status_code == 200
    first_matches = [t for t in first.json()["transitioned"] if t["pk"] == contest["id"]]
    second_matches = [t for t in second.json()["transitioned"] if t["pk"] == contest["id"]]
    assert len(first_matches) == 1
    assert second_matches == []
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.JUDGING_ENDED


@pytest.mark.django_db
def test_awarded_contest_is_never_moved_to_judging_ended_by_the_tick(
    client, category, landing_type
):
    """CLOSED -> JUDGING_ENDED 규칙의 from_state는 CLOSED뿐이다 — Award로 이미
    AWARDED가 된 Contest는 이 규칙에 애초에 걸리지 않는다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    award_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert award_resp.status_code == 200

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(judging_ends_at + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    matching = [t for t in tick_resp.json()["transitioned"] if t["pk"] == contest["id"]]
    assert matching == []
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.AWARDED


# --- Sponsor 비교 화면 --------------------------------------------------------


@pytest.mark.django_db
def test_sponsor_can_compare_submissions_along_requirement_checklist(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[
            {"text": "로그인 기능", "grade": "required"},
            {"text": "다크모드", "grade": "optional"},
        ],
    )
    requirement_ids = [r["id"] for r in contest["requirements"]]

    dev_a = _verified_user(client, "dev-a", "ci-a")
    dev_b = _verified_user(client, "dev-b", "ci-b")

    submission_a = _submit(
        client,
        dev_a,
        contest["id"],
        requirement_responses=[
            {
                "requirement_id": requirement_ids[0],
                "is_met": True,
                "note": "구현했습니다",
                "evidence": [{"kind": "source_location", "value": "src/auth.py:10"}],
            }
        ],
    )
    submission_b = _submit(
        client,
        dev_b,
        contest["id"],
        requirement_responses=[
            {"requirement_id": requirement_ids[0], "is_met": False, "note": "미구현"}
        ],
    )

    # 마감 전에는 비교할 수 없다.
    early_resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/compare", **_auth_header(sponsor["access"])
    )
    assert early_resp.status_code == 403

    _close_contest(client, contest, deadline=deadline)

    resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/compare", **_auth_header(sponsor["access"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contest_id"] == contest["id"]
    assert {s["submission_id"] for s in body["submissions"]} == {
        submission_a["id"],
        submission_b["id"],
    }

    by_requirement = {r["requirement_id"]: r for r in body["requirements"]}
    required = by_requirement[requirement_ids[0]]
    entries_by_submission = {e["submission_id"]: e for e in required["entries"]}
    assert entries_by_submission[submission_a["id"]]["is_met"] is True
    assert entries_by_submission[submission_a["id"]]["is_linked"] is True
    assert entries_by_submission[submission_b["id"]]["is_met"] is False
    assert entries_by_submission[submission_b["id"]]["is_linked"] is False

    # optional 요구사항은 아무도 응답하지 않았다 — 그래도 축에는 나타난다.
    optional = by_requirement[requirement_ids[1]]
    assert {e["submission_id"] for e in optional["entries"]} == {
        submission_a["id"],
        submission_b["id"],
    }
    assert all(e["is_met"] is False for e in optional["entries"])


@pytest.mark.django_db
def test_non_sponsor_cannot_compare_submissions(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    outsider = _verified_user(client, "outsider", "outsider-ci")

    resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/compare", **_auth_header(outsider["access"])
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_anonymous_cannot_compare_submissions(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    resp = client.get(f"{CONTESTS_URL}/{contest['id']}/submissions/compare")
    assert resp.status_code == 401


# --- Award ---------------------------------------------------------------


@pytest.mark.django_db
def test_sponsor_can_award_exactly_one_submission(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev_a = _verified_user(client, "dev-a", "ci-a")
    dev_b = _verified_user(client, "dev-b", "ci-b")
    submission_a = _submit(client, dev_a, contest["id"])
    submission_b = _submit(client, dev_b, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission_a["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["contest_id"] == contest["id"]
    assert body["submission_id"] == submission_a["id"]

    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.AWARDED
    assert Award.objects.filter(contest_id=contest["id"], submission_id=submission_a["id"]).exists()

    # 이미 Award된 Contest에 다른 Submission을 다시 Award할 수 없다.
    second_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission_b["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert second_resp.status_code == 409
    assert Award.objects.filter(contest_id=contest["id"]).count() == 1
    assert not Award.objects.filter(submission_id=submission_b["id"]).exists()


@pytest.mark.django_db
def test_non_sponsor_cannot_award(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)
    outsider = _verified_user(client, "outsider", "outsider-ci")

    # 제출자 본인도 Sponsor가 아니면 Award할 수 없다.
    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 403
    assert Award.objects.count() == 0

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(outsider["access"]),
    )
    assert resp.status_code == 403
    assert Award.objects.count() == 0


@pytest.mark.django_db
def test_award_before_contest_closes_is_refused(client, category, landing_type):
    """아직 마감 전(PUBLISHED)이면 심사기간 자체가 없다."""

    deadline = timezone.now() + timedelta(days=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 409
    assert Award.objects.count() == 0


@pytest.mark.django_db
def test_award_with_submission_from_another_contest_is_rejected(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _, other_contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid="sponsor-2",
        sponsor_ci="sponsor-ci-2",
        deadline_at=deadline,
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    foreign_submission = _submit(client, dev, other_contest["id"])

    _close_contest(client, contest, deadline=deadline)
    _close_contest(client, other_contest, deadline=deadline)

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": foreign_submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 404
    assert Award.objects.count() == 0


@pytest.mark.django_db
def test_award_is_refused_after_judging_period_ends_even_before_the_tick_runs(
    client, category, landing_type
):
    """스캔 주기만큼 틱이 아직 CLOSED -> JUDGING_ENDED를 못 옮긴 경우에도, 시각으로
    한 번 더 막는다 — Contest.status만 보고 판단하면 이 창이 뚫린다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(judging_ends_at + timedelta(minutes=1))
    # 틱을 쏘지 않았다 — status는 여전히 CLOSED다.
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 403
    assert Award.objects.count() == 0


@pytest.mark.django_db
def test_award_is_refused_after_the_tick_has_ended_judging_period(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(judging_ends_at + timedelta(minutes=1))
    client.post(TICK_URL, **_internal_headers())
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.JUDGING_ENDED

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 409
    assert Award.objects.count() == 0


# --- 유료 연장 (REQUEST.md "기간 연장", ADR-0003) ------------------------------


@pytest.mark.django_db
def test_extension_updates_only_the_transition_time_column(client, category, landing_type):
    """핵심 불변식 — 연장은 judging_ends_at 컬럼만 갱신한다. core.transitions
    레지스트리는 앱 기동 시 한 번만 채워지는 정적 리스트다 — 연장 호출 전후로 그
    길이가 바뀌지 않는다는 것으로 "재등록이 없다"를 직접 증명한다. 그리고 원래
    judging_ends_at을 지난 시각에 틱을 쏴도 CLOSED에 그대로 머문다는 것으로
    "예약이 실제로 미뤄졌다"를 행동으로 증명한다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    original_judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    registry_size_before = len(TRANSITION_REGISTRY)

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["judging_extension_count"] == 1
    assert body["refund_disabled"] is False

    registry_size_after = len(TRANSITION_REGISTRY)
    assert registry_size_after == registry_size_before

    extended = Contest.objects.get(id=contest["id"])
    expected = original_judging_ends_at + timedelta(days=settings.JUDGING_EXTENSION_DAYS)
    assert extended.judging_ends_at == expected
    assert extended.status == Contest.Status.CLOSED

    # 원래 심사기간 종료 시각을 지나도, 아직 연장된 시각 전이면 여전히 CLOSED다 —
    # 이 레지스트리 규칙을 다시 등록하지 않고 값만 바뀐 것만으로 이미 이렇게 된다.
    _freeze(original_judging_ends_at + timedelta(minutes=1))
    client.post(TICK_URL, **_internal_headers())
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    # 연장된 시각을 지나면 그제서야 JUDGING_ENDED로 옮긴다.
    _freeze(expected + timedelta(minutes=1))
    client.post(TICK_URL, **_internal_headers())
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.JUDGING_ENDED


@pytest.mark.django_db
def test_two_or_more_extensions_permanently_disable_refund(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    first = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert first.status_code == 200
    assert first.json()["judging_extension_count"] == 1
    assert first.json()["refund_disabled"] is False
    assert Contest.objects.get(id=contest["id"]).refund_disabled is False

    second = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert second.status_code == 200
    assert second.json()["judging_extension_count"] == 2
    assert second.json()["refund_disabled"] is True
    assert Contest.objects.get(id=contest["id"]).refund_disabled is True

    # 세 번째 연장 이후에도 계속 True로 남는다("영구히"의 실제 구현).
    third = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert third.status_code == 200
    assert third.json()["judging_extension_count"] == 3
    assert third.json()["refund_disabled"] is True

    # Contest 상세 API에도 이 확정 상태가 그대로 드러난다.
    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 200
    assert detail.json()["refund_disabled"] is True
    assert detail.json()["judging_extension_count"] == 3


@pytest.mark.django_db
def test_non_sponsor_cannot_extend_judging_period(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    outsider = _verified_user(client, "outsider", "outsider-ci")

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(outsider["access"]),
    )
    assert resp.status_code == 403
    assert Contest.objects.get(id=contest["id"]).judging_extension_count == 0


@pytest.mark.django_db
def test_extension_before_contest_closes_is_rejected(client, category, landing_type):
    deadline = timezone.now() + timedelta(days=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_extension_after_judging_period_already_ended_is_rejected(
    client, category, landing_type
):
    """status가 아직 CLOSED로 보이는 스캔 지연 구간에서도, 시각으로 한 번 더
    막는다 — Award의 시각 방어선(test_award_is_refused_after_judging_period_ends_
    even_before_the_tick_runs)과 같은 원칙이다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    _freeze(judging_ends_at + timedelta(minutes=1))
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 409
    assert Contest.objects.get(id=contest["id"]).judging_extension_count == 0


@pytest.mark.django_db
def test_extension_after_award_is_rejected(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    award_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert award_resp.status_code == 200

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 409
    assert Contest.objects.get(id=contest["id"]).judging_extension_count == 0


@pytest.mark.django_db
def test_failed_extension_payment_does_not_touch_the_contest(client, category, landing_type):
    """결제 실패는 402를 돌려주고 judging_ends_at·연장 횟수 어느 것도 건드리지
    않는다 — 돈이 안 들어왔는데 심사기간만 늘어나는 사고를 막는다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    before = Contest.objects.get(id=contest["id"])

    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={"simulate": "failed"},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 402

    after = Contest.objects.get(id=contest["id"])
    assert after.judging_ends_at == before.judging_ends_at
    assert after.judging_extension_count == 0
    assert after.refund_disabled is False


# --- 마감 이후에도 목록·상세·아카이브가 계속 공개된다는 계약(#11)이 새 상태에서도
# 이어진다 (#12 리뷰 지적 5의 재발 방지) -------------------------------------------


@pytest.mark.django_db
def test_awarded_and_judging_ended_contests_stay_publicly_visible(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    award_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/award",
        data={"submission_id": submission["id"]},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert award_resp.status_code == 200

    detail_resp = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail_resp.status_code == 200
    assert detail_resp.json()["status"] == "awarded"

    list_resp = client.get(CONTESTS_URL)
    assert list_resp.status_code == 200
    assert contest["id"] in [c["id"] for c in list_resp.json()["items"]]

    # Developer 본인도 자기 Submission을 계속 조회할 수 있다.
    me_resp = client.get(
        f"{CONTESTS_URL}/{contest['id']}/submissions/me", **_auth_header(dev["access"])
    )
    assert me_resp.status_code == 200
    assert me_resp.json()["id"] == submission["id"]
