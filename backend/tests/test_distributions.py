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
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from distributions.models import Distribution, DistributionShare
from ledger.services import contest_balance, contest_entries
from payouts.models import Payout
from policies.models import PlatformPolicy
from policies.services import get_current_policy
from storage.adapters.fake import FakeStorageAdapter
from submissions.models import Submission

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


def _submit_multi(
    client, dev: dict, contest_id: int, *, requirement_ids: list[int], grounded_flags: list[bool]
) -> dict:
    """여러 Requirement에 대해 각각 grounded 여부를 따로 지정해 제출한다 — 0%나
    100%가 아닌 중간 백분율(예: 2개 중 1개만 grounded = 50%)이 필요한 테스트에
    쓴다(`_submit`을 여러 Requirement로 일반화한 것, test_scoring.py의
    `_PartialVerdictAdapter` 테스트가 확인한 것과 같은 산식 — met/total * 100).
    """

    assert len(requirement_ids) == len(grounded_flags)
    source_key = _source_object_key(contest_id, dev["user_id"])
    marker = f"MARKER_{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": f"# {marker}\n"}))

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": rid,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": marker}] if grounded else [],
                }
                for rid, grounded in zip(requirement_ids, grounded_flags)
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
        + timedelta(days=get_current_policy().distribution_wait_days, minutes=1)
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
    """모든 테스트가 같은 기본 컷라인(60%)에서 출발하게 한다(#79 — PlatformPolicy로
    흡수된 뒤에도 옛 DistributionCutline 픽스처와 같은 역할)."""

    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"distribution_cutline_percentage": Decimal("60.00")}
    )


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

    # 운영자가 컷라인을 낮췄다고 가정한다 — DB 행을 직접 조정한다(지금은
    # `manage.py shell`이 유일한 경로다, #76 전. core.models.ClockOverride를
    # 테스트가 직접 조정하는 것과 같은 관용구).
    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"distribution_cutline_percentage": Decimal("0.00")}
    )

    _run_due_distributions(client)

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.qualifying_count == 1
    assert distribution.cutline_percentage == Decimal("0.00")
    assert DistributionShare.objects.filter(submission_id=submission_low["id"]).exists()


