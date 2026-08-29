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
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from accounts.models import DeveloperProfile, SocialAccount, SponsorProfile
from awards.models import Award
from contests.models import Category, Contest, DeliverableType, Requirement
from scoring.models import Score
from submissions.models import Evidence, RequirementResponse, Submission

PREFIX = "[E2E] "

# FE-06(#31) 인수조건 — 소스코드와 test_account 는 developer 공개 프로필 HTML
# 어디에도 나오면 안 된다. 두 값을 여기 심어두고 frontend/e2e 스펙이 이 정확한
# 문자열이 응답 본문에 "없다"는 걸 단언한다(있는지를 확인하는 게 아니라 없는지를
# 확인하는 것이므로, 흔한 단어와 겹치지 않을 만큼 특이한 sentinel 이어야 한다).
SENSITIVE_SOURCE_OBJECT_KEY = "submission:__e2e__:source/deadbeefdeadbeefdeadbeefdeadbeef"
SENSITIVE_TEST_ACCOUNT = "e2e-secret-test-account:hunter2-should-never-leak"

# FE-11(#36) 인수조건 — 심사 비교 화면(GET /contests/{id}/submissions/compare)의
# HTML 응답 본문 전체(SSR 페이로드·하이드레이션 스크립트 포함)에 소스코드와 AI
# 채점 점수(Score)가 어디에도 나오면 안 된다(ADR-0014, ADR-0006). 위
# SENSITIVE_* 와 같은 원칙 — "존재를 확인"이 아니라 "부재를 확인"하는 sentinel
# 이라 흔한 단어와 겹치지 않아야 한다. 두 Submission 에 서로 다른 소스 sentinel
# 을 심어 "다른 제출작의 소스가 실수로 섞여 보이는" 사고도 같이 잡는다.
JUDGING_SOURCE_SENTINEL_A = "submission:__e2e_judging_a__:source/f00dbabef00dbabef00dbabef00dbabe"
JUDGING_SOURCE_SENTINEL_B = "submission:__e2e_judging_b__:source/c0ffeec0ffeec0ffeec0ffeec0ffeec0"
JUDGING_TEST_ACCOUNT_SENTINEL = "e2e-judging-secret-test-account:hunter3-should-never-leak"
# Score 는 실제로 DB 에 존재하게 심는다 — "화면이 그리지 않는다"가 아니라
# "코드 경로 자체가 이 문자열을 어디서도 응답에 넣지 않는다"까지 증명하려면,
# 안 그리는 값이 아예 없는 게 아니라 있는데도 안 새는지를 확인해야 한다.
JUDGING_SCORE_MODEL_SENTINEL = "e2e-judging-score-model-should-never-leak-v1"

