"""Assignment 7 — 강사가 소스를 펼쳐 보고 그 열람이 남는다 (#211, ADR-0022/0028).

공모전에서 Sponsor가 Award 전까지 소스를 못 보는 이유(ADR-0014 — 돈을 안 내고
아이디어·코드만 가져가는 것을 막는다)가 Assignment에는 없다(Escrow도 지식재산권
이전도 없다, ADR-0028). 대신 ADR-0022가 Operator에 대해 세운 모양을 그대로
Sponsor에게 적용한다:

- 기본은 접혀 있고 명시적으로 펼 때만 기록이 남는다 — 목록·상세를 훑는 것만으로는
  남지 않는다.
- 누가·언제·어느 Submission의 소스를 봤는지가 남는다(`AssignmentSourceReading`).
- Developer가 자기 것을 확인할 수 있다.

그리고 공모전의 규칙(ADR-0014 — Sponsor는 Award 후에만)은 하나도 바뀌지 않는다 —
이 파일의 마지막 테스트가 그것을 증명한다.

Prior art: `tests/test_source_readings.py`(Operator쪽 같은 모양),
`tests/test_assignment_submissions.py`(과제 생성·열기·제출 헬퍼).
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from contests.models import Category, Contest, DeliverableType
from submissions.models import AssignmentSourceReading, Submission

ASSIGNMENTS_URL = "/api/assignments"
CONTESTS_URL = "/api/contests"
SUBMISSIONS_URL = "/api/submissions"
PAYMENTS_URL = "/api/payments"
GRANT_URL = "/api/operator/assignment-permissions/grant"
OPERATOR_PW = "operator-pw-asrc-9931-xyz"
OPERATOR_ORIGIN = "http://testserver"


def _sign(*, webhook_id: str, order_id: str, status: str) -> str:
    key = settings.PAYMENT_WEBHOOK_SECRET
    canonical = f"{webhook_id}:{order_id}:{status}".encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _operator_client(username="root-asrc"):
    call_command("create_operator", username, password=OPERATOR_PW, superuser=True)
    client = Client()
    response = client.post(
        "/api/operator/login",
        data={"username": username, "password": OPERATOR_PW},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content
    return client


def _login(client, uid, email=None):
    email = email or f"{uid}@example.com"
    response = client.post(
        "/api/auth/social/kakao/login",
        data={"access_token": f"{uid}:{email}"},
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    return response.json()


def _auth_header(access: str) -> dict:
    return {"HTTP_AUTHORIZATION": f"Bearer {access}"}


def _me(client, access: str) -> dict:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()


def _verify(client, access: str, *, ci: str) -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"사람|1995-01-01|{ci}|{ci}-di"},
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 200, response.content


def _grant_permission(operator_client, *, username, reason="수업 개설 승인"):
    response = operator_client.post(
        GRANT_URL,
        data={"username": username, "reason": reason},
        content_type="application/json",
        HTTP_ORIGIN=OPERATOR_ORIGIN,
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def landing_type(db):
    return DeliverableType.objects.create(name="랜딩·원페이지", minimum_prize=500_000)


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _create_and_open_assignment(client, *, deliverable_type_ids, sponsor_uid, deadline_at=None):
    root = _operator_client(f"root-{sponsor_uid}")
    pair = _login(client, sponsor_uid)
    username = _me(client, pair["access"])["username"]
    _grant_permission(root, username=username)

    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))
    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": f"{sponsor_uid}의 과제",
            "deliverable_type_ids": deliverable_type_ids,
            "description": "과제 설명",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [{"text": "함수를 정의한다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]

    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert opened.status_code == 200, opened.content
    return {
        "id": assignment_id,
        "invite_code": opened.json()["invite_code"],
        "sponsor_access": pair["access"],
    }


def _submit_with_repo(client, access: str, contest_id: int, developer_user_id: int) -> dict:
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest_id, developer_user_id),
                    "label": "메인 소스",
                },
                {
                    "kind": "repository",
                    "value": "https://github.com/asrc-org/asrc-repo",
                    "label": "GitHub",
                },
            ],
            "invite_code": None,
        },
        content_type="application/json",
        **_auth_header(access),
    )
    return response


def _submit(client, access: str, contest_id: int, invite_code: str) -> dict:
    developer_user_id = _me(client, access)["id"]
    response = client.post(
        f"{CONTESTS_URL}/{contest_id}/submissions",
        data={
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest_id, developer_user_id),
                    "label": "메인 소스",
                },
                {
                    "kind": "repository",
                    "value": "https://github.com/asrc-org/asrc-repo",
                    "label": "GitHub",
                },
            ],
            "invite_code": invite_code,
        },
        content_type="application/json",
        **_auth_header(access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _reveal(client, sponsor_access: str, assignment_id: int, submission_id: int):
    return client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/submissions/{submission_id}/source",
        content_type="application/json",
        **_auth_header(sponsor_access),
    )


@pytest.mark.django_db
def test_sponsor_can_reveal_submission_source_before_deadline_and_it_is_recorded(
    client, landing_type
):
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-1"
    )
    student_pair = _login(client, "asrc-student-1")
    submission = _submit(client, student_pair["access"], assignment["id"], assignment["invite_code"])

    # 마감이 이레 뒤인데도(진행 중), 강사가 지도를 위해 소스를 펼칠 수 있다.
    reveal = _reveal(client, assignment["sponsor_access"], assignment["id"], submission["id"])
    assert reveal.status_code == 200, reveal.content
    body = reveal.json()
    kinds = {a["kind"] for a in body["assets"]}
    assert kinds == {"source", "repository"}
    source_asset = next(a for a in body["assets"] if a["kind"] == "source")
    assert source_asset["url"]  # presigned 다운로드 URL
    repo_asset = next(a for a in body["assets"] if a["kind"] == "repository")
    assert repo_asset["url"] == "https://github.com/asrc-org/asrc-repo"

    assert AssignmentSourceReading.objects.filter(submission_id=submission["id"]).count() == 1

    # 학생이 자기 열람 기록을 확인할 수 있다.
    own = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}/assignment-source-readings",
        **_auth_header(student_pair["access"]),
    )
    assert own.status_code == 200, own.content
    readings = own.json()
    assert len(readings) == 1
    assert "read_at" in readings[0]
    assert "read_by" not in readings[0]


@pytest.mark.django_db
def test_revealed_source_download_url_has_a_filename_with_extension(client, landing_type):
    """#241: 이 경로는 storage.api를 거치지 않고 직접 presign하지만(위 `_reveal`
    docstring), 그래도 같은 헬퍼(`storage.filenames.build_download_filename`)로
    파일명을 만들어야 한다 — 한 곳만 고치면 나머지에서 같은 신고가 다시 온다는
    것이 #241의 범위 진술이다."""

    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-ext"
    )
    student_pair = _login(client, "asrc-student-ext")
    developer_user_id = _me(client, student_pair["access"])["id"]

    submit = client.post(
        f"{CONTESTS_URL}/{assignment['id']}/submissions",
        data={
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(assignment["id"], developer_user_id),
                    "label": "메인 소스",
                    "content_type": "application/zip",
                },
            ],
            "invite_code": assignment["invite_code"],
        },
        content_type="application/json",
        **_auth_header(student_pair["access"]),
    )
    assert submit.status_code == 201, submit.content
    submission = submit.json()

    reveal = _reveal(client, assignment["sponsor_access"], assignment["id"], submission["id"])
    assert reveal.status_code == 200, reveal.content
    source_asset = next(a for a in reveal.json()["assets"] if a["kind"] == "source")
    assert 'filename="download.zip"' in source_asset["url"]


