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
from django.db.models import Count, F
from django.db.models.functions import TruncDate
from django.utils import timezone
from ninja import Query, Router, Schema
from ninja.errors import HttpError

from core.clock import Clock
from core.operator_auth import OperatorAuth

from .models import ClassMember, ClassroomSubmission
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

    return ClassMember.objects.exclude(user_id=F("classroom__instructor_id"))


def counted_submissions():
    """세는 강의실 제출 — 그 클래스의 강사가 낸 것만 뺀다(내보낸 학생의 제출은 남긴다)."""

    return ClassroomSubmission.objects.exclude(member__user_id=F("problem__classroom__instructor_id"))


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
