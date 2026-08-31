"""SourceReading — Operator 의 소스 펼침이 남기는 기록 (#60, ADR-0022).

#59 가 이의 상세 조회의 부수 효과로 새던 소스를 닫았다. 이 파일은 그 반대쪽을
연다 — 소스가 필요한 심판을 위해 다시 여는 경로를, **기록과 함께**.

핵심 대상:

- `POST /operator/appeals/{id}/source` 가 200 과 함께 채점에 쓰인 소스(=
  `Score.prompt`)를 돌려준다.
- 그 요청 하나가 `SourceReading` 을 정확히 하나 만든다 — 어느 Submission, 어느
  Appeal, 누가, 언제. 네 필드 모두 NOT NULL, `read_by` 는 PROTECT.
- 열람은 사건이다 — 같은 Operator 가 다시 펼치면 행이 하나 더 쌓인다.
- 인증·Origin 검증·404 는 다른 운영자 엔드포인트와 같은 규율을 따른다.
- 기록 없이 소스를 얻는 다른 경로가 없다 — 운영자 표면 전체를 훑는다.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.utils import timezone

from appeals.models import SourceReading
from contests.models import Category, Contest, DeliverableType
from storage.adapters.fake import FakeStorageAdapter

CONTESTS_URL = "/api/contests"
PAYMENTS_URL = "/api/payments"
TICK_URL = "/api/internal/tick"
SCORING_RUN_PENDING_URL = "/api/internal/scoring/run-pending"
OPERATOR_APPEALS_URL = "/api/operator/appeals"
OPERATOR_ORIGIN = "http://testserver"


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _operator_client(username="operator-1"):
    from django.test import Client

    call_command("create_operator", username, password="operator-pw-9134-xyz")
    operator = Client()
    response = operator.post(
        "/api/operator/login",
        data={"username": username, "password": "operator-pw-9134-xyz"},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return operator


def _reveal_source(operator, appeal_id, *, origin=OPERATOR_ORIGIN):
    kwargs = {}
    if origin is not None:
        kwargs["HTTP_ORIGIN"] = origin
    return operator.post(
        f"{OPERATOR_APPEALS_URL}/{appeal_id}/source",
        content_type="application/json",
        **kwargs,
    )


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


import hashlib
import hmac


def _sign(*, webhook_id: str, order_id: str, status: str) -> str:
    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _publish_contest(
    client, *, category, deliverable_type, sponsor_uid="sponsor-1", sponsor_ci="sponsor-ci-1",
    deadline_at=None, requirements=None, prize=900_000,
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
        PAYMENTS_URL, data={"contest_id": contest["id"]},
        content_type="application/json", **_auth_header(sponsor["access"]),
    )
    assert payment_resp.status_code == 201
    payment = payment_resp.json()

    webhook_id = f"wh-{contest['id']}-{uuid.uuid4().hex}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign(webhook_id=webhook_id, order_id=payment["order_id"], status="paid")
    webhook_resp = client.post(f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json")
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


def _submit(client, dev: dict, contest_id: int, *, requirement_id: int) -> dict:
    source_key = _source_object_key(contest_id, dev["user_id"])
    marker = f"MARKER_{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": f"# {marker}\n"}))

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "source_object_key": source_key,
            "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": marker}],
                }
            ],
        },
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _close_contest(client, contest: dict, *, deadline) -> None:
    from core.models import ClockOverride

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED


def _run_scoring(client) -> dict:
    response = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _appeal_ready(client, category, landing_type) -> tuple[int, int]:
    """(appeal_id, submission_id)를 돌려준다 — 채점까지 끝난 Submission 에 이의를
    하나 걸어둔다."""

    deadline = timezone.now() + timedelta(hours=1)
    sponsor, contest = _publish_contest(
        client, category=category, deliverable_type=landing_type, deadline_at=deadline,
        requirements=[{"text": "로그인 기능이 있다", "grade": "required"}],
    )
    requirement_id = contest["requirements"][0]["id"]
    dev = _verified_user(client, "dev-1", "dev-ci-1")
    submission = _submit(client, dev, contest["id"], requirement_id=requirement_id)
    _close_contest(client, contest, deadline=deadline)
    _run_scoring(client)

    response = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": "Evidence가 실제로 소스에 있습니다."},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()["id"], submission["id"]


@pytest.fixture
def category(db):
    return Category.objects.create(name="게임")


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="웹 서비스", minimum_prize=500_000)


# --- 펼치면 소스가 나오고 기록이 남는다 -----------------------------------------


@pytest.mark.django_db
def test_revealing_source_returns_the_scored_prompt(client, category, landing_type):
    from scoring.models import Score

    appeal_id, submission_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client()
    score = Score.objects.get(submission_id=submission_id)

    response = _reveal_source(operator, appeal_id)

    assert response.status_code == 200, response.content
    assert response.json()["prompt"] == score.prompt


@pytest.mark.django_db
def test_revealing_source_creates_exactly_one_source_reading(client, category, landing_type):
    from django.contrib.auth import get_user_model

    appeal_id, submission_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-reveal")

    assert SourceReading.objects.count() == 0
    response = _reveal_source(operator, appeal_id)
    assert response.status_code == 200

    assert SourceReading.objects.count() == 1
    reading = SourceReading.objects.get()
    assert reading.submission_id == submission_id
    assert reading.appeal_id == appeal_id
    assert reading.read_by == get_user_model().objects.get(username="op-reveal")
    assert reading.read_at is not None


@pytest.mark.django_db
def test_the_same_operator_revealing_twice_creates_two_rows(client, category, landing_type):
    """열람은 상태가 아니라 사건이다 — 중복 제거하지 않는다."""

    appeal_id, _submission_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-repeat")

    assert _reveal_source(operator, appeal_id).status_code == 200
    assert _reveal_source(operator, appeal_id).status_code == 200

    assert SourceReading.objects.count() == 2


@pytest.mark.django_db
def test_different_operators_are_recorded_under_their_own_names(client, category, landing_type):
    from django.contrib.auth import get_user_model

    appeal_id, _submission_id = _appeal_ready(client, category, landing_type)
    op_a = _operator_client("op-a")
    op_b = _operator_client("op-b")

    assert _reveal_source(op_a, appeal_id).status_code == 200
    assert _reveal_source(op_b, appeal_id).status_code == 200

    usernames = set(
        SourceReading.objects.values_list("read_by__username", flat=True)
    )
    assert usernames == {"op-a", "op-b"}


# --- 인증·Origin·404 --------------------------------------------------------


@pytest.mark.django_db
def test_revealing_source_without_a_session_is_401(client, category, landing_type):
    appeal_id, _submission_id = _appeal_ready(client, category, landing_type)

    response = client.post(
        f"{OPERATOR_APPEALS_URL}/{appeal_id}/source",
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )

    assert response.status_code == 401
    assert SourceReading.objects.count() == 0


@pytest.mark.django_db
def test_revealing_source_with_a_non_operator_session_is_403(client, category, landing_type):
    """세션은 있지만 Operator(is_staff)가 아닌 계정 — 로그인은 됐지만 권한이 없다.

    `/operator/login`은 is_staff가 아니면 애초에 세션을 내주지 않으므로(401), 그
    경로로는 이 상태를 만들 수 없다. `force_login`으로 세션만 직접 심어
    `OperatorAuth`의 두 번째 판정("로그인은 됐지만 Operator가 아니다")을 친다 —
    `test_operator_session.py`가 이미 쓰는 것과 같은 수법이다.
    """

    from django.contrib.auth import get_user_model
    from django.test import Client

    appeal_id, _submission_id = _appeal_ready(client, category, landing_type)

    participant = get_user_model().objects.create_user(username="plain-user")
    plain = Client()
    plain.force_login(participant)

    response = _reveal_source(plain, appeal_id)

    assert response.status_code == 403
    assert SourceReading.objects.count() == 0


@pytest.mark.django_db
def test_revealing_source_without_origin_is_403(client, category, landing_type):
    appeal_id, _submission_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-no-origin")

    response = _reveal_source(operator, appeal_id, origin=None)

    assert response.status_code == 403
    assert SourceReading.objects.count() == 0


@pytest.mark.django_db
def test_revealing_source_with_wrong_origin_is_403(client, category, landing_type):
    appeal_id, _submission_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-wrong-origin")

    response = _reveal_source(operator, appeal_id, origin="http://evil.example.com")

    assert response.status_code == 403
    assert SourceReading.objects.count() == 0


@pytest.mark.django_db
def test_revealing_source_for_a_nonexistent_appeal_is_404_and_records_nothing(client):
    operator = _operator_client("op-404")

    response = _reveal_source(operator, 999_999)

    assert response.status_code == 404
    assert SourceReading.objects.count() == 0


# --- 기록 없이 소스를 얻는 다른 경로가 없다 --------------------------------------


@pytest.mark.django_db
def test_no_other_operator_surface_returns_source_text(client, category, landing_type):
    """운영자 표면 전체에서 소스를 돌려주는 것은 펼침 엔드포인트뿐이다.

    #59 가 상세 응답에서 프롬프트를 지웠다 — 여기서는 목록·상세 둘 다 훑어
    소스 문자열이 어디에도 없음을 다시 확인한다(두 티켓을 잇는 회귀 방지).
    """

    appeal_id, submission_id = _appeal_ready(client, category, landing_type)
    operator = _operator_client("op-scan")

    from scoring.models import Score

    score = Score.objects.get(submission_id=submission_id)
    # 프롬프트 안에 실제로 소스가 있다는 사실을 먼저 확인한다(픽스처 검증).
    assert "MARKER_" in score.prompt

    detail = operator.get(f"{OPERATOR_APPEALS_URL}/{appeal_id}")
    listing = operator.get(f"{OPERATOR_APPEALS_URL}?status=pending")

    assert "prompt" not in detail.json()["score"]
    for resp in (detail, listing):
        assert score.prompt not in resp.content.decode("utf-8")
