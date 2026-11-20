"""SourceReading — Operator 의 소스 펼침이 남기는 기록과 그 소비처 (#60·#61, ADR-0022).

#59 가 이의 상세 조회의 부수 효과로 새던 소스를 닫았다. 이 파일은 그 반대쪽을
연다 — 소스가 필요한 심판을 위해 다시 여는 경로를 **기록과 함께**(#60) 만들고,
그 기록에 **읽는 사람**을 붙인다(#61) — 쓰기만 하고 아무도 읽지 않는 필드는
이 저장소가 반복해서 겪은 결함 모양이다(ADR-0022).

핵심 대상:

- `POST /operator/appeals/{id}/source` 가 200 과 함께 채점에 쓰인 소스(=
  `Score.prompt`)를 돌려준다.
- 그 요청 하나가 `SourceReading` 을 정확히 하나 만든다 — 어느 Submission, 어느
  Appeal, 누가, 언제. 네 필드 모두 NOT NULL, `read_by` 는 PROTECT.
- 열람은 사건이다 — 같은 Operator 가 다시 펼치면 행이 하나 더 쌓인다.
- 인증·Origin 검증·404 는 다른 운영자 엔드포인트와 같은 규율을 따른다.
- 기록 없이 소스를 얻는 다른 경로가 없다 — 운영자 표면 전체를 훑는다.
- `GET /submissions/{id}/source-readings` — Developer 본인이 자기 Submission 의
  열람 시각 목록을 본다. 운영자 이름은 없다. #60 의 펼침을 실제로 두 번 일으킨
  뒤 여기서 두 건이 보이는, 두 티켓을 잇는 테스트가 있다.
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
SCORING_RUN_PENDING_URL = "/api/internal/scans/submission-scoring"
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
    # 표시 이름이 없으면 결제 시작이 422로 막힌다(#447).
    profile_resp = client.post(
        "/api/accounts/sponsor-profile",
        data={"display_name": f"{sponsor_uid} 개최자"},
        content_type="application/json",
        **_auth_header(sponsor["access"]),
    )
    assert profile_resp.status_code == 200, profile_resp.content
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
    """충족으로 채점될 제출 하나 — 흉내 채점기는 Requirement 문구가 소스에 있으면 충족으로
    보므로(#909) 그 문구를 공모전 API 에서 읽어 소스에 싣는다. 확인 위치(Evidence)는 판정과
    무관하지만 화면·API 시험이 읽으므로 하나 붙여 둔다."""

    detail = client.get(f"{CONTESTS_URL}/{contest_id}")
    assert detail.status_code == 200, detail.content
    text = next(r["text"] for r in detail.json()["requirements"] if r["id"] == requirement_id)
    source_key = _source_object_key(contest_id, dev["user_id"])
    marker = f"MARKER_{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": f"# {marker} {text}\n"}))

    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={"assets": [{"kind": "source", "value": source_key}], "requirement_responses": [
                {
                    "requirement_id": requirement_id,
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": marker}],
                }
            ]},
        content_type="application/json",
        **_auth_header(dev["access"]),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _close_contest(client, contest: dict, *, deadline) -> None:
    """마감 전이 스캔만 돌린다 — `/tick` 은 등록부 전부를 한 바퀴 돌아(#137) 채점까지 같이
    실행하므로, 「마감은 됐지만 채점 전」을 관찰하는 테스트(my_contests·my_participation 이
    이 헬퍼를 가져다 쓴다)가 그 상태를 볼 수 없게 된다."""

    from core.models import ClockOverride

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )
    tick_resp = client.post("/api/internal/scans/contest-close", **_internal_headers())
    assert tick_resp.status_code == 200
    assert Contest.objects.get(id=contest["id"]).status == Contest.Status.CLOSED


def _run_scoring(client) -> dict:
    response = client.post(SCORING_RUN_PENDING_URL, **_internal_headers())
    assert response.status_code == 200
    return response.json()


def _appeal_ready_full(client, category, landing_type) -> tuple[int, int, dict]:
    """(appeal_id, submission_id, dev)를 돌려준다 — 채점까지 끝난 Submission 에
    이의를 하나 걸어둔다. `dev`는 본인 조회 표면(#61) 테스트에 쓴다."""

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
    return response.json()["id"], submission["id"], dev


def _appeal_ready(client, category, landing_type) -> tuple[int, int]:
    """(appeal_id, submission_id)를 돌려준다 — dev 자격증명이 필요 없는 테스트용."""

    appeal_id, submission_id, _dev = _appeal_ready_full(client, category, landing_type)
    return appeal_id, submission_id


def SOURCE_READINGS_URL(submission_id: int) -> str:
    return f"/api/submissions/{submission_id}/source-readings"


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


# --- Developer 가 자기 소스의 열람 기록을 본다 (#61, ADR-0022) -----------------


@pytest.mark.django_db
def test_developer_sees_no_readings_before_anyone_reveals(client, category, landing_type):
    """열람이 없으면 빈 목록으로 200 — "아직 아무도 안 봤다"는 없는 리소스가 아니다."""

    _appeal_id, submission_id, dev = _appeal_ready_full(client, category, landing_type)

    response = client.get(SOURCE_READINGS_URL(submission_id), **_auth_header(dev["access"]))

    assert response.status_code == 200
    # 페이지네이션된 응답(#72) — 빈 목록은 items 가 비고 count 가 0 이다.
    assert response.json() == {"items": [], "count": 0}


@pytest.mark.django_db
def test_two_reveals_are_visible_as_two_readings_on_the_developer_surface(
    client, category, landing_type
):
    """#60 의 펼침을 실제로 두 번 일으킨 뒤 이 표면에서 두 건이 보인다 — 기록이
    실제로 여기까지 도달한다는 것을 한 번은 끝까지 친다(#61 AC)."""

    appeal_id, submission_id, dev = _appeal_ready_full(client, category, landing_type)
    operator = _operator_client("op-twice")

    assert _reveal_source(operator, appeal_id).status_code == 200
    assert _reveal_source(operator, appeal_id).status_code == 200

    response = client.get(SOURCE_READINGS_URL(submission_id), **_auth_header(dev["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 2
    items = body["items"]
    assert len(items) == 2
    # 최신순 — 두 열람 시각이 내림차순으로 정렬되어 있다.
    assert items[0]["read_at"] >= items[1]["read_at"]


@pytest.mark.django_db
def test_developer_cannot_see_another_developers_source_readings(client, category, landing_type):
    _appeal_id, submission_id, _dev = _appeal_ready_full(client, category, landing_type)
    other_dev = _verified_user(client, "dev-2", "dev-2-ci")

    response = client.get(
        SOURCE_READINGS_URL(submission_id), **_auth_header(other_dev["access"])
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_unauthenticated_request_for_source_readings_is_401(client, category, landing_type):
    _appeal_id, submission_id, _dev = _appeal_ready_full(client, category, landing_type)

    response = client.get(SOURCE_READINGS_URL(submission_id))

    assert response.status_code == 401


@pytest.mark.django_db
def test_source_reading_response_does_not_expose_operator_identity(
    client, category, landing_type
):
    """운영자의 이름은 주지 않는다 — 응답 본문에 신원이 없음을 직접 확인한다."""

    appeal_id, submission_id, dev = _appeal_ready_full(client, category, landing_type)
    operator = _operator_client("op-secret-name")
    assert _reveal_source(operator, appeal_id).status_code == 200

    response = client.get(SOURCE_READINGS_URL(submission_id), **_auth_header(dev["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert set(body["items"][0].keys()) == {"read_at"}
    assert "op-secret-name" not in response.content.decode("utf-8")


# --- #72: 감사 기록은 대상의 삭제에 딸려 사라지지 않는다 --------------------------


@pytest.mark.django_db
def test_deleting_an_appeal_cannot_silently_erase_its_source_readings(
    client, category, landing_type
):
    """Appeal 을 지우는 것만으로 "누가 이 소스를 봤는가"가 사라지면 안 된다(#72).

    `read_by` 만 PROTECT 로 지켜서는 부족했다 — 열람한 계정을 지울 수는 없어도
    Appeal 행 하나를 지우면 기록이 통째로 조용히 사라졌다. 지우려면 감사 기록을
    **먼저 명시적으로** 지워야 한다. 그 한 줄이 코드에 남는 것이 이 결정의 목적이다.
    """

    from django.db.models import ProtectedError

    from appeals.models import Appeal

    appeal_id, submission_id, _dev = _appeal_ready_full(client, category, landing_type)
    operator = _operator_client("op-protect-appeal")
    assert _reveal_source(operator, appeal_id).status_code == 200

    with pytest.raises(ProtectedError):
        Appeal.objects.get(id=appeal_id).delete()

    assert SourceReading.objects.filter(submission_id=submission_id).count() == 1


@pytest.mark.django_db
def test_deleting_a_submission_cannot_silently_erase_its_source_readings(
    client, category, landing_type
):
    """Submission 쪽 경로도 같이 막는다 — 한쪽만 막으면 다른 쪽으로 돌아 지울 수 있다."""

    from django.db.models import ProtectedError

    from submissions.models import Submission

    appeal_id, submission_id, _dev = _appeal_ready_full(client, category, landing_type)
    operator = _operator_client("op-protect-submission")
    assert _reveal_source(operator, appeal_id).status_code == 200

    with pytest.raises(ProtectedError):
        Submission.objects.get(id=submission_id).delete()

    assert SourceReading.objects.filter(submission_id=submission_id).count() == 1


@pytest.mark.django_db
def test_deleting_an_appeal_cannot_silently_erase_its_ruling(client, category, landing_type):
    """심판 기록도 같다(#72) — "누가 돈을 움직였는가"가 삭제 한 번으로 사라지면
    #24 가 연 문제로 되돌아간다."""

    from django.db.models import ProtectedError

    from appeals.models import Appeal, AppealRuling

    appeal_id, _submission_id, _dev = _appeal_ready_full(client, category, landing_type)
    operator = _operator_client("op-protect-ruling")
    ruled = operator.post(
        f"{OPERATOR_APPEALS_URL}/{appeal_id}/rule",
        data={"decision": "reject", "ruling_note": "기각한다."},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert ruled.status_code == 200, ruled.content

    with pytest.raises(ProtectedError):
        Appeal.objects.get(id=appeal_id).delete()

    assert AppealRuling.objects.filter(appeal_id=appeal_id).count() == 1


# --- #72: 열람 기록 조회에 상한이 있다 -------------------------------------------


@pytest.mark.django_db
def test_source_reading_list_is_paginated(client, category, landing_type):
    """열람은 중복 제거가 없어 무제한으로 쌓이는데(#60), 조회에는 상한이 있어야 한다.

    한 페이지를 넘게 펼친 뒤, 한 번의 응답이 페이지 크기를 넘지 않으면서도 전체
    개수는 정확히 말하는지 확인한다 — 상한이 "일부를 조용히 감춘다"가 되면 안 된다.
    """

    page_size = 20
    appeal_id, submission_id, dev = _appeal_ready_full(client, category, landing_type)
    operator = _operator_client("op-many-reveals")
    for _ in range(page_size + 3):
        assert _reveal_source(operator, appeal_id).status_code == 200

    response = client.get(SOURCE_READINGS_URL(submission_id), **_auth_header(dev["access"]))

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == page_size + 3
    assert len(body["items"]) == page_size

    second = client.get(
        SOURCE_READINGS_URL(submission_id), {"page": 2}, **_auth_header(dev["access"])
    )
    assert second.status_code == 200
    assert len(second.json()["items"]) == 3


@pytest.mark.django_db
def test_pagination_does_not_open_another_developers_readings(client, category, landing_type):
    """소유권 검사가 페이지네이션보다 먼저다 — 남의 것이면 빈 페이지가 아니라 403 이다."""

    _appeal_id, submission_id, _dev = _appeal_ready_full(client, category, landing_type)
    other_dev = _verified_user(client, "dev-3", "dev-3-ci")

    response = client.get(
        SOURCE_READINGS_URL(submission_id), {"page": 1}, **_auth_header(other_dev["access"])
    )

    assert response.status_code == 403
