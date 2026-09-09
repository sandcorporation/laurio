"""Assignment 6 — 마감되면 채점되고 학생과 강사가 점수를 본다 (#210, ADR-0003/0006/0028).

**백엔드에 새 코드가 거의 없어야 정상이다.** 마감 전이(`assignment-close`)와 채점 스캔
(`submission-scoring`)은 이미 #207/#208이 남긴 분류 선언(`Contest.Status.SCOREABLE`에
`ASSIGNMENT_CLOSED: True`)만으로 과제를 집는다 — 이 파일의 절반은 그 사실을 HTTP로
확인하는 것이다(CLAUDE.md — 시임은 언제나 HTTP).

**진짜로 고친 것 하나**: `Contest.appeal_window_open`이 심사기간이 없는 Contest를
"창이 닫히지 않았다"로 답해 왔는데(#74의 원래 뜻은 CLOSED 상태에서 `judging_ends_at`이
아직 안 찍힌 찰나를 위한 것이었다 — 실제로는 도달 불가능한 경우였다), Assignment는
`judging_ends_at`을 영원히 null로 둔다(ADR-0028 — 심사기간 자체가 없다). 그 결과 채점이
끝난 과제 제출에 대해 `POST /submissions/{id}/appeal`이 **성공해 버렸다** — 스펙 #197의
"Award·Appeal·Distribution·Payout이 없다"를 정면으로 어긴다. 이 파일이 그 red를 먼저
잡고, `contests/models.py`가 Assignment status를 명시적으로 제외하도록 고친다.

Prior art: `tests/test_own_score.py`(Developer 자기 점수 조회), `tests/test_source_readings.py`
(`_close_contest`·`_run_scoring`·ClockOverride로 시각을 옮기는 법), `tests/test_assignments.py`·
`tests/test_assignment_submissions.py`(과제 생성·열기·InviteCode 제출 헬퍼).
"""

from __future__ import annotations

import io
import uuid
import zipfile
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from contests.models import Contest, DeliverableType
from core.models import ClockOverride
from storage.adapters.fake import FakeStorageAdapter

ASSIGNMENTS_URL = "/api/assignments"
CONTESTS_URL = "/api/contests"
GRANT_URL = "/api/operator/assignment-permissions/grant"
ASSIGNMENT_CLOSE_SCAN_URL = "/api/internal/scans/assignment-close"
SCORING_SCAN_URL = "/api/internal/scans/submission-scoring"
TICK_URL = "/api/internal/tick"
OPERATOR_PW = "correct-horse-battery-9931-xyz"
OPERATOR_ORIGIN = "http://testserver"


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _operator_client(username="root-asgnscore"):
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


def _username(client, access: str) -> str:
    response = client.get("/api/accounts/me", HTTP_AUTHORIZATION=f"Bearer {access}")
    assert response.status_code == 200, response.content
    return response.json()["username"]


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
    return DeliverableType.objects.create(name="랜딩·원페이지-점수", minimum_prize=500_000)


def _create_and_open_assignment(client, *, deliverable_type_ids, sponsor_uid, deadline_at):
    root = _operator_client(f"root-{sponsor_uid}")
    pair = _login(client, sponsor_uid)
    username = _username(client, pair["access"])
    _grant_permission(root, username=username)

    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": f"{sponsor_uid}의 과제",
            "deliverable_type_ids": deliverable_type_ids,
            "description": "과제 설명",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [{"text": "로그인 기능이 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]
    requirement_id = created.json()["requirements"][0]["id"]

    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(pair["access"]),
    )
    assert opened.status_code == 200, opened.content
    body = opened.json()
    return {
        "id": assignment_id,
        "invite_code": body["invite_code"],
        "requirement_id": requirement_id,
        "sponsor": pair,
    }


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit_scoreable(client, student_access: str, student_user_id: int, assignment: dict) -> dict:
    """Evidence 가 소스에서 실제로 확인되도록 심어 100% 채점이 나오게 한다
    (`FakeLLMScoringAdapter`, `tests/test_source_readings.py`와 같은 패턴)."""

    source_key = _source_object_key(assignment["id"], student_user_id)
    marker = f"MARKER_{uuid.uuid4().hex}"
    FakeStorageAdapter().write_object(source_key, _zip_bytes({"app.py": f"# {marker}\n"}))

    response = client.post(
        f"{CONTESTS_URL}/{assignment['id']}/submissions",
        data={
            "assets": [{"kind": "source", "value": source_key}],
            "requirement_responses": [
                {
                    "requirement_id": assignment["requirement_id"],
                    "is_met": True,
                    "evidence": [{"kind": "source_location", "value": marker}],
                }
            ],
            "invite_code": assignment["invite_code"],
        },
        content_type="application/json",
        **_auth_header(student_access),
    )
    assert response.status_code == 201, response.content
    return response.json()


def _move_deadline_into_the_past(assignment_id: int, *, deadline: "timezone.datetime") -> None:
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )


