"""과제(Assignment) Contest를 HTTP 없이 직접 조립하는 헬퍼 (#361).

과제 라우터(`contests.assignment_api`)가 걷힌 뒤에도, 공유 배관(제출 API·스토리지
가시성·영상 보존·결제 게이트)의 `is_assignment` 분기는 남아 있다 — 그 분기를 계속
테스트하려면 kind=ASSIGNMENT인 Contest가 여전히 필요하다. 예전에는 그 Contest를
`POST /api/assignments`·`.../open`으로 만들었지만 그 엔드포인트가 사라졌으므로,
여기서는 모델을 직접 조립한다. `Contest.objects.create(status=...)`가 DRAFT가 아닌
리터럴을 찍는 것은 시드·테스트 픽스처의 특권이다(`contests/transitions.py`의
`CREATION_STATES` 독스트링) — `tests/ast_scan_support.py`가 `tests/` 자체를 그
정적 스캔에서 빼는 이유도 같다.

이 파일은 `test_` 로 시작하지 않아 pytest가 수집하지 않는다(`ast_scan_support.py`와
같은 관용구).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from accounts.models import SponsorProfile
from accounts.tokens import issue_token_pair
from contests.assignment_category import get_assignment_category
from contests.models import Contest, InviteCode, Requirement


def create_open_assignment(
    *,
    deliverable_types,
    sponsor_uid: str,
    requirements: list[dict] | None = None,
    deadline_at=None,
) -> dict:
    """열려 있는(kind=ASSIGNMENT, status=ASSIGNMENT_OPEN) Contest 하나 — Requirement
    (기본 하나)와 활성 InviteCode를 함께 만든다. 반환값은 예전 `POST /api/assignments`
    + `.../open` 응답이 주던 것과 같은 모양(id·invite_code, Requirement가 있으면
    첫 번째의 id를 `requirement_id`로도)에 `sponsor_access`(이 Sponsor로 인증된
    JWT access 토큰)를 더한다 — 소셜 로그인 HTTP 왕복 없이
    `accounts.tokens.issue_token_pair`로 직접 발급한다(이 User는 소셜 계정이
    없어 로그인 엔드포인트로는 애초에 들어올 수 없다).

    `requirements=[]`를 주면 요구사항 없는 과제(리졸버 검증처럼 요구사항 자체가
    관심사가 아닌 자리)를 만든다."""

    if requirements is None:
        requirements = [{"text": "함수를 정의한다", "grade": "required"}]

    User = get_user_model()
    user = User.objects.create(username=f"sponsor-{sponsor_uid}")
    sponsor = SponsorProfile.objects.create(user=user, can_open_assignments=True)

    contest = Contest.objects.create(
        sponsor=sponsor,
        title=f"{sponsor_uid}의 과제",
        category=get_assignment_category(),
        kind=Contest.Kind.ASSIGNMENT,
        description="과제 설명",
        prize=0,
        deadline_at=deadline_at or (timezone.now() + timedelta(days=7)),
        status=Contest.Status.ASSIGNMENT_OPEN,
        required_minimum_prize=0,
        is_underfunded=False,
    )
    contest.deliverable_types.set(deliverable_types)
    created_requirements = Requirement.objects.bulk_create(
        [
            Requirement(contest=contest, text=r["text"], grade=r["grade"], order=index)
            for index, r in enumerate(requirements)
        ]
    )
    invite = InviteCode.objects.create(contest=contest)

    result = {
        "id": contest.id,
        "invite_code": invite.code,
        "sponsor_access": issue_token_pair(user.id).access,
    }
    if created_requirements:
        result["requirement_id"] = created_requirements[0].id
    return result
