"""Classroom 도메인 모델 (CONTEXT.md 「강의실」, ADR-0037, #278).

강사 한 명이 열고 참여자를 모으는 학습 단위다. 상금도 결제도 본인확인도 없다 —
그래서 `Class`는 `contests.Contest`와 닮았어도 그 모델을 재사용하지 않는다
(ADR-0037이 두 도메인의 import 자체를 양방향으로 막는다).

**`Class`는 `User`를 직접 가리킨다** — `accounts.SponsorProfile`도
`accounts.DeveloperProfile`도 쓰지 않는다. 강의실의 강사·참여자는 역할 프로필이
필요 없다(이름은 `ClassMember`가 따로 들 자리라 프로필이 할 일이 없다, CONTEXT.md).
"""

from __future__ import annotations

from django.conf import settings
from django.db import models


class Class(models.Model):
    #: 이 클래스를 연 강사. `accounts.SponsorProfile`이 아니라 `User`를 바로
    #: 가리킨다 — 프로필을 쓰지 않기로 한 것 자체가 ADR-0037의 합의다.
    instructor = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name="classrooms", on_delete=models.CASCADE
    )
    name = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Class(id={self.pk}, name={self.name!r})"
