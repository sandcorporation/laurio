"""staging 의 홈 큐레이션을 실제 데이터로 채우는 데모 시드 (#52, spec #92).

**왜 필요한가** — staging 이 떴는데 홈의 네 묶음(진행중·마감임박·심사중·완료)이
전부 「아직 없습니다」였다. 코드가 틀린 게 아니라 DB 에 공모전이 없어서인데,
그 상태로는 큐레이션이 실제로 어떻게 보이는지·묶음 배정이 맞는지를 눈으로
확인할 수 없다. #94 의 인수조건은 "빈 묶음도 깨지지 않고 보인다"였지 "전부
비어 있다"가 아니다.

**왜 e2e 시드를 재사용하지 않는가** — `seed_e2e_contests` 는 Playwright 스펙이
파싱하는 JSON 을 뱉고, 그 스펙들이 단언하는 정확한 문자열·상태를 고정한다.
데모용으로 하나 더 넣거나 마감을 옮기는 순간 e2e 가 깨진다. 목적이 다른 두
시드를 한 명령에 합치면 둘 다 못 쓰게 된다.

**정상 개최 플로우를 타지 않는 이유** — 그 경로는 본인확인·Sponsor 인증·결제를
전부 통과해야 하는데, staging 의 결제 어댑터는 실물(토스 샌드박스)이다. 데모
데이터를 만들자고 샌드박스 결제를 여러 건 일으키는 것은 목적과 무관한 비용이고,
실패하면 원인이 시드인지 결제인지 갈리지 않는다. ORM 으로 상태를 직접 만든다.

**멱등하다** — `[데모]` 접두어가 붙은 것만 지우고 다시 만든다. 접두어가 없는
실데이터는 건드리지 않는다(`seed_e2e_contests` 의 `[E2E]` 규율 그대로).

**production 에서는 거부한다.** staging 은 검증용 서브 호스트지만 production 은
아니다 — 홈에 가짜 공모전이 실려 나가는 것은 되돌리기 어려운 종류의 사고다.
"""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from contests.curation import HomeCurationBucket, home_bucket_for
from contests.models import Category, Contest, DeliverableType, Requirement
from submissions.models import Submission

PREFIX = "[데모] "

# 각 묶음에 몇 개씩 보일지. 카드가 하나만 있으면 "목록"으로 보이지 않고, 너무
# 많으면 스크롤만 길어진다.
_DEMO_CONTESTS = [
    # (제목, 카테고리, 요구형태, 상금, 마감까지, 상태, 기대 묶음)
    (
        "동네 반려동물 산책 메이트 앱",
        "라이프스타일",
        "모바일 앱",
        3_000_000,
        timedelta(days=24),
        Contest.Status.PUBLISHED,
        HomeCurationBucket.ONGOING,
    ),
    (
        "소상공인 재고 관리 웹 서비스",
        "라이프스타일",
        "웹 서비스",
        2_500_000,
        timedelta(days=17),
        Contest.Status.PUBLISHED,
        HomeCurationBucket.ONGOING,
    ),
    (
        "초등 코딩 학습 게임",
        "교육",
        "웹 서비스",
        1_800_000,
        timedelta(days=9),
        Contest.Status.PUBLISHED,
        HomeCurationBucket.ONGOING,
    ),
    (
        "인디 밴드 공연 예매 랜딩",
        "엔터테인먼트",
        "랜딩·원페이지",
        600_000,
        timedelta(days=2),
        Contest.Status.PUBLISHED,
        HomeCurationBucket.IMMINENT,
    ),
    (
        "스터디 카페 좌석 현황 관리자 페이지",
        "교육",
        "관리자 페이지",
        1_200_000,
        timedelta(hours=20),
        Contest.Status.PUBLISHED,
        HomeCurationBucket.IMMINENT,
    ),
    (
        "협동조합 조합원 투표 웹 서비스",
        "라이프스타일",
        "웹 서비스",
        2_000_000,
        timedelta(days=-2),
        Contest.Status.CLOSED,
        HomeCurationBucket.IN_JUDGING,
    ),
    (
        "로컬 맛집 지도 모바일 앱",
        "라이프스타일",
        "모바일 앱",
        2_800_000,
        timedelta(days=-5),
        Contest.Status.CLOSED,
        HomeCurationBucket.IN_JUDGING,
    ),
    # **완료 묶음의 마감은 최근이어야 한다.** staging 에는 celery beat 가 돌고,
    # 배분 스캔이 `JUDGING_ENDED` 이면서 `judging_ends_at` 이 정책의
    # `distribution_wait_days`(기본 14일)만큼 지난 Contest 를 집는다
    # (`distributions.services.distribution_due_q`). 데모를 「한 달 전에 끝난
    # 공모전」으로 심으면 그 스캔이 결제도 수상자도 없는 Contest 로 배분을
    # 만들려 들어 60초마다 실패한다 — 데모가 실물 돈 경로를 건드리게 된다.
    #
    # `judging_ends_at` 을 하루 전으로 두면 어떤 정책값에서도 안전하다
    # (`distribution_wait_days >= 1` 이 DB 제약이다). 홈의 묶음 배정은 상태로
    # 결정되므로 날짜를 당겨도 「완료」에 그대로 남는다.
    (
        "보드게임 룰 검색 서비스",
        "게임",
        "웹 서비스",
        1_500_000,
        timedelta(days=-8),
        Contest.Status.AWARDED,
        HomeCurationBucket.COMPLETED,
    ),
    (
        "학원 수강생 출결 관리자 페이지",
        "교육",
        "관리자 페이지",
        1_000_000,
        timedelta(days=-8),
        Contest.Status.JUDGING_ENDED,
        HomeCurationBucket.COMPLETED,
    ),
]

