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
from awards.models import Award
from contests.curation import HomeCurationBucket, home_bucket_for
from contests.models import Category, Contest, DeliverableType, Requirement
from submissions.models import RequirementResponse, Submission, SubmissionAsset

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

# 참가작을 낼 개발자들. **여럿이어야 한다** — 공개 프로필(`/developers/{id}`)이
# 마감된 참가작을 아카이브해 보여주는데(#11), 한 사람이 전부 낸 것으로 심으면
# 그 화면이 「한 명이 아홉 개 낸 공모전」이 되어 실제와 다른 인상을 준다.
_DEMO_DEVELOPERS = [
    "김하늘",
    "이준서",
    "박서연",
    "최민재",
    "정유진",
    "한지우",
]

# Contest 마다 참가작을 몇 개 붙일지. **진행중인 공모전에도 붙인다** — 참가작이
# 하나도 없는 공모전만 늘어서 있으면 발주자에게 "여기 내면 사람이 온다"가
# 보이지 않는다(spec #92 의 큐레이션 근거). 진행 중에는 소유자·Sponsor 외에는
# 존재 자체가 안 보이지만(ADR-0014), 발주자 콘솔과 마감 이후 화면이 그때
# 비어 있지 않게 된다.
#
# 수를 고정 목록으로 두는 이유 — `contest.id % n` 같은 식으로 정하면 DB 를 새로
# 만들 때마다 id 가 달라져 배치가 바뀐다. 데모는 몇 번을 다시 심어도 같아야
# 스크린샷과 설명이 어긋나지 않는다.
_SUBMISSION_COUNTS = [3, 2, 4, 2, 3, 4, 3, 3, 2]

# 참가작에 붙일 Requirement 응답. 전부 충족으로 심으면 심사 비교 화면의
# 매트릭스가 한 색으로 채워져 그 화면이 무엇을 보여주는지 알 수 없다 — 필수는
# 대체로 충족하고 선택은 갈리게 둔다.
_RESPONSE_NOTES = [
    "구현했습니다. 데모 계정으로 바로 확인하실 수 있습니다.",
    "구현했으나 일부 화면은 아직 다듬는 중입니다.",
    "시간 관계로 이번 제출에는 포함하지 못했습니다.",
]


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
        developers = [self._demo_developer(i, name) for i, name in enumerate(_DEMO_DEVELOPERS)]

        counts: dict[str, int] = {}
        submission_total = 0
        # 참가자를 Contest 마다 한 칸씩 밀어 배정한다 — 매번 앞에서부터 자르면
        # 앞의 두세 명만 참가작을 갖고 뒤의 사람들은 빈 프로필이 된다.
        developer_cursor = 0

        for index, entry in enumerate(_DEMO_CONTESTS):
            title, category_name, type_name, prize, offset, status, expected = entry
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

            wanted = _SUBMISSION_COUNTS[index % len(_SUBMISSION_COUNTS)]
            entrants = [
                developers[(developer_cursor + offset_) % len(developers)]
                for offset_ in range(wanted)
            ]
            developer_cursor += wanted

            submissions = [
                self._create_submission(contest=contest, developer=developer, rank=rank)
                for rank, developer in enumerate(entrants)
            ]
            submission_total += len(submissions)

            # 수상까지 간 공모전에는 Award 가 있어야 한다. **없으면 상태만
            # AWARDED 이고 수상작이 없는 모순**이 되어, 그 Contest 를 여는
            # 화면들이 실제 배포에서는 나올 수 없는 조합을 그린다.
            if status == Contest.Status.AWARDED:
                Award.objects.create(
                    contest=contest,
                    submission=submissions[0],
                    awarded_at=contest.judging_ends_at - timedelta(days=1),
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
        self.stdout.write(
            self.style.SUCCESS(f"seed_demo_contests: {summary} / 참가작 {submission_total}건")
        )

    def _clear(self) -> int:
        # **Award 를 먼저 지운다.** `Award.submission` 은 `on_delete=PROTECT` 인데,
        # Django 의 delete collector 는 "그 Award 자체도 이번 삭제로 함께 사라진다"는
        # 것을 감안하지 않고 PROTECT 를 만나는 즉시 막는다 — Contest 부터 지우면
        # ProtectedError 로 명령 전체가 죽어 멱등성이 깨진다(`seed_e2e_contests`
        # 가 같은 자리에서 이미 한 번 겪었다).
        Award.objects.filter(contest__title__startswith=PREFIX).delete()
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

    def _demo_developer(self, index: int, name: str) -> DeveloperProfile:
        # username 을 이름의 `hash()` 에서 뽑지 않는다 — 파이썬의 문자열 해시는
        # 프로세스마다 무작위라(PYTHONHASHSEED) 같은 시드를 두 번 돌리면 계정
        # 아이디가 달라진다. 데모는 다시 심어도 같아야 한다.
        username = f"demo-seed-dev-{index:02d}"
        user = get_user_model().objects.create_user(
            username=username, email=f"{username}@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        return DeveloperProfile.objects.create(
            user=user,
            display_name=f"{PREFIX}{name}",
            bio=f"{name} 입니다. 웹과 모바일을 주로 만듭니다. (staging 검증용 데모 계정)",
        )

    def _create_submission(
        self, *, contest: Contest, developer: DeveloperProfile, rank: int
    ) -> Submission:
        """참가작 하나 — Requirement 응답까지 함께 붙인다.

        응답이 없으면 심사 비교 화면(#36)의 Requirement 축 매트릭스가 통째로
        비어, 그 화면이 무엇을 보여주는 곳인지 데모에서 알 수 없다.
        """

        submission = Submission.objects.create(contest=contest, developer=developer)
        SubmissionAsset.objects.create(
            submission=submission,
            kind=SubmissionAsset.Kind.SOURCE,
            value=f"submission:demo:{contest.pk}/{rank}/source.zip",
        )
        SubmissionAsset.objects.create(
            submission=submission,
            kind=SubmissionAsset.Kind.DEMO_URL,
            value=f"https://demo.laurio.invalid/{contest.pk}/{rank}",
            test_account="demo@example.invalid / demo1234" if rank % 3 != 2 else "",
        )
        # 영상은 일부만 낸다 — 실제로도 전원이 내지는 않는다.
        if rank % 2 == 0:
            SubmissionAsset.objects.create(
                submission=submission,
                kind=SubmissionAsset.Kind.DEMO_VIDEO,
                value=f"submission:demo:{contest.pk}/{rank}/demo.mp4",
            )

        for requirement in contest.requirements.all().order_by("order", "id"):
            # 필수는 대체로 충족하고 선택은 갈린다 — 전부 충족으로 심으면
            # 매트릭스가 한 색이 되어 비교 화면이 아무것도 말하지 않는다.
            if requirement.grade == Requirement.Grade.REQUIRED:
                is_met = rank % 4 != 3
            else:
                is_met = rank % 2 == 0
            note_index = 0 if is_met else 2
            if is_met and rank % 3 == 1:
                note_index = 1
            RequirementResponse.objects.create(
                submission=submission,
                requirement=requirement,
                is_met=is_met,
                note=_RESPONSE_NOTES[note_index],
            )

        return submission

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
