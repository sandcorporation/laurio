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
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone

from appeals.models import Appeal, AppealRuling
from contests.models import Category, Contest, DeliverableType
from core.models import ClockOverride
from ledger.services import contest_balance, contest_entries
from scoring.models import Score
from storage.adapters.fake import FakeStorageAdapter

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
TICK_URL = "/api/internal/tick"
SCORING_RUN_PENDING_URL = "/api/internal/scans/submission-scoring"
OPERATOR_APPEALS_URL = "/api/operator/appeals"
# Django 테스트 클라이언트의 기본 호스트. 운영자 경로의 변경 요청은 Origin 을
# 검증한다(#43, ADR-0016 의 성립 조건).
OPERATOR_ORIGIN = "http://testserver"


# --- 헬퍼 (test_distributions.py/test_scoring.py와 같은 형식) -------------------


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _operator_client(username="operator-1", *, superuser=False):
    """로그인된 Operator 용 클라이언트 (#44).

    Developer 와 **다른 클라이언트**를 쓴다. 둘은 서로소인 신원이고(ADR-0018) 인증
    수단도 다르다 — Developer 는 Bearer, Operator 는 세션 쿠키다. 한 클라이언트에
    둘을 섞으면 테스트가 그 구분을 흐린다.
    """

    from django.test import Client

    call_command("create_operator", username, password="operator-pw-9134-xyz", superuser=superuser)
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": "operator-pw-9134-xyz"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _appeal_ready(client, category, landing_type):
    """채점까지 끝난 Submission 에 이의를 하나 걸어두고 그 id 를 돌려준다."""

    _sponsor, dev, _contest, submission = _scored_submission(
        client, category, landing_type, grounded=False, prize=900_000
    )
    response = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "Evidence가 실제로 소스에 있습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()["id"]


def _rule(operator, appeal_id, **payload):
    return operator.post(
        f"{OPERATOR_APPEALS_URL}/{appeal_id}/rule",
        data=payload,
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )


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
        data={"assets": [{"kind": "source", "value": source_key}], "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": (
                        [{"kind": "source_location", "value": marker}] if grounded else []
                    ),
                }
            ]},
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
    operator = _operator_client()
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

    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["score"]["percentage"] == str(score.percentage)
    assert body["score"]["model_version"] == score.model_version
    assert body["score"]["reasoning"] == score.reasoning
    assert body["score"]["created_at"] is not None
    # #59, ADR-0022: 프롬프트(=소스 전문)는 상세 응답에 없다 — 스키마에서 제거됐다.
    assert "prompt" not in body["score"]
    # 심판에 필요한 나머지(이의 사유·상태·확정된 심판)는 여전히 돌아온다.
    assert body["reason"] == "근거를 다시 봐주세요."
    assert body["status"] == "pending"
    assert body["ruling"] is None

    listing = operator.get(f"{OPERATOR_APPEALS_URL}?status=pending")
    assert listing.status_code == 200
    assert any(a["id"] == appeal_id for a in listing.json())