# 마감된 Contest 에 붙일 제출. **완료 묶음이 비어 있지 않아야 발주자에게 설득이
# 된다** — 제출 없는 공모전은 "사람들이 실제로 참여하고 끝까지 간다"를 보여주지
# 못한다(spec #92 의 큐레이션 근거).
_DEMO_DEVELOPERS = ["김하늘", "이준서", "박서연"]


class Command(BaseCommand):
    help = "staging 데모용 — 홈 큐레이션 네 묶음을 채울 공개 Contest 를 멱등하게 심는다."

    def add_arguments(self, parser) -> None:
        parser.add_argument(
            "--clear",
            action="store_true",
            help="데모 데이터를 지우기만 하고 새로 심지 않는다.",
        )

    @transaction.atomic
    def handle(self, *args, **options) -> None:
        if settings.IS_PRODUCTION_DEPLOYMENT:
            raise CommandError(
                "production 에서는 데모 시드를 돌리지 않는다 — 홈에 가짜 공모전이 실려 나간다."
            )

        removed = self._clear()
        if options["clear"]:
            self.stdout.write(self.style.SUCCESS(f"seed_demo_contests: Contest -{removed}"))
            return

        now = timezone.now()
        sponsor = self._demo_sponsor()
        developers = [self._demo_developer(name) for name in _DEMO_DEVELOPERS]

        counts: dict[str, int] = {}
        for title, category_name, type_name, prize, offset, status, expected in _DEMO_CONTESTS:
            contest = self._create_contest(
                sponsor=sponsor,
                title=title,
                category_name=category_name,
                type_name=type_name,
                prize=prize,
                deadline_at=now + offset,
                status=status,
                now=now,
            )

            # 마감된 것에는 제출을 붙인다 — 심사중·완료 묶음이 실제로 무언가
            # 일어난 것처럼 보여야 한다.
            if status != Contest.Status.PUBLISHED:
                for index, developer in enumerate(developers[: 2 + (contest.id % 2)]):
                    Submission.objects.create(
                        contest=contest,
                        developer=developer,
                        source_object_key=f"submission:demo:{contest.id}/{index}",
                        demo_url=f"https://demo.laurio.invalid/{contest.id}/{index}",
                    )

            # **심은 것이 의도한 묶음에 실제로 들어가는지 여기서 확인한다.**
            # 시드가 조용히 엉뚱한 묶음을 채우면 화면을 봐도 무엇이 틀렸는지
            # 알 수 없다 — 판정은 `home_bucket_for` 하나뿐이므로 그것에 물어본다.
            actual = home_bucket_for(contest, now=now)
            if actual != expected:
                raise CommandError(
                    f"'{title}' 이 기대한 묶음({expected})이 아니라 {actual} 에 들어갔다 — "
                    "시드의 마감·상태 조합이 큐레이션 판정과 어긋난다."
                )
            counts[str(actual)] = counts.get(str(actual), 0) + 1

        summary = ", ".join(f"{bucket} {count}건" for bucket, count in sorted(counts.items()))
        self.stdout.write(self.style.SUCCESS(f"seed_demo_contests: {summary}"))

    def _clear(self) -> int:
        removed, _ = Contest.objects.filter(title__startswith=PREFIX).delete()
        get_user_model().objects.filter(username__startswith="demo-seed-").delete()
        return removed

    def _demo_sponsor(self) -> SponsorProfile:
        user = get_user_model().objects.create_user(
            username="demo-seed-sponsor", email="demo-seed-sponsor@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return SponsorProfile.objects.create(user=user, display_name=f"{PREFIX}발주자")

    def _demo_developer(self, name: str) -> DeveloperProfile:
        username = f"demo-seed-dev-{abs(hash(name)) % 100000}"
        user = get_user_model().objects.create_user(
            username=username, email=f"{username}@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return DeveloperProfile.objects.create(user=user, display_name=f"{PREFIX}{name}")

    def _create_contest(
        self,
        *,
        sponsor: SponsorProfile,
        title: str,
        category_name: str,
        type_name: str,
        prize: int,
        deadline_at,
        status: str,
        now,
    ) -> Contest:
        # 카테고리·요구형태는 `seed_dev_data` 가 이미 심어 둔 것을 쓴다. staging
        # 에는 그 명령이 돌지 않으므로(dev compose 만 부른다) 없으면 만든다 —
        # 데모 시드가 그것 때문에 멈추면 목적을 잃는다.
        category, _ = Category.objects.get_or_create(name=category_name)
        deliverable_type, _ = DeliverableType.objects.get_or_create(
            name=type_name, defaults={"minimum_prize": 200_000}
        )

        # CLOSED 이후에는 심사기간이 이미 시작돼 있다(#13) — 마감 시각에
        # 정책상의 심사기간을 더한 값이 그 끝이다. 심사중 묶음이 「아직
        # 진행중인 심사」로 보이려면 이 값이 미래여야 한다.
        judging_ends_at = None
        if status == Contest.Status.CLOSED:
            judging_ends_at = max(deadline_at + timedelta(days=7), now + timedelta(days=2))
        elif status in (Contest.Status.AWARDED, Contest.Status.JUDGING_ENDED):
            judging_ends_at = deadline_at + timedelta(days=7)

        contest = Contest.objects.create(
            sponsor=sponsor,
            title=f"{PREFIX}{title}",
            category=category,
            description=(
                f"{title} 를 만들 개발자를 찾습니다. "
                "이 공모전은 staging 검증용 데모 데이터입니다 — 실제 발주가 아닙니다."
            ),
            prize=prize,
            deadline_at=deadline_at,
            status=status,
            required_minimum_prize=deliverable_type.minimum_prize,
            is_underfunded=prize < deliverable_type.minimum_prize,
            judging_ends_at=judging_ends_at,
        )
        contest.deliverable_types.set([deliverable_type])
        Requirement.objects.create(
            contest=contest,
            text="로그인과 회원가입이 동작해야 합니다.",
            grade=Requirement.Grade.REQUIRED,
            order=0,
        )
        Requirement.objects.create(
            contest=contest,
            text="모바일 화면에서도 쓸 수 있어야 합니다.",
            grade=Requirement.Grade.OPTIONAL,
            order=1,
        )
        return contest
