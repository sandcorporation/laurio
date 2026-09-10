"""Classroom 도메인 모델 (CONTEXT.md 「강의실」, ADR-0037, #278/#282/#283).

강사 한 명이 열고 참여자를 모으는 학습 단위다. 상금도 결제도 본인확인도 없다 —
그래서 `Class`·`Problem`은 `contests.Contest`와 닮았어도 그 모델을 재사용하지
않는다(ADR-0037이 두 도메인의 import 자체를 양방향으로 막는다).

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

    #: 채점이 실제로 쓰는 강사 본인의 OpenAI 키(#284). `core.crypto.encrypt`로
    #: 암호화된 값만 여기 남는다 — 평문은 저장하지 않는다. 빈 문자열이면
    #: 키가 없다는 뜻이다.
    openai_api_key_encrypted = models.TextField(blank=True, default="")
    #: 마스킹 표시용 마지막 네 자리. **복호화는 채점 요청을 보낼 때만
    #: 한다**는 규율(#284) 때문에, 화면에 보여줄 마스킹은 암호문을 다시 풀지
    #: 않고 저장 시점에 평문에서 떼어 둔 이 값으로만 만든다.
    openai_api_key_last4 = models.CharField(max_length=4, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Class(id={self.pk}, name={self.name!r})"


class Problem(models.Model):
    """Class 안의 문제 하나. Contest와 달리 **마감이 없다**(ADR-0039) — 이
    모델에는 마감 필드가 아예 없다. 제출 형식은 소스 또는 저장소뿐이다.

    `status`(초안/열림)는 여기서 이미 구별되지만, 참여자가 실제로 열린 것만
    보게 거르는 표면은 `ClassMember`가 생기는 #280부터다 — 그 전까지는
    강사가 아닌 모든 요청이 클래스 자체를 404로 받는다(#278과 같은 이유).
    """

    class SubmissionFormat(models.TextChoices):
        SOURCE = "source", "소스"
        REPOSITORY = "repository", "저장소"

    class Status(models.TextChoices):
        DRAFT = "draft", "초안"
        OPEN = "open", "열림"

    classroom = models.ForeignKey(Class, related_name="problems", on_delete=models.CASCADE)
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")
    submission_format = models.CharField(max_length=20, choices=SubmissionFormat.choices)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    #: 클래스 상세에서의 노출 순서. 생성 순서가 아니라 강사가 직접 재배열한다.
    order = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"Problem(id={self.pk}, title={self.title!r})"


class ChecklistItem(models.Model):
    """채점이 보는 항목 하나(#283). `required=True`를 전부 충족하면 **통과**다
    — 문제마다 합격선을 따로 두지 않는다(CONTEXT.md 「통과」). 필수 항목이
    하나도 없으면 통과가 정의되지 않으므로, 그런 문제는 열 수 없다(API에서
    강제한다).

    이미 통과한 사람이 있어도 강사가 언제든 고친다 — 돈이 걸려 있지 않아
    "나중에 낸 사람이 유리해진다"가 성립하지 않는다. 지난 점수는 그대로
    남고 달성률만 새 기준으로 다시 셈된다(CONTEXT.md 「달성률」) — 그 셈은
    Score가 생기는 채점 티켓의 몫이고, 여기서는 그 사실을 화면이 미리
    말해 줄 수 있도록 `Problem.status`만 정확히 유지한다.
    """

    problem = models.ForeignKey(Problem, related_name="checklist_items", on_delete=models.CASCADE)
    label = models.CharField(max_length=200)
    required = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["order", "id"]

    def __str__(self) -> str:  # pragma: no cover
        return f"ChecklistItem(id={self.pk}, label={self.label!r})"