@pytest.mark.django_db
def test_operator_appeal_detail_does_not_leak_source_text(client, category, landing_type):
    """이의 상세 응답 어디에도 채점에 쓰인 소스 문자열이 나타나지 않는다 (#59, ADR-0022).

    "필드가 없다"가 아니라 "내용이 없다"를 친다 — 실제로 소스가 담긴 프롬프트로
    채점된 뒤, 그 소스 문자열이 응답 바디 전체(직렬화된 원문 바이트)에 한 글자도
    없는지 확인한다. `grounded=True`는 제출 소스(app.py)에 고유 마커를 심고, 그
    마커가 채점 프롬프트에 실제로 임베드됐는지까지 먼저 확인해 픽스처 자체가
    무의미하지 않음을 보장한다.
    """

    operator = _operator_client()
    sponsor, dev, contest, submission = _scored_submission(
        client, category, landing_type, grounded=True
    )
    # `_submit`이 소스(app.py)에 심고 Evidence로도 되돌려주는 고유 마커 — 채점
    # 프롬프트가 실제로 이 소스 내용을 그대로 삼켰다는 것을 증명하는 데 쓴다.
    source_marker = submission["requirement_responses"][0]["evidence"][0]["value"]

    score = Score.objects.get(submission_id=submission["id"])
    assert source_marker in score.prompt  # 픽스처가 정말로 소스를 프롬프트에 심었는지 확인

    appeal_resp = client.post(
        APPEAL_URL(submission["id"]),
        data={"reason": "근거를 다시 봐주세요."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert appeal_resp.status_code == 201
    appeal_id = appeal_resp.json()["id"]

    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}")
    assert detail.status_code == 200
    assert "prompt" not in detail.json()["score"]
    # 응답 원문 어디에도 소스 문자열이 없다 — 필드 부재가 아니라 내용 부재를 친다.
    assert source_marker not in detail.content.decode("utf-8")


# --- 인용: 정정 분개 추가, 기존 분개는 그대로, 원장은 균형 -----------------------


@pytest.mark.django_db
def test_upholding_appeal_adds_correction_entry_without_touching_originals(
    client, category, landing_type
):
    operator = _operator_client()
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

    rule_resp = _rule(operator, appeal_id, **{
            "decision": "uphold",
            "ruling_note": "재검토 결과 근거가 확인되어 인용합니다.",
            "correction_amount": 50_000,
        })
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
    assert appeal.ruling.correction_journal_entry_id is not None
    correction_entry = next(
        e for e in entries_after if e.id == appeal.ruling.correction_journal_entry_id
    )
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
    operator = _operator_client()
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

    rule_resp = _rule(operator, appeal_id, **{"decision": "reject", "ruling_note": "근거 부족으로 기각합니다."})
    assert rule_resp.status_code == 200
    body = rule_resp.json()
    assert body["status"] == "rejected"
    assert body["correction_amount"] is None

    entries_after = {e.id for e in contest_entries(contest_obj.ledger_id)}
    assert entries_after == entries_before

    appeal = Appeal.objects.get(id=appeal_id)
    assert appeal.ruling.correction_journal_entry_id is None


@pytest.mark.django_db
def test_ruling_an_already_ruled_appeal_is_rejected(client, category, landing_type):
    operator = _operator_client()
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

    first = _rule(operator, appeal_id, **{"decision": "uphold", "ruling_note": "인용", "correction_amount": 10_000})
    assert first.status_code == 200

    contest_obj = Contest.objects.get(id=contest["id"])
    entries_after_first = {e.id for e in contest_entries(contest_obj.ledger_id)}

    second = _rule(operator, appeal_id, **{"decision": "uphold", "ruling_note": "다시 인용", "correction_amount": 99_999})
    assert second.status_code == 409

    entries_after_second = {e.id for e in contest_entries(contest_obj.ledger_id)}
    assert entries_after_second == entries_after_first

    appeal = Appeal.objects.get(id=appeal_id)
    assert appeal.ruling.correction_amount == 10_000


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


# --- 심판에 신원이 남는다 (#44, #24, ADR-0018) ---------------------------------
#
# #24 가 지목한 공백이 이것이다 — 이의를 인용하면 원장에 정정 분개가 들어가는데(돈이
# 움직인다) 그것을 한 사람이 누구인지 어디에도 남지 않았다. 원장은 무엇이 일어났는지
# 완벽하게 남기지만 누가 결정했는지에서 끊겼다.


@pytest.mark.django_db
def test_a_ruling_cannot_be_stored_without_an_author(client, category, landing_type):
    """공백이 다시 열릴 수 없다는 것을 스키마 수준에서 확인한다.

    예전에는 심판 결과가 Appeal 의 nullable 컬럼 네 개였다. 거기에 `ruled_by` 를
    다섯 번째로 붙였다면 "신원 없는 심판" 이 여전히 표현 가능한 상태로 남았을
    것이다. 떼어냈으므로 이제는 표현 자체가 불가능하다.
    """

    appeal_id = _appeal_ready(client, category, landing_type)

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            AppealRuling.objects.create(
                appeal_id=appeal_id,
                ruled_by=None,
                decision=AppealRuling.Decision.REJECTED,
                note="신원 없이",
                ruled_at=timezone.now(),
            )


@pytest.mark.django_db
def test_the_operator_who_ruled_is_traceable_from_the_correction_journal_entry(
    client, category, landing_type
):
    """감사 사슬 — 돈(분개) → 심판 → 사람.

    원장에는 행위자 컬럼이 없다(ADR-0018). 대신 분개 번호로 심판을 되짚으면 신원이
    나온다. 그 되짚기가 실제로 되는지를 고정한다 — 안 되면 원장에 컬럼을 넣지
    않기로 한 결정의 근거가 사라진다.
    """

    appeal_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-tracer")

    response = _rule(
        operator,
        appeal_id,
        decision="uphold",
        ruling_note="근거가 확인되어 인용합니다.",
        correction_amount=40_000,
    )
    assert response.status_code == 200, response.content

    entry_id = AppealRuling.objects.get(appeal_id=appeal_id).correction_journal_entry_id
    assert entry_id is not None

    # 분개 번호만 들고 시작한다 — 감사자가 실제로 가진 것이 그것뿐이다.
    traced = AppealRuling.objects.select_related("ruled_by").get(
        correction_journal_entry_id=entry_id
    )
    assert traced.ruled_by.username == "op-tracer"
    assert traced.decision == AppealRuling.Decision.UPHELD
    assert traced.note == "근거가 확인되어 인용합니다."


@pytest.mark.django_db
def test_a_rejection_also_records_who_decided(client, category, landing_type):
    """돈이 움직이지 않아도 신원은 남는다 — Developer 에게는 이쪽이 더 아픈 결정이다."""

    appeal_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-rejector")

    assert _rule(
        operator, appeal_id, decision="reject", ruling_note="근거 부족으로 기각합니다."
    ).status_code == 200

    ruling = AppealRuling.objects.select_related("ruled_by").get(appeal_id=appeal_id)
    assert ruling.ruled_by.username == "op-rejector"
    assert ruling.decision == AppealRuling.Decision.REJECTED
    assert ruling.correction_journal_entry_id is None


@pytest.mark.django_db
def test_the_operator_surface_shows_who_ruled(client, category, landing_type):
    appeal_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-viewer")
    _rule(operator, appeal_id, decision="reject", ruling_note="기각합니다.")

    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}")

    assert detail.status_code == 200
    ruling = detail.json()["ruling"]
    assert ruling["ruled_by_username"] == "op-viewer"
    assert ruling["decision"] == "rejected"