@pytest.mark.django_db
def test_browsing_list_and_detail_does_not_create_a_reading(client, landing_type):
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-2"
    )
    student_pair = _login(client, "asrc-student-2")
    submission = _submit(client, student_pair["access"], assignment["id"], assignment["invite_code"])

    list_resp = client.get(
        f"{ASSIGNMENTS_URL}/{assignment['id']}/submissions",
        **_auth_header(assignment["sponsor_access"]),
    )
    assert list_resp.status_code == 200, list_resp.content
    assert len(list_resp.json()) == 1
    # 목록 스키마는 #210 의 `AssignmentSubmissionOut` 하나로 합쳐졌다(통합) —
    # 두 체인이 병렬로 같은 엔드포인트를 만들어 필드 이름이 갈렸던 자리다.
    assert list_resp.json()[0]["submission_id"] == submission["id"]

    detail_resp = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}",
        **_auth_header(assignment["sponsor_access"]),
    )
    assert detail_resp.status_code == 200, detail_resp.content
    # 상세를 훑는 것만으로는 소스가 보이지 않는다 — 펼치는 행위가 따로 있어야 한다.
    detail_kinds = {a["kind"] for a in detail_resp.json()["assets"]}
    assert "source" not in detail_kinds
    assert "repository" not in detail_kinds

    assert AssignmentSourceReading.objects.filter(submission_id=submission["id"]).count() == 0

    own = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}/assignment-source-readings",
        **_auth_header(student_pair["access"]),
    )
    assert own.status_code == 200, own.content
    assert own.json() == []


@pytest.mark.django_db
def test_reveal_twice_creates_two_readings(client, landing_type):
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-3"
    )
    student_pair = _login(client, "asrc-student-3")
    submission = _submit(client, student_pair["access"], assignment["id"], assignment["invite_code"])

    first = _reveal(client, assignment["sponsor_access"], assignment["id"], submission["id"])
    second = _reveal(client, assignment["sponsor_access"], assignment["id"], submission["id"])
    assert first.status_code == 200, first.content
    assert second.status_code == 200, second.content

    assert AssignmentSourceReading.objects.filter(submission_id=submission["id"]).count() == 2

    own = client.get(
        f"{SUBMISSIONS_URL}/{submission['id']}/assignment-source-readings",
        **_auth_header(student_pair["access"]),
    )
    assert len(own.json()) == 2


