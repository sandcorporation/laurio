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
from contests.models import Category, Contest, DeliverableType, JudgingExtensionPayment
from core.models import ClockOverride
from core.transitions import TRANSITION_REGISTRY
from policies.services import get_current_policy

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


def _initiate_extension(client, sponsor: dict, contest_id: int) -> dict:
    resp = client.post(
        f"{CONTESTS_URL}/{contest_id}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 201, resp.content
    return resp.json()


def _confirm_extension(client, sponsor: dict, contest_id: int, order_id: str, *, simulate=None):
    return client.post(
        f"{CONTESTS_URL}/{contest_id}/extend-judging-period/{order_id}/confirm",
        data={"simulate": simulate} if simulate is not None else {},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )


def _extend(client, sponsor: dict, contest_id: int, *, simulate=None) -> dict:
    """initiate + confirm을 한 번에 — payments.api의 두 단계 구조를 그대로 따르는
    연장 결제를, 대부분의 테스트가 신경 쓰지 않아도 되는 해피 패스로 감싼다."""

    initiated = _initiate_extension(client, sponsor, contest_id)
    confirm_resp = _confirm_extension(
        client, sponsor, contest_id, initiated["order_id"], simulate=simulate
    )
    assert confirm_resp.status_code == 200, confirm_resp.content
    return confirm_resp.json()


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
    # judging_ends_at은 스캔이 실제로 실행된 시각(close_at)이 아니라 이 Contest
    # 자신의 deadline_at에서 파생된다(#13 리뷰 지적 4) — REQUEST.md의 "마감 후
    # 7일"은 마감 시각 기준이지 스캔이 도착한 시각 기준이 아니다. 이 테스트에서는
    # deadline과 close_at이 1분밖에 안 떨어져 있어 차이가 작아 보이지만, 아래
    # test_judging_ends_at_is_derived_from_each_contests_own_deadline이 그 차이를
    # 직접 증명한다.
    expected_judging_ends_at = deadline + timedelta(days=get_current_policy().judging_period_days)
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
def test_judging_period_length_follows_policy_change_not_a_hardcoded_default(
    client, category, landing_type
):
    """운영자가 심사기간을 바꾸면 그 뒤에 마감되는 Contest의 judging_ends_at이
    실제로 달라진다(#78 AC) — "정책 행에 값이 저장됐다"로 멈추지 않고 효과를
    확인한다. 기본값(7일)이 아니라 정책 행이 정한 값(여기서는 3일)으로
    judging_ends_at이 계산되는지를 직접 비교한다 — contests/apps.py가 여전히
    7을 하드코딩하고 있다면 이 테스트가 실제로 빨개진다.
    """

    from policies.models import PlatformPolicy

    PlatformPolicy.objects.update_or_create(pk=1, defaults={"judging_period_days": 3})

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )

    _close_contest(client, contest, deadline=deadline)

    closed = Contest.objects.get(id=contest["id"])
    assert closed.judging_ends_at == deadline + timedelta(days=3)
    # 바뀌기 전 기본값(7일)으로 계산했다면 나왔을 시각과는 다르다는 것을
    # 명시적으로 대조한다.
    assert closed.judging_ends_at != deadline + timedelta(days=7)