@pytest.mark.django_db
def test_a_pending_appeal_has_no_ruling_in_the_operator_view(client, category, landing_type):
    appeal_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-early")

    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}")

    assert detail.status_code == 200
    assert detail.json()["ruling"] is None


@pytest.mark.django_db
def test_ruling_without_a_reason_is_refused(client, category, landing_type):
    """돈을 움직이는 판단에 근거가 없으면 감사 기록으로서 값이 없다."""

    appeal_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-silent")

    response = _rule(operator, appeal_id, decision="reject", ruling_note="   ")

    assert response.status_code == 422, response.content
    assert not AppealRuling.objects.filter(appeal_id=appeal_id).exists()


@pytest.mark.django_db
def test_the_operator_account_that_ruled_cannot_be_deleted(client, category, landing_type):
    """PROTECT — 계정을 지우면 감사 기록이 주인을 잃는다. 비활성화는 하되 삭제는 막는다."""

    appeal_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-permanent")
    _rule(operator, appeal_id, decision="reject", ruling_note="기각합니다.")

    account = get_user_model().objects.get(username="op-permanent")

    with pytest.raises(ProtectedError):
        account.delete()


@pytest.mark.django_db
def test_the_operator_surface_is_closed_to_everyone_else(client, category, landing_type):
    """신원 없이는 이의를 볼 수도, 심판할 수도 없다 — #24 가 지목한 그 경로다."""

    appeal_id = _appeal_ready(client, category, landing_type)

    assert client.get(OPERATOR_APPEALS_URL).status_code == 401
    assert client.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}").status_code == 401
    # 공유 시크릿을 들고 와도 마찬가지다.
    assert client.get(
        OPERATOR_APPEALS_URL, **_internal_headers()
    ).status_code == 401


@pytest.mark.django_db
def test_internal_appeals_endpoints_are_gone(client):
    """공유 시크릿만 알면 신원 없이 돈을 움직일 수 있던 경로가 사라졌다 (#24)."""

    assert client.get("/api/internal/appeals", **_internal_headers()).status_code == 404
    assert client.get("/api/internal/appeals/1", **_internal_headers()).status_code == 404
    assert (
        client.post(
            "/api/internal/appeals/1/rule",
            data={"decision": "uphold", "ruling_note": "x", "correction_amount": 1},
            content_type="application/json",
            **_internal_headers(),
        ).status_code
        == 404
    )


@pytest.mark.django_db
def test_the_remaining_internal_scan_endpoints_still_work(client):
    """Celery beat 의 틱 전이가 흔들리면 안 된다 — InternalAuth 는 그대로 남는다."""

    assert client.post(TICK_URL, **_internal_headers()).status_code == 200
