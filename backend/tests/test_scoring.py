"""LLM 어댑터 + 소스·Evidence 기반 AI 채점 + Score 불변 스냅샷 (#12, ADR-0006/0007/0014).

핵심 대상:

- 마감 전이(#11) 직후 채점이 시작된다 — 여기서는 `/api/internal/tick`으로 Contest를
  CLOSED로 옮긴 뒤 `/api/internal/scoring/run-pending`을 쏘는 두 단계로 재현한다.
  notifications 앱의 `/dispatch-due`와 core 앱의 `/tick`이 이미 별개의 주기적
  진입점으로 공존하는 것과 같은 구조다.
- 채점 근거는 자가 응답이 아니라 소스코드와 Evidence다 — 자가 응답을 전부 충족으로
  채우고 Evidence를 비운 Submission은 0점에 수렴해야 한다(이 파일의 핵심 테스트).
- Score는 Submission당 정확히 한 번만 만들어지고 이후 절대 바뀌지 않는다.
- LLM 실패는 다음 스캔에서 자동으로 재시도되고, 운영자는 채점 미완료 Contest를
  식별할 수 있다.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import uuid
import zipfile
from datetime import timedelta
from decimal import Decimal

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from ledger.models import AppendOnlyError
from scoring.models import Score, ScoringAttempt
from storage.adapters.fake import FakeStorageAdapter

TICK_URL = "/api/internal/tick"
RUN_PENDING_URL = "/api/internal/scoring/run-pending"
INCOMPLETE_CONTESTS_URL = "/api/internal/scoring/incomplete-contests"
CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"


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


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _close_contest(client, contest: dict, *, deadline: "timezone.datetime") -> None:
    _freeze(deadline + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED


def _run_pending(client) -> dict:
    response = client.post(RUN_PENDING_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


# --- 채점 근거: 소스·Evidence, 자가 응답은 신뢰하지 않는다 (ADR-0014) ------------------


@pytest.mark.django_db
def test_evidence_grounded_in_source_scores_required_requirement_as_met(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(
        source_key,
        _zip_bytes({"app.py": "def login():\n    # MAGIC_MARKER_LOGIN\n    pass\n"}),
    )

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [
                        {"kind": "source_location", "value": "MAGIC_MARKER_LOGIN"}
                    ],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert submit_resp.status_code == 201
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)
    result = _run_pending(client)
    assert result["count"] == 1
    assert result["results"][0]["status"] == "scored"

    score = Score.objects.get(submission_id=submission_id)
    assert score.percentage == Decimal("100.00")
    assert score.model_version == "fake-llm-v1"
    assert "MAGIC_MARKER_LOGIN" in score.prompt
    assert score.reasoning == [
        {
            "requirement_id": requirement_id,
            "is_met": True,
            "reasoning": "Evidence가 소스에서 확인되어 충족으로 판정했다.",
        }
    ]


@pytest.mark.django_db
def test_self_report_all_met_with_no_evidence_converges_to_zero(client, category, landing_type):
    """이 티켓의 존재 이유 — 살포 방지 (ADR-0014).

    자가 응답을 전부 충족으로 채우고 Evidence를 비운 Submission은 필수 Requirement
    달성률이 0에 수렴해야 한다.
    """
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[
            {"text": "로그인 기능이 있다", "grade": "required"},
            {"text": "결제 기능이 있다", "grade": "required"},
        ],
    )
    req_ids = [r["id"] for r in contest["requirements"]]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(
        source_key, _zip_bytes({"app.py": "print('hello world')\n"})
    )

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {"requirement_id": rid, "is_met": True, "evidence": []} for rid in req_ids
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert submit_resp.status_code == 201
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)
    _run_pending(client)

    score = Score.objects.get(submission_id=submission_id)
    assert score.percentage == Decimal("0.00")
    assert all(not v["is_met"] for v in score.reasoning)


@pytest.mark.django_db
def test_evidence_present_but_not_grounded_in_source_is_unmet(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "결제 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(
        source_key, _zip_bytes({"app.py": "print('no such feature here')\n"})
    )

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [
                        {"kind": "source_location", "value": "NONEXISTENT_PAYMENT_FUNC"}
                    ],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert submit_resp.status_code == 201
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)
    _run_pending(client)

    score = Score.objects.get(submission_id=submission_id)
    assert score.percentage == Decimal("0.00")


# --- 1회만 채점, 불변 스냅샷 (ADR-0006) ---------------------------------------------


@pytest.mark.django_db
def test_running_pending_scan_twice_scores_only_once(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": "MARKER\n"}))

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "MARKER"}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)

    first = _run_pending(client)
    assert first["count"] == 1
    assert first["results"][0]["status"] == "scored"

    first_score = Score.objects.get(submission_id=submission_id)

    second = _run_pending(client)
    assert second["count"] == 0
    assert Score.objects.filter(submission_id=submission_id).count() == 1

    second_score = Score.objects.get(submission_id=submission_id)
    assert second_score.pk == first_score.pk
    assert second_score.created_at == first_score.created_at
    assert second_score.prompt == first_score.prompt


@pytest.mark.django_db
def test_score_cannot_be_modified_after_creation(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": "MARKER\n"}))

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "MARKER"}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)
    _run_pending(client)

    score = Score.objects.get(submission_id=submission_id)

    score.percentage = Decimal("0.00")
    with pytest.raises(AppendOnlyError):
        score.save()

    with pytest.raises(AppendOnlyError):
        Score.objects.filter(pk=score.pk).update(percentage=Decimal("0.00"))

    with pytest.raises(AppendOnlyError):
        score.delete()

    unchanged = Score.objects.get(submission_id=submission_id)
    assert unchanged.percentage == Decimal("100.00")


# --- LLM 실패 재시도 + 운영자 가시성 --------------------------------------------------


@pytest.mark.django_db
def test_llm_failure_is_logged_and_retried_on_next_scan(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": "MARKER\n"}))

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "MARKER"}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)

    with override_settings(LLM_FAKE_RAISING_SUBMISSION_IDS=[submission_id]):
        failed = _run_pending(client)
    assert failed["count"] == 1
    assert failed["results"][0]["status"] == "failed"
    assert not Score.objects.filter(submission_id=submission_id).exists()
    assert ScoringAttempt.objects.filter(submission_id=submission_id).count() == 1

    # 실패 흉내를 껐으니 다음 스캔에서 같은 코드 경로(첫 시도)가 자동으로 재시도된다.
    retried = _run_pending(client)
    assert retried["count"] == 1
    assert retried["results"][0]["status"] == "scored"
    assert Score.objects.filter(submission_id=submission_id).count() == 1


@pytest.mark.django_db
def test_incomplete_contests_endpoint_lists_unscored_closed_contest(
    client, category, landing_type
):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": "MARKER\n"}))
    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "MARKER"}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)

    before = client.get(INCOMPLETE_CONTESTS_URL, **_internal_headers())
    assert before.status_code == 200
    before_body = before.json()
    matching = [c for c in before_body["contests"] if c["contest_id"] == contest["id"]]
    assert len(matching) == 1
    assert matching[0]["unscored_submissions"] == 1
    assert matching[0]["total_submissions"] == 1

    _run_pending(client)

    after = client.get(INCOMPLETE_CONTESTS_URL, **_internal_headers())
    after_body = after.json()
    assert all(c["contest_id"] != contest["id"] for c in after_body["contests"])
    assert Score.objects.get(submission_id=submission_id).percentage == Decimal("100.00")


@pytest.mark.django_db
def test_run_pending_never_scores_submissions_of_a_still_open_contest(
    client, category, landing_type
):
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": "MARKER\n"}))
    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "MARKER"}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    submission_id = submit_resp.json()["id"]

    result = _run_pending(client)
    assert result["count"] == 0
    assert not Score.objects.filter(submission_id=submission_id).exists()


# --- 대형 저장소 파일 선별 전략 -----------------------------------------------------


@pytest.mark.django_db
def test_excluded_vendor_directories_are_never_sent_to_the_llm(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    FakeStorageAdapter().write_object(
        source_key,
        _zip_bytes(
            {
                "app.py": "def login():\n    # REAL_MARKER\n    pass\n",
                "node_modules/some-lib/index.js": "VENDOR_TRAP_MARKER",
                "dist/bundle.js": "BUILD_TRAP_MARKER",
                "README.md": "not code",
            }
        ),
    )

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "REAL_MARKER"}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)
    _run_pending(client)

    score = Score.objects.get(submission_id=submission_id)
    assert "REAL_MARKER" in score.prompt
    assert "VENDOR_TRAP_MARKER" not in score.prompt
    assert "BUILD_TRAP_MARKER" not in score.prompt
    assert score.percentage == Decimal("100.00")


@pytest.mark.django_db
def test_oversized_source_is_truncated_to_the_selection_budget(client, category, landing_type):
    from scoring.source_selection import MAX_SOURCE_BYTES

    deadline = timezone.now() + timedelta(hours=1)
    _sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]

    dev = _verified_user(client, "dev-1", "dev-ci-1")
    source_key = _source_object_key(contest["id"], dev["user_id"])
    huge_content = "x" * (MAX_SOURCE_BYTES * 2)
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": huge_content}))

    submit_resp = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": "x" * 20}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    submission_id = submit_resp.json()["id"]

    _close_contest(client, contest, deadline=deadline)
    _run_pending(client)

    score = Score.objects.get(submission_id=submission_id)
    # 선별 예산을 넘지 않는다 — 통째로 다 보내지 않았다는 것의 직접 증거.
    assert len(score.prompt) < MAX_SOURCE_BYTES * 2
