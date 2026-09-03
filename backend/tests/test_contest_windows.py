"""Contest 가 자기 시간 창을 안다 (#143, #124) — 술어와 매니저 Q 가 경계에서 갈리지 않는다.

Award·연장 가드와 Sponsor/Developer 번역기가 같은 메서드를 부르므로, 이 파일이 지키는 것은 그
메서드의 경계와 「필터로 물어도 같은 답」이다. 행위별 동작은 각 HTTP 테스트(test_judging_period_and_
award·test_appeals·test_my_contests·test_handover)가 본다.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from contests.models import Contest
from policies.scope import current_policy
from tests.predicate_pairs import assert_predicate_matches_q
from tests.test_home_curation import (  # noqa: F401 - 픽스처
    _make_contest,
    category,
    deliverable_type,
    sponsor,
)

ONE_SECOND = timedelta(seconds=1)


def _window_cases(sponsor, category, deliverable_type, *, now):
    deadline = now - timedelta(days=7)
    return [
        (
            label,
            _make_contest(
                sponsor, category, deliverable_type,
                status=Contest.Status.CLOSED, deadline_at=deadline, judging_ends_at=judging_ends_at,
                title=f"심사 창 — {label}",
            ),
        )
        for label, judging_ends_at in [
            ("종료 1초 전", now + ONE_SECOND),
            ("종료 정확히 지금", now),
            ("종료 1초 후", now - ONE_SECOND),
            ("심사기간 없음", None),
        ]
    ]


@pytest.mark.django_db
def test_judging_window_predicate_matches_its_queryset_at_the_boundary(sponsor, category, deliverable_type):
    now = timezone.now()
    cases = _window_cases(sponsor, category, deliverable_type, now=now)
    assert_predicate_matches_q(
        cases, lambda c: c.judging_window_open(now), Contest.objects.judging_window_open(now)
    )
    by_label = {label: c.judging_window_open(now) for label, c in cases}
    # 스케줄러와 같은 경계 — judging_ends_at 과 같아지는 순간 이미 닫혀 있다. 심사기간이 없으면 닫혀 있다.
    assert by_label == {"종료 1초 전": True, "종료 정확히 지금": False, "종료 1초 후": False, "심사기간 없음": False}


@pytest.mark.django_db
def test_appeal_window_predicate_matches_its_queryset_at_the_boundary(sponsor, category, deliverable_type):
    now = timezone.now()
    cases = _window_cases(sponsor, category, deliverable_type, now=now)
    assert_predicate_matches_q(
        cases, lambda c: c.appeal_window_open(now), Contest.objects.appeal_window_open(now)
    )
    by_label = {label: c.appeal_window_open(now) for label, c in cases}
    # 끝은 심사 창과 같은 시각이지만, 심사기간이 없는 Contest 의 이의 창은 닫히지 않는다.
    assert by_label == {"종료 1초 전": True, "종료 정확히 지금": False, "종료 1초 후": False, "심사기간 없음": True}


@pytest.mark.django_db
def test_distribution_due_predicate_matches_its_queryset_at_the_boundary(sponsor, category, deliverable_type):
    policy = current_policy()
    as_of = timezone.now()
    due_at = as_of - timedelta(days=policy.distribution_wait_days)
    deadline = due_at - timedelta(days=policy.judging_period_days)
    cases = [
        (
            label,
            _make_contest(
                sponsor, category, deliverable_type,
                status=status, deadline_at=deadline, judging_ends_at=judging_ends_at,
                title=f"배분 차례 — {label}",
            ),
        )
        for label, status, judging_ends_at in [
            ("대기 1초 부족", Contest.Status.JUDGING_ENDED, due_at + ONE_SECOND),
            ("대기 정확히 채움", Contest.Status.JUDGING_ENDED, due_at),
            ("대기 1초 초과", Contest.Status.JUDGING_ENDED, due_at - ONE_SECOND),
            ("아직 심사 중(CLOSED)", Contest.Status.CLOSED, due_at - ONE_SECOND),
            ("심사기간 없음", Contest.Status.JUDGING_ENDED, None),
        ]
    ]
    assert_predicate_matches_q(
        cases, lambda c: c.distribution_due(as_of, policy), Contest.objects.distribution_due(as_of, policy)
    )
    by_label = {label: c.distribution_due(as_of, policy) for label, c in cases}
    assert by_label == {
        "대기 1초 부족": False,
        "대기 정확히 채움": True,
        "대기 1초 초과": True,
        "아직 심사 중(CLOSED)": False,
        "심사기간 없음": False,
    }