@pytest.mark.django_db
def test_raising_cutline_disqualifies_a_submission_that_previously_cleared_it(
    client, category, landing_type
):
    """운영자가 컷라인을 올리면, 그 전이었다면 통과했을 Submission이 배분에서
    빠진다(#79 AC) — "값이 저장됐다"가 아니라 자격자 집합(배분 결과) 자체가
    실제로 바뀌는 것을 본다.

    "이전에는 통과했다"를 실제로 증명하려면 낮은 컷라인에서 진짜로 통과하는
    것부터 봐야 한다(코드리뷰 지적 #79 후속) — Distribution은 Contest 하나에
    최대 한 번만 만들어지므로, 같은 Contest로 "전"과 "후"를 둘 다 볼 수는
    없다. 그래서 조건이 동일한 두 Contest를 쓴다:

    - contest_control: 컷라인 40%에서 배분한다. 50%짜리 dev_mid_control이
      실제로 자격을 얻는다는 것을 먼저 확인한다(positive control) — 이 확인이
      없으면 뒤의 "raising it disqualified a submission that previously
      cleared it"이라는 주장은 근거 없는 이름일 뿐이다.
    - contest_treatment: 완전히 동일한 조건(같은 두 required Requirement,
      같은 50% 채점)이지만, Distribution이 만들어지기 직전에 운영자가 컷라인을
      70%로 올린다 — 이제 그 50%는 더 이상 넘지 못한다. dev_high_treatment
      (100%, 두 요건 모두 grounded)를 함께 둬 컷라인 미달자뿐이라 컷라인이
      waive되는 경우(cutline_waived)와 "진짜로 컷라인에 걸려 제외됨"을
      구별한다.
    """

    # --- control: 컷라인 40%에서 50%짜리 제출작이 실제로 통과한다 -----------------

    deadline_control = timezone.now() + timedelta(hours=1)
    _, contest_control = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline_control,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "결제 기능이 있다", "grade": "required"},
        ],
        prize=1_000_000,
        sponsor_uid="sponsor-cutline-control",
        sponsor_ci="sponsor-cutline-control-ci",
    )
    control_requirement_ids = [r["id"] for r in contest_control["requirements"]]

    dev_mid_control = _verified_user(client, "dev-mid-control", "dev-mid-control-ci")
    submission_mid_control = _submit_multi(
        client,
        dev_mid_control,
        contest_control["id"],
        requirement_ids=control_requirement_ids,
        grounded_flags=[True, False],
    )

    _close_contest(client, contest_control, deadline=deadline_control)
    _run_scoring(client)
    _end_judging_period(client, contest_control["id"])
    _advance_past_distribution_wait(contest_control["id"])

    score_control = Submission.objects.get(id=submission_mid_control["id"]).score.percentage
    assert score_control == Decimal("50.00")

    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"distribution_cutline_percentage": Decimal("40.00")}
    )
    _run_due_distributions(client)

    distribution_control = Distribution.objects.get(contest_id=contest_control["id"])
    assert distribution_control.cutline_percentage == Decimal("40.00")
    assert distribution_control.cutline_waived is False
    # positive control — 40%에서는 50%짜리가 실제로 자격을 얻는다.
    assert DistributionShare.objects.filter(submission_id=submission_mid_control["id"]).exists()

    # --- treatment: 같은 조건, 다만 배분 직전에 컷라인을 70%로 올린다 -------------

    # control 처리가 시계를 (배분 대기 기간만큼) 미래로 돌려놨다 — 그대로 두면
    # 곧 발행할 contest_treatment의 마감이 이미 "지난" 것으로 보여 제출 자체가
    # 403으로 막힌다. 실제 지금 시각으로 되돌린다(이후 _close_contest 등이 각
    # 자신의 기준으로 다시 얼린다).
    _freeze(timezone.now())

    deadline_treatment = timezone.now() + timedelta(hours=2)
    _, contest_treatment = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline_treatment,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "결제 기능이 있다", "grade": "required"},
        ],
        prize=1_000_000,
        sponsor_uid="sponsor-cutline-treatment",
        sponsor_ci="sponsor-cutline-treatment-ci",
    )
    treatment_requirement_ids = [r["id"] for r in contest_treatment["requirements"]]

    dev_high_treatment = _verified_user(client, "dev-high-treatment", "dev-high-treatment-ci")
    submission_high_treatment = _submit_multi(
        client,
        dev_high_treatment,
        contest_treatment["id"],
        requirement_ids=treatment_requirement_ids,
        grounded_flags=[True, True],
    )

    dev_mid_treatment = _verified_user(client, "dev-mid-treatment", "dev-mid-treatment-ci")
    submission_mid_treatment = _submit_multi(
        client,
        dev_mid_treatment,
        contest_treatment["id"],
        requirement_ids=treatment_requirement_ids,
        grounded_flags=[True, False],
    )

    _close_contest(client, contest_treatment, deadline=deadline_treatment)
    _run_scoring(client)
    _end_judging_period(client, contest_treatment["id"])
    _advance_past_distribution_wait(contest_treatment["id"])

    score_treatment = Submission.objects.get(id=submission_mid_treatment["id"]).score.percentage
    assert score_treatment == Decimal("50.00")

    # 운영자가 배분 실행 전에 컷라인을 70%로 올린다 — 같은 50%가 이제는 못 넘고,
    # dev_high_treatment(100%)는 여전히 넘는다.
    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"distribution_cutline_percentage": Decimal("70.00")}
    )
    _run_due_distributions(client)

    distribution_treatment = Distribution.objects.get(contest_id=contest_treatment["id"])
    assert distribution_treatment.cutline_percentage == Decimal("70.00")
    # dev_high_treatment가 진짜로 컷라인을 넘어 자격을 얻으므로, dev_mid_treatment의
    # 제외는 "아무도 못 넘어 waive됐다"가 아니라 컷라인에 실제로 걸린 것이다.
    assert distribution_treatment.cutline_waived is False
    assert distribution_treatment.qualifying_count == 1
    assert DistributionShare.objects.filter(
        submission_id=submission_high_treatment["id"]
    ).exists()
    assert not DistributionShare.objects.filter(
        submission_id=submission_mid_treatment["id"]
    ).exists()


