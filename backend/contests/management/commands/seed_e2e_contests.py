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
import re
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from accounts.models import DeveloperProfile, SocialAccount, SponsorProfile
from awards.models import Award
from contests.models import Category, Contest, ContestSubmission, DeliverableType, Requirement
from core.management.stdout_utf8 import write_stdout_utf8
from ledger.models import hard_delete_e2e_fixture_rows
from core.quality_review import (
    QualityItemScore,
    checklist_fingerprint,
    historical_columns,
    quality_total,
    records,
)
from scoring.models import Score, SubmissionQualityReview
from scoring.quality import requirement_inputs
from submissions.models import (
    Evidence,
    RequirementResponse,
    Submission,
    SubmissionAsset,
)

# 네임스페이스 없이 부를 때의 기본 접두어. 런타임에 Contest 를 만드는
# 스펙들(submit·upload·grill·payment)이 이 문자열을 직접 쓰고,
# `frontend/e2e/global-setup.ts` 의 일괄 정리도 이 접두어를 훑는다 — 바꾸려면
# 그 셋을 함께 봐야 한다.
DEFAULT_PREFIX = "[E2E] "

# 이 명령이 만드는 계정들의 이름 뿌리. 네임스페이스가 붙으면 `<base>-<token>` 이
# 된다(`Command._account`). 정리가 이 목록을 쓰므로, 계정을 하나 늘리면 여기도
# 늘려야 한다 — 안 그러면 그 계정만 남아 다음 시드가 username 충돌로 터진다.
_SEEDED_ACCOUNT_BASES = (
    "e2e-seed-sponsor",
    "e2e-seed-developer",
    "e2e-judging-sponsor",
    "e2e-judging-developer-a",
    "e2e-judging-developer-b",
)

