"""운영자가 클래스 하나의 사용량을 문제별·날짜 × 문제로 본다 (#494, 부모 #491).

문제별 표는 클래스 전체 기간을, 날짜 × 문제 표는 `?from=&to=` 기간을 센다. 세는
기준은 #492 와 같다 — 강사가 자기 클래스에 낸 제출은 빼고, 내보낸 학생의 제출은
센다. 응답에는 집계 숫자와 클래스·문제의 이름만 있다.

준비는 HTTP 로 한다. 예외 둘 — 시각(`created_at` 이 `auto_now_add`)은 QuerySet
`update()` 로 옮기고, 채점 실패 이력(`ClassroomScoringAttempt`)은 벤더만 남기는 값이라
직접 만든다(`tests/test_classroom_scoring.py` 와 같은 관례).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from zoneinfo import ZoneInfo

from django.test import Client

from classroom.models import ClassMember, ClassroomScoringAttempt, ClassroomSubmission
from tests.classroom_scenarios import (
    CLASSES_URL,
    auth_header,
    create_class,
    create_open_problem,
    join_class,
    login,
    submit_repository,
)
from tests.test_classroom_usage_operator import _freeze, _operator_client

SEOUL = ZoneInfo("Asia/Seoul")
DAY = date(2026, 9, 26)
NOON_UTC = datetime(2026, 9, 26, 3, 0, tzinfo=dt_timezone.utc)


def _url(class_id: int) -> str:
    return f"/api/operator/classroom/usage/classes/{class_id}"


def _detail(operator: Client, class_id: int, **params) -> dict:
    response = operator.get(_url(class_id), params)
    assert response.status_code == 200, response.content
    return response.json()


def _problem(body: dict, problem_id: int) -> dict:
    return next(row for row in body["problems"] if row["problem_id"] == problem_id)


def _day(body: dict, day: date) -> dict:
    return next(row for row in body["days"] if row["date"] == day.isoformat())


def _hide(client, access: str, class_id: int, problem_id: int) -> None:
    response = client.post(
        f"{CLASSES_URL}/{class_id}/problems/{problem_id}/hide",
        content_type="application/json",
        **auth_header(access),
    )
    assert response.status_code == 200, response.content


def _expel(client, instructor_access: str, class_id: int, uid: str) -> None:
    member_id = ClassMember.objects.get(classroom_id=class_id, user__username=f"kakao:{uid}").id
    response = client.post(
        f"{CLASSES_URL}/{class_id}/members/{member_id}/expel",
        content_type="application/json",
        **auth_header(instructor_access),
    )
    assert response.status_code == 200, response.content


def _class_with_student(client):
    instructor = login(client, "instructor")
    student = login(client, "student")
    class_id = create_class(client, instructor["access"])
    join_class(client, student["access"], class_id, instructor_access=instructor["access"])
    return instructor, student, class_id


def test_problems_without_submissions_are_listed_with_zeros_and_their_status(client, db):
    instructor, student, class_id = _class_with_student(client)
    busy = create_open_problem(client, instructor["access"], class_id, title="1주차")
    quiet = create_open_problem(client, instructor["access"], class_id, title="2주차")
    draft = create_open_problem(client, instructor["access"], class_id, title="3주차", open=False)
    hidden = create_open_problem(client, instructor["access"], class_id, title="4주차")
    _hide(client, instructor["access"], class_id, hidden.id)
    submit_repository(client, student["access"], class_id, busy.id)
    operator = _operator_client()

    body = _detail(operator, class_id)

    assert [row["problem_id"] for row in body["problems"]] == [busy.id, quiet.id, draft.id, hidden.id]
    assert _problem(body, busy.id)["submissions"] == 1
    assert _problem(body, quiet.id) == {
        "problem_id": quiet.id,
        "title": "2주차",
        "status": "open",
        "submissions": 0,
        "submitters": 0,
        "first_submitted_on": None,
        "last_submitted_on": None,
        "failed_scoring_submissions": 0,
    }
    assert _problem(body, draft.id)["status"] == "draft"
    assert _problem(body, hidden.id)["status"] == "hidden"


def test_only_submissions_with_a_failed_scoring_attempt_count_as_failed(client, db):
    instructor, student, class_id = _class_with_student(client)
    problem = create_open_problem(client, instructor["access"], class_id)
    failed_twice = submit_repository(client, student["access"], class_id, problem.id)
    failed_once = submit_repository(client, student["access"], class_id, problem.id)
    submit_repository(client, student["access"], class_id, problem.id)  # 실패 이력 없음
    for submission_id, times in ((failed_twice["id"], 2), (failed_once["id"], 1)):
        submission = ClassroomSubmission.objects.get(pk=submission_id)
        for _ in range(times):
            ClassroomScoringAttempt.objects.create(submission=submission, error="저장소가 공개가 아니다")
    operator = _operator_client()

    row = _problem(_detail(operator, class_id), problem.id)

    assert row["submissions"] == 3
    assert row["failed_scoring_submissions"] == 2  # 시도 수(3)가 아니라 제출 수


def test_instructors_own_submissions_are_left_out_and_expelled_students_stay(client, db):
    instructor, student, class_id = _class_with_student(client)
    leaver = login(client, "leaver")
    join_class(client, leaver["access"], class_id, instructor_access=instructor["access"])
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(client, instructor["access"], class_id, instructor_access=instructor["access"])
    own = submit_repository(client, instructor["access"], class_id, problem.id)
    ClassroomScoringAttempt.objects.create(
        submission=ClassroomSubmission.objects.get(pk=own["id"]), error="강사의 시험 제출"
    )
    submit_repository(client, student["access"], class_id, problem.id)
    submit_repository(client, leaver["access"], class_id, problem.id)
    ClassroomSubmission.objects.update(created_at=NOON_UTC)
    _expel(client, instructor["access"], class_id, "leaver")
    operator = _operator_client()

    body = _detail(operator, class_id, **{"from": DAY.isoformat(), "to": DAY.isoformat()})

    assert _problem(body, problem.id)["submissions"] == 2
    assert _problem(body, problem.id)["submitters"] == 2
    assert _problem(body, problem.id)["failed_scoring_submissions"] == 0
    assert _day(body, DAY)["submissions"] == 2
    assert _day(body, DAY)["problems"] == [{"problem_id": problem.id, "submissions": 2, "submitters": 2}]


def test_the_date_by_problem_table_covers_every_day_and_cuts_on_seoul_dates(client, db):
    instructor, student, class_id = _class_with_student(client)
    first = create_open_problem(client, instructor["access"], class_id, title="1주차")
    second = create_open_problem(client, instructor["access"], class_id, title="2주차")
    early = submit_repository(client, student["access"], class_id, first.id)
    submit_repository(client, student["access"], class_id, second.id)
    # 서울 9/26 00:30 = UTC 9/25 15:30 — UTC 로 자르면 전날로 간다.
    ClassroomSubmission.objects.filter(pk=early["id"]).update(
        created_at=datetime(2026, 9, 26, 0, 30, tzinfo=SEOUL)
    )
    ClassroomSubmission.objects.exclude(pk=early["id"]).update(created_at=NOON_UTC - timedelta(days=2))
    operator = _operator_client()

    body = _detail(operator, class_id, **{"from": "2026-09-23", "to": "2026-09-26"})

    assert [row["date"] for row in body["days"]] == ["2026-09-23", "2026-09-24", "2026-09-25", "2026-09-26"]
    assert [[cell["submissions"] for cell in row["problems"]] for row in body["days"]] == [
        [0, 0],
        [0, 1],
        [0, 0],
        [1, 0],
    ]
    assert _day(body, date(2026, 9, 23)) == {
        "date": "2026-09-23",
        "submissions": 0,
        "submitters": 0,
        "problems": [
            {"problem_id": first.id, "submissions": 0, "submitters": 0},
            {"problem_id": second.id, "submissions": 0, "submitters": 0},
        ],
    }
    assert _problem(body, first.id)["first_submitted_on"] == "2026-09-26"
    assert _problem(body, second.id)["last_submitted_on"] == "2026-09-24"


def test_the_period_total_counts_distinct_submitters_across_days(client, db):
    instructor, student, class_id = _class_with_student(client)
    other = login(client, "other")
    join_class(client, other["access"], class_id, instructor_access=instructor["access"])
    first = create_open_problem(client, instructor["access"], class_id, title="1주차")
    second = create_open_problem(client, instructor["access"], class_id, title="2주차")
    yesterday = submit_repository(client, student["access"], class_id, first.id)
    submit_repository(client, student["access"], class_id, first.id)
    submit_repository(client, other["access"], class_id, first.id)
    outside = submit_repository(client, other["access"], class_id, second.id)
    ClassroomSubmission.objects.update(created_at=NOON_UTC)
    ClassroomSubmission.objects.filter(pk=yesterday["id"]).update(created_at=NOON_UTC - timedelta(days=1))
    ClassroomSubmission.objects.filter(pk=outside["id"]).update(created_at=NOON_UTC - timedelta(days=10))
    operator = _operator_client()

    body = _detail(operator, class_id, **{"from": "2026-09-25", "to": "2026-09-26"})

    assert body["period_total"] == {
        "submissions": 3,
        "submitters": 2,  # 날마다의 1 + 2 가 아니다, 기간 밖 제출은 빠진다
        "problems": [
            {"problem_id": first.id, "submissions": 3, "submitters": 2},
            {"problem_id": second.id, "submissions": 0, "submitters": 0},
        ],
    }


def test_problem_totals_ignore_the_period(client, db):
    instructor, student, class_id = _class_with_student(client)
    problem = create_open_problem(client, instructor["access"], class_id)
    old = submit_repository(client, student["access"], class_id, problem.id)
    submit_repository(client, student["access"], class_id, problem.id)
    ClassroomSubmission.objects.update(created_at=NOON_UTC)
    ClassroomSubmission.objects.filter(pk=old["id"]).update(created_at=NOON_UTC - timedelta(days=60))
    operator = _operator_client()

    body = _detail(operator, class_id, **{"from": DAY.isoformat(), "to": DAY.isoformat()})

    assert _problem(body, problem.id)["submissions"] == 2
    assert _problem(body, problem.id)["first_submitted_on"] == "2026-07-28"
    assert _day(body, DAY)["submissions"] == 1


def test_default_period_is_the_last_30_days(client, db):
    instructor, _student, class_id = _class_with_student(client)
    _freeze(datetime(2026, 9, 26, 12, 0, tzinfo=SEOUL))
    operator = _operator_client()

    body = _detail(operator, class_id)

    assert body["start_date"] == "2026-08-28"
    assert body["end_date"] == "2026-09-26"
    assert len(body["days"]) == 30


def test_unknown_class_is_404_and_start_after_end_is_422(client, db):
    instructor, _student, class_id = _class_with_student(client)
    operator = _operator_client()

    missing = operator.get(_url(class_id + 1000))
    reversed_period = operator.get(_url(class_id), {"from": "2026-09-27", "to": "2026-09-26"})

    assert missing.status_code == 404
    assert isinstance(missing.json()["detail"], str)
    assert reversed_period.status_code == 422
    assert reversed_period.json()["detail"] == "시작일이 종료일보다 늦습니다."


def test_participants_are_refused(client, db):
    instructor, student, class_id = _class_with_student(client)

    assert client.get(_url(class_id), **auth_header(student["access"])).status_code in (401, 403)
    assert Client().get(_url(class_id)).status_code in (401, 403)


def test_the_response_carries_no_user_or_submission_ids_or_names(client, db):
    instructor = login(client, "instructor")
    student = login(client, "student", email="student-mail@example.com")
    class_id = create_class(client, instructor["access"], name="웹 스터디")
    problem = create_open_problem(client, instructor["access"], class_id)
    join_class(
        client, student["access"], class_id, instructor_access=instructor["access"], display_name="홍길동"
    )
    submitted = submit_repository(client, student["access"], class_id, problem.id)
    operator = _operator_client()

    response = operator.get(_url(class_id))
    body = response.json()

    assert set(body) == {"name", "archived", "start_date", "end_date", "problems", "days", "period_total"}
    assert set(body["period_total"]) == {"submissions", "submitters", "problems"}
    assert body["name"] == "웹 스터디"
    assert body["archived"] is False
    assert set(body["problems"][0]) == {
        "problem_id",
        "title",
        "status",
        "submissions",
        "submitters",
        "first_submitted_on",
        "last_submitted_on",
        "failed_scoring_submissions",
    }
    assert {key for row in body["days"] for key in row} == {"date", "submissions", "submitters", "problems"}
    assert {key for row in body["days"] for cell in row["problems"] for key in cell} == {
        "problem_id",
        "submissions",
        "submitters",
    }
    text = response.content.decode()
    for leaked in ("홍길동", "student-mail", "kakao:", "강사", "octocat"):
        assert leaked not in text
    assert f'"id": {submitted["id"]}' not in text