# 심사 비교/Award 는 심사기간(judging_ends_at) 중 CLOSED Contest 를 전제한다 —
# 정상 경로(마감 스케줄러 틱)를 타면 /api/internal/tick 이 필요한데, 그 경로는
# BFF 프록시 허용목록에서 의도적으로 막혀 있다(디스패치 지침). 그래서 다른
# 시드 Contest 들처럼 ORM 으로 CLOSED 상태를 직접 만든다 — #13 백엔드 테스트가
# 이 전이 자체는 이미 검증했으므로 여기서 다시 검증할 필요가 없다.
JUDGING_SPONSOR_LOGIN_SEED = "e2e-judging-sponsor"


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

        # FE-11(#36) — 심사 비교 화면(Requirement 축 매트릭스 + Award)이 쓸 CLOSED
        # Contest. 심사기간(judging_ends_at)이 아직 남아 있어야 Award 가 허용된다
        # (awards.api.award_submission). Sponsor 는 fake 소셜 로그인으로 그대로
        # 로그인할 수 있도록 SocialAccount 를 함께 심는다 — award.spec.ts 가
        # "본인만 Award 할 수 있다"를 검증하려면 그 Contest 의 진짜 Sponsor 로
        # 로그인해야 하기 때문이다(다른 Sponsor 로 시도하는 거부 테스트는 매번
        # 새로 만드는 임의의 계정으로 충분하다).
        judging_sponsor = self._seed_judging_sponsor()
        judging = self._create_contest(
            sponsor=judging_sponsor,
            title=f"{PREFIX}심사 비교용 공모전",
            category=category_productivity,
            deliverable_types=[web_service],
            description="Requirement 매트릭스 비교와 Award 테스트용 공모전입니다.",
            prize=4_000_000,
            deadline_at=now - timedelta(days=1),
            status=Contest.Status.CLOSED,
            requirements=[
                ("필수 요구사항 — 로그인 기능", Requirement.Grade.REQUIRED),
                ("선택 요구사항 — 다크모드", Requirement.Grade.OPTIONAL),
            ],
            judging_ends_at=now + timedelta(days=5),
        )
        judging_required_req, judging_optional_req = list(
            judging.requirements.all().order_by("order", "id")
        )

        developer_a = self._seed_named_developer(
            "e2e-judging-developer-a", f"{PREFIX}심사 개발자 A"
        )
        developer_b = self._seed_named_developer(
            "e2e-judging-developer-b", f"{PREFIX}심사 개발자 B"
        )

        # Submission A — 필수 Requirement 에 Evidence 가 연결돼 있다(칸이
        # "충족·증거 있음"으로 즉시 구분돼야 한다). Evidence 의 value 는
        # source_location 이라도 소스 내 "위치 포인터"일 뿐 소스 내용 자체가
        # 아니므로 노출해도 된다(submissions.schemas.EvidenceOut 이 이미 그렇게
        # 설계돼 있다) — source_object_key(전체 소스) sentinel 과는 다른 것을
        # 분명히 하려고 일부러 같은 테스트에서 둘 다 심는다.
        submission_a = Submission.objects.create(
            contest=judging,
            developer=developer_a,
            source_object_key=JUDGING_SOURCE_SENTINEL_A,
            demo_url="https://example.invalid/e2e-judging-demo-a",
            test_account=JUDGING_TEST_ACCOUNT_SENTINEL,
        )
        response_a_required = RequirementResponse.objects.create(
            submission=submission_a,
            requirement=judging_required_req,
            is_met=True,
            note=f"{PREFIX}로그인 폼과 세션 발급을 구현했습니다.",
        )
        Evidence.objects.create(
            response=response_a_required,
            kind=Evidence.Kind.SOURCE_LOCATION,
            value="src/auth/login.ts",
        )
        RequirementResponse.objects.create(
            submission=submission_a, requirement=judging_optional_req, is_met=False, note=""
        )

        # Submission B — 두 Requirement 모두 자가 응답 자체가 없다. "증거가 없는
        # 칸이 즉시 구분된다"는 인수조건은 Evidence 만 비어있는 경우와, 응답
        # 자체가 없는 경우를 둘 다 커버해야 한다.
        submission_b = Submission.objects.create(
            contest=judging,
            developer=developer_b,
            source_object_key=JUDGING_SOURCE_SENTINEL_B,
        )

        # AI Score 는 실제로 존재한다 — 심사 화면이 "코드 경로가 아예 없어서"가
        # 아니라 "있는데도 안 새는지"를 증명하려면 DB 에 진짜 값이 있어야 한다
        # (ADR-0006/0014, awards.api 의 award_submission 이 Score 를 아예 조회하지
        # 않는 것과 같은 원칙 — submissions.api.compare_submissions 응답 스키마
        # 어디에도 Score 필드가 없다).
        Score.objects.create(
            submission=submission_a,
            percentage=Decimal("91.50"),
            model_version=JUDGING_SCORE_MODEL_SENTINEL,
            prompt=f"{PREFIX}fake prompt",
            reasoning=[
                {
                    "requirement_id": judging_required_req.id,
                    "is_met": True,
                    "reasoning": f"{PREFIX}fake reasoning",
                }
            ],
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
            "judging": self._serialize_judging(
                judging,
                requirements=[judging_required_req, judging_optional_req],
                submission_a=submission_a,
                submission_b=submission_b,
                developer_a=developer_a,
                developer_b=developer_b,
            ),
        }
        self._write_stdout_utf8(json.dumps(payload, ensure_ascii=False) + "\n")

    def _cleanup(self) -> None:
        # Award.submission 은 on_delete=PROTECT 다(awards/models.py) — Django의
        # delete collector 는 "그 Award 자체도 이번 삭제로 함께 사라진다"는 걸
        # 감안하지 않고 PROTECT 를 만나는 즉시 막는다. FE-11(#36) e2e 가 실제로
        # POST /award 를 호출해 Award 행을 만들기 시작한 뒤로(judging-compare.spec.ts
        # 의 "Sponsor 본인은 Award할 수 있다" 테스트), Contest 를 삭제하기 전에
        # 그 Contest 에 걸린 Award 를 먼저 지워야 한다 — Handover.award 는 CASCADE
        # 라 Award 를 지우면 함께 정리된다.
        Award.objects.filter(contest__title__startswith=PREFIX).delete()
        Contest.objects.filter(title__startswith=PREFIX).delete()
        Category.objects.filter(name__startswith=PREFIX).delete()
        DeliverableType.objects.filter(name__startswith=PREFIX).delete()
        get_user_model().objects.filter(
            username__in=[
                "e2e-seed-sponsor",
                "e2e-seed-developer",
                "e2e-judging-sponsor",
                "e2e-judging-developer-a",
                "e2e-judging-developer-b",
            ]
        ).delete()

    def _seed_sponsor(self) -> SponsorProfile:
        user = get_user_model().objects.create_user(
            username="e2e-seed-sponsor", email="e2e-seed-sponsor@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return SponsorProfile.objects.create(user=user, display_name="E2E 시드 스폰서")

    def _seed_judging_sponsor(self) -> SponsorProfile:
        """FE-11(#36) 전용 Sponsor — fake 소셜 로그인으로 직접 로그인할 수 있도록
        SocialAccount 를 함께 심는다(accounts.api.social_login 이 (provider,
        provider_uid) 로만 사용자를 찾으므로, provider_uid 를 로그인 seed 문자열과
        똑같이 맞추면 frontend/e2e 가 그 seed 로 로그인했을 때 바로 이 계정으로
        귀결된다)."""

        user = get_user_model().objects.create_user(
            username=JUDGING_SPONSOR_LOGIN_SEED, email=f"{JUDGING_SPONSOR_LOGIN_SEED}@example.test"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        SocialAccount.objects.create(
            user=user,
            provider=SocialAccount.Provider.KAKAO,
            provider_uid=JUDGING_SPONSOR_LOGIN_SEED,
            email=f"{JUDGING_SPONSOR_LOGIN_SEED}@example.test",
        )
        return SponsorProfile.objects.create(user=user, display_name=f"{PREFIX}심사 스폰서")

    def _seed_developer(self) -> DeveloperProfile:
        return self._seed_named_developer(
            "e2e-seed-developer",
            f"{PREFIX}개발자",
            bio=f"{PREFIX}자기소개 — SSR 로 색인되어야 하는 공개 프로필입니다.",
        )

    def _seed_named_developer(
        self, username: str, display_name: str, *, bio: str = ""
    ) -> DeveloperProfile:
        user = get_user_model().objects.create_user(
            username=username, email=f"{username}@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return DeveloperProfile.objects.create(user=user, display_name=display_name, bio=bio)

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

    def _serialize_judging(
        self,
        contest: Contest,
        *,
        requirements: list[Requirement],
        submission_a: Submission,
        submission_b: Submission,
        developer_a: DeveloperProfile,
        developer_b: DeveloperProfile,
    ) -> dict:
        return {
            "id": contest.id,
            "title": contest.title,
            # frontend/e2e 가 이 seed 로 fake 로그인하면 이 Contest 의 진짜
            # Sponsor 로 귀결된다(_seed_judging_sponsor 참고) — "본인만 Award 할
            # 수 있다"를 검증하려면 진짜 Sponsor 로 로그인해야 하기 때문이다.
            "sponsor_login_seed": JUDGING_SPONSOR_LOGIN_SEED,
            "judging_ends_at": (
                contest.judging_ends_at.isoformat() if contest.judging_ends_at else None
            ),
            "requirements": [
                {"id": r.id, "text": r.text, "grade": r.grade} for r in requirements
            ],
            "submissions": [
                {
                    "id": submission_a.id,
                    "developer_id": developer_a.id,
                    "developer_display_name": developer_a.display_name,
                },
                {
                    "id": submission_b.id,
                    "developer_id": developer_b.id,
                    "developer_display_name": developer_b.display_name,
                },
            ],
            # 아래 세 sentinel 은 "부재"를 확인하는 용도다 — 심사 비교 화면의
            # HTML 응답 본문(SSR 페이로드·하이드레이션 스크립트 포함) 어디에도
            # 있으면 안 된다(ADR-0006, ADR-0014, frontend/e2e/judging-compare.spec.ts).
            "sensitive_source_object_key_a": JUDGING_SOURCE_SENTINEL_A,
            "sensitive_source_object_key_b": JUDGING_SOURCE_SENTINEL_B,
            "sensitive_test_account": JUDGING_TEST_ACCOUNT_SENTINEL,
            "sensitive_score_model_version": JUDGING_SCORE_MODEL_SENTINEL,
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