@pytest.mark.django_db
def test_deadline_scan_closes_the_assignment_when_deadline_has_passed(client, landing_type):
    """마감 전이 스캔이 시각만 보고 ASSIGNMENT_OPEN -> ASSIGNMENT_CLOSED 로 옮긴다
    (#207 이 등록한 스캔, ADR-0003) — 이 파일의 몫은 이것을 HTTP 로 확인하는 것뿐이다."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-1",
        deadline_at=deadline,
    )
    _move_deadline_into_the_past(assignment["id"], deadline=deadline)

    scan_resp = client.post(ASSIGNMENT_CLOSE_SCAN_URL, **_internal_headers())
    assert scan_resp.status_code == 200, scan_resp.content

    contest = Contest.objects.get(id=assignment["id"])
    assert contest.status == Contest.Status.ASSIGNMENT_CLOSED
    # Assignment 에는 심사기간이 없다 — Award·Distribution 이 전혀 없으므로 채울
    # 이유가 없다(ADR-0028, contests/apps.py 의 등록 주석).
    assert contest.judging_ends_at is None


@pytest.mark.django_db
def test_scoring_scan_picks_up_closed_assignment_submission(client, landing_type):
    """채점 스캔이 `Contest.Status.SCOREABLE`(ASSIGNMENT_CLOSED: True)만 보고
    과제의 Submission 을 집어 Score 를 남긴다 — 과제 전용 분기가 스캔 안에 없다."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-2",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-2")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    submission = _submit_scoreable(client, student_pair["access"], student_id, assignment)

    _move_deadline_into_the_past(assignment["id"], deadline=deadline)
    close_resp = client.post(ASSIGNMENT_CLOSE_SCAN_URL, **_internal_headers())
    assert close_resp.status_code == 200, close_resp.content

    score_resp = client.post(SCORING_SCAN_URL, **_internal_headers())
    assert score_resp.status_code == 200, score_resp.content
    assert score_resp.json()["count"] == 1

    own_score = client.get(
        f"/api/submissions/{submission['id']}/score", **_auth_header(student_pair["access"])
    )
    assert own_score.status_code == 200, own_score.content
    assert own_score.json()["percentage"] == "100.00"


@pytest.mark.django_db
def test_scoring_scan_is_a_no_op_once_the_submission_already_has_a_score(client, landing_type):
    """ADR-0006 — 한 번만 채점된다. 스캔을 두 번 쏴도 두 번째는 대상에서 빠진다
    (`scoring.services` 의 후보 쿼리가 `score__isnull=True` 를 본다)."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-3",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-3")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    _submit_scoreable(client, student_pair["access"], student_id, assignment)

    _move_deadline_into_the_past(assignment["id"], deadline=deadline)
    client.post(ASSIGNMENT_CLOSE_SCAN_URL, **_internal_headers())
    first = client.post(SCORING_SCAN_URL, **_internal_headers())
    assert first.json()["count"] == 1

    second = client.post(SCORING_SCAN_URL, **_internal_headers())
    assert second.status_code == 200
    assert second.json()["count"] == 0


@pytest.mark.django_db
def test_tick_runs_the_whole_registry_and_both_close_and_score_the_assignment_in_one_pass(
    client, landing_type
):
    """`/api/internal/tick`(`run_all`) 이 등록부 전체를 한 바퀴 돈다 — 데모/시연 지침
    (CLAUDE.md — tick 은 시간을 앞당기지 않는다, 데이터의 시각을 과거로 옮긴 뒤 쏜다)이
    실제로 성립하는지 여기서 확인한다."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-4",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-4")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    submission = _submit_scoreable(client, student_pair["access"], student_id, assignment)

    _move_deadline_into_the_past(assignment["id"], deadline=deadline)
    tick_resp = client.post(TICK_URL, **_internal_headers())
    assert tick_resp.status_code == 200, tick_resp.content

    contest = Contest.objects.get(id=assignment["id"])
    assert contest.status == Contest.Status.ASSIGNMENT_CLOSED

    own_score = client.get(
        f"/api/submissions/{submission['id']}/score", **_auth_header(student_pair["access"])
    )
    assert own_score.status_code == 200, own_score.content


