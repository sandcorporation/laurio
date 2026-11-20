"""휴면 판정이 셀 공모전 행위 — `contests.apps` 가 `verification.ports.LAST_ACTIVITY` 에 올린다(#1102)."""

from __future__ import annotations

from django.db.models import Expression, Max


def last_activity_expressions() -> tuple[Expression, ...]:
    """Sponsor 로서 만든 가장 최근 Contest, Developer 로서 낸 가장 최근 제출."""

    return (
        Max("user__sponsor_profile__contests__created_at"),
        Max("user__developer_profile__submissions__created_at"),
    )
