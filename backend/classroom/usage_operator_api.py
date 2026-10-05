"""운영자가 보는 강의실 사용 현황 (#491 스펙, #492).

**숫자만 돌려준다.** 응답 스키마에 사용자 id·표시 이름·제출 id 가 없다 — 화면에서
감추는 것이 아니라 API 가 애초에 집계만 낸다(#491 「개인은 응답에도 없다」).

**세는 기준이 숫자의 전부다**(#491 표):

- 가입 — 그날 생긴 계정(`User.date_joined`). Operator(`is_staff`) 는 참가자와
  서로소라 세지 않는다.
- 클래스 가입 — 그날의 `ClassMember.joined_at`. **그 클래스의 강사 자신**의 가입은
  뺀다. 나중에 내보내진 가입도 센다(그날 실제로 있었던 일이다).
- 강의실 제출 — 그날 만들어진 `ClassroomSubmission`. **제출이 속한 클래스의 강사**가
  낸 것만 뺀다 — 다른 사람의 클래스에 학생으로 낸 제출은 센다. 내보낸 학생의 제출도
  센다.
- 제출자 수 — 위 제출을 낸 서로 다른 사람 수.

**날짜는 서울 시각의 달력 날이다.** UTC 로 자르면 오전 9시 이전의 활동이 전날로 간다.
「오늘」은 주입 가능한 시계(`core.clock.Clock`, ADR-0003)에서 온다.

**0 인 날을 채우는 것은 백엔드다** — 응답이 기간의 모든 날을 담는다. 기간 길이에
상한은 두지 않았다(#491 Further Notes, 사용자 결정).

**운영자 전원이 본다** — 바꾸는 화면이 아니라 상위 등급(`SuperuserOperatorAuth`)을
걸지 않는다. 클래스 목록(#493)·클래스 상세(#494)가 같은 라우터에 더해진다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.db.models import Count, Max, Min
from django.db.models.functions import TruncDate
from django.utils import timezone
from ninja import Query, Router, Schema
from ninja.errors import HttpError

from core.clock import Clock
from core.operator_auth import OperatorAuth

from .instructors import is_instructor_q
from .models import Class, ClassMember, ClassroomSubmission, Problem
from .schemas import ErrorOut

SEOUL = ZoneInfo("Asia/Seoul")

#: 기간을 주지 않았을 때의 길이 — 오늘을 포함한 최근 30일.
DEFAULT_PERIOD_DAYS = 30

usage_operator_router = Router(tags=["operator", "classroom", "usage"], auth=OperatorAuth())


class UsageDayOut(Schema):
    date: date
    signups: int
    class_joins: int
    submissions: int
    submitters: int


class UsageTotalsOut(Schema):
    signups: int
    class_joins: int
    submissions: int
    #: 기간 전체에서 제출한 서로 다른 사람 수 — 날마다의 제출자 수를 더한 값이 아니다.
    submitters: int


class UsageDailyOut(Schema):
    start_date: date
    end_date: date
    days: list[UsageDayOut]
    totals: UsageTotalsOut


def seoul_today() -> date:
    return timezone.localtime(Clock.now(), SEOUL).date()


def _parse_day(raw: str | None, label: str) -> date | None:
    if raw is None or raw == "":
        return None
    try:
        return date.fromisoformat(raw)
    except ValueError:
        raise HttpError(422, f"{label}은 YYYY-MM-DD 형식이어야 합니다.") from None


def resolve_period(raw_from: str | None, raw_to: str | None) -> tuple[date, date]:
    """`?from=&to=` 를 서울 날짜 구간으로 푼다 — 비면 오늘을 포함한 최근 30일.

    끝만 주면 그날까지의 30일, 시작만 주면 그날부터 오늘까지다. 클래스 상세(#494)의
    날짜 × 문제 표도 같은 규칙을 쓴다.
    """

    start = _parse_day(raw_from, "시작일")
    end = _parse_day(raw_to, "종료일")
    if end is None:
        end = seoul_today()
    if start is None:
        start = end - timedelta(days=DEFAULT_PERIOD_DAYS - 1)
    if start > end:
        raise HttpError(422, "시작일이 종료일보다 늦습니다.")
    return start, end


def seoul_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    """서울 달력 날 `start`~`end`(양끝 포함)를 덮는 반열린 시각 구간."""

    return (
        datetime.combine(start, time.min, tzinfo=SEOUL),
        datetime.combine(end + timedelta(days=1), time.min, tzinfo=SEOUL),
    )


def counted_class_joins():
    """세는 클래스 가입 — 강사가 자기 클래스에 든 가입만 뺀다(내보내진 가입은 남긴다)."""

    return ClassMember.objects.exclude(is_instructor_q(user="user_id", classroom="classroom"))


def counted_submissions():
    """세는 강의실 제출 — 그 클래스의 강사가 낸 것만 뺀다(내보낸 학생의 제출은 남긴다)."""

    return ClassroomSubmission.objects.exclude(
        is_instructor_q(user="member__user_id", classroom="problem__classroom")
    )


def _per_day(queryset, field: str, **aggregates) -> dict[date, dict]:
    rows = (
        queryset.annotate(day=TruncDate(field, tzinfo=SEOUL))
        .values("day")
        .annotate(**aggregates)
        .order_by()
    )
    return {row["day"]: row for row in rows}


@usage_operator_router.get(
    "/classroom/usage/daily",
    response={200: UsageDailyOut, 422: ErrorOut},
)
def usage_daily(
    request,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    """날짜별 가입·클래스 가입·강의실 제출·제출자 수(#492). 기간의 모든 날이 한 줄씩 온다."""

    start, end = resolve_period(date_from, date_to)
    lower, upper = seoul_bounds(start, end)

    signups = _per_day(
        get_user_model().objects.filter(
            is_staff=False, date_joined__gte=lower, date_joined__lt=upper
        ),
        "date_joined",
        n=Count("id"),
    )
    joins = _per_day(
        counted_class_joins().filter(joined_at__gte=lower, joined_at__lt=upper),
        "joined_at",
        n=Count("id"),
    )
    period_submissions = counted_submissions().filter(created_at__gte=lower, created_at__lt=upper)
    submissions = _per_day(
        period_submissions,
        "created_at",
        n=Count("id"),
        people=Count("member__user_id", distinct=True),
    )

    days: list[UsageDayOut] = []
    day = start
    while day <= end:
        sub = submissions.get(day)
        days.append(
            UsageDayOut(
                date=day,
                signups=signups[day]["n"] if day in signups else 0,
                class_joins=joins[day]["n"] if day in joins else 0,
                submissions=sub["n"] if sub else 0,
                submitters=sub["people"] if sub else 0,
            )
        )
        day += timedelta(days=1)

    totals = UsageTotalsOut(
        signups=sum(d.signups for d in days),
        class_joins=sum(d.class_joins for d in days),
        submissions=sum(d.submissions for d in days),
        submitters=period_submissions.values("member__user_id").distinct().count(),
    )
    return UsageDailyOut(start_date=start, end_date=end, days=days, totals=totals)


# --- 클래스 목록 (#493) ------------------------------------------------------


class ClassUsageOut(Schema):
    """클래스 하나의 **전체 기간** 합계. 강사·학생을 가리키는 값은 없다 — 클래스
    id 는 상세(#494)로 가는 주소에 쓰인다."""

    id: int
    name: str
    created_at: datetime
    archived: bool
    #: 지금 남아 있는 학생 — 강사 제외, 내보내지 않은 멤버.
    participants: int
    problems_open: int
    problems_draft: int
    problems_hidden: int
    #: 강사 자신의 것을 뺀 제출. 내보낸 학생의 제출도 센다.
    submissions: int
    #: 위 제출을 낸 서로 다른 사람 — 내보낸 학생도 센다.
    submitting_students: int
    #: 지금 남아 있는 학생 중 한 번이라도 낸 사람 — 참여율의 분자.
    participants_submitted: int
    #: participants_submitted / participants. 참여자가 0 이면 값이 없다(0 이 아니다).
    participation_rate: float | None


def _count_by(queryset, key: str, **aggregates) -> dict:
    rows = queryset.values(key).annotate(**aggregates).order_by()
    return {row[key]: row for row in rows}


@usage_operator_router.get("/classroom/usage/classes", response=list[ClassUsageOut])
def usage_classes(request):
    """클래스마다 참여자·문제(열림/초안/숨김)·제출·제출한 학생·참여율(#493).

    기간을 받지 않는다 — 클래스 전체 기간의 합계다. 보관된 클래스도 돌려주되
    진행 중인 클래스 뒤에 둔다(각 묶음 안에서는 최근에 만든 것이 먼저).
    """
    participants = _count_by(
        counted_class_joins().filter(expelled_at__isnull=True), "classroom_id", n=Count("id")
    )
    problems: dict[int, dict[str, int]] = {}
    for row in Problem.objects.values("classroom_id", "status").annotate(n=Count("id")).order_by():
        problems.setdefault(row["classroom_id"], {})[row["status"]] = row["n"]
    submissions = _count_by(
        counted_submissions(),
        "member__classroom_id",
        n=Count("id"),
        people=Count("member__user_id", distinct=True),
    )
    submitted_now = _count_by(
        counted_submissions().filter(member__expelled_at__isnull=True),
        "member__classroom_id",
        people=Count("member__user_id", distinct=True),
    )

    classes = sorted(
        Class.objects.only("id", "name", "created_at", "archived_at"),
        key=lambda c: (c.archived_at is not None, -c.created_at.timestamp()),
    )
    result: list[ClassUsageOut] = []
    for c in classes:
        n_participants = participants[c.id]["n"] if c.id in participants else 0
        n_submitted_now = submitted_now[c.id]["people"] if c.id in submitted_now else 0
        by_status = problems.get(c.id, {})
        sub = submissions.get(c.id)
        result.append(
            ClassUsageOut(
                id=c.id,
                name=c.name,
                created_at=c.created_at,
                archived=c.archived_at is not None,
                participants=n_participants,
                problems_open=by_status.get(Problem.Status.OPEN, 0),
                problems_draft=by_status.get(Problem.Status.DRAFT, 0),
                problems_hidden=by_status.get(Problem.Status.HIDDEN, 0),
                submissions=sub["n"] if sub else 0,
                submitting_students=sub["people"] if sub else 0,
                participants_submitted=n_submitted_now,
                participation_rate=(n_submitted_now / n_participants) if n_participants else None,
            )
        )
    return result

# --- 클래스 상세(#494) --------------------------------------------------------
#
# 문제별 표는 **클래스 전체 기간**을 센다 — 「아무도 안 낸 문제」를 찾는 표라 기간을
# 받지 않는다. 날짜 × 문제 표만 `?from=&to=`(위 `resolve_period` 와 같은 규칙)를
# 받는다. 세는 기준은 위 머리말 그대로다(강사가 자기 클래스에 낸 제출은 빼고,
# 내보낸 학생의 제출은 센다). 보관된 클래스·숨긴 문제도 그대로 센다 — 그때 있었던
# 활동이다(#491).


class UsageProblemOut(Schema):
    problem_id: int
    title: str
    #: 문제 상태 — `draft`(초안)·`open`(열림)·`hidden`(숨김).
    status: str
    submissions: int
    submitters: int
    #: 첫·마지막 제출의 서울 날짜. 제출이 없으면 null.
    first_submitted_on: date | None
    last_submitted_on: date | None
    #: 채점 실패 시도(`ClassroomScoringAttempt`)가 하나 이상 남은 제출 수 —
    #: 그 테이블은 실패한 시도만 적는다.
    failed_scoring_submissions: int


class UsageProblemCellOut(Schema):
    problem_id: int
    submissions: int
    submitters: int


class UsageClassDayOut(Schema):
    date: date
    #: 그날 이 클래스 전체의 제출 수·제출자 수(문제를 가리지 않고 센 서로 다른 사람).
    submissions: int
    submitters: int
    #: `problems` 와 같은 순서로, 문제마다 한 칸 — 0 인 칸도 있다.
    problems: list[UsageProblemCellOut]


class UsageClassPeriodTotalOut(Schema):
    """날짜 × 문제 표의 합계 줄 — 제출자 수는 날마다의 값을 더한 것이 아니라 기간 전체에서
    겹치지 않게 센 사람 수다(`UsageTotalsOut.submitters` 와 같은 뜻)."""

    submissions: int
    submitters: int
    #: `problems` 와 같은 순서로, 문제마다 한 칸.
    problems: list[UsageProblemCellOut]


class UsageClassDetailOut(Schema):
    name: str
    archived: bool
    start_date: date
    end_date: date
    problems: list[UsageProblemOut]
    days: list[UsageClassDayOut]
    period_total: UsageClassPeriodTotalOut


def _seoul_date(value: datetime | None) -> date | None:
    return timezone.localtime(value, SEOUL).date() if value is not None else None


@usage_operator_router.get(
    "/classroom/usage/classes/{class_id}",
    response={200: UsageClassDetailOut, 404: ErrorOut, 422: ErrorOut},
)
def usage_class_detail(
    request,
    class_id: int,
    date_from: str | None = Query(None, alias="from"),
    date_to: str | None = Query(None, alias="to"),
):
    """클래스 하나의 문제별 표와 날짜 × 문제 표(#494). 집계 숫자만 돌려준다."""

    classroom = Class.objects.filter(pk=class_id).first()
    if classroom is None:
        raise HttpError(404, "클래스를 찾을 수 없습니다.")
    start, end = resolve_period(date_from, date_to)
    lower, upper = seoul_bounds(start, end)

    problems = list(Problem.objects.filter(classroom=classroom).order_by("order", "id"))
    class_submissions = counted_submissions().filter(problem__classroom=classroom)

    totals = {
        row["problem_id"]: row
        for row in class_submissions.values("problem_id")
        .annotate(
            n=Count("id"),
            people=Count("member__user_id", distinct=True),
            first=Min("created_at"),
            last=Max("created_at"),
        )
        .order_by()
    }
    failed = {
        row["problem_id"]: row["n"]
        for row in class_submissions.filter(classroom_scoring_attempts__isnull=False)
        .values("problem_id")
        .annotate(n=Count("id", distinct=True))
        .order_by()
    }

    period_submissions = class_submissions.filter(created_at__gte=lower, created_at__lt=upper)
    cells = {
        (row["day"], row["problem_id"]): row
        for row in period_submissions.annotate(day=TruncDate("created_at", tzinfo=SEOUL))
        .values("day", "problem_id")
        .annotate(n=Count("id"), people=Count("member__user_id", distinct=True))
        .order_by()
    }
    per_day = _per_day(
        period_submissions, "created_at", n=Count("id"), people=Count("member__user_id", distinct=True)
    )
    period_by_problem = {
        row["problem_id"]: row
        for row in period_submissions.values("problem_id")
        .annotate(n=Count("id"), people=Count("member__user_id", distinct=True))
        .order_by()
    }
    period_whole = period_submissions.aggregate(n=Count("id"), people=Count("member__user_id", distinct=True))

    problem_rows = []
    for problem in problems:
        total = totals.get(problem.id)
        problem_rows.append(
            UsageProblemOut(
                problem_id=problem.id,
                title=problem.title,
                status=problem.status,
                submissions=total["n"] if total else 0,
                submitters=total["people"] if total else 0,
                first_submitted_on=_seoul_date(total["first"]) if total else None,
                last_submitted_on=_seoul_date(total["last"]) if total else None,
                failed_scoring_submissions=failed.get(problem.id, 0),
            )
        )

    days: list[UsageClassDayOut] = []
    day = start
    while day <= end:
        whole = per_day.get(day)
        day_cells = []
        for problem in problems:
            cell = cells.get((day, problem.id))
            day_cells.append(
                UsageProblemCellOut(
                    problem_id=problem.id,
                    submissions=cell["n"] if cell else 0,
                    submitters=cell["people"] if cell else 0,
                )
            )
        days.append(
            UsageClassDayOut(
                date=day,
                submissions=whole["n"] if whole else 0,
                submitters=whole["people"] if whole else 0,
                problems=day_cells,
            )
        )
        day += timedelta(days=1)

    return UsageClassDetailOut(
        name=classroom.name,
        archived=classroom.archived_at is not None,
        start_date=start,
        end_date=end,
        problems=problem_rows,
        days=days,
        period_total=UsageClassPeriodTotalOut(
            submissions=period_whole["n"],
            submitters=period_whole["people"],
            problems=[
                UsageProblemCellOut(
                    problem_id=problem.id,
                    submissions=period_by_problem[problem.id]["n"] if problem.id in period_by_problem else 0,
                    submitters=period_by_problem[problem.id]["people"] if problem.id in period_by_problem else 0,
                )
                for problem in problems
            ],
        ),
    )