@pytest.mark.django_db
def test_student_sees_own_score_and_reasoning_with_no_appeal_window(client, landing_type):
    """학생이 마감 후 자기 Score 와 판정 근거를 본다 — 그리고 이의 창은 언제나 닫혀
    있다(과제에는 이의제기가 없다, 스펙 #197)."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-5",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-5")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    submission = _submit_scoreable(client, student_pair["access"], student_id, assignment)

    _move_deadline_into_the_past(assignment["id"], deadline=deadline)
    client.post(TICK_URL, **_internal_headers())

    own_score = client.get(
        f"/api/submissions/{submission['id']}/score", **_auth_header(student_pair["access"])
    ).json()

    assert own_score["percentage"] == "100.00"
    assert own_score["model_version"]
    assert own_score["reasoning"]
    assert own_score["can_appeal"] is False
    assert own_score["appeal_deadline"] is None


@pytest.mark.django_db
def test_scored_assignment_submission_next_action_names_no_missing_concept(client, landing_type):
    """#248 — 채점이 끝난 과제 제출의 `next_action`이 과제에 없는 개념(이의·인수·
    배분)을 가리키면 안 된다(ADR-0028).

    `submissions.participation.next_action_for`는 공모전을 염두에 두고
    짜였다 — 이의 창(`appeal_window_open`)과 심사 창(`judging_window_open`)이
    둘 다 거짓이면(과제는 항상 그렇다, 위 다른 테스트가 이미 고정한 사실) 그
    뒤에 남는 유일한 기본 분기는 `AWAITING_DISTRIBUTION`("상금 배분을
    기다리는 중입니다")이다. 과제에는 Award도 Distribution도 없으므로 그
    문장은 거짓이고, 학생 화면(#248)이 그 거짓을 그대로 옮겨 보여주게 된다."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-nextaction",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-nextaction")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    submission = _submit_scoreable(client, student_pair["access"], student_id, assignment)

    _move_deadline_into_the_past(assignment["id"], deadline=deadline)
    client.post(TICK_URL, **_internal_headers())

    own = client.get(
        f"{CONTESTS_URL}/{assignment['id']}/submissions/me", **_auth_header(student_pair["access"])
    )
    assert own.status_code == 200, own.content
    assert own.json()["next_action"] == "assignment_scored"

    # 「내 참가 현황」도 같은 값을 낸다 — 판정기가 하나(`next_action_for`)뿐이라
    # 두 조회가 갈릴 수 없다.
    mine = client.get("/api/submissions/mine", **_auth_header(student_pair["access"]))
    assert mine.status_code == 200, mine.content
    (row,) = [item for item in mine.json()["items"] if item["submission_id"] == submission["id"]]
    assert row["next_action"] == "assignment_scored"


@pytest.mark.django_db
def test_creating_an_appeal_for_an_assignment_submission_is_rejected(client, landing_type):
    """과제에는 Appeal 이 없다(스펙 #197 Out of Scope). `Contest.appeal_window_open`이
    심사기간 없는 Contest 를 "닫히지 않았다"로 답해 왔는데, Assignment 는 심사기간이
    영원히 없어 이 규칙을 그대로 두면 이의가 접수돼 버린다 — 그 red 를 여기서 잡는다."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-6",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-6")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    submission = _submit_scoreable(client, student_pair["access"], student_id, assignment)

    _move_deadline_into_the_past(assignment["id"], deadline=deadline)
    client.post(TICK_URL, **_internal_headers())

    response = client.post(
        f"/api/submissions/{submission['id']}/appeal",
        data={"reason": "이 판정에 이견이 있습니다."},
        content_type="application/json",
        **_auth_header(student_pair["access"]),
    )
    assert response.status_code == 409, response.content


@pytest.mark.django_db
def test_sponsor_sees_submission_list_with_scores_after_deadline(client, landing_type):
    """강사가 제출 목록과 각 제출의 Score·근거를 본다."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-7",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-7")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    _submit_scoreable(client, student_pair["access"], student_id, assignment)

    _move_deadline_into_the_past(assignment["id"], deadline=deadline)
    client.post(TICK_URL, **_internal_headers())

    listing = client.get(
        f"{ASSIGNMENTS_URL}/{assignment['id']}/submissions",
        **_auth_header(assignment["sponsor"]["access"]),
    )
    assert listing.status_code == 200, listing.content
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["score"] is not None
    assert rows[0]["score"]["percentage"] == "100.00"
    assert rows[0]["score"]["reasoning"]


@pytest.mark.django_db
def test_sponsor_submission_list_shows_null_score_before_scoring(client, landing_type):
    """마감 전에는 아직 채점되지 않았다 — `score` 는 null 이지 빈 배열이나 0 이 아니다."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-8",
        deadline_at=deadline,
    )
    student_pair = _login(client, "ascore-student-8")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    _submit_scoreable(client, student_pair["access"], student_id, assignment)

    listing = client.get(
        f"{ASSIGNMENTS_URL}/{assignment['id']}/submissions",
        **_auth_header(assignment["sponsor"]["access"]),
    )
    assert listing.status_code == 200, listing.content
    rows = listing.json()
    assert len(rows) == 1
    assert rows[0]["score"] is None


@pytest.mark.django_db
def test_another_sponsor_cannot_list_this_assignments_submissions(client, landing_type):
    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="ascore-sponsor-9",
        deadline_at=deadline,
    )
    root = _operator_client("root-stranger-9")
    stranger_pair = _login(client, "ascore-stranger-9")
    stranger_username = _username(client, stranger_pair["access"])
    _grant_permission(root, username=stranger_username)

    response = client.get(
        f"{ASSIGNMENTS_URL}/{assignment['id']}/submissions",
        **_auth_header(stranger_pair["access"]),
    )
    assert response.status_code == 404