@pytest.mark.django_db
def test_other_assignments_sponsor_cannot_reveal(client, landing_type):
    assignment_a = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-4a"
    )
    assignment_b = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-4b"
    )
    student_pair = _login(client, "asrc-student-4")
    submission = _submit(
        client, student_pair["access"], assignment_a["id"], assignment_a["invite_code"]
    )

    # b의 강사가 a 과제의 assignment_id 를 빌려 시도해도 404, a 강사 것으로도 확인.
    cross = _reveal(client, assignment_b["sponsor_access"], assignment_a["id"], submission["id"])
    assert cross.status_code == 404

    wrong_assignment_id = _reveal(
        client, assignment_b["sponsor_access"], assignment_b["id"], submission["id"]
    )
    assert wrong_assignment_id.status_code == 404

    assert AssignmentSourceReading.objects.filter(submission_id=submission["id"]).count() == 0


@pytest.mark.django_db
def test_assignment_list_and_reveal_require_owner_sponsor(client, landing_type):
    assignment_a = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-5a"
    )
    assignment_b = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="asrc-sponsor-5b"
    )

    list_resp = client.get(
        f"{ASSIGNMENTS_URL}/{assignment_a['id']}/submissions",
        **_auth_header(assignment_b["sponsor_access"]),
    )
    assert list_resp.status_code == 404


@pytest.mark.django_db
def test_prize_contest_sponsor_source_access_rule_unchanged(client, landing_type):
    """ADR-0014 회귀 테스트 — Assignment의 소스 펼침이 프라이즈 공모전 규칙을 건드리지
    않는다: Sponsor는 여전히 Award 전까지 소스를 볼 수 없고, Assignment 전용
    펼침 엔드포인트도 프라이즈 Contest에는 아예 닿지 않는다."""

    category = Category.objects.create(name="교육-asrc-prize")
    sponsor_pair = _login(client, "asrc-prize-sponsor")
    _verify(client, sponsor_pair["access"], ci="asrc-prize-sponsor-ci")

    contest_resp = client.post(
        CONTESTS_URL,
        data={
            "title": "상금 공모전",
            "category_id": category.id,
            "deliverable_type_ids": [landing_type.id],
            "prize": 1_000_000,
            "deadline_at": (timezone.now() + timedelta(days=7)).isoformat(),
            "requirements": [],
        },
        content_type="application/json",
        **_auth_header(sponsor_pair["access"]),
    )
    assert contest_resp.status_code == 200, contest_resp.content
    contest = contest_resp.json()

    payment = client.post(
        PAYMENTS_URL,
        data={"contest_id": contest["id"]},
        content_type="application/json",
        **_auth_header(sponsor_pair["access"]),
    ).json()
    webhook_id = f"wh-asrc-{contest['id']}"
    body = {"webhook_id": webhook_id, "order_id": payment["order_id"], "status": "paid"}
    body["signature"] = _sign(webhook_id=webhook_id, order_id=payment["order_id"], status="paid")
    webhook_resp = client.post(f"{PAYMENTS_URL}/webhook", data=body, content_type="application/json")
    assert webhook_resp.status_code == 200, webhook_resp.content

    student_pair = _login(client, "asrc-prize-student")
    _verify(client, student_pair["access"], ci="asrc-prize-student-ci")
    student_user_id = _me(client, student_pair["access"])["id"]

    submitted = client.post(
        f"{CONTESTS_URL}/{contest['id']}/submissions",
        data={
            "assets": [
                {
                    "kind": "source",
                    "value": _source_object_key(contest["id"], student_user_id),
                }
            ]
        },
        content_type="application/json",
        **_auth_header(student_pair["access"]),
    )
    assert submitted.status_code == 201, submitted.content
    submission_id = submitted.json()["id"]

    # 1) 일반 상세 조회에서 Sponsor에게 소스가 여전히 보이지 않는다(ADR-0014).
    detail = client.get(
        f"{SUBMISSIONS_URL}/{submission_id}", **_auth_header(sponsor_pair["access"])
    )
    assert detail.status_code == 200, detail.content
    assert "source" not in {a["kind"] for a in detail.json()["assets"]}

    # 2) Assignment 전용 펼침 엔드포인트는 프라이즈 Contest 의 id 로는 아예 404다 —
    #    카테고리가 assignment_category 가 아니므로 `_get_owned_assignment` 가 막는다.
    reveal = _reveal(client, sponsor_pair["access"], contest["id"], submission_id)
    assert reveal.status_code == 404

    assert AssignmentSourceReading.objects.filter(submission_id=submission_id).count() == 0
    assert Submission.objects.filter(id=submission_id).exists()