@pytest.mark.django_db
def test_changing_the_policy_cutline_does_not_alter_an_already_created_distribution(
    client, category, landing_type
):
    """`Distribution.cutline_percentage`는 스냅샷이다(#79 AC, ADR-0006이 Score에
    대해 세운 것과 같은 규율) — 배분이 이미 만들어진 뒤 운영자가
    `PlatformPolicy.distribution_cutline_percentage`를 바꿔도, 그 배분이 그때
    실제로 쓴 값은 흔들리지 않는다.
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
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])

    # 이 스캔은 기본 컷라인(60%, _default_cutline 픽스처)으로 배분을 만든다.
    _run_due_distributions(client)
    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.cutline_percentage == Decimal("60.00")

    # 운영자가 그 뒤에 정책 컷라인을 90%로 올린다 — 미래의 배분에만 영향을 줘야
    # 하고, 이미 만들어진 이 Distribution의 기록은 바뀌면 안 된다.
    PlatformPolicy.objects.update_or_create(
        pk=1, defaults={"distribution_cutline_percentage": Decimal("90.00")}
    )

    distribution.refresh_from_db()
    assert distribution.cutline_percentage == Decimal("60.00")

    # 정책값 자체는 실제로 바뀌었다는 것도 확인한다 — 위 unchanged 단언이
    # "애초에 아무것도 안 바뀌었다"가 아니라 진짜 스냅샷임을 보장한다.
    assert PlatformPolicy.objects.get(pk=1).distribution_cutline_percentage == Decimal("90.00")


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


@pytest.mark.django_db
def test_platform_policy_is_read_once_per_scan_not_once_per_share(
    client, category, landing_type
):
    """정책 읽기는 스캔 스코프당 한 번이다(#75, ADR-0023) — 몫마다 다시 읽으면
    채점·배분·지급 경로에서 쿼리가 몫 수만큼 늘어난다. 3개 몫을 만들어 그 스캔
    도중 platform_policy 테이블을 정확히 한 번만 쳤는지를 실제로 센다 —
    "요청 스코프당 한 번"이라는 주장을 코드 리딩이 아니라 쿼리 수로 증명한다."""

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

    devs = [_verified_user(client, f"dev-qpol-{i}", f"dev-qpol-{i}-ci") for i in range(3)]
    for dev in devs:
        _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])

    # 정책 행이 미리 있는지 다시 한 번 확인한다(_default_cutline 픽스처가 이미
    # PlatformPolicy를 만들어 두지만, 명시적으로 남겨 이 테스트의 전제를 분명히
    # 한다) — 그래야 스캔 도중 잡히는 쿼리가 순수하게 "몫마다 다시 읽는가"만
    # 잰다. 행이 없으면 get_or_create의 최초 생성이 SELECT+INSERT 두 문장을
    # 내므로, 그 생성 비용까지 섞이면 "몫 수만큼 늘었는지"를 못 가린다.

    PlatformPolicy.objects.get_or_create(pk=1)

    with CaptureQueriesContext(connection) as ctx:
        _run_due_distributions(client)

    policy_queries = [q for q in ctx.captured_queries if "policies_platformpolicy" in q["sql"]]
    payouts = Payout.objects.filter(distribution_share__distribution__contest_id=contest["id"])
    assert payouts.count() == 3
    assert len(policy_queries) == 1, (
        f"platform_policy 테이블 쿼리가 {len(policy_queries)}번 나갔다 — 몫(3개)마다 "
        "다시 읽으면 안 되고 스캔당 한 번이어야 한다."
    )

    # 쿼리 수만 세고 배분 몫 Payout이 실제로 요율 스냅샷을 제대로 기록하는지는
    # 확인하지 않았다는 코드리뷰 지적(#75 후속) — 지급 요청 경로만이 아니라
    # 배분 경로로 만들어진 Payout도 확인한다. 몫(1,000,000원)은 면제 임계값
    # (250,000원) 위이므로 정상적으로 요율이 걷힌다.
    for payout in payouts:
        assert payout.platform_fee_bps == 1000
        assert payout.withholding_tax_bps == 440
        assert payout.withholding_exempt is False
        assert payout.withholding_tax_amount == 1_000_000 * 440 // 10_000


@pytest.mark.django_db
def test_distribution_shares_at_or_below_the_withholding_threshold_are_exempt(
    client, category, landing_type
):
    """배분으로 만들어진 Payout도 과세최저한 면제를 제대로 적용한다 — 1/N
    배분 몫은 250,000원 이하가 흔한 경우다(#75 코드리뷰 지적 4). 위 스냅샷
    테스트가 (수정 전처럼) `get_or_create_payout`에 넘기는 `platform_fee_bps`/
    `withholding_tax_bps` kwargs를 지워도 통과했다는 지적을 받았으므로, 이 값이
    실제로 배분 경로에서도 쓰인다는 것을 이 테스트로 증명한다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=700_000,
    )
    requirement_id = contest["requirements"][0]["id"]

    devs = [_verified_user(client, f"dev-exempt-{i}", f"dev-exempt-{i}-ci") for i in range(3)]
    for dev in devs:
        _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)

    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])
    _run_due_distributions(client)

    distribution = Distribution.objects.get(contest_id=contest["id"])
    assert distribution.qualifying_count == 3
    assert distribution.share_amount == 233_333  # 700,000 // 3 — 250,000원 이하.

    payouts = Payout.objects.filter(distribution_share__distribution=distribution)
    assert payouts.count() == 3
    for payout in payouts:
        assert payout.prize_amount == 233_333
        assert payout.withholding_tax_amount == 0
        assert payout.withholding_exempt is True
        assert payout.withholding_tax_bps == 0  # 정책의 명목 요율(440)이 아니다.
        # 수수료는 면제 대상이 아니므로 그대로 걷힌다.
        assert payout.platform_fee_bps == 1000
        assert payout.platform_fee_amount == 233_333 * 1000 // 10_000
        assert payout.net_amount == payout.prize_amount - payout.platform_fee_amount


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


