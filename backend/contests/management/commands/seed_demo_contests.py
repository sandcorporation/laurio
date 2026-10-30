"""dev 의 홈 큐레이션을 실제 데이터로 채우는 데모 시드 (#52, spec #92).

**왜 필요한가** — 옛 staging 이 떴는데 홈의 네 묶음(진행중·마감임박·심사중·완료)이
전부 「아직 없습니다」였다. 코드가 틀린 게 아니라 DB 에 공모전이 없어서인데,
그 상태로는 큐레이션이 실제로 어떻게 보이는지·묶음 배정이 맞는지를 눈으로
확인할 수 없다. #94 의 인수조건은 "빈 묶음도 깨지지 않고 보인다"였지 "전부
비어 있다"가 아니다.

**왜 e2e 시드를 재사용하지 않는가** — `seed_e2e_contests` 는 Playwright 스펙이
파싱하는 JSON 을 뱉고, 그 스펙들이 단언하는 정확한 문자열·상태를 고정한다.
데모용으로 하나 더 넣거나 마감을 옮기는 순간 e2e 가 깨진다. 목적이 다른 두
시드를 한 명령에 합치면 둘 다 못 쓰게 된다.

**정상 개최 플로우를 타지 않는 이유** — 그 경로는 본인확인·Sponsor 인증·결제를
전부 통과해야 하는데, 배포의 결제 어댑터는 실물이다. 데모
데이터를 만들자고 결제를 여러 건 일으키는 것은 목적과 무관한 비용이고,
실패하면 원인이 시드인지 결제인지 갈리지 않는다. ORM 으로 상태를 직접 만든다.

**멱등하다 — 채점이 돈 뒤에도** (#254, ADR-0064). 지우는 기준은 제목의
`[데모]` 접두어가 아니라 이 시드만 쓰는 표지 `Contest.is_demo_seed` 다 — 표지가 없는
실데이터는 제목이 무엇이든 건드리지 않는다. 데모 Contest 에 매달린 append-only `Score`
는 `scoring.models.hard_delete_demo_seed_scores` 가 그 표지로 범위를 고정한 채 지운다
(production 에서는 그 함수도 이 명령도 거부한다). 조건 하나 — 데모 Submission 을 PROTECT
로 잡는 다른 행(배분 몫·이의 판독 등)이 생기면 지우지 못하고 **무엇이 잡고 있는지를
말하며 거절한다**; 그런 행은 데모가 실물 돈·심판 경로에 들어갔다는 뜻이라 시드가
조용히 지울 물건이 아니다.

**production 에서는 거부한다.** 홈에 가짜 공모전이 실려 나가는 것은 되돌리기 어려운
종류의 사고다.

**데모 Developer·Sponsor 는 VERIFIED 신원을 함께 심는다(#252).** 옛 staging 실측 —
이 시드가 만드는 Developer 는 전원 Verification 이 없어, 데모 계정으로 로그인해도
「내 참여 → 제출물 수정하러 가기」가 본인확인 안내 화면에서 막혔다. 공모전 참가의
중심 화면 하나가 통째로 막혀 있으면 데모의 목적(걸어서 보여주는 것)이 반쯤
무너진다.

무엇을 심을지가 이 티켓의 진짜 판단이었다 — "가짜 신원을 심자"가 아니다.
`Verification`은 암호화된 실명·생년월일·CI/DI 를 담고, 지급·정산 경로
(`payouts.services.ensure_seller_registered`)가 그 값을 그대로 벤더(토스)에
실어 보낸다. 그래서 데모가 필요로 하는 것("제출 화면이 열린다")과 데모가
허락되지 않는 것("지급까지 된다")의 경계를 여기서 정한다:

- **CI 는 채운다 — 비울 수 없다.** `submissions.api._require_verification`은
  `status == VERIFIED`만 보지만, 그 바로 다음에 도는
  `_reject_self_dealing`(자전거래 차단, ADR-0011/0025)은 VERIFIED인데
  `ci_hash`가 비어 있으면 "불변식 위반"으로 보고 fail-closed 403을 던진다 —
  정상 운영에서는 도달 불가능해야 하는 그 경로를 데모가 밟게 된다. CI 없이
  VERIFIED로 두면 제출 화면이 오히려 새로운 방식으로 막힌다. Sponsor 쪽도
  같은 이유로 VERIFIED + CI 가 필요하다 — 없으면 데모 Contest 전체가 이
  가드에 걸려 죽는다.
- **그래도 실제 CI 포맷을 흉내 내지 않는다.** 값을 `demo-seed-ci-` 로 시작하는
  합성 문자열로 짓는다 — 실제 CI(NICE/KMC 가 발급하는 불투명 base64)와 절대
  겹치지 않고, 복호화해서 봐도 데모임이 즉시 드러난다. real_name 도
  "데모"라는 말을 담아 실제 이름으로 오인되지 않게 한다.
- **DI 는 비운다.** 이 저장소에서 `.di`를 읽어 비교하는 코드가 없다(탈퇴·휴면이
  지울 때만 건드린다) — 안 쓰이는 합성 개인정보를 만들 이유가 없다.
- **Seller·Payout·Handover 는 만들지 않는다.** 지급 경로가 이 데모 신원을 써서
  실제 이체를 "시도"하려면 다음 중 하나가 있어야 하는데, 이 시드는 둘 다
  만들지 않는다:
  1. `distributions.services.distribution_due_q`(배분 스캔의 후보) — JUDGING_ENDED
     이면서 `distribution_wait_days` 가 지나야 후보가 된다. 데모의 JUDGING_ENDED
     Contest 는 `judging_ends_at` 을 의도적으로 "하루 전"에 둬서(아래
     `_create_contest`) 이 스캔의 후보가 되지 않는다 — 이미 `test_demo_seed_
     leaves_nothing_for_the_money_scans`가 이걸 고정하고 있었다.
  2. `POST /contests/{id}/payout`(Developer 본인의 명시적 요청) — `Handover`가
     `RELEASED`여야 한다. 데모의 AWARDED Contest 는 `awards.api`(진짜 개최
     플로우)를 거치지 않고 ORM 으로 Award 행만 만들므로 Handover 자체가
     없다 — 지급 요청은 404 로 끝난다.

  즉 VERIFIED 신원은 **제출 화면을 여는 열쇠**일 뿐, 지급·정산 경로로 이어지는
  문(Handover·Seller·Payout)은 이 시드가 애초에 만들지 않는다.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from accounts.models import DeveloperProfile, SponsorProfile
from awards.models import Award
from contests.curation import HomeCurationBucket, home_bucket_for
from contests.models import Category, Contest, ContestSubmission, DeliverableType, Requirement
from contests.submission_target_refs import target_ref_for_asset_kind
from scoring.models import hard_delete_demo_seed_scores
from submissions.models import Evidence, RequirementResponse, Submission, SubmissionAsset
from verification.models import Verification

PREFIX = "[데모] "

# 데모 신원의 생년월일 — 값 자체에 의미는 없고(성인이기만 하면 된다), 모두가 같은
# 값을 쓴다는 사실이 "실제로 조사해서 넣은 값이 아니다"를 스스로 말해준다.
_DEMO_BIRTH_DATE = date(2000, 1, 1)


def _requirement_symbol(requirement) -> str:
    """Requirement 하나가 소스에서 갖는 이름."""

    return f"feature_{requirement.order}"


def _evidence_value(requirement) -> str:
    """근거가 가리키는 소스 위치 — **소스에 문자 그대로 있어야 한다**.

    채점은 근거가 소스에서 실제로 확인되는지를 본다(ADR-0014). dev/test 의 fake
    어댑터는 그것을 「근거 문자열이 소스 텍스트에 등장하는가」로 결정적으로
    흉내내므로, 여기서 지어낸 문구를 쓰면 데모의 모든 요구사항이 「근거를 소스에서
    찾지 못했다」로 미달이 된다 — 실측했다: 채점은 도달하는데 12건 전부 0.00% 였다.

    그래서 값을 소스가 실제로 담는 줄과 **같은 문자열**로 만든다. 시드가 소스와
    근거를 둘 다 만드는 이상, 둘이 어긋나면 그건 데이터가 스스로 모순인 것이다.
    """

    return f"def {_requirement_symbol(requirement)}():"


def _demo_source_bytes(contest, rank: int, met_requirements) -> bytes:
    """데모 제출물의 소스 (#253).

    **읽을 수 있는 내용이어야 한다.** 채점은 이 바이트를 실제로 읽어 Requirement
    별로 판정한다 — 빈 파일이나 뜻 없는 문자열을 심으면 채점이 도달하기는 해도
    전부 미달이 나와, 데모가 보여주는 것이 「채점이 된다」가 아니라 「전부 0점」이
    된다.

    **참가자가 미달이라고 적은 요구사항의 구현은 넣지 않는다.** 넣으면 소스가
    참가자 자신의 응답과 모순된다 — dev 의 fake 어댑터는 근거 문자열만 보므로
    그 모순을 못 보지만, staging 의 실제 LLM 은 소스를 읽고 「구현되어 있다」고
    판정할 수 있다. 그러면 심사·이의 화면에서 참가자의 「미달」 메모와 채점 결과가
    서로 다른 말을 하고, 그 화면들의 존재 이유(같은 것을 보고 이야기한다)가
    무너진다.

    충족이라고 적은 것에는 함수 하나를 두고 이름을 `_requirement_symbol` 로
    맞춘다 — 근거(Evidence)가 가리키는 위치와 소스가 실제로 일치해야 한다.
    """

    met_ids = {r.id for r in met_requirements}
    lines = [
        f"# {contest.title} — 데모 제출물 #{rank}",
        "# staging/dev 데모용으로 생성된 소스입니다. 실제 참가작이 아닙니다.",
        "",
    ]
    for requirement in contest.requirements.all().order_by("order", "id"):
        if requirement.id not in met_ids:
            lines += [
                f"# TODO: {requirement.text} — 아직 구현하지 못했습니다.",
                "",
            ]
            continue
        lines += [
            f"def {_requirement_symbol(requirement)}():",
            f'    """{requirement.text}"""',
            "    # 데모 구현 — 이 요구사항을 만족하는 자리입니다.",
            "    return True",
            "",
        ]
    return "\n".join(lines).encode("utf-8")


def _is_met(requirement, rank: int) -> bool:
    """이 참가작이 그 요구사항을 충족했다고 적는가.

    필수는 대체로 충족하고 선택은 갈린다 — 전부 충족으로 심으면 심사 비교 화면의
    매트릭스가 한 색이 되어 아무것도 말하지 않는다.
    """

    if requirement.grade == Requirement.Grade.REQUIRED:
        return rank % 4 != 3
    return rank % 2 == 0


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
    help = "dev 데모용 — 홈 큐레이션 네 묶음을 채울 공개 Contest 를 멱등하게 심는다."

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
        """표지(`Contest.is_demo_seed`)가 붙은 것만 지운다 (#254, ADR-0064).

        **삭제 기준은 제목이 아니라 표지다.** 제목 접두어로 지우면 사람이 `[데모] ` 로
        시작하는 실제 공모전을 열었을 때 그 행과 그 Score 가 이 시드에 지워진다 — 표지는
        이 시드만 쓰므로(tests/test_seed_demo_contests_reseed.py 가 소스를 훑어 고정한다)
        그 사고가 구조적으로 없다.

        **스토리지 오브젝트는 남는다**(#253). 재시드마다 새 `uuid4` 키를 받으므로
        옛 오브젝트는 아무도 참조하지 않는 채로 버킷에 남는다. 지우려면 스토리지
        포트에 삭제를 더해야 하는데, ADR-0005 는 그 포트를 **의도적으로 좁게**
        유지하기로 정했다 — 시드 청소를 위해 그 경계를 넓히는 것은 그 ADR 이
        경계하는 바로 그 일이다. 데모 오브젝트는 작은 텍스트 몇 개이고(회차당
        20여 개), 버킷 정리는 저장소 밖의 운영 작업으로 둔다.
        """

        # **Award 를 먼저 지운다.** `Award.submission` 은 `on_delete=PROTECT` 인데,
        # Django 의 delete collector 는 "그 Award 자체도 이번 삭제로 함께 사라진다"는
        # 것을 감안하지 않고 PROTECT 를 만나는 즉시 막는다 — Contest 부터 지우면
        # ProtectedError 로 명령 전체가 죽어 멱등성이 깨진다(`seed_e2e_contests`
        # 가 같은 자리에서 이미 한 번 겪었다).
        demo_contests = Contest.objects.filter(is_demo_seed=True)
        Award.objects.filter(contest__in=demo_contests).delete()
        # **Score 도 먼저 지운다** — `Score.submission` 역시 PROTECT 이고(#240), 채점 스캔이
        # 한 번 돌면 마감된 데모 공모전마다 Score 가 생겨 Contest 삭제를 막는다. Score 는
        # append-only 라 `.delete()` 가 거부되므로, 표지로 범위를 고정한 좁은 우회
        # (`hard_delete_demo_seed_scores`)로만 지운다. e2e 시드의 우회
        # (`hard_delete_e2e_fixture_rows`)는 배포 환경에서 거부되므로 여기서 쓸 수 없고,
        # 그 거부를 푸는 것은 #240 이 막은 문을 다시 여는 일이라 하지 않는다.
        hard_delete_demo_seed_scores()
        try:
            removed, _ = demo_contests.delete()
            # 데모 계정은 표지가 붙은 Contest 의 발주자·참가자다 — 사람이 만든 계정은
            # 이 접두어를 갖지 않지만, 그래도 표지가 붙은 Contest 와 묶인 것만 지운다.
            get_user_model().objects.filter(username__in=self._demo_usernames()).delete()
        except ProtectedError as exc:
            # 의도된 거절이다 — Django 내부 예외를 그대로 내보내지 않는다(#254 AC).
            holders = sorted({type(obj).__name__ for obj in exc.protected_objects})
            raise CommandError(
                "데모 데이터를 지울 수 없다 — 데모 Submission 을 PROTECT 로 잡고 있는 행이 "
                f"있다: {', '.join(holders)}. 데모가 실물 돈·심판 경로(배분·이의 판독)에 들어갔다는 "
                "뜻이므로 시드가 조용히 지우지 않는다. 그 행이 왜 생겼는지 먼저 보고, 데모 "
                "데이터가 맞으면 그 행을 만든 경로에서 치운 뒤 다시 돌린다."
            ) from exc
        return removed

    @staticmethod
    def _demo_usernames() -> list[str]:
        """이 시드가 만드는 계정 이름 전부 — 발주자 하나와 참가자들(`_demo_developer` 가
        짓는 이름과 같은 규칙)."""
        return [
            "demo-seed-sponsor",
            *(f"demo-seed-dev-{i:02d}" for i in range(len(_DEMO_DEVELOPERS))),
        ]

    def _demo_verification(self, user, *, ci_seed: str, label: str) -> Verification:
        """VERIFIED 신원 하나 — 모듈 docstring의 경계(CI는 채우되 합성값, DI는
        비움, Seller/Payout/Handover는 만들지 않음)를 그대로 구현한다.

        `Verification.set_ci`는 빈 값을 거부하므로(#84, ADR-0024) 먼저 만든
        뒤 `set_ci`로 채운다 — 모델이 강제하는 "CI 없이 VERIFIED 없다"를
        시드도 그대로 따른다.
        """

        # 암호화 필드(real_name·birth_date·ci)는 프로퍼티라 생성자 kwargs 가 아니라
        # 속성 대입으로 채운다 — `accounts.withdrawal.execute_withdrawal`이 이미
        # 같은 모양으로 `RetainedIdentity`를 만든다.
        verification = Verification(
            user=user,
            status=Verification.Status.VERIFIED,
            verified_at=timezone.now(),
        )
        verification.real_name = f"(데모 시드 가상신원) {label}"
        verification.birth_date = _DEMO_BIRTH_DATE
        verification.set_ci(f"demo-seed-ci-{ci_seed}")
        verification.save()
        return verification

    def _demo_sponsor(self) -> SponsorProfile:
        user = get_user_model().objects.create_user(
            username="demo-seed-sponsor", email="demo-seed-sponsor@example.invalid"
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        self._demo_verification(user, ci_seed="sponsor", label="발주자")
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
        # CI 시드도 username 과 같은 규칙(고정 index) — 다시 심어도 같은 값이어야
        # 데모가 "다시 심을 때마다 같다"는 규율(위 username 주석)이 신원에서도
        # 깨지지 않는다.
        self._demo_verification(user, ci_seed=f"dev-{index:02d}", label=name)
        return DeveloperProfile.objects.create(
            user=user,
            display_name=f"{PREFIX}{name}",
            bio=f"{name} 입니다. 웹과 모바일을 주로 만듭니다. (staging 검증용 데모 계정)",
        )

    def _upload_asset(
        self,
        submission: ContestSubmission,
        *,
        kind: str,
        content_type: str,
        content: bytes,
        label: str,
    ) -> SubmissionAsset:
        """업로드가 실제로 일어난 것처럼 자료 하나를 만든다 (#253).

        **값을 손으로 조립하지 않는다.** 접두어는 쓰기 검증이 쓰는
        `target_ref_for_asset_kind`, 그 뒤는 업로드 발급이 쓰는
        `storage.api.new_object_key` — 둘 다 실제 경로가 쓰는 바로 그 함수다.
        시드가 규칙을 따로 적던 동안 그 값은 **세 곳**에서 걸렸다: 쓰기 검증
        (「본인의 업로드 대상에 속하지 않습니다」), 다운로드의 object_key 패턴,
        그리고 채점(오브젝트가 없어 소스를 못 찾는다). 셋 다 저장·다운로드·채점을
        실제로 해 본 사람만 발견한다.

        **오브젝트도 함께 쓴다.** 값만 맞고 파일이 없으면 채점이 소스를 못 찾아
        재시도하다 상한에 걸리고, 참가자는 「플랫폼이 채점하지 못했다」는 0% 를
        받는다(ADR-0031). staging 실측 — 데모 제출물 14건이 전부 그 상태였다.
        데모가 플랫폼 장애를 전시하고 있었던 셈이다.

        **라벨을 붙인다.** 업로드 자료의 `value` 는 오브젝트 키라 사람이 읽을 것이
        없다 — 근거(Evidence)를 어느 자료에 걸지 고르는 드롭다운은 그 값을 그대로
        보여주므로, 라벨이 없으면 데모에서 그 화면이 16진수 나열이 된다.

        **설정된 어댑터로 쓴다** — 채점이 읽는 것과 같은 어댑터여야 하기
        때문이다(`seed_e2e_operator_queues` 가 같은 이유로 같은 관용구를 쓴다).

        **다만 fake 스토리지는 이 프로세스보다 오래 살지 못한다.**
        `FakeStorageAdapter._store` 는 클래스 딕셔너리라 명령이 끝나면 사라진다 —
        테스트는 같은 프로세스에서 곧바로 읽으니 괜찮지만, 호스트에서 시드만
        돌리고 컨테이너의 backend(=MinIO)가 나중에 채점하면 소스가 없는 것과
        같다. 그게 정확히 이 티켓이 없앤 증상이므로, 그 조합이면 **경고한다** —
        거부하지는 않는다(테스트가 바로 그 조합으로 돈다).
        """

        from storage.adapters import get_storage_adapter
        from storage.api import new_object_key

        self._warn_once_if_storage_is_ephemeral()

        target_ref = target_ref_for_asset_kind(
            kind,
            contest_id=submission.contest_id,
            developer_user_id=submission.developer.user_id,
        )
        object_key = new_object_key(target_ref)
        # content_type 을 **쓰기에도** 넘긴다 — 행에만 남기면 오브젝트는
        # `application/octet-stream` 으로 올라가고, 다운로드 파일명(#241)이
        # 확장자를 고를 근거를 스토리지 쪽에서 잃는다.
        get_storage_adapter().write_object(object_key, content, content_type=content_type)
        return SubmissionAsset.objects.create(
            submission=submission,
            kind=kind,
            value=object_key,
            content_type=content_type,
            label=label,
        )

    def _warn_once_if_storage_is_ephemeral(self) -> None:
        """fake 스토리지에 쓰고 있으면 한 번 경고한다.

        조용히 지나가면 「시드는 성공했는데 나중에 채점만 실패한다」가 되고, 그
        증상은 스토리지 이야기를 어디에도 하지 않는다 — 이 저장소가 이미 한 번
        그 길로 진단을 헤맸다(`CLAUDE.md` 의 `seed_e2e_*` 주의).
        """

        if getattr(self, "_warned_ephemeral_storage", False):
            return
        if (getattr(settings, "STORAGE_BACKEND", "") or "fake") != "fake":
            return
        self._warned_ephemeral_storage = True
        self.stderr.write(
            "경고: STORAGE_BACKEND 가 fake 다 — 방금 쓴 오브젝트는 이 프로세스가 "
            "끝나면 사라진다. 컨테이너의 backend(MinIO)가 이 데모를 채점하게 하려면 "
            "STORAGE_BACKEND=s3 와 접속 정보를 함께 주고 다시 돌려라."
        )

    def _create_submission(
        self, *, contest: Contest, developer: DeveloperProfile, rank: int
    ) -> ContestSubmission:
        """참가작 하나 — Requirement 응답까지 함께 붙인다.

        응답이 없으면 심사 비교 화면(#36)의 Requirement 축 매트릭스가 통째로
        비어, 그 화면이 무엇을 보여주는 곳인지 데모에서 알 수 없다.
        """

        submission = ContestSubmission.objects.create(
            user=developer.user,
            product=Submission.Product.CONTEST,
            contest=contest,
            developer=developer,
        )
        requirements = list(contest.requirements.all().order_by("order", "id"))
        # 소스를 만들기 **전에** 무엇을 충족으로 적을지 정한다 — 소스와 응답이
        # 같은 판정에서 나와야 둘이 서로를 반박하지 않는다.
        met = [r for r in requirements if _is_met(r, rank)]
        source_asset = self._upload_asset(
            submission,
            kind=SubmissionAsset.Kind.SOURCE,
            content_type="text/plain",
            content=_demo_source_bytes(contest, rank, met),
            label="제출 소스 (데모 데이터)",
        )
        SubmissionAsset.objects.create(
            submission=submission,
            kind=SubmissionAsset.Kind.DEMO_URL,
            value=f"https://demo.codemit.invalid/{contest.pk}/{rank}",
            # **링크 텍스트가 곧 이 라벨이다**(#253) — 화면은 `label || "데모 보기"`
            # 로 그린다. `.invalid` 는 예약 TLD라 절대 열리지 않는데(그게 의도다 —
            # 실재하는 남의 사이트를 가리키는 것보다 정직하다), 「데모 보기」라고만
            # 적혀 있으면 누른 사람은 서비스가 깨졌다고 읽는다.
            label="데모 보기 (데모 데이터 — 열리지 않습니다)",
            test_account="demo@example.invalid / demo1234" if rank % 3 != 2 else "",
        )
        # 영상은 일부만 낸다 — 실제로도 전원이 내지는 않는다.
        if rank % 2 == 0:
            self._upload_asset(
                submission,
                kind=SubmissionAsset.Kind.DEMO_VIDEO,
                content_type="video/mp4",
                content=f"demo video placeholder — contest {contest.pk} rank {rank}".encode(),
                label="시연 영상 (데모 데이터)",
            )

        met_ids = {r.id for r in met}
        for requirement in requirements:
            is_met = requirement.id in met_ids
            note_index = 0 if is_met else 2
            if is_met and rank % 3 == 1:
                note_index = 1
            response = RequirementResponse.objects.create(
                submission=submission,
                requirement=requirement,
                is_met=is_met,
                note=_RESPONSE_NOTES[note_index],
            )
            # **충족 주장에는 근거를 붙인다**(#253). 근거 없는 주장은 미달로
            # 채점된다(CONTEXT.md 의 Evidence) — 소스를 제대로 심어 놓고 근거를
            # 빼면 데모의 점수가 전부 0% 로 남는다. 「플랫폼이 채점하지 못했다」가
            # 「참가자가 근거를 안 냈다」로 바뀔 뿐 보이는 것은 똑같다.
            if is_met:
                Evidence.objects.create(
                    response=response,
                    kind=Evidence.Kind.SOURCE_LOCATION,
                    value=_evidence_value(requirement),
                    asset=source_asset,
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
            # 재시드의 삭제 범위이자 Score 하드 삭제의 근거 — 이 자리 말고는 아무도 쓰지 않는다.
            is_demo_seed=True,
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
