"""Assignment 8 — 과제만 연 강사가 탈퇴한다, 돈·통지 불변식 전수 확인 (#212, ADR-0028/0025/0004).

**이 티켓의 몸통은 새 코드가 아니라 전수 확인이다.** #205가 선언한 28개 분류
(`Contest.Status.REFUNDABLE`·`REOPENABLE`·`SENDS_LIFECYCLE_NOTICES`·
`BLOCKS_SPONSOR_WITHDRAWAL`·`REQUIRES_IDENTITY_RETENTION`이 Assignment 두 상태
모두에 False)만으로 환불·배분·지급·연장·재개최·알림·원장·탈퇴 전부가 과제를
비켜간다 — 새로 고칠 것이 있다면 그 선언이 부족했다는 뜻이다.

**단언의 모양이 중요하다.** "발송이 성공했다"가 아니라 **행이 하나도 생기지
않았다**로 단언한다 — Fake 알림 어댑터는 수신자를 보지 않고 성공을 반환하므로
성공 단언은 연락처 없는 학생에게 실패한 dispatch 세 건이 쌓이는 실제 버그를
그대로 통과시킨다(ADR-0028이 적어 둔 함정).

Prior art: `tests/test_assignment_scoring.py`(과제 생성·열기·제출·마감·채점
헬퍼), `tests/test_withdrawal.py`(탈퇴 HTTP 패턴), `tests/test_scheduler_tick.py`
(`run_all`/`/api/internal/tick`).
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

from accounts.models import SponsorProfile
from contests.models import Contest, DeliverableType
from core.models import ClockOverride
from distributions.models import Distribution
from ledger.models import JournalEntry
from notifications.models import Notification, NotificationDispatch
from payouts.models import Payout
from storage.adapters.fake import FakeStorageAdapter
from verification.models import RetainedIdentity, Verification

ASSIGNMENTS_URL = "/api/assignments"
CONTESTS_URL = "/api/contests"
GRANT_URL = "/api/operator/assignment-permissions/grant"
WITHDRAWAL_URL = "/api/accounts/withdrawal"
TICK_URL = "/api/internal/tick"
ASSIGNMENT_CLOSE_SCAN_URL = "/api/internal/scans/assignment-close"
SCORING_SCAN_URL = "/api/internal/scans/submission-scoring"
OPERATOR_PW = "correct-horse-battery-9931-sweep"
OPERATOR_ORIGIN = "http://testserver"


def _internal_headers():
    return {"HTTP_X_INTERNAL_TOKEN": settings.INTERNAL_API_TOKEN}


def _operator_client(username="root-asweep"):
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


def _verify(client, access: str, *, ci: str, name: str = "사람", birth: str = "1995-01-01") -> None:
    response = client.post(
        "/api/verification/verify",
        data={"verification_token": f"{name}|{birth}|{ci}|{ci}-di"},
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
    return DeliverableType.objects.create(name="랜딩·원페이지-스윕", minimum_prize=500_000)


def _create_and_open_assignment(
    client, *, deliverable_type_ids, sponsor_uid, sponsor_access=None, deadline_at=None
):
    """열려 있는 과제 하나 — 자격 부여부터 연 상태까지. `sponsor_access`를 주면
    (이미 로그인된 sponsor를 재사용하려는 호출부를 위해) 새로 로그인하지 않는다."""

    root = _operator_client(f"root-{sponsor_uid}")
    if sponsor_access is None:
        pair = _login(client, sponsor_uid)
        sponsor_access = pair["access"]
    username = _username(client, sponsor_access)
    _grant_permission(root, username=username)

    deadline_at = deadline_at or (timezone.now() + timedelta(days=7))
    created = client.post(
        ASSIGNMENTS_URL,
        data={
            "title": f"{sponsor_uid}의 과제",
            "deliverable_type_ids": deliverable_type_ids,
            "description": "스윕 검증용",
            "deadline_at": deadline_at.isoformat(),
            "requirements": [{"text": "로그인 기능이 있다", "grade": "required"}],
        },
        content_type="application/json",
        **_auth_header(sponsor_access),
    )
    assert created.status_code == 201, created.content
    assignment_id = created.json()["id"]
    requirement_id = created.json()["requirements"][0]["id"]

    opened = client.post(
        f"{ASSIGNMENTS_URL}/{assignment_id}/open",
        content_type="application/json",
        **_auth_header(sponsor_access),
    )
    assert opened.status_code == 200, opened.content
    body = opened.json()
    return {
        "id": assignment_id,
        "invite_code": body["invite_code"],
        "requirement_id": requirement_id,
        "sponsor_access": sponsor_access,
    }


def _zip_bytes(files: dict[str, str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for path, content in files.items():
            zf.writestr(path, content)
    return buf.getvalue()


def _source_object_key(contest_id: int, developer_user_id: int) -> str:
    return f"submission:{contest_id}:{developer_user_id}:source/{uuid.uuid4().hex}"


def _submit(client, student_access: str, student_user_id: int, assignment: dict) -> dict:
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


def _ledger_entry_count(contest_id: int) -> int:
    contest = Contest.objects.get(id=contest_id)
    return JournalEntry.objects.filter(contest_id=contest.ledger_id).count()


# --- 전수 확인: 스캔 등록부 전체를 한 바퀴 돌려도 아무 일도 없다 ------------------------


@pytest.mark.django_db
def test_running_the_whole_scan_registry_with_an_open_assignment_moves_nothing_but_the_assignment_itself(
    client, landing_type
):
    """과제가 열린 상태(마감 전)로 등록부 전체(`run_all`)를 한 바퀴 돌려도
    환불·배분·지급·연장·재개최 어느 것도 일어나지 않는다. 스캔마다 따로 보지
    않고 `/api/internal/tick` 한 번으로 확인한다(#212 — 스캔이 늘어도 이 확인이
    계속 유효하다)."""

    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="sweep-sponsor-1"
    )
    student_pair = _login(client, "sweep-student-1")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    _submit(client, student_pair["access"], student_id, assignment)

    tick = client.post(TICK_URL, **_internal_headers())
    assert tick.status_code == 200, tick.content

    # 마감이 미래라 assignment-close조차 이 과제를 건드리지 않는다 — 상태가
    # 그대로다.
    contest = Contest.objects.get(id=assignment["id"])
    assert contest.status == Contest.Status.ASSIGNMENT_OPEN

    # 돈이 움직이는 모델 전부가 0건 — 이 테스트 함수의 트랜잭션 안에는 이
    # 과제·이 제출 말고 아무것도 없으므로 전역 카운트로 단언해도 정확하다.
    assert Payout.objects.count() == 0
    assert Distribution.objects.count() == 0
    assert _ledger_entry_count(assignment["id"]) == 0

    # 통지 — 「발송이 성공했다」가 아니라 「행이 생기지 않았다」로 단언한다
    # (Fake 알림 어댑터는 수신자를 보지 않고 성공을 반환해 성공 단언을 통과시킨다).
    assert Notification.objects.count() == 0
    assert NotificationDispatch.objects.count() == 0


@pytest.mark.django_db
def test_the_whole_lifecycle_up_to_scoring_leaves_the_ledger_silent(client, landing_type):
    """과제 하나가 열려서 채점까지 가는 동안 원장에 분개가 하나도 생기지 않는다
    (ADR-0004 — 0원 분개는 원장이 지키려던 것을 오염시킨다)."""

    deadline = timezone.now() + timedelta(hours=1)
    assignment = _create_and_open_assignment(
        client, deliverable_type_ids=[landing_type.id], sponsor_uid="sweep-sponsor-2",
        deadline_at=deadline,
    )
    student_pair = _login(client, "sweep-student-2")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    _submit(client, student_pair["access"], student_id, assignment)

    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )
    close = client.post(ASSIGNMENT_CLOSE_SCAN_URL, **_internal_headers())
    assert close.status_code == 200, close.content
    score = client.post(SCORING_SCAN_URL, **_internal_headers())
    assert score.status_code == 200, score.content
    assert score.json()["count"] == 1

    assert _ledger_entry_count(assignment["id"]) == 0
    assert Notification.objects.count() == 0
    assert NotificationDispatch.objects.count() == 0
    assert Payout.objects.count() == 0
    assert Distribution.objects.count() == 0


# --- 탈퇴: 과제만 연 강사 -------------------------------------------------------------


@pytest.mark.django_db
def test_sponsor_who_only_opened_an_assignment_can_withdraw_with_no_retained_identity(
    client, landing_type
):
    """과제는 「진행 중인 거래」가 아니므로 탈퇴를 막지 않고(BLOCKS_SPONSOR_
    WITHDRAWAL: False), 「보존 의무를 낳는 거래」도 아니므로(REQUIRES_IDENTITY_
    RETENTION: False) 탈퇴 후 실명이 보존되지 않는다 — 본인확인을 마친 강사라도.
    """

    pair = _login(client, "sweep-withdraw-sponsor-1")
    _verify(client, pair["access"], ci="sweep-withdraw-ci-1")
    assignment = _create_and_open_assignment(
        client,
        deliverable_type_ids=[landing_type.id],
        sponsor_uid="sweep-withdraw-sponsor-1",
        sponsor_access=pair["access"],
    )

    header = _auth_header(pair["access"])
    eligibility = client.get(WITHDRAWAL_URL, **header)
    assert eligibility.json() == {"can_withdraw": True, "blocking_reasons": []}

    response = client.post(WITHDRAWAL_URL, content_type="application/json", **header)
    assert response.status_code == 200, response.content

    from django.contrib.auth import get_user_model

    user = get_user_model().objects.get(
        social_accounts__provider_uid="sweep-withdraw-sponsor-1"
    )
    assert not RetainedIdentity.objects.filter(user=user).exists()

    verification = Verification.objects.get(user=user)
    assert verification.status == Verification.Status.WITHDRAWN
    assert verification.real_name_encrypted == ""
    assert verification.ci_encrypted == ""

    # Contest.sponsor는 CASCADE지만 부모 행(User·SponsorProfile)이 지워지지
    # 않으므로 자식(Contest)도 지워지지 않는다(ADR-0025 — 탈퇴는 값을 지우지
    # 행을 지우지 않는다).
    contest = Contest.objects.get(id=assignment["id"])
    assert contest.status == Contest.Status.ASSIGNMENT_OPEN

    sponsor_profile = SponsorProfile.objects.get(user=user)
    assert sponsor_profile.display_name == ""


@pytest.mark.django_db
def test_assignment_and_student_submission_survive_sponsor_withdrawal_and_student_still_sees_their_score(
    client, landing_type
):
    """탈퇴는 프로필 행을 지우지 않고 표시 이름만 비우므로 Contest의 CASCADE가
    발동하지 않는다 — 학생은 자기 결과를 잃지 않는다. 이름이 빈 강사의 과제를
    학생이 계속 조회할 수 있는지(InviteCode 조회·자기 점수 조회)까지 확인한다
    (스펙 #197 — 「이름이 빈 강사의 과제」 화면 처리)."""

    deadline = timezone.now() + timedelta(hours=1)
    pair = _login(client, "sweep-withdraw-sponsor-2")
    _verify(client, pair["access"], ci="sweep-withdraw-ci-2")
    assignment = _create_and_open_assignment(
        client,
        deliverable_type_ids=[landing_type.id],
        sponsor_uid="sweep-withdraw-sponsor-2",
        sponsor_access=pair["access"],
        deadline_at=deadline,
    )
    student_pair = _login(client, "sweep-withdraw-student-2")
    student_id = client.get(
        "/api/accounts/me", **_auth_header(student_pair["access"])
    ).json()["id"]
    submission = _submit(client, student_pair["access"], student_id, assignment)

    # 마감 후 채점까지 마친 뒤에 강사가 탈퇴한다 — 학생이 이미 점수를 받은
    # 뒤에도 그 결과가 사라지지 않아야 한다는 것이 더 강한 확인이다.
    ClockOverride.objects.update_or_create(
        pk=1, defaults={"overridden_at": deadline + timedelta(minutes=1)}
    )
    client.post(ASSIGNMENT_CLOSE_SCAN_URL, **_internal_headers())
    client.post(SCORING_SCAN_URL, **_internal_headers())

    withdrawal = client.post(
        WITHDRAWAL_URL, content_type="application/json", **_auth_header(pair["access"])
    )
    assert withdrawal.status_code == 200, withdrawal.content

    # 과제 자체 — InviteCode 조회는 인증이 필요 없다(ADR-0028), 이름이 빈
    # 강사라도 500이 아니라 정상 응답이어야 한다.
    invite_lookup = client.get(f"{ASSIGNMENTS_URL}/invite/{assignment['invite_code']}")
    assert invite_lookup.status_code == 200, invite_lookup.content

    # 제출물 — 학생이 자기 것을 계속 볼 수 있다.
    my_submission = client.get(
        f"{CONTESTS_URL}/{assignment['id']}/submissions/me",
        **_auth_header(student_pair["access"]),
    )
    assert my_submission.status_code == 200, my_submission.content

    # 점수 — 강사가 탈퇴해도 학생은 계속 자기 점수를 본다.
    own_score = client.get(
        f"/api/submissions/{submission['id']}/score", **_auth_header(student_pair["access"])
    )
    assert own_score.status_code == 200, own_score.content
    assert own_score.json()["percentage"] == "100.00"