# 워커별 네임스페이스 토큰이 들어갈 수 있는 글자 (#104). username·title 에 그대로
# 실리므로 좁게 막는다 — 공백이나 구분자가 섞이면 접두어 비교(`startswith`)가
# 다른 네임스페이스를 잡아먹고, 길면 username 길이 제한을 넘겨 시드가 런타임에
# 터진다.
_NAMESPACE_RE = re.compile(r"^[a-z0-9]{1,16}$")

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

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--prune-all-namespaces",
            action="store_true",
            help=(
                "심지 않고, 어느 네임스페이스의 것이든 이 명령이 만든 데이터를 전부 지운다 "
                "(#104). 워커별 정리는 자기 범위만 지우므로, 죽은 워커가 남긴 것과 런타임에 "
                "만들어진 `[E2E] ` Contest 는 아무도 걷지 않는다 — 스위트 시작 전에 "
                "`global-setup` 이 한 번 부른다. 워커가 아직 없는 시점이라 경합이 없다."
            ),
        )
        parser.add_argument(
            "--namespace",
            default="",
            help=(
                "이 시드가 자기 것으로 삼을 네임스페이스 토큰 (#104). 주면 title 접두어와 "
                "계정 이름이 그 토큰으로 갈려, **다른 네임스페이스의 데이터를 지우지 않는다** "
                "— e2e 를 워커 여럿으로 돌릴 때 두 워커가 서로의 픽스처를 파괴하지 않게 하는 "
                "장치다. 안 주면 예전과 똑같이 `[E2E] ` 로 심는다."
            ),
        )
        parser.add_argument(
            "--bulk",
            type=int,
            default=0,
            help=(
                "전용 Category 에 공개 Contest 를 N 건 더 심는다(#39). "
                "목록이 한 페이지를 넘어도 필터·정렬이 정확한지 e2e 로 재현할 때 쓴다."
            ),
        )

    def handle(self, *args, **options) -> None:
        # **네임스페이스가 이 명령의 「자기 것」 범위를 정한다** (#104). 접두어와
        # 계정 이름이 그 토큰으로 갈리고, `_cleanup` 도 그 범위만 지운다 — 그래서
        # 워커 둘이 동시에 불러도 서로의 픽스처를 파괴하지 않는다.
        if options.get("prune_all_namespaces"):
            self.stdout.write(self.style.SUCCESS(f"pruned {self._prune_all_namespaces()} contests"))
            return

        namespace = (options.get("namespace") or "").strip()
        if namespace and not _NAMESPACE_RE.match(namespace):
            raise CommandError(
                f"--namespace 는 소문자 영숫자 1~16자여야 한다(받은 값: {namespace!r}). "
                "이 토큰은 username 과 title 에 그대로 실리므로, 공백이나 구분자가 섞이면 "
                "접두어 비교가 다른 네임스페이스를 잡아먹고 길면 username 길이 제한을 넘긴다."
            )
        self.namespace = namespace
        self.prefix = f"[E2E-{namespace}] " if namespace else DEFAULT_PREFIX

        self._cleanup()

        sponsor = self._seed_sponsor()
        # 삭제하고 다시 만들지 않고 **제자리에서 맞춤다**(_cleanup 주석 참고). 기준데이터라
        # 이름이 고정이고, 유지해두면 다른 스펙이 런타임에 만든 Contest 가 이것들을
        # 참조하고 있어도 시드가 깨지지 않는다.
        category_lifestyle, _ = Category.objects.get_or_create(name=f"{self.prefix}라이프스타일")
        category_productivity, _ = Category.objects.get_or_create(name=f"{self.prefix}생산성")
        web_service, _ = DeliverableType.objects.update_or_create(
            name=f"{self.prefix}웹 서비스", defaults={"minimum_prize": 2_000_000}
        )
        mobile_app, _ = DeliverableType.objects.update_or_create(
            name=f"{self.prefix}모바일 앱", defaults={"minimum_prize": 1_500_000}
        )

        now = timezone.now()

        funded = self._create_contest(
            sponsor=sponsor,
            title=f"{self.prefix}알림 앱 리디자인",
            category=category_lifestyle,
            deliverable_types=[web_service],
            # **설명은 마크다운으로 그려진다**(2026-09-16, `@codemit/markdown`) — 그래서
            # 시드도 마크다운으로 심는다. 제목·목록·인라인 코드·코드블록을 한 줄씩
            # 넣어 두면, 공개 상세가 **서버에서** 그 태그를 만들었는지를 e2e 가 JS 없이
            # 확인할 수 있다(ADR-0015, CLAUDE.md 「남길 것」1번).
            description=(
                "## 알림 앱 리디자인\n\n"
                "기존 알림 앱의 UI 를 다시 그리는 공모전입니다.\n\n"
                "- 다크모드가 있어야 합니다\n\n"
                "실행은 `pnpm dev` 한 줄입니다.\n\n"
                "```ts config.ts\nexport const theme = \"dark\";\n```\n"
            ),
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
            title=f"{self.prefix}러닝 크루 기록 앱",
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
            title=f"{self.prefix}마감된 공모전",
            category=category_lifestyle,
            deliverable_types=[web_service],
            # #227 이후: 공개 상세에는 계속 남지만, 기본 목록(GET /api/contests)
            # 에서는 빠지고 ?closed=true 로만 나온다 — "공개 목록·상세에 남아야
            # 한다"던 예전 문장은 상세에만 해당한다.
            description="이미 마감되었지만 공개 상세에는 계속 남아야 하는 공모전입니다.",
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
            title=f"{self.prefix}드래프트 공모전",
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
            title=f"{self.prefix}심사 비교용 공모전",
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
            self._account("e2e-judging-developer-a"), f"{self.prefix}심사 개발자 A"
        )
        developer_b = self._seed_named_developer(
            self._account("e2e-judging-developer-b"), f"{self.prefix}심사 개발자 B"
        )

        # Submission A — 필수 Requirement 에 Evidence 가 연결돼 있다(칸이
        # "충족·증거 있음"으로 즉시 구분돼야 한다). Evidence 의 value 는
        # source_location 이라도 소스 내 "위치 포인터"일 뿐 소스 내용 자체가
        # 아니므로 노출해도 된다(submissions.schemas.EvidenceOut 이 이미 그렇게
        # 설계돼 있다) — source_object_key(전체 소스) sentinel 과는 다른 것을
        # 분명히 하려고 일부러 같은 테스트에서 둘 다 심는다.
        submission_a = ContestSubmission.objects.create(
            user=developer_a.user,
            product=Submission.Product.CONTEST,
            contest=judging,
            developer=developer_a,
        )
        SubmissionAsset.objects.create(
            submission=submission_a,
            kind=SubmissionAsset.Kind.SOURCE,
            value=JUDGING_SOURCE_SENTINEL_A,
        )
        SubmissionAsset.objects.create(
            submission=submission_a,
            kind=SubmissionAsset.Kind.DEMO_URL,
            value="https://example.invalid/e2e-judging-demo-a",
            test_account=JUDGING_TEST_ACCOUNT_SENTINEL,
        )
        response_a_required = RequirementResponse.objects.create(
            submission=submission_a,
            requirement=judging_required_req,
            is_met=True,
            note=f"{self.prefix}로그인 폼과 세션 발급을 구현했습니다.",
        )
        Evidence.objects.create(
            response=response_a_required,
            kind=Evidence.Kind.SOURCE_LOCATION,
            value="src/auth/login.ts",
        )
        # 시연 영상 링크(#910) — 유튜브(임베드)와 그 밖의 링크(새 창), 확인 위치가 각각을 가리킨다.
        video_youtube = SubmissionAsset.objects.create(
            submission=submission_a,
            kind=SubmissionAsset.Kind.VIDEO_LINK,
            value="https://youtu.be/dQw4w9WgXcQ",
            label="유튜브 시연",
            order=1,
        )
        video_other = SubmissionAsset.objects.create(
            submission=submission_a,
            kind=SubmissionAsset.Kind.VIDEO_LINK,
            value="https://videos.example.invalid/e2e-demo",
            label="다른 사이트 시연",
            order=2,
        )
        Evidence.objects.create(
            response=response_a_required,
            kind=Evidence.Kind.VIDEO_TIMESTAMP,
            value="01:23",
            asset=video_youtube,
        )
        Evidence.objects.create(
            response=response_a_required,
            kind=Evidence.Kind.VIDEO_TIMESTAMP,
            value="00:10",
            asset=video_other,
        )
        RequirementResponse.objects.create(
            submission=submission_a, requirement=judging_optional_req, is_met=False, note=""
        )

        # Submission B — 두 Requirement 모두 자가 응답 자체가 없다. "증거가 없는
        # 칸이 즉시 구분된다"는 인수조건은 Evidence 만 비어있는 경우와, 응답
        # 자체가 없는 경우를 둘 다 커버해야 한다.
        submission_b = ContestSubmission.objects.create(
            user=developer_b.user,
            product=Submission.Product.CONTEST,
            contest=judging,
            developer=developer_b,
        )
        SubmissionAsset.objects.create(
            submission=submission_b,
            kind=SubmissionAsset.Kind.SOURCE,
            value=JUDGING_SOURCE_SENTINEL_B,
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
            prompt=f"{self.prefix}fake prompt",
            reasoning=[
                {
                    "requirement_id": judging_required_req.id,
                    "is_met": True,
                    "reasoning": f"{self.prefix}fake reasoning",
                }
            ],
        )

        # 완성도(#884·#904) — 심사 화면의 「완성도」 열(A 1.2 / 3점, B 2.6 / 3점)·「완성도순」 정렬을 e2e 가 본다. 서버 순서(id)와
        # 완성도 순서가 거꾸로 되게 A 를 낮게, B 를 높게 심는다(B 에도 Score 를 둔다 — 완성도는 Score 가
        # 있는 제출에만 생긴다).
        Score.objects.create(
            submission=submission_b,
            percentage=Decimal("0.00"),
            model_version=JUDGING_SCORE_MODEL_SENTINEL,
            prompt=f"{self.prefix}fake prompt",
            reasoning=[
                {
                    "requirement_id": judging_required_req.id,
                    "is_met": False,
                    "reasoning": f"{self.prefix}fake reasoning",
                }
            ],
        )
        quality_items = requirement_inputs([judging_required_req, judging_optional_req])
        for submission, (required_score, optional_score) in ((submission_a, (2, 2)), (submission_b, (5, 3))):
            scores = [
                QualityItemScore(
                    item_id=item.item_id,
                    label=item.label,
                    required=item.required,
                    score=value,
                    reasoning=f"{self.prefix}{item.label} 완성도 근거",
                )
                for item, value in zip(quality_items, (required_score, optional_score), strict=True)
            ]
            scored = records(scores)
            total = quality_total(scored, {item.item_id: item.points for item in quality_items})
            SubmissionQualityReview.objects.create(
                submission=submission,
                checklist_fingerprint=checklist_fingerprint(quality_items),
                model_version="e2e-quality-fake",
                prompt=f"{self.prefix}fake quality prompt",
                items=scored,
                **historical_columns(total),
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
        archived = ContestSubmission.objects.create(
            user=developer.user,
            product=Submission.Product.CONTEST,
            contest=closed,
            developer=developer,
        )
        SubmissionAsset.objects.create(
            submission=archived,
            kind=SubmissionAsset.Kind.SOURCE,
            value=SENSITIVE_SOURCE_OBJECT_KEY,
        )
        SubmissionAsset.objects.create(
            submission=archived,
            kind=SubmissionAsset.Kind.DEMO_VIDEO,
            value=f"{self.prefix}demo-video/deadbeefdeadbeefdeadbeefdeadbeef",
        )
        SubmissionAsset.objects.create(
            submission=archived,
            kind=SubmissionAsset.Kind.DEMO_URL,
            value="https://example.invalid/e2e-archived-demo",
            test_account=SENSITIVE_TEST_ACCOUNT,
        )
        # 아직 마감되지 않은 Contest 에 낸 Submission — 프로필에 나타나면 안 된다.
        ongoing = ContestSubmission.objects.create(
            user=developer.user,
            product=Submission.Product.CONTEST,
            contest=funded,
            developer=developer,
        )
        SubmissionAsset.objects.create(
            submission=ongoing,
            kind=SubmissionAsset.Kind.SOURCE,
            value=SENSITIVE_SOURCE_OBJECT_KEY.replace("deadbeef", "cafebabe", 1),
        )
        # `test_account` 는 데모 URL 자료에 붙는다(#190) — 진행 중 Submission 에도
        # sentinel 이 하나 있어야 "진행 중인 것은 프로필에 안 나온다" 를 그 값으로
        # 확인할 수 있다.
        SubmissionAsset.objects.create(
            submission=ongoing,
            kind=SubmissionAsset.Kind.DEMO_URL,
            value="https://example.invalid/e2e-ongoing-demo",
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
        bulk_count = options.get("bulk") or 0
        if bulk_count > 0:
            payload["bulk"] = self._seed_bulk(sponsor, web_service, count=bulk_count)

        write_stdout_utf8(self.stdout, json.dumps(payload, ensure_ascii=False) + "\n")

    def _seed_bulk(self, sponsor, deliverable_type, *, count: int) -> dict:
        """전용 Category 에 공개 Contest 를 count 건 심는다 (#39).

        왜 필요한가 — 예전 프론트는 목록 전체를 한 번에 받아와 직접 걸렀고, 그
        방식은 공개 Contest 가 한 번에 받을 수 있는 수(ninja 의 max page size,
        기본 100)를 넘는 순간 뒤쪽을 **조용히 누락**했다. 그 실패를 UI 로 재현하려면
        그 천장을 실제로 넘겨야 한다.

        상금은 인덱스와 함께 내려가고 마감은 올라간다 — 그래서 상금순 첫 페이지와
        마지막 페이지에 무엇이 와야 하는지가 코드가 아니라 **구성으로** 정해진다
        (테스트가 정렬 로직을 그대로 다시 계산하지 않는다).
        """

        category, _ = Category.objects.get_or_create(name=f"{self.prefix}대량")
        now = timezone.now()

        contests = Contest.objects.bulk_create(
            [
                Contest(
                    sponsor=sponsor,
                    title=f"{self.prefix}대량 {i:04d}",
                    category=category,
                    description="목록 페이지네이션 재현용 Contest 입니다.",
                    prize=10_000_000 - i,
                    deadline_at=now + timedelta(days=1, minutes=i),
                    status=Contest.Status.PUBLISHED,
                )
                for i in range(count)
            ]
        )
        through = Contest.deliverable_types.through
        through.objects.bulk_create(
            [through(contest_id=c.id, deliverabletype_id=deliverable_type.id) for c in contests]
        )

        return {
            "category": category.name,
            "category_id": category.id,
            "count": count,
            # 상금순 정렬의 양 끝. 마지막 항목이 예전 구조에서 조용히 사라지던
            # 바로 그 자리다(천장 너머).
            "highest_prize_title": contests[0].title,
            "lowest_prize_title": contests[-1].title,
        }

    def _prune_all_namespaces(self) -> int:
        """네임스페이스와 무관하게 이 명령 계열이 만든 것을 전부 지운다 (#104).

        워커별 정리(`_cleanup`)는 일부러 자기 범위만 지운다 — 그래야 옆 워커를
        파괴하지 않는다. 그 대가로 **아무도 걷지 않는 것**이 생긴다: 죽은 워커가
        남긴 네임스페이스, 그리고 런타임에 Contest 를 만드는 스펙들이 쓰는
        `[E2E] ` 접두어. 접두어가 없던 시절 그것들이 쌓여 목록 페이지네이션
        스펙이 조용히 깨진 적이 있다(16건까지 쌓인 것을 확인했다).

        그래서 스위트 시작 전에 한 번만 이 경로로 전부 걷는다 — 그 시점에는
        워커가 아직 없어 경합이 성립하지 않는다.
        """

        # `[E2E] ` 와 `[E2E-w0] ` 를 함께 잡는 공통 조각. Award 를 먼저 지운다 —
        # `Award.submission` 이 PROTECT 라 Contest 부터 지우면 막힌다.
        stem = "[E2E"
        Award.objects.filter(contest__title__startswith=stem).delete()
        # `Score.submission` 도 이제 PROTECT 다(#240) — `handle` 안 심사 픽스처(judging)가
        # `Score.objects.create(...)`로 실제 Score 를 심으므로 먼저 지우지 않으면 Contest
        # 삭제가 `ProtectedError` 로 막힌다. 이 픽스처의 Score 는 이름 접두어로 격리된 이
        # 명령 자신의 재현 가능한 시드 데이터일 뿐이라 지워도 ADR-0006 이 지키려는
        # 실데이터 감사 추적에 해당하지 않는다 — `hard_delete_e2e_fixture_rows`가 그
        # 좁은 우회를 명시적으로 허락한다.
        hard_delete_e2e_fixture_rows(Score.objects.filter(submission__contestsubmission__contest__title__startswith=stem))
        removed, _ = Contest.objects.filter(title__startswith=stem).delete()
        # **`e2e-` 로 뭉뚱그리지 않는다.** 그렇게 하면 운영자 시드가 만든 계정까지
        # 잡히는데, 그 계정들은 `AppealRuling.ruled_by`·`PolicyChange.operator` 가
        # PROTECT 로 잡고 있어 삭제가 통째로 막힌다(실제로 겪었다). 이 명령이 만드는
        # 다섯 계정만, 네임스페이스 접미가 붙은 것까지 함께 고른다.
        account_filter = Q()
        for base in _SEEDED_ACCOUNT_BASES:
            account_filter |= Q(username=base) | Q(username__startswith=f"{base}-")
        get_user_model().objects.filter(account_filter).delete()
        return removed

    def _account(self, base: str) -> str:
        """계정 이름도 네임스페이스로 가른다 (#104).

        `username` 은 unique 라, 네임스페이스를 안 가르면 두 번째 워커의 시드가
        `IntegrityError` 로 터진다. title 접두어와 같은 토큰을 쓴다 — 정리할 때
        「이 네임스페이스의 계정」을 접두어 하나로 고를 수 있어야 한다.
        """

        return f"{base}-{self.namespace}" if self.namespace else base

    def _cleanup(self) -> None:
        # Award.submission 은 on_delete=PROTECT 다(awards/models.py) — Django의
        # delete collector 는 "그 Award 자체도 이번 삭제로 함께 사라진다"는 걸
        # 감안하지 않고 PROTECT 를 만나는 즉시 막는다. FE-11(#36) e2e 가 실제로
        # POST /award 를 호출해 Award 행을 만들기 시작한 뒤로(judging-compare.spec.ts
        # 의 "Sponsor 본인은 Award할 수 있다" 테스트), Contest 를 삭제하기 전에
        # 그 Contest 에 걸린 Award 를 먼저 지워야 한다 — Handover.award 는 CASCADE
        # 라 Award 를 지우면 함께 정리된다.
        Award.objects.filter(contest__title__startswith=self.prefix).delete()
        # `Score.submission` 도 PROTECT 다(#240, 위 `_prune_all_namespaces` 와 같은 이유) —
        # 심사 픽스처가 실제 Score 를 심으므로 Contest 를 지우기 전에 먼저 지운다.
        hard_delete_e2e_fixture_rows(
            Score.objects.filter(submission__contestsubmission__contest__title__startswith=self.prefix)
        )
        # 다른 스펙이 런타임에 만드는 Contest(submit/upload/grill)도 제목에 이 접두어를
        # 달아 여기서 함께 정리된다(#39). 접두어가 없던 시절에는 스위트를 돌릴 때마다
        # 쌓이기만 해서, 목록이 페이지네이션되기 시작하면 시드 Contest 가 1페이지 밖으로
        # 밀려나 스펙이 조용히 깨졌다 — 실제로 "제출 폼 데모용 Contest" 가 16건까지
        # 쌓인 것을 확인했다.
        Contest.objects.filter(title__startswith=self.prefix).delete()
        # Category 와 DeliverableType 은 **지우지 않는다** — 지우려고 했다가 이
        # 명령이 통째로 죽었다. Contest.category 는 on_delete=PROTECT 인데,
        # submit/upload/grill 스펙은 자기 Contest 를 **런타임에** 만들면서 이
        # "[E2E]" 기준데이터를 재사용한다. 그 Contest 들은 제목에 접두어가
        # 없어 위의 Contest 삭제에 걸리지 않으므로, 다음 시드 실행이
        # Category 를 지우려는 순간 ProtectedError 로 명령 전체가 죽는다 —
        # 그러면 JSON 이 안 나오고 e2e 가 엉뚱한 id 로 404 를 맞는다.
        # 실제로 같은 DB 에 스위트를 두 번째 돌릴 때부터 깨졌다(1회차 초록,
        # 2회차 7개 실패, 3회차 10개 실패 — 런타임 Contest 가 쌓일수록 악화).
        #
        # 기준데이터는 이름이 고정이라 삭제할 이유가 애초에 없다 — 위에서
        # get_or_create/update_or_create 로 제자리에서 맞춘다. 멱등성은 그대로고,
        # "접두어 없는 실데이터는 절대 건드리지 않는다"는 약속도 그대로 지킨다.
        # 계정도 이 네임스페이스의 것만 지운다 (#104) — 이름을 하나씩 나열하는 대신
        # `_account` 가 붙이는 접두어로 고른다. 그래야 이름이 하나 늘어도 정리에서
        # 빠지는 일이 없고, 다른 워커의 계정을 건드리지 않는다.
        get_user_model().objects.filter(
            username__in=[self._account(base) for base in _SEEDED_ACCOUNT_BASES]
        ).delete()

    def _seed_sponsor(self) -> SponsorProfile:
        # 이메일도 네임스페이스를 따른다(2026-09-16, ADR-0049) — 비어 있지 않은
        # 계정 이메일은 유일해서, 고정 주소로 두면 두 번째 네임스페이스의 시드가
        # 유일 제약에 걸려 죽는다(아래 두 시드가 이미 쓰던 방식과 같게 맞췄다).
        username = self._account("e2e-seed-sponsor")
        user = get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.invalid",
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

        login_seed = self._account(JUDGING_SPONSOR_LOGIN_SEED)
        user = get_user_model().objects.create_user(
            username=login_seed, email=f"{login_seed}@example.test"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        SocialAccount.objects.create(
            user=user,
            provider=SocialAccount.Provider.KAKAO,
            provider_uid=login_seed,
            email=f"{login_seed}@example.test",
        )
        return SponsorProfile.objects.create(user=user, display_name=f"{self.prefix}심사 스폰서")

    def _seed_developer(self) -> DeveloperProfile:
        return self._seed_named_developer(
            self._account("e2e-seed-developer"),
            f"{self.prefix}개발자",
            bio=f"{self.prefix}자기소개 — SSR 로 색인되어야 하는 공개 프로필입니다.",
        )

    def _seed_named_developer(
        self, username: str, display_name: str, *, bio: str = ""
    ) -> DeveloperProfile:
        user = get_user_model().objects.create_user(
            username=username, email=f"{username}@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        # **SocialAccount 를 함께 심는다** — 심사 Sponsor 에 대해 이미 하고 있던
        # 것을 Developer 에게도 한다(#74). `accounts.api.social_login` 이
        # (provider, provider_uid) 로만 사용자를 찾으므로, provider_uid 를 로그인
        # seed 문자열과 같게 두면 e2e 가 그 seed 로 로그인했을 때 바로 이 계정이
        # 된다.
        #
        # 이게 없으면 **제출을 가진 Developer 로 로그인할 방법이 없다** — 「내 참가
        # 현황」·이의 제기·지급처럼 Developer 본인의 화면은 전부 그 상태를
        # 필요로 하는데, 매번 UI 로 개최·결제·제출을 다시 걷는 것은 그 화면이
        # 검증하려는 것과 무관한 비용이다.
        SocialAccount.objects.create(
            user=user,
            provider=SocialAccount.Provider.KAKAO,
            provider_uid=username,
            email=f"{username}@example.invalid",
        )
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
            "category_id": contest.category_id,
            "is_underfunded": contest.is_underfunded,
            "required_minimum_prize": contest.required_minimum_prize,
            "deliverable_types": [dt.name for dt in contest.deliverable_types.all()],
            "deliverable_type_ids": [dt.id for dt in contest.deliverable_types.all()],
            "requirements": [
                {"text": r.text, "grade": r.grade}
                for r in contest.requirements.all().order_by("order", "id")
            ],
            # #106 — 이 호출 시점의 실제 Submission 수. 호출부(handle)가 이
            # Contest 에 낼 Submission 을 전부 심은 뒤에 _serialize 를 부르므로
            # 여기서 다시 세면 GET /api/contests/{id} 가 낸 submission_count 와
            # 같은 값이 나와야 한다 — frontend/e2e 가 그 일치를 그대로 단언한다.
            "submission_count": contest.submissions.count(),
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
        submission_a: ContestSubmission,
        submission_b: ContestSubmission,
        developer_a: DeveloperProfile,
        developer_b: DeveloperProfile,
    ) -> dict:
        return {
            "id": contest.id,
            "title": contest.title,
            # frontend/e2e 가 이 seed 로 fake 로그인하면 이 Contest 의 진짜
            # Sponsor 로 귀결된다(_seed_judging_sponsor 참고) — "본인만 Award 할
            # 수 있다"를 검증하려면 진짜 Sponsor 로 로그인해야 하기 때문이다.
            "sponsor_login_seed": contest.sponsor.user.username,
            # Developer 본인의 화면(#74)이 "이 Contest 에 제출을 가진 개발자" 로
            # 로그인할 수 있게 한다 — provider_uid 를 username 과 같게 심어 뒀다.
            # **문자열을 따로 적지 않고 객체에서 꺼낸다** — 적어 두면 시드가 쓰는
            # 개발자가 바뀌었을 때 조용히 다른 사람으로 로그인하게 된다.
            "developer_login_seed": developer_a.user.username,
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

