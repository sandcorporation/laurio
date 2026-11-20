"""status enum 의 분류는 빠짐없어야 한다 (#141, #121).

이 파일이 `Classification` 의 계약이다: 모든 질문의 키 집합 == enum 전체 값. 새 값을 더하면 질문마다
결정을 요구한다 — 「이 값은 환불 가능한가」를 지나칠 수 없다. 파생 집합의 내용은 이관 전의 리터럴과
같다(행동 보존) — 그 값들도 여기서 못 박는다.
"""

import pytest

from contests.models import Contest, HomeStatusAxis
from core.classification import classifications_of
from payouts.models import Payout

S = Contest.Status
P = Payout.Status


def test_contest_status_has_classifications():
    assert classifications_of(S), "Contest.Status 에 붙은 질문이 하나도 없다"


@pytest.mark.parametrize("name", sorted(classifications_of(S)))
def test_every_contest_status_question_answers_for_every_value(name):
    question = classifications_of(S)[name]
    assert question.keys == set(S), (
        f"Contest.Status.{name} 이 답하지 않는 값이 있다: {set(S) - question.keys} — 새 값을 더했다면 "
        f"이 질문에 그 값의 답을 적어라"
    )


def test_contest_status_sets_are_the_ones_the_call_sites_used_to_spell_out():
    """호출부가 예전에 손으로 적어 두던 집합들 — 값 하나가 끼어들면 이 단언이 먼저 깨진다."""

    assert S.PUBLICLY_VISIBLE.statuses == {S.PUBLISHED, S.CLOSED, S.AWARDED, S.JUDGING_ENDED}
    assert S.SUBMITTABLE.statuses == {S.PUBLISHED}
    assert S.SENDS_LIFECYCLE_NOTICES.statuses == {S.PUBLISHED}
    assert S.SCOREABLE.statuses == {S.CLOSED, S.AWARDED, S.JUDGING_ENDED}
    assert S.AWARDABLE.statuses == {S.CLOSED}
    assert S.JUDGING_EXTENDABLE.statuses == {S.CLOSED}
    assert S.REFUNDABLE.statuses == {S.CLOSED, S.JUDGING_ENDED}
    assert S.REOPENABLE.statuses == {S.CLOSED, S.JUDGING_ENDED}
    assert S.EDITABLE.statuses == {S.DRAFT}
    assert S.CONTENT_EDITABLE.statuses == {S.DRAFT, S.PUBLISHED}
    assert S.PAYABLE.statuses == {S.DRAFT}
    assert S.BLOCKS_SPONSOR_WITHDRAWAL.statuses == {S.PUBLISHED, S.CLOSED}
    assert S.HAS_AWARD.statuses == {S.AWARDED}
    assert S.AWAITING_DISTRIBUTION.statuses == {S.JUDGING_ENDED}
    assert S.REQUIRES_IDENTITY_RETENTION.statuses == {S.PUBLISHED, S.CLOSED, S.AWARDED, S.JUDGING_ENDED}
    assert S.HOME_AXIS.where(HomeStatusAxis.OPEN) == {S.PUBLISHED}
    assert S.HOME_AXIS.where(HomeStatusAxis.IN_JUDGING) == {S.CLOSED}
    assert S.HOME_AXIS.where(HomeStatusAxis.COMPLETED) == {S.AWARDED, S.JUDGING_ENDED}
    assert S.HOME_AXIS.where(HomeStatusAxis.HIDDEN) == {S.DRAFT}
    assert S.SUBMISSION_REQUIRES_VERIFICATION.statuses == {S.PUBLISHED, S.CLOSED, S.AWARDED, S.JUDGING_ENDED}
    assert S.OWN_SUBMISSION_VIEWABLE.statuses == {
        S.PUBLISHED, S.CLOSED, S.AWARDED, S.JUDGING_ENDED
    }


def test_an_unknown_status_value_is_loud_not_silently_false():
    """DB 에 enum 밖 값이 남는 마이그레이션 사고는 조용한 False 가 아니라 KeyError 여야 한다."""

    with pytest.raises(KeyError):
        S.SCOREABLE("paused")


@pytest.mark.parametrize("name", sorted(classifications_of(P)))
def test_every_payout_status_question_answers_for_every_value(name):
    question = classifications_of(P)[name]
    assert question.keys == set(P), f"Payout.Status.{name} 이 답하지 않는 값이 있다: {set(P) - question.keys}"


def test_payout_status_sets_are_the_ones_the_call_sites_used_to_spell_out():
    assert P.ACTIVE.statuses == {
        P.REQUESTED, P.CONFIRMED_IDENTITY_PENDING, P.CONFIRMED_SELLER_PENDING, P.CONFIRMED
    }
    assert P.SETTLED.statuses == {P.CONFIRMED_IDENTITY_PENDING, P.CONFIRMED_SELLER_PENDING, P.CONFIRMED}
    assert P.BLOCKS_DEVELOPER_WITHDRAWAL.statuses == {
        P.REQUESTED, P.CONFIRMED_IDENTITY_PENDING, P.CONFIRMED_SELLER_PENDING
    }


def test_active_payout_unique_constraints_are_derived_from_the_active_question():
    """DB 레벨 최후 방어선(부분 유니크 제약 둘)과 애플리케이션 조회 기준이 한 집합이다."""

    conditions = {
        c.name: c.condition for c in Payout._meta.constraints if c.name.startswith("unique_active_payout")
    }
    assert set(conditions) == {"unique_active_payout_per_handover", "unique_active_payout_per_distribution_share"}
    for name, condition in conditions.items():
        ((lookup, values),) = condition.children
        assert lookup == "status__in", name
        assert set(values) == {s.value for s in P.ACTIVE.statuses}, name
