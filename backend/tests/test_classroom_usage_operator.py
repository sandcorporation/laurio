"""운영자가 날짜별 강의실 사용량을 본다 (#492, 부모 #491).

세는 기준(#491 표)이 숫자의 전부다 — 강사는 **자기 클래스에서만** 뺀다, 내보낸
학생의 지난 활동은 남긴다, Operator 계정은 가입에서 뺀다, 날짜는 서울 달력 날이다.
응답에는 집계 숫자만 있다.

준비는 HTTP 로 한다. 시각만은 예외다 — `created_at`·`joined_at`·`date_joined` 가
`auto_now_add` 라 정상 경로로는 과거 시각을 만들 수 없어, 그 줄만 QuerySet
`update()` 로 옮긴다(`tests/classroom_scenarios.py` 머리말의 규율). 「오늘」은
`ClockOverride` 로 고정한다(ADR-0003).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client

from classroom.models import ClassMember, ClassroomSubmission
from core.models import ClockOverride
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    join_class,
    login,
    submit_repository,
)

DAILY_URL = "/api/operator/classroom/usage/daily"
OPERATOR_ORIGIN = "http://testserver"
SEOUL = ZoneInfo("Asia/Seoul")

#: 모든 행을 이 하루(서울 정오)로 옮겨 날짜별 숫자를 고정된 날에서 읽는다.
DAY = date(2026, 9, 26)
NOON_UTC = datetime(2026, 9, 26, 3, 0, tzinfo=dt_timezone.utc)


def _operator_client(username="operator-1", *, superuser=False) -> Client:
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


def _freeze(at: datetime) -> None:
    ClockOverride.objects.update_or_create(pk=1, defaults={"overridden_at": at})


def _move_everything_to(at: datetime) -> None:
    """지금까지 HTTP 로 만든 계정·가입·제출의 시각을 한 시각으로 옮긴다."""

    get_user_model().objects.update(date_joined=at)
    ClassMember.objects.update(joined_at=at)
    ClassroomSubmission.objects.update(created_at=at)


def _daily(operator: Client, **params) -> dict:
    response = operator.get(DAILY_URL, params)
    assert response.status_code == 200, response.content
    return response.json()


def _day(body: dict, day: date) -> dict:
    return next(row for row in body["days"] if row["date"] == day.isoformat())


def _expel(client, instructor_access: str, class_id: int, uid: str) -> None:
    member_id = ClassMember.objects.get(classroom_id=class_id, user__username=f"kakao:{uid}").id
    response = client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **auth_header(instructor_access),
    )
    assert response.status_code == 200, response.content


def test_instructor_is_left_out_only_in_their_own_class(client, db):
    """강사가 자기 클래스에 든 가입·낸 제출은 빠지고, 남의 클래스에 학생으로 낸 제출은 센다."""

    alice = login(client, "alice")  # 클래스 A 의 강사
    bob = login(client, "bob")  # 클래스 B 의 강사
    student = login(client, "student")

    class_a = create_class(client, alice["access"], name="A")
    class_b = create_class(client, bob["access"], name="B")
    problem_a = create_open_problem(client, alice["access"], class_a)
    problem_b = create_open_problem(client, bob["access"], class_b)

    # alice 는 자기 클래스 A 에 들어가 시험 삼아 한 번 낸다 — 빠져야 한다.
    join_class(client, alice["access"], class_a, instructor_access=alice["access"])
    submit_repository(client, alice["access"], class_a, problem_a.id)
    # alice 는 bob 의 클래스 B 에 학생으로 들어가 낸다 — 세어져야 한다.
    join_class(client, alice["access"], class_b, instructor_access=bob["access"])
    submit_repository(client, alice["access"], class_b, problem_b.id)
    # 평범한 학생 하나가 A 에 두 번 낸다.
    join_class(client, student["access"], class_a, instructor_access=alice["access"])
    submit_repository(client, student["access"], class_a, problem_a.id)
    submit_repository(client, student["access"], class_a, problem_a.id)

    _move_everything_to(NOON_UTC)
    operator = _operator_client()

    row = _day(_daily(operator, **{"from": DAY.isoformat(), "to": DAY.isoformat()}), DAY)

    assert row == {
        "date": "2026-09-26",
        "signups": 3,  # 강사 여부와 무관하게 계정 셋, Operator 는 빠진다
        "class_joins": 2,  # alice→B, student→A (alice→A 는 자기 클래스)
        "submissions": 3,  # alice→B 1 + student→A 2 (alice→A 는 자기 클래스)
        "submitters": 2,
    }


def test_expelled_students_past_activity_stays_in_the_daily_numbers(client, db):
    instructor = login(client, "instructor")
    student = login(client, "student")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, student["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, student["access"], class_id, problem.id)

    _move_everything_to(NOON_UTC)
    _expel(client, instructor["access"], class_id, "student")
    operator = _operator_client()

    row = _day(_daily(operator, **{"from": DAY.isoformat(), "to": DAY.isoformat()}), DAY)
    assert row["class_joins"] == 1
    assert row["submissions"] == 1
    assert row["submitters"] == 1


def test_a_submission_at_half_past_midnight_seoul_counts_on_the_seoul_date(client, db):
    """서울 9/26 00:30 = UTC 9/25 15:30 — UTC 로 자르면 전날로 간다."""

    instructor = login(client, "instructor")
    student = login(client, "student")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, student["access"], class_id, instructor_access=instructor["access"])
    submit_repository(client, student["access"], class_id, problem.id)

    half_past_midnight = datetime(2026, 9, 26, 0, 30, tzinfo=SEOUL)
    _move_everything_to(half_past_midnight)
    _freeze(half_past_midnight)
    operator = _operator_client()

    # 기간을 주지 않는다 — 고정한 시계의 서울 날짜가 「오늘」이다.
    body = _daily(operator)

    assert body["end_date"] == "2026-09-26"
    assert _day(body, date(2026, 9, 26))["submissions"] == 1
    assert _day(body, date(2026, 9, 25))["submissions"] == 0


def test_default_period_is_the_last_30_days_including_today_and_quiet_days_are_zero(client, db):
    _freeze(datetime(2026, 9, 26, 12, 0, tzinfo=SEOUL))
    operator = _operator_client()

    body = _daily(operator)

    assert body["start_date"] == "2026-08-28"
    assert body["end_date"] == "2026-09-26"
    assert [row["date"] for row in body["days"]] == [
        (date(2026, 8, 28) + timedelta(days=i)).isoformat() for i in range(30)
    ]
    assert all(
        row == {"date": row["date"], "signups": 0, "class_joins": 0, "submissions": 0, "submitters": 0}
        for row in body["days"]
    )
    assert body["totals"] == {"signups": 0, "class_joins": 0, "submissions": 0, "submitters": 0}


def test_totals_count_distinct_submitters_across_the_period(client, db):
    instructor = login(client, "instructor")
    student = login(client, "student")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, student["access"], class_id, instructor_access=instructor["access"])
    first = submit_repository(client, student["access"], class_id, problem.id)
    submit_repository(client, student["access"], class_id, problem.id)

    _move_everything_to(NOON_UTC)
    ClassroomSubmission.objects.filter(pk=first["id"]).update(created_at=NOON_UTC - timedelta(days=1))
    operator = _operator_client()

    body = _daily(operator, **{"from": "2026-09-25", "to": "2026-09-26"})

    assert [row["submitters"] for row in body["days"]] == [1, 1]
    assert body["totals"]["submissions"] == 2
    assert body["totals"]["submitters"] == 1  # 날마다의 1 + 1 이 아니다


def test_start_after_end_is_422_with_a_korean_detail(db):
    operator = _operator_client()

    response = operator.get(DAILY_URL, {"from": "2026-09-27", "to": "2026-09-26"})

    assert response.status_code == 422
    assert response.json()["detail"] == "시작일이 종료일보다 늦습니다."


def test_malformed_date_is_422_with_a_korean_detail(db):
    operator = _operator_client()

    response = operator.get(DAILY_URL, {"from": "9/26"})

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], str)
    assert "YYYY-MM-DD" in response.json()["detail"]


def test_participants_and_anonymous_callers_are_refused(client, db):
    participant = login(client, "student")

    as_participant = client.get(DAILY_URL, **auth_header(participant["access"]))
    anonymous = Client().get(DAILY_URL)

    assert as_participant.status_code in (401, 403)
    assert anonymous.status_code in (401, 403)


def test_a_regular_operator_sees_it_too(db):
    operator = _operator_client("plain-operator", superuser=False)

    response = operator.get(DAILY_URL)

    assert response.status_code == 200


def test_the_response_carries_no_user_id_or_name(client, db):
    instructor = login(client, "instructor")
    student = login(client, "student", email="student-mail@example.com")
    class_id = create_class(client, instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(
        client, student["access"], class_id, instructor_access=instructor["access"], display_name="홍길동"
    )
    submit_repository(client, student["access"], class_id, problem.id)
    operator = _operator_client()

    response = operator.get(DAILY_URL)
    body = response.json()

    assert set(body) == {"start_date", "end_date", "days", "totals"}
    assert {key for row in body["days"] for key in row} == {
        "date",
        "signups",
        "class_joins",
        "submissions",
        "submitters",
    }
    assert set(body["totals"]) == {"signups", "class_joins", "submissions", "submitters"}
    text = response.content.decode()
    for leaked in ("홍길동", "student-mail", "kakao:", "강사"):
        assert leaked not in text
