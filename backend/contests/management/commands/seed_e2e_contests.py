"""FE-04/FE-05(#29·#30) e2e 테스트용 공개 Contest 를 결정적으로(재현 가능하게) 심는다.

왜 관리 명령인가 — SSR 테스트는 「클라이언트에서 가져오면 없고, 서버가 가져오면 있는」
**백엔드가 준 값**을 확인해야 증명이 된다(frontend/e2e/seam.spec.ts 상단 주석,
ADR-0017). 프론트에 하드코딩한 픽스처를 심으면 그 구분 자체가 사라지므로, 진짜
Contest 를 백엔드 DB에 만든다.

정상 개최 플로우(POST /api/contests → 결제 웹훅 → PUBLISHED)를 그대로 타지 않는
이유 — 그 경로는 Verification·Sponsor 인증·결제(#8·#9)까지 전부 통과해야 하는데,
이 명령의 목적은 "SSR이 공개 표면 데이터를 실제로 그리는지"만 검증하는 것이지 개최
플로우 자체를 다시 검증하는 게 아니다(그건 이미 backend 의 416개 테스트가 지킨다,
spec #25). 그래서 ORM으로 상태를 직접 만든다 — Django 관리 명령·셸로 시드하라는
디스패치 지침 그대로다.

멱등성 — 이 명령이 여러 번 돌아도(로컬 재실행, CI 재시도) 항상 같은 결과가
나오도록, "[E2E]" 접두어가 붙은 기존 Contest/Category/DeliverableType/User 를 먼저
지우고 다시 만든다. 접두어가 없는 실데이터는 절대 건드리지 않는다.

출력 — 생성된 Contest 들의 id·제목·상금·마감·requirements 를 표준출력에 JSON 하나로
찍는다. Playwright 쪽(frontend/e2e/lib/seed.ts)이 이 출력을 그대로 파싱해 단언에
쓴다 — 백엔드 문자열을 프론트 스펙 파일에 다시 손으로 베끼면 두 곳이 각자
드리프트하므로, 이 명령이 유일한 진실 공급원이다.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from contests.models import Category, Contest, DeliverableType, Requirement
from submissions.models import Submission

PREFIX = "[E2E] "

# FE-06(#31) 인수조건 — 소스코드와 test_account 는 developer 공개 프로필 HTML
# 어디에도 나오면 안 된다. 두 값을 여기 심어두고 frontend/e2e 스펙이 이 정확한
# 문자열이 응답 본문에 "없다"는 걸 단언한다(있는지를 확인하는 게 아니라 없는지를
# 확인하는 것이므로, 흔한 단어와 겹치지 않을 만큼 특이한 sentinel 이어야 한다).
SENSITIVE_SOURCE_OBJECT_KEY = "submission:__e2e__:source/deadbeefdeadbeefdeadbeefdeadbeef"
SENSITIVE_TEST_ACCOUNT = "e2e-secret-test-account:hunter2-should-never-leak"


class Command(BaseCommand):
    help = "FE-04/FE-05 SSR e2e 테스트가 검증할 공개 Contest 를 결정적으로 심는다."

    def handle(self, *args, **options) -> None:
        self._cleanup()

        sponsor = self._seed_sponsor()
        category_lifestyle = Category.objects.create(name=f"{PREFIX}라이프스타일")
        category_productivity = Category.objects.create(name=f"{PREFIX}생산성")
        web_service = DeliverableType.objects.create(
            name=f"{PREFIX}웹 서비스", minimum_prize=2_000_000
        )
        mobile_app = DeliverableType.objects.create(
            name=f"{PREFIX}모바일 앱", minimum_prize=1_500_000
        )

        now = timezone.now()

        funded = self._create_contest(
            sponsor=sponsor,
            title=f"{PREFIX}알림 앱 리디자인",
            category=category_lifestyle,
            deliverable_types=[web_service],
            description="기존 알림 앱의 UI 를 다시 그리는 공모전입니다.",
            prize=3_000_000,
            deadline_at=now + timedelta(days=10),
            status=Contest.Status.PUBLISHED,
            requirements=[
                ("로그인 기능 구현", Requirement.Grade.REQUIRED),
                ("다크모드 지원", Requirement.Grade.OPTIONAL),
            ],
        )

        underfunded = self._create_contest(
            sponsor=sponsor,
            title=f"{PREFIX}러닝 크루 기록 앱",
            category=category_productivity,
            deliverable_types=[web_service, mobile_app],
            description="러닝 크루의 기록을 남기는 앱입니다.",
            prize=1_000_000,
            deadline_at=now + timedelta(days=2),
            status=Contest.Status.PUBLISHED,
            requirements=[
                ("러닝 기록 저장", Requirement.Grade.REQUIRED),
            ],
        )

        closed = self._create_contest(
            sponsor=sponsor,
            title=f"{PREFIX}마감된 공모전",
            category=category_lifestyle,
            deliverable_types=[web_service],
            description="이미 마감되었지만 공개 목록·상세에 남아야 하는 공모전입니다.",
            prize=2_500_000,
            deadline_at=now - timedelta(days=2),
            status=Contest.Status.CLOSED,
            requirements=[
                ("반려동물 산책 기록", Requirement.Grade.REQUIRED),
            ],
            judging_ends_at=now + timedelta(days=5),
        )

        draft = self._create_contest(
            sponsor=sponsor,
            title=f"{PREFIX}드래프트 공모전",
            category=category_lifestyle,
            deliverable_types=[web_service],
            description="아직 공개되지 않은 draft 입니다 — 404 여야 합니다.",
            prize=5_000_000,
            deadline_at=now + timedelta(days=30),
            status=Contest.Status.DRAFT,
            requirements=[],
        )

        # FE-06(#31) — 개발자 공개 프로필(GET /api/developers/{id}/profile)이
        # 아카이브하는 것은 "마감된 Contest 의 Submission" 뿐이다(ADR-0014,
        # submissions.api.get_developer_public_profile). `closed` 는 이미 마감된
        # Contest 이므로 여기 낸 Submission 이 프로필에 나타나야 하고, `funded` 는
        # 아직 진행 중이므로 같은 개발자가 냈어도 프로필에 나타나면 안 된다 — 두
        # 상태를 한 번에 검증할 수 있게 일부러 같은 developer 로 둘 다 심는다.
        #
        # source_object_key·test_account 는 SENSITIVE_* sentinel 을 그대로 심는다 —
        # DeveloperPublicProfileOut/PublicSubmissionOut 스키마 자체에 이 필드가
        # 없어(backend/submissions/schemas.py) 백엔드는 이미 안전하지만, frontend
        # 가 API 응답 객체를 통째로 넘기는 실수를 하면 이 값이 SSR HTML 에 그대로
        # 샐 수 있다 — 그 실수를 잡는 게 이 sentinel 의 목적이다.
        developer = self._seed_developer()
        Submission.objects.create(
            contest=closed,
            developer=developer,
            source_object_key=SENSITIVE_SOURCE_OBJECT_KEY,
            demo_video_object_key=f"{PREFIX}demo-video/deadbeefdeadbeefdeadbeefdeadbeef",
            demo_url="https://example.invalid/e2e-archived-demo",
            test_account=SENSITIVE_TEST_ACCOUNT,
        )
        # 아직 마감되지 않은 Contest 에 낸 Submission — 프로필에 나타나면 안 된다.
        Submission.objects.create(
            contest=funded,
            developer=developer,
            source_object_key=SENSITIVE_SOURCE_OBJECT_KEY.replace("deadbeef", "cafebabe", 1),
            test_account=SENSITIVE_TEST_ACCOUNT,
        )

        payload = {
            "funded": self._serialize(funded),
            "underfunded": self._serialize(underfunded),
            "closed": self._serialize(closed),
            "draft": self._serialize(draft),
            "developer": self._serialize_developer(developer, closed_contest=closed),
        }
        self._write_stdout_utf8(json.dumps(payload, ensure_ascii=False) + "\n")

    def _cleanup(self) -> None:
        Contest.objects.filter(title__startswith=PREFIX).delete()
        Category.objects.filter(name__startswith=PREFIX).delete()
        DeliverableType.objects.filter(name__startswith=PREFIX).delete()
        get_user_model().objects.filter(
            username__in=["e2e-seed-sponsor", "e2e-seed-developer"]
        ).delete()

    def _seed_sponsor(self) -> SponsorProfile:
        user = get_user_model().objects.create_user(
            username="e2e-seed-sponsor", email="e2e-seed-sponsor@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return SponsorProfile.objects.create(user=user, display_name="E2E 시드 스폰서")

    def _seed_developer(self) -> DeveloperProfile:
        user = get_user_model().objects.create_user(
            username="e2e-seed-developer", email="e2e-seed-developer@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return DeveloperProfile.objects.create(
            user=user,
            display_name=f"{PREFIX}개발자",
            bio=f"{PREFIX}자기소개 — SSR 로 색인되어야 하는 공개 프로필입니다.",
        )

    def _create_contest(
        self,
        *,
        sponsor: SponsorProfile,
        title: str,
        category: Category,
        deliverable_types: list[DeliverableType],
        description: str,
        prize: int,
        deadline_at,
        status: str,
        requirements: list[tuple[str, str]],
        judging_ends_at=None,
    ) -> Contest:
        required_minimum_prize = sum(dt.minimum_prize for dt in deliverable_types)
        contest = Contest.objects.create(
            sponsor=sponsor,
            title=title,
            category=category,
            description=description,
            prize=prize,
            deadline_at=deadline_at,
            status=status,
            required_minimum_prize=required_minimum_prize,
            is_underfunded=prize < required_minimum_prize,
            judging_ends_at=judging_ends_at,
        )
        contest.deliverable_types.set(deliverable_types)
        for order, (text, grade) in enumerate(requirements):
            Requirement.objects.create(contest=contest, text=text, grade=grade, order=order)
        return contest

    def _serialize(self, contest: Contest) -> dict:
        return {
            "id": contest.id,
            "title": contest.title,
            "prize": contest.prize,
            "deadline_at": contest.deadline_at.isoformat(),
            "status": contest.status,
            "category": contest.category.name,
            "is_underfunded": contest.is_underfunded,
            "required_minimum_prize": contest.required_minimum_prize,
            "deliverable_types": [dt.name for dt in contest.deliverable_types.all()],
            "requirements": [
                {"text": r.text, "grade": r.grade}
                for r in contest.requirements.all().order_by("order", "id")
            ],
        }

    def _serialize_developer(self, developer: DeveloperProfile, *, closed_contest: Contest) -> dict:
        return {
            "id": developer.id,
            "display_name": developer.display_name,
            "bio": developer.bio,
            "archived_submission": {
                "contest_id": closed_contest.id,
                "contest_title": closed_contest.title,
                "demo_url": "https://example.invalid/e2e-archived-demo",
            },
            # 단언 대상은 값의 "존재"가 아니라 "부재"다 — HTML 본문 전체에 이
            # 문자열이 없어야 한다(frontend/e2e/developer-profile.spec.ts).
            "sensitive_source_object_key": SENSITIVE_SOURCE_OBJECT_KEY,
            "sensitive_test_account": SENSITIVE_TEST_ACCOUNT,
        }

    def _write_stdout_utf8(self, payload: str) -> None:
        # export_openapi_schema.py 와 같은 이유 — Windows 콘솔 기본 코덱(cp949)이
        # 한글을 인코딩하지 못해 UnicodeEncodeError 로 죽는 것을 피한다.
        buffer = getattr(self.stdout, "buffer", None)
        if buffer is not None:
            buffer.write(payload.encode("utf-8"))
            buffer.flush()
        else:
            self.stdout.write(payload, ending="")
