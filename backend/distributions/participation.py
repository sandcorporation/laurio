"""공모전 판정이 묻는 배분 사실 — `distributions.apps` 가 `contests.ports` 에 올린다(#1102)."""

from __future__ import annotations

from django.db.models import Q


def no_distribution_q() -> Q:
    """`Contest` 에 아직 Distribution 이 없다."""

    return Q(distribution__isnull=True)