@pytest.mark.django_db
def test_judging_ends_at_is_derived_from_each_contests_own_deadline(client, category, landing_type):
    """#13 리뷰 지적 4의 핵심 증명 — 마감 시각이 서로 다른 두 Contest가 같은 틱에
    우연히 함께 CLOSED로 넘어가도, 둘의 judging_ends_at은 서로 다르다(각자의
    deadline_at + JUDGING_PERIOD_DAYS). extra_fields가 배치 전체가 공유하는 as_of가
    아니라 각 행 자신에게서 값을 파생시켜야만 이게 성립한다.

    두 deadline의 간격은 JUDGING_PERIOD_DAYS(기본 7일)보다 훨씬 짧게 잡는다 —
    간격이 그보다 크면 이 틱 한 번(PUBLISHED -> CLOSED에 이어 CLOSED ->
    JUDGING_ENDED까지 같은 as_of로 순차 처리한다, core.transitions.
    run_due_transitions)이 먼저 닫힌 Contest의 심사기간까지 함께 끝내버려 CLOSED
    상태로 비교할 수 없게 된다."""

    early_deadline = timezone.now() + timedelta(hours=1)
    late_deadline = early_deadline + timedelta(hours=2)

    _sponsor_a, contest_a = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid="sponsor-early",
        sponsor_ci="sponsor-early-ci",
        deadline_at=early_deadline,
    )
    _sponsor_b, contest_b = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid="sponsor-late",
        sponsor_ci="sponsor-late-ci",
        deadline_at=late_deadline,
    )

    # 두 Contest 모두 이제 마감이 지난 시각으로 한 번에 틱을 쏜다 — 같은 as_of를
    # 공유하는 같은 스캔 배치 안에서 둘 다 CLOSED로 전이한다.
    _freeze(late_deadline + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    transitioned_ids = {t["pk"] for t in tick_resp.json()["transitioned"] if t["model"] == "Contest"}
    assert {contest_a["id"], contest_b["id"]} <= transitioned_ids

    closed_a = Contest.objects.get(id=contest_a["id"])
    closed_b = Contest.objects.get(id=contest_b["id"])
    assert closed_a.status == Contest.Status.CLOSED
    assert closed_b.status == Contest.Status.CLOSED

    assert closed_a.judging_ends_at == early_deadline + timedelta(days=get_current_policy().judging_period_days)
    assert closed_b.judging_ends_at == late_deadline + timedelta(days=get_current_policy().judging_period_days)
    assert closed_a.judging_ends_at != closed_b.judging_ends_at


@pytest.mark.django_db
def test_judging_period_ends_exactly_at_judging_ends_at_boundary(client, category, landing_type):
    """스케줄러는 judging_ends_at <= as_of일 때 전이한다 — 경계 순간(now ==
    judging_ends_at)도 이미 끝난 것으로 본다(#13 리뷰 지적 7)."""

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    _freeze(judging_ends_at)
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
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
def test_award_is_refused_exactly_at_judging_ends_at_boundary(client, category, landing_type):
    """now == judging_ends_at도 이미 심사기간이 끝난 것으로 본다 — 스케줄러가
    `judging_ends_at <= as_of`에서 전이하는 것과 같은 경계(#13 리뷰 지적 7).
    `>`였다면 이 순간에는 통과해버려 스케줄러의 판단과 어긋난다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"])
    _close_contest(client, contest, deadline=deadline)

    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at
    _freeze(judging_ends_at)

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
#
# payments.api.initiate_payment/confirm_payment와 같은 두 단계 구조를 그대로
# 따른다: initiate가 결제 의도를 영속화하고, confirm이 PG 결과를 실제로 반영한다
# (#13 리뷰 지적 1/2/3). _extend() 헬퍼가 이 둘을 한 번에 묶어 대부분의 테스트가
# 해피 패스에 집중할 수 있게 한다 — 두 단계 자체를 검증하는 테스트는 _initiate_
# extension/_confirm_extension을 따로 부른다.


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

    body = _extend(client, sponsor, contest["id"])
    assert body["status"] == "paid"
    assert body["judging_extension_count"] == 1
    assert body["refund_disabled"] is False

    registry_size_after = len(TRANSITION_REGISTRY)
    assert registry_size_after == registry_size_before

    extended = Contest.objects.get(id=contest["id"])
    expected = original_judging_ends_at + timedelta(days=get_current_policy().judging_extension_days)
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
def test_extension_days_is_snapshotted_at_initiate_not_re_read_at_confirm(
    client, category, landing_type
):
    """#78 코드리뷰 지적 2 — initiate와 confirm 사이에 운영자가
    judging_extension_days를 바꿔도, 이미 청구된 금액(amount)과 실제로
    늘어나는 심사기간이 같은 시점(initiate)의 정책값을 가리켜야 한다.
    confirm 시점에 정책을 다시 읽으면 Sponsor가 (initiate 시점 기준) 7일치
    금액을 내고 3일만 받는 불일치가 생긴다 — extension_days 스냅샷을 없애고
    confirm이 정책을 다시 읽게 되돌리면 이 테스트가 빨간불이 된다.
    """

    from policies.models import PlatformPolicy

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    original_judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    initiated = _initiate_extension(client, sponsor, contest["id"])
    original_extension_days = get_current_policy().judging_extension_days
    assert initiated["amount"] == get_current_policy().judging_extension_fee

    # initiate와 confirm 사이에 운영자가 연장 단위를 7일에서 3일로 바꾼다.
    PlatformPolicy.objects.update_or_create(pk=1, defaults={"judging_extension_days": 3})

    confirm_resp = _confirm_extension(client, sponsor, contest["id"], initiated["order_id"])
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["amount"] == initiated["amount"]

    extended = Contest.objects.get(id=contest["id"])
    # initiate 시점(7일, 스냅샷)대로 늘어나야 한다 — confirm 시점에 바뀐 새
    # 값(3일)이 아니다.
    assert extended.judging_ends_at == original_judging_ends_at + timedelta(
        days=original_extension_days
    )
    assert extended.judging_ends_at != original_judging_ends_at + timedelta(days=3)


@pytest.mark.django_db
def test_extension_confirm_persists_journal_entry_and_updates_auto_now(
    client, category, landing_type
):
    """#13 리뷰 지적 6 — claim_transition을 거치므로 updated_at(auto_now)이
    실제로 갱신된다. 그리고 결제가 실제로 원장에 분개로 남는다(대사 가능성,
    #13 리뷰 지적 1)."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    before = Contest.objects.get(id=contest["id"])
    original_updated_at = before.updated_at

    _freeze(Contest.objects.get(id=contest["id"]).judging_ends_at - timedelta(minutes=30))
    _extend(client, sponsor, contest["id"])

    after = Contest.objects.get(id=contest["id"])
    assert after.updated_at != original_updated_at

    payment = JudgingExtensionPayment.objects.get(contest_id=contest["id"])
    assert payment.status == JudgingExtensionPayment.Status.PAID
    assert payment.journal_entry_id is not None

    from ledger.services import contest_entries

    entries = list(contest_entries(Contest.objects.get(id=contest["id"]).ledger_id))
    assert any(e.id == payment.journal_entry_id for e in entries)


@pytest.mark.django_db
def test_two_or_more_extensions_permanently_disable_refund(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    first = _extend(client, sponsor, contest["id"])
    assert first["judging_extension_count"] == 1
    assert first["refund_disabled"] is False
    assert Contest.objects.get(id=contest["id"]).refund_disabled is False

    second = _extend(client, sponsor, contest["id"])
    assert second["judging_extension_count"] == 2
    assert second["refund_disabled"] is True
    assert Contest.objects.get(id=contest["id"]).refund_disabled is True

    # 세 번째 연장 이후에도 계속 True로 남는다("영구히"의 실제 구현).
    third = _extend(client, sponsor, contest["id"])
    assert third["judging_extension_count"] == 3
    assert third["refund_disabled"] is True

    # judging_extension_count·refund_disabled는 공개 Contest 상세에는 없다(#13
    # 리뷰 지적 8) — 연장 결제 응답에서만(Sponsor 본인 인증) 확인할 수 있다.
    detail = client.get(f"{CONTESTS_URL}/{contest['id']}")
    assert detail.status_code == 200
    assert "refund_disabled" not in detail.json()
    assert "judging_extension_count" not in detail.json()
    assert Contest.objects.get(id=contest["id"]).judging_extension_count == 3
    assert Contest.objects.get(id=contest["id"]).refund_disabled is True


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
    assert JudgingExtensionPayment.objects.count() == 0


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
    assert JudgingExtensionPayment.objects.count() == 0


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
def test_extension_is_rejected_exactly_at_judging_ends_at_boundary(client, category, landing_type):
    """now == judging_ends_at도 이미 끝난 것으로 본다 — Award의 경계 판정
    (test_award_is_refused_exactly_at_judging_ends_at_boundary)과 같은 `>=`
    (#13 리뷰 지적 7)."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    _freeze(judging_ends_at)
    resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/extend-judging-period",
        data={},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert resp.status_code == 409


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
    """결제 실패는 confirm 응답에 "failed"를 돌려주고 judging_ends_at·연장
    횟수·refund_disabled 어느 것도 건드리지 않는다 — 돈이 안 들어왔는데 심사기간만
    늘어나는 사고를 막는다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    before = Contest.objects.get(id=contest["id"])

    initiated = _initiate_extension(client, sponsor, contest["id"])
    confirm_resp = _confirm_extension(
        client, sponsor, contest["id"], initiated["order_id"], simulate="failed"
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "failed"

    after = Contest.objects.get(id=contest["id"])
    assert after.judging_ends_at == before.judging_ends_at
    assert after.judging_extension_count == 0
    assert after.refund_disabled is False
    assert JudgingExtensionPayment.objects.get(order_id=initiated["order_id"]).status == (
        JudgingExtensionPayment.Status.FAILED
    )


# --- 결제 규율: payments 앱과 같은 멱등성·타임아웃·동시성 방어 (#13 리뷰 지적 1/2/3) ---


@pytest.mark.django_db
def test_initiate_persists_intent_before_any_pg_call_so_it_is_recoverable(
    client, category, landing_type
):
    """#13 리뷰 지적 1 — initiate 시점에 이미 JudgingExtensionPayment(REQUESTED)가
    DB에 남는다. confirm을 아예 부르지 않아도(클라이언트가 죽거나, PG 콜백을
    영영 못 받아도) 이 행이 대사 대상으로 남아 있다 — "돈이 플랫폼 관점에서
    통째로 사라지는" 사고를 막는 최소 조건이다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    initiated = _initiate_extension(client, sponsor, contest["id"])
    assert initiated["status"] == "requested"

    payment = JudgingExtensionPayment.objects.get(order_id=initiated["order_id"])
    assert payment.status == JudgingExtensionPayment.Status.REQUESTED
    assert payment.contest_id == contest["id"]
    assert payment.journal_entry_id is None

    # 연장은 아직 전혀 적용되지 않았다 — confirm이 확정해야만 적용된다.
    assert Contest.objects.get(id=contest["id"]).judging_extension_count == 0


@pytest.mark.django_db
def test_double_clicking_extend_before_confirming_reuses_the_same_pending_payment(
    client, category, landing_type
):
    """#13 리뷰 지적 2 — 더블클릭(같은 REQUESTED 결제가 아직 안 끝났는데 다시
    initiate)이 두 번째 주문을 새로 만들지 않는다.
    unique_pending_judging_extension_payment_per_contest가 두 번째 방어선이고,
    이 응답 레벨에서는 첫 번째 결제를 그대로 재사용해서 보인다(payments.api.
    initiate_payment의 existing 재사용 분기와 같은 형태)."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    first = _initiate_extension(client, sponsor, contest["id"])
    second = _initiate_extension(client, sponsor, contest["id"])

    assert first["order_id"] == second["order_id"]
    assert JudgingExtensionPayment.objects.filter(contest_id=contest["id"]).count() == 1

    # 딱 한 번만 confirm해도 정확히 한 번만 연장된다.
    confirm_resp = _confirm_extension(client, sponsor, contest["id"], first["order_id"])
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["judging_extension_count"] == 1


@pytest.mark.django_db
def test_confirming_the_same_extension_payment_twice_does_not_double_charge(
    client, category, landing_type
):
    """#13 리뷰 지적 2 — 같은 order_id로 confirm이 재전송되거나 재시도돼도
    (payments.api.confirm_payment의 웹훅 재전송 시나리오와 같은 형태) 원장 분개와
    심사기간 연장은 정확히 한 번만 일어난다. `JudgingExtensionPayment.status`의
    조건부 UPDATE(REQUESTED -> PAID)가 그 방어선이다 — 순차 호출로도 그 DB 레벨
    보장을 그대로 관찰할 수 있다(코드베이스 전체가 "틱을 두 번 쏴도 한 번만
    통과한다"를 검증하는 방식과 동일)."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    original_judging_ends_at = Contest.objects.get(id=contest["id"]).judging_ends_at

    initiated = _initiate_extension(client, sponsor, contest["id"])

    first_confirm = _confirm_extension(client, sponsor, contest["id"], initiated["order_id"])
    second_confirm = _confirm_extension(client, sponsor, contest["id"], initiated["order_id"])

    assert first_confirm.status_code == 200
    assert second_confirm.status_code == 200
    assert first_confirm.json()["status"] == "paid"
    assert second_confirm.json()["status"] == "paid"
    assert second_confirm.json()["judging_extension_count"] == 1

    extended = Contest.objects.get(id=contest["id"])
    assert extended.judging_extension_count == 1
    assert extended.judging_ends_at == original_judging_ends_at + timedelta(
        days=get_current_policy().judging_extension_days
    )

    payment = JudgingExtensionPayment.objects.get(order_id=initiated["order_id"])
    assert payment.status == JudgingExtensionPayment.Status.PAID

    from ledger.services import contest_entries

    entries = [
        e
        for e in contest_entries(extended.ledger_id)
        if e.id == payment.journal_entry_id
    ]
    assert len(entries) == 1


@pytest.mark.django_db
def test_extension_confirm_timeout_resolves_via_query_status_and_still_applies(
    client, category, landing_type
):
    """#13 리뷰 지적 1 — confirm 호출이 타임아웃돼도 곧바로 실패로 단정하지 않고
    query_status로 실제 결과를 확정한다(ADR-0008). PG 쪽에서는 실제로 성공했다면
    연장이 정상 적용돼야 한다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)

    initiated = _initiate_extension(client, sponsor, contest["id"])
    confirm_resp = _confirm_extension(
        client, sponsor, contest["id"], initiated["order_id"], simulate="timeout_then_success"
    )

    assert confirm_resp.status_code == 200
    body = confirm_resp.json()
    assert body["status"] == "paid"
    assert body["judging_extension_count"] == 1

    payment = JudgingExtensionPayment.objects.get(order_id=initiated["order_id"])
    assert payment.status == JudgingExtensionPayment.Status.PAID
    assert payment.journal_entry_id is not None


@pytest.mark.django_db
def test_extension_confirm_timeout_then_failed_does_not_apply(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    before = Contest.objects.get(id=contest["id"])

    initiated = _initiate_extension(client, sponsor, contest["id"])
    confirm_resp = _confirm_extension(
        client, sponsor, contest["id"], initiated["order_id"], simulate="timeout_then_failed"
    )

    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["status"] == "failed"

    after = Contest.objects.get(id=contest["id"])
    assert after.judging_ends_at == before.judging_ends_at
    assert after.judging_extension_count == 0
    payment = JudgingExtensionPayment.objects.get(order_id=initiated["order_id"])
    assert payment.status == JudgingExtensionPayment.Status.FAILED
    assert payment.journal_entry_id is None


@pytest.mark.django_db
def test_extension_confirm_for_someone_elses_order_id_is_rejected(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline
    )
    _close_contest(client, contest, deadline=deadline)
    outsider = _verified_user(client, "outsider", "outsider-ci")

    initiated = _initiate_extension(client, sponsor, contest["id"])
    resp = _confirm_extension(client, outsider, contest["id"], initiated["order_id"])
    assert resp.status_code == 403

    assert JudgingExtensionPayment.objects.get(
        order_id=initiated["order_id"]
    ).status == JudgingExtensionPayment.Status.REQUESTED


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
