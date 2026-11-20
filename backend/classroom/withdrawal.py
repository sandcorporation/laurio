"""탈퇴 판정 중 강의실 몫 — `accounts.ports` 에 `classroom.apps` 가 올린다(#1086, #302).

판정의 순서와 사유 목록은 `accounts.withdrawal` 이 든다.
"""

from __future__ import annotations

from django.contrib.auth.models import AbstractBaseUser

from .models import Class


def instructor_has_class_in_progress(user: AbstractBaseUser) -> bool:
    """**소유한** 클래스(강의실의 Class.instructor) 중 보관되지 않은 것이 있는가
    (#302). 공동 강사인 클래스는 세지 않는다 — 공동 강사는 탈퇴로 그 자리에서 빠지고
    클래스는 소유자에게 남는다(CONTEXT.md 「공동 강사」, ADR-0055). 그래서 이 자리는
    「강사인가」가 아니라 소유자 자체를 본다.

    Sponsor/Developer 와 달리 강의실은 프로필을 두지 않고 계정(User)을
    직접 가리킨다(ADR-0037, CONTEXT.md 「당사자」) — 그래서 여기는 profile 이 아니라
    user 자체로 조회한다. 신원이 사라지면 참여자들이 새 문제를 열어 줄 사람도 명단을
    손볼 사람도 없는 클래스에 남는다."""

    return Class.objects.filter(instructor=user, archived_at__isnull=True).exists()