# --- 심판 대기 중인 이의는 배분을 막는다 (#74) ------------------------------------


@pytest.mark.django_db
def test_a_pending_appeal_holds_the_distribution_for_that_contest(
    client, category, landing_type
):
    """심판되지 않은 이의가 있으면 그 Contest 의 배분을 진행하지 않는다 (#74).

    이의가 묻는 것이 정확히 "내 점수가 컷라인을 넘는가" 이고, 점수가 돈을
    정하는 유일한 곳이 배분의 컷라인이다(`Score` 는 Award 를 결정하지 않는다 —
    ADR-0006/0014). 답이 안 나온 채 배분하면 이의 제도 자체가 무의미해진다.

    **대가를 알고 택한 결정이다**: 한 사람의 이의가 그 Contest 의 배분 전체를
    멈춘다 — 다른 참가자들의 돈도 함께 미뤄진다. 그래서 운영자 큐가 "이 이의가
    배분을 막고 있다" 를 보여줘야 한다(#74 스펙).
    """

    seeded = _seed_scored_contest(client, category, landing_type, uid="dev-hold")

    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "컷라인 판정에 이의가 있습니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert filed.status_code == 201, filed.content

    _advance_to_distribution_due(client, seeded["contest_id"])
    _run_due_distributions(client)

    assert not Distribution.objects.filter(contest_id=seeded["contest_id"]).exists(), (
        "심판 대기 중인 이의가 있는데 배분이 만들어졌다"
    )


