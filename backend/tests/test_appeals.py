"""Appeal — 이의제기 + 정정 분개 (#21, ADR-0004, ADR-0006).

핵심 대상:

- Developer가 자신의 (채점이 끝난) Submission에만 이의를 제기할 수 있다. 채점
  전이거나 남의 Submission이면 거부한다.
- 운영자가 Score 스냅샷(점수·근거·prompt·model_version)과 함께 이의를 조회한다.
- 인용하면 기존 분개를 수정하지 않고 정정 분개가 새로 추가된다 — 원장은 여전히
  균형을 이룬다(차변 합==대변 합).
- 기각하면 원장에 아무 것도 남기지 않는다.
- 이미 심판이 끝난 이의제기는 다시 심판할 수 없다(정정 분개 중복 방지).
- 인용해도 Score 자체는 절대 바뀌지 않는다(불변 스냅샷) — 그리고 이 앱 코드
  어디에도 재채점 경로가 없다.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import uuid
import zipfile
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from appeals.models import Appeal
from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from ledger.services import contest_balance, contest_entries
from scoring.models import Score
from storage.adapters.fake import FakeStorageAdapter

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
TICK_URL = "/api/internal/tick"
SCORING_RUN_PENDING_URL = "/api/internal/scoring/run-pending"
INTERNAL_APPEALS_URL = "/api/internal/appeals"


# --- 헬퍼 (test_distributions.py/test_scoring.py와 같은 형식) -------------------


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


def _close_contest(client, contest: dict, *, deadline) -> None:
    _freeze(deadline + timedelta(minutes=1))
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED


def _run_scoring(client) -> dict:
    response = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _scored_submission(client, category, landing_type, *, grounded: bool, prize=900_000):
    """(sponsor, dev, contest, submission)을 돌려준다 — Submission은 이미 채점까지
    끝나 있다. `grounded=False`면 필수 Requirement 미달(0%)로 채점된다.
    """

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
        prize=prize,
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(
        client, dev, contest["id"], requirement_id=requirement_id, grounded=grounded
    )
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)
    return sponsor, dev, contest, submission


def APPEAL_URL(submission_id: int) -> str:
    return f"/api/submissions/{submission_id}/appeal"


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


# --- Developer가 자신의 Score에 이의를 제기한다 -----------------------------------


@pytest.mark.django_db
def test_developer_can_appeal_own_score(client, category, landing_type):
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=False
    )

    resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "Evidence가 실제로는 소스에 있는데 미달로 판정됐습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 201, resp.content
    body = resp.json()
    assert body["status"] == "pending"
    assert body["submission_id"] == submission["id"]

    get_resp = client.get(APPEAL_URL(submission["id"]), **_auth_header(dev["access"]))
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == body["id"]


@pytest.mark.django_db
def test_appeal_before_scoring_is_rejected(client, category, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client,
        category=category,
        deliverable_type=landing_type,
        deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(
        client, dev, contest["id"], requirement_id=requirement_id, grounded=True
    )

    resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "아직 채점 전인데 이의를 제기해봅니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert resp.status_code == 409


@pytest.mark.django_db
def test_developer_cannot_appeal_others_submission(client, category, landing_type):
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=False
    )
    other_dev = _verified_user(client, "dev-2", "dev-2-ci")

    resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "남의 제출물에 이의를 제기해봅니다."},
        content_type="application/json",
        **_auth_header(other_dev["access"]),
    )
    assert resp.status_code == 403


@pytest.mark.django_db
def test_duplicate_appeal_is_rejected(client, category, landing_type):
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=False
    )

    first = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "첫 번째 이의제기입니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert first.status_code == 201

    second = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "두 번째 이의제기입니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert second.status_code == 409


# --- 운영자가 Score 스냅샷과 함께 조회한다 ----------------------------------------


@pytest.mark.django_db
def test_operator_views_appeal_with_full_score_snapshot(client, category, landing_type):
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=False
    )
    appeal_resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "근거를 다시 봐주세요."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    appeal_id = appeal_resp.json()["id"]

    score = Score.objects.get(submission_id=submission["id"])

    detail = client.get(f"{INTERNAL_APPEALS_URL}/{appeal_id}", **_internal_headers())
    assert detail.status_code == 200
    body = detail.json()
    assert body["score"]["percentage"] == str(score.percentage)
    assert body["score"]["model_version"] == score.model_version
    assert body["score"]["prompt"] == score.prompt
    assert body["score"]["reasoning"] == score.reasoning

    listing = client.get(f"{INTERNAL_APPEALS_URL}?status=pending", **_internal_headers())
    assert listing.status_code == 200
    assert any(a["id"] == appeal_id for a in listing.json())


# --- 인용: 정정 분개 추가, 기존 분개는 그대로, 원장은 균형 -----------------------


@pytest.mark.django_db
def test_upholding_appeal_adds_correction_entry_without_touching_originals(
    client, category, landing_type
):
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=False, prize=900_000
    )
    appeal_resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "Evidence가 실제로 소스에 있습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    appeal_id = appeal_resp.json()["id"]

    contest_obj = Contest.objects.get(id=contest["id"])
    score_before = Score.objects.get(submission_id=submission["id"])
    original_entries_before = [
        (e.id, e.memo, [(l.account, l.side, l.amount) for l in e.lines.all()])
        for e in contest_entries(contest_obj.ledger_id)
    ]
    assert len(original_entries_before) >= 1  # 결제 확정 분개가 이미 있다.

    rule_resp = client.post(
        f"{INTERNAL_APPEALS_URL}/{appeal_id}/rule",
        data={
            "decision": "uphold",
            "ruling_note": "재검토 결과 근거가 확인되어 인용합니다.",
            "correction_amount": 50_000,
        },
        content_type="application/json",
        **_internal_headers(),
    )
    assert rule_resp.status_code == 200, rule_resp.content
    body = rule_resp.json()
    assert body["status"] == "upheld"
    assert body["correction_amount"] == 50_000

    # 기존 분개는 단 하나도 수정되지 않았다.
    entries_after = list(contest_entries(contest_obj.ledger_id))
    original_entries_after = [
        (e.id, e.memo, [(l.account, l.side, l.amount) for l in e.lines.all()])
        for e in entries_after
        if e.id in {eid for eid, _, _ in original_entries_before}
    ]
    assert original_entries_after == original_entries_before

    # 새 정정 분개가 추가됐다.
    appeal = Appeal.objects.get(id=appeal_id)
    assert appeal.correction_journal_entry_id is not None
    correction_entry = next(e for e in entries_after if e.id == appeal.correction_journal_entry_id)
    lines = {(l.account, l.side): l.amount for l in correction_entry.lines.all()}
    assert lines[("platform_fee_revenue", "debit")] == 50_000
    assert lines[("developer_payable", "credit")] == 50_000

    # Contest 원장 합계는 여전히 0(균형)이다.
    assert contest_balance(contest_obj.ledger_id)["is_balanced"] is True

    # Score는 절대 바뀌지 않았다 — 재채점 경로가 없다는 증거다.
    score_after = Score.objects.get(submission_id=submission["id"])
    assert score_after.percentage == score_before.percentage
    assert score_after.reasoning == score_before.reasoning
    assert score_after.prompt == score_before.prompt
    assert score_after.model_version == score_before.model_version
    assert score_after.created_at == score_before.created_at


@pytest.mark.django_db
def test_rejecting_appeal_leaves_ledger_untouched(client, category, landing_type):
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=False
    )
    appeal_resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "다시 봐주세요."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    appeal_id = appeal_resp.json()["id"]

    contest_obj = Contest.objects.get(id=contest["id"])
    entries_before = {e.id for e in contest_entries(contest_obj.ledger_id)}

    rule_resp = client.post(
        f"{INTERNAL_APPEALS_URL}/{appeal_id}/rule",
        data={"decision": "reject", "ruling_note": "근거 부족으로 기각합니다."},
        content_type="application/json",
        **_internal_headers(),
    )
    assert rule_resp.status_code == 200
    body = rule_resp.json()
    assert body["status"] == "rejected"
    assert body["correction_amount"] is None

    entries_after = {e.id for e in contest_entries(contest_obj.ledger_id)}
    assert entries_after == entries_before

    appeal = Appeal.objects.get(id=appeal_id)
    assert appeal.correction_journal_entry_id is None


@pytest.mark.django_db
def test_ruling_an_already_ruled_appeal_is_rejected(client, category, landing_type):
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=False
    )
    appeal_resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "다시 봐주세요."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    appeal_id = appeal_resp.json()["id"]

    first = client.post(
        f"{INTERNAL_APPEALS_URL}/{appeal_id}/rule",
        data={"decision": "uphold", "ruling_note": "인용", "correction_amount": 10_000},
        content_type="application/json",
        **_internal_headers(),
    )
    assert first.status_code == 200

    contest_obj = Contest.objects.get(id=contest["id"])
    entries_after_first = {e.id for e in contest_entries(contest_obj.ledger_id)}

    second = client.post(
        f"{INTERNAL_APPEALS_URL}/{appeal_id}/rule",
        data={"decision": "uphold", "ruling_note": "다시 인용", "correction_amount": 99_999},
        content_type="application/json",
        **_internal_headers(),
    )
    assert second.status_code == 409

    entries_after_second = {e.id for e in contest_entries(contest_obj.ledger_id)}
    assert entries_after_second == entries_after_first

    appeal = Appeal.objects.get(id=appeal_id)
    assert appeal.correction_amount == 10_000


# --- 재채점 경로는 존재하지 않는다 ------------------------------------------------


def test_no_rescoring_code_path_exists_in_appeals_app():
    """`appeals.api`/`appeals.services`는 `scoring` 앱의 어떤 심볼도 import하지
    않는다 — 재채점을 실행할 수 있는 코드 경로 자체가 없다는 정적 증거다(#21 AC,
    ADR-0006). 설명 주석에서 다른 앱 이름을 언급하는 것과 실제 import는 다르므로,
    AST를 파싱해 import 문만 정확히 검사한다.
    """

    import ast
    import inspect

    import appeals.api as api_module
    import appeals.services as services_module

    for module in (api_module, services_module):
        tree = ast.parse(inspect.getsource(module))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.split(".")[0] == "scoring", (
                        f"{module.__name__}이 scoring을 import한다: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module_name = node.module or ""
                assert module_name.split(".")[0] != "scoring", (
                    f"{module.__name__}이 scoring에서 import한다: {module_name}"
                )
