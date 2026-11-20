"""공모전 판정이 묻는 선정 사실 — `awards.apps` 가 `contests.ports` 에 올린다(#1102)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from django.contrib.auth.models import AbstractBaseUser

    from contests.models import Contest

#: 「다음 행동」이 `ContestSubmission` 에서 당길 관계
NEXT_ACTION_RELATIONS = ("contest__award",)
#: 운영자 무료 공모전 목록이 `Contest` 에서 당길 관계
FREE_CONTEST_RELATIONS = ("award__submission__user",)


def awarded_submission_id(contest: Contest) -> int | None:
    award = getattr(contest, "award", None)
    return None if award is None else award.submission_id


def free_contest_winner(contest: Contest) -> AbstractBaseUser | None:
    award = getattr(contest, "award", None)
    return None if award is None else award.submission.user