@pytest.mark.django_db
def test_the_hold_lifts_once_the_appeal_is_ruled(client, category, landing_type):
    """심판이 끝나면 다음 스캔이 배분한다 — 보류는 실패가 아니다.

    위 테스트만 있으면 "영원히 막힘" 도 통과한다. 보류가 **풀린다**는 것을
    함께 고정해야 그 결정이 돈이 사라지는 경로가 아님을 증명한다(ADR-0020).
    """

    seeded = _seed_scored_contest(client, category, landing_type, uid="dev-lift")
    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "재검토를 요청합니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert filed.status_code == 201
    appeal_id = filed.json()["id"]

    _advance_to_distribution_due(client, seeded["contest_id"])
    _run_due_distributions(client)
    assert not Distribution.objects.filter(contest_id=seeded["contest_id"]).exists()

    from tests.test_source_readings import OPERATOR_ORIGIN, _operator_client

    operator = _operator_client("op-distribution-hold")
    ruled = operator.post(
        f"/api/operator/appeals/{appeal_id}/rule",
        data={"decision": "reject", "ruling_note": "판정을 유지한다."},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert ruled.status_code == 200, ruled.content

    _run_due_distributions(client)

    assert Distribution.objects.filter(contest_id=seeded["contest_id"]).exists(), (
        "심판이 끝났는데도 다음 스캔이 배분하지 않았다 — 보류가 영구 정지가 됐다"
    )


def _seed_scored_contest(client, category, landing_type, *, uid: str) -> dict:
    """채점까지 끝낸 상태 — 아직 심사기간 안이라 이의를 낼 수 있다.

    **순서가 중요하다.** 이의 기한은 심사기간 종료이고(#74) 배분은 그로부터
    14일 뒤다. 그래서 "배분을 막는 이의" 는 **심사기간 안에 내고 심판이 늦어진**
    것일 수밖에 없다 — 배분 시점에는 이미 새 이의를 낼 수 없다. 이 헬퍼가
    채점까지만 하고 멈추는 이유다.
    """

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        sponsor_uid=f"{uid}-sponsor",
        sponsor_ci=f"{uid}-sponsor-ci",
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    dev = _verified_user(client, uid, f"{uid}-ci")
    submission = _submit(
        client,
        dev,
        contest["id"],
        requirement_id=contest["requirements"][0]["id"],
        grounded=True,
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    return {
        "access": dev["access"],
        "submission_id": submission["id"],
        "contest_id": contest["id"],
    }


def _advance_to_distribution_due(client, contest_id: int) -> None:
    _end_judging_period(client, contest_id)
    _advance_past_distribution_wait(contest_id)


_OPERATOR_SEQ = 0


def _operator_appeals(client) -> list[dict]:
    """운영자 큐를 읽는다. Operator 는 Developer 와 서로소인 신원이라 클라이언트를
    따로 쓴다(ADR-0018).

    **캐시하지 않는다.** 세션은 실제 Redis 에 살지만(ADR-0018) Operator 행은
    테스트 트랜잭션과 함께 롤백되므로, 앞 테스트의 클라이언트를 재사용하면 세션은
    남았는데 가리키는 사용자가 없어 401 이 난다.
    """

    from tests.test_appeals import _operator_client

    # 이름이 매번 달라야 한다 — 한 테스트가 큐를 두 번 읽으면(막기 전·후) 같은
    # 이름으로 두 번 만들게 되고, `create_operator` 는 중복을 거절한다.
    global _OPERATOR_SEQ
    _OPERATOR_SEQ += 1
    operator = _operator_client(f"op-hold-visibility-{_OPERATOR_SEQ}")

    response = operator.get("/api/operator/appeals?status=pending")
    assert response.status_code == 200, response.content
    return response.json()


def _rule_appeal(client, appeal_id: int, *, decision: str) -> None:
    from tests.test_appeals import OPERATOR_ORIGIN, _operator_client

    operator = _operator_client("op-hold-ruler")
    response = operator.post(
        f"/api/operator/appeals/{appeal_id}/rule",
        data={"decision": decision, "ruling_note": "확인했습니다."},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content


# --- 보류가 보인다 (#74 스토리 24·37·38) -----------------------------------------
#
# 한 사람의 이의가 그 Contest 의 배분 전체를 멈춘다 — 다른 참가자들의 돈도 함께
# 미뤄진다. 그 대가를 치르기로 했으면, 막고 있다는 사실이 **양쪽 화면에** 보여야
# 한다. 운영자에게는 "이 심판이 돈을 막고 있다"는 우선순위 신호이고, 제출자에게는
# "내 이의 때문에 아직 안 움직인다 — 사라진 게 아니다"라는 설명이다.


@pytest.mark.django_db
def test_an_appeal_that_holds_a_distribution_says_so_to_the_operator(
    client, category, landing_type
):
    """운영자 큐가 「배분을 막고 있다」를 표시한다 — 심판이 밀리면 돈이 밀린다."""

    seeded = _seed_scored_contest(client, category, landing_type, uid="dev-hold-vis")
    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "컷라인 판정에 이의가 있습니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    assert filed.status_code == 201

    # 아직 배분 시각이 오지 않았다 — 막고 있는 게 아니라 그냥 대기다.
    before = _operator_appeals(client)
    assert before[0]["is_holding_distribution"] is False

    _advance_to_distribution_due(client, seeded["contest_id"])

    after = _operator_appeals(client)
    assert after[0]["is_holding_distribution"] is True, (
        "배분 시각이 지났는데도 큐가 「막고 있다」를 말하지 않는다"
    )


@pytest.mark.django_db
def test_the_developer_sees_that_their_appeal_is_holding_the_money(
    client, category, landing_type
):
    """제출자도 같은 사실을 본다 — 침묵은 돈이 사라진 것으로 읽힌다(ADR-0020)."""

    seeded = _seed_scored_contest(client, category, landing_type, uid="dev-hold-own")
    client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "컷라인 판정에 이의가 있습니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    _advance_to_distribution_due(client, seeded["contest_id"])

    response = client.get(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        **_auth_header(seeded["access"]),
    )

    assert response.status_code == 200
    assert response.json()["is_holding_distribution"] is True


@pytest.mark.django_db
def test_a_ruled_appeal_no_longer_holds_anything(client, category, landing_type):
    """심판이 끝나면 표시도 사라진다 — 안 그러면 「막고 있다」가 영구 라벨이 된다."""

    seeded = _seed_scored_contest(client, category, landing_type, uid="dev-hold-ruled")
    filed = client.post(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        data={"reason": "컷라인 판정에 이의가 있습니다."},
        content_type="application/json",
        **_auth_header(seeded["access"]),
    )
    _advance_to_distribution_due(client, seeded["contest_id"])
    assert _operator_appeals(client)[0]["is_holding_distribution"] is True

    _rule_appeal(client, filed.json()["id"], decision="reject")

    # 운영자 큐(pending)에서는 아예 사라진다. 라벨이 남았는지는 제출자 쪽에서
    # 본다 — 같은 직렬화이고, 「막고 있다」가 심판 뒤에도 붙어 있으면 제출자는
    # 자기 이의가 여전히 돈을 막고 있다고 믿는다.
    assert _operator_appeals(client) == []

    own = client.get(
        f"/api/submissions/{seeded['submission_id']}/appeal",
        **_auth_header(seeded["access"]),
    )
    assert own.status_code == 200
    assert own.json()["is_holding_distribution"] is False


@pytest.mark.django_db
def test_share_payout_timeout_then_failed_requery_stays_requested_not_attempt_failed(
    client, category, landing_type
):
    """몫 지급의 confirm 이 타임아웃하고 재확인(query_status)도 실패하면, 그 몫은
    「시도 실패」행이 아니라 미확정(REQUESTED)으로 남아 다음 스캔이 마저 확정한다
    (#125). 전에는 재확인 예외가 몫 단위 격리(except Exception)에 잡혀
    payout_attempt_failed 로 기록됐다 — 격리는 살았지만 "실패"라는 말이 틀렸다."""

    from unittest.mock import patch

    from payouts.adapters import FakePayoutAdapter, PayoutTimeoutError

    deadline = timezone.now() + timedelta(hours=1)
    _, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=333_333,
        sponsor_uid="sponsor-timeout",
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-timeout", "dev-timeout-ci")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])

    def _timeout(self, **kwargs):
        raise PayoutTimeoutError("fake: 벤더 응답 없음")

    with (
        patch.object(FakePayoutAdapter, "confirm", _timeout),
        patch.object(FakePayoutAdapter, "query_status", _timeout),
    ):
        resp = _run_due_distributions(client)

    events = {r.get("submission_id"): r for r in resp["results"] if "submission_id" in r}
    row = events[submission["id"]]
    assert row["event"] == "payout_attempted", row
    assert row["status"] == "requested"

    payout = Payout.objects.get(distribution_share__submission_id=submission["id"])
    assert payout.status == Payout.Status.REQUESTED
    assert payout.journal_entry_id is None


@pytest.mark.django_db
def test_share_payout_with_ready_seller_but_failed_transfer_stays_identity_pending(
    client, category, landing_type
):
    """Distribution 몫 지급도 같은 advance 를 탄다 (#133) — Seller 가 READY 인데 실이체가 거절되면
    Award 경로와 똑같이 CONFIRMED 가 아니라 CONFIRMED_IDENTITY_PENDING + transfer FAILED 에 머문다
    (표의 빈칸이었던 「Distribution 기반 Payout 의 실이체 실패 가지」)."""

    from django.test import override_settings

    deadline = timezone.now() + timedelta(hours=1)
    _, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=444_444,
        sponsor_uid="sponsor-share-fail",
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-share-fail", "dev-share-fail-ci")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id, grounded=True)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    _end_judging_period(client, contest["id"])
    _advance_past_distribution_wait(contest["id"])

    with override_settings(
        PAYOUT_ADAPTER_MODE="tests.test_payouts._TransferFailsOnceSellerReadyPayoutAdapter"
    ):
        resp = _run_due_distributions(client)

    row = next(r for r in resp["results"] if r.get("submission_id") == submission["id"])
    assert row["event"] == "payout_attempted"
    assert row["status"] == "confirmed_identity_pending"

    payout = Payout.objects.get(distribution_share__submission_id=submission["id"])
    assert payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING
    assert payout.transfer_status == Payout.TransferStatus.FAILED
    assert payout.journal_entry_id is not None  # 원장 분개는 실이체 결과와 무관하게 남는다
