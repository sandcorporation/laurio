"""무료 공모전 보관·해제 (#870, CONTEXT.md 「보관」).

보관은 소프트 삭제다 — `Contest.archived_at` 을 채우고, 영구 삭제는 없다. 보관한 공모전은
공개 목록·상세(소유자 말고는 404)·검색·홈·강의실 들여오기 목록에서 빠진다. 해제하면 돌아온다.

**보관할 수 있는 때**: 초안, 끝난 공모전(CLOSED·AWARDED·JUDGING_ENDED), 제출이 0건인
PUBLISHED. 제출을 받은 PUBLISHED 를 보관하면 참가자가 낸 곳이 사라지므로 막는다.

상태(`status`)를 바꾸지 않는다 — 보관은 상태 흐름의 간선이 아니라 그 옆의 표지다. 저장은
`save(update_fields=...)` 로 해 검색 색인 신호(`contests.indexing`)가 그대로 돈다.
"""

from __future__ import annotations

from datetime import datetime

from django.contrib.auth.base_user import AbstractBaseUser
from ninja.errors import HttpError

from core.clock import Clock

from .models import Contest, ContestArchiveEvent

_FINISHED = {Contest.Status.CLOSED, Contest.Status.AWARDED, Contest.Status.JUDGING_ENDED}


def archive_refusal(contest: Contest) -> str | None:
    """지금 보관할 수 없으면 그 이유를, 할 수 있으면 None 을."""

    if contest.archived_at is not None:
        return "이미 보관한 공모전입니다."
    if contest.status == Contest.Status.DRAFT or contest.status in _FINISHED:
        return None
    if contest.status == Contest.Status.PUBLISHED and not contest.submissions.exists():
        return None
    if contest.status == Contest.Status.PUBLISHED:
        return "제출을 받은 공모전은 마감한 뒤에 보관할 수 있습니다."
    return "지금 상태에서는 보관할 수 없습니다."


def archive_contest(contest: Contest, *, actor: AbstractBaseUser | None, via: str) -> Contest:
    """보관하고 기록을 한 행 남긴다. `actor` 는 계정(User), `via` 는 길의 이름이다."""

    refusal = archive_refusal(contest)
    if refusal is not None:
        raise HttpError(409, refusal)
    now = Clock.now()
    contest.archived_at = now
    contest.save(update_fields=["archived_at"])
    _record(contest, ContestArchiveEvent.Action.ARCHIVED, actor, via, now)
    return contest


def unarchive_contest(contest: Contest, *, actor: AbstractBaseUser | None, via: str) -> Contest:
    if contest.archived_at is None:
        raise HttpError(409, "보관하지 않은 공모전입니다.")
    contest.archived_at = None
    contest.save(update_fields=["archived_at"])
    _record(contest, ContestArchiveEvent.Action.UNARCHIVED, actor, via, Clock.now())
    return contest


def _record(contest: Contest, action: str, actor: AbstractBaseUser | None, via: str, at: datetime) -> None:
    ContestArchiveEvent.objects.create(contest=contest, action=action, actor=actor, via=via, occurred_at=at)
