"""홈이 공모전을 네 묶음으로 큐레이션할 때 쓰는 판정 (#94, spec #92).

`submissions.participation`(`NextAction`)·`contests.sponsorship`(`SponsorNextAction`)
과 같은 이유로 같은 모양을 쓴다 — 화면이 `Contest.status`와 `deadline_at`에서
직접 재파생하면, 새 상태가 하나 생겼을 때 어느 분기에도 걸리지 않고 조용히 그
부류가 화면에서 사라진다. 이 저장소가 반복해서 겪은 실패 모양이다.

값을 `str`가 아니라 enum(`HomeCurationBucket`)으로 두는 이유도 같다 — 생성된
프론트 타입에 4개짜리 리터럴 유니온이 되고, 값이 하나 늘면 번역표를 가진
파일에서 `tsc --noEmit`이 빌드타임에 잡는다. `NextAction`이 #74의 `can_appeal`
누락을, `SponsorNextAction`이 #81의 `no_submissions` 누락을 이 방식으로 잡았다.

이 모듈은 조회를 내지 않는다. `contest`는 호출부가 이미 가져온 것을 그대로
받는다 — 행마다 조회를 내면 홈 하나가 N+1이 된다.
"""

from datetime import timedelta

from django.db import models
from django.db.models import Q

# 마감임박의 임계값. **`PlatformPolicy`(ADR-0023)에 넣지 않는다.** 그 ADR은
# 수수료율·심사기간·배분 대기일처럼 돈이나 행동을 바꾸는 값을 위한 것이고, 이
# 값은 카드가 「진행중」 칸에 있는지 「마감임박」 칸에 있는지 — 표시 방식만
# 바꾼다. 정책 테이블에 넣으면 마이그레이션·운영자 API·변경 이력이 표시 선택
# 하나에 딸려온다. 그래서 코드 상수로 두고, 바뀔 필요가 생기면 배포로 바꾼다.
#
# `/contests` 목록 화면의 강조색 임계값(frontend/lib/contest-format.ts의
# `IMMINENT_DEADLINE_DAYS`)과 같은 3일을 쓴다 — 서로 다른 화면에서 "임박"의
# 뜻이 갈리면 방문자가 같은 공모전을 보고도 다른 판단을 하게 된다. 다만 그
# 값과 이 값은 각자 다른 목적(행 강조 vs 홈 묶음 배정)의 별개 상수다 — 하나가
# 바뀐다고 다른 하나가 자동으로 따라가지 않는다는 뜻이므로, 둘을 맞출 필요가
# 생기면 사람이 둘 다 고쳐야 한다.
HOME_IMMINENT_DEADLINE_DAYS = 3


class HomeCurationBucket(models.TextChoices):
    """홈에서 공모전이 속하는 네 묶음 중 하나 (#94)."""

    # 공개돼 있고 마감이 아직 멀다.
    ONGOING = "ongoing", "진행중"
    # 공개돼 있고 마감이 `HOME_IMMINENT_DEADLINE_DAYS` 이내로 가깝다.
    IMMINENT = "imminent", "마감임박"
    # 마감됐고(CLOSED) 심사기간 중이다 — 데모·영상은 이미 전면 공개다(ADR-0014).
    IN_JUDGING = "in_judging", "심사중"
    # 선정됐거나(AWARDED) 심사기간이 끝났다(JUDGING_ENDED) — 둘 다 진짜 끝난
    # 것이다.
    COMPLETED = "completed", "완료"


def home_bucket_for(contest, *, now) -> str | None:
    """이 Contest가 홈의 어느 묶음에 속하는지 하나 고른다.

    **이 함수가 유일한 판정 기준이다.** `contests.api.get_home_curation`이
    성능 때문에(#94 코드리뷰 4 — 공개 Contest 전체를 매 요청 fetch할 수
    없다) 묶음마다 별도 쿼리로 이 판정을 SQL WHERE로 다시 표현하지만
    (`contests.api._home_bucket_queryset`), 그 쿼리가 돌려준 각 행을 여기로
    다시 통과시켜 갈리면 로그로 드러낸다 — 조건을 두 벌로 쓰면 언젠가
    갈라진다는 이 저장소의 경험(`submissions.participation`·
    `contests.sponsorship`) 그대로다. `backend/tests/test_home_curation.py`의
    경계값 테스트들이 두 표현을 계속 맞춰 둔다.

    `DRAFT`는 `None`이다 — 결제 전 Contest가 홈에 새면 안 된다(#94 인수조건).
    이 함수를 부르는 쪽은 애초에 `Contest.Status.PUBLICLY_VISIBLE`로
    이미 걸러진 Contest만 넘기지만(공개 목록·상세와 같은 경계), `DRAFT`가
    실수로 들어와도 여기서 다시 한번 막는다 — 조건을 한 곳에 두면 어느 한쪽만
    고쳐 갈라지는 사고를 막을 수 있다.

    반환값이 `None`이면 그 Contest는 어느 묶음에도 들어가지 않는다 — 호출부는
    이 경우를 조용히 버리지 않고 드러내야 한다(`contests.api.get_home_curation`
    참고).
    """

    from contests.models import Contest, HomeStatusAxis

    axis = Contest.Status.HOME_AXIS(contest.status)

    if axis is HomeStatusAxis.OPEN:
        remaining = contest.deadline_at - now

        # 마감 시각은 지났는데 스캔이 아직 CLOSED로 옮기지 않은 아주 짧은
        # 창이다(core.transitions, 스케줄러 틱 주기 이내 — ADR-0003).
        # `submissions.participation.next_action_for`가 같은 상황에서
        # `Contest.status`가 아니라 `deadline_at`을 직접 비교해 마감 이후로
        # 취급하는 것과 같은 근거다. **하한 없이 "마감이 3일 이내"만 보면
        # 이 음수 구간(마감이 며칠 전이어도 참)이 「마감임박」의 오름차순
        # 정렬에서 맨 앞자리를 영구히 차지해, 실제 D-1·D-2 Contest를
        # 밀어낸다**(#94 코드리뷰 2) — 그래서 "아직 안 지났다"를 먼저 걸러
        # 이 구간을 「심사중」으로 보낸다.
        if remaining < timedelta(0):
            return HomeCurationBucket.IN_JUDGING

        if remaining <= timedelta(days=HOME_IMMINENT_DEADLINE_DAYS):
            return HomeCurationBucket.IMMINENT
        return HomeCurationBucket.ONGOING

    if axis is HomeStatusAxis.IN_JUDGING:
        return HomeCurationBucket.IN_JUDGING

    if axis is HomeStatusAxis.COMPLETED:
        return HomeCurationBucket.COMPLETED

    return None


def home_bucket_queryset(base, bucket, *, now):
    """`bucket`에 속하는 Contest만, 그 묶음에 맞는 정렬로 돌려준다 (#94).

    **바로 위 `home_bucket_for`가 판정의 원본이고, 이 함수는 그 판정을 SQL WHERE로
    다시 표현한 것이다.** 두 표현이 한 화면에 나란히 살도록 여기 둔다(#144) — 한쪽만
    고치는 사고는 다른 쪽이 눈에 보일 때 줄어든다. 원래는(#94 1차) 공개 Contest를
    전부 가져와 Python에서 `home_bucket_for`를 한 번씩만 부르는 단일 질의
    였다 — 조건을 두 벌로 쓰지 않으려던 것이었는데, 그러면 공개 Contest가
    쌓일수록(수천 건) 매 홈 방문마다 전부 fetch하고
    `deliverable_types`·`requirements`까지 prefetch하게 된다(#94 코드리뷰
    4 — 홈은 `force-dynamic`이라 캐시도 없다). 그래서 묶음마다 상태·기한으로
    좁히고 그 묶음에 맞는 정렬로 DB에서 상위 `_HOME_BUCKET_LIMIT`건만 뽑는다.

    **이 이중화는 방치되지 않는다** — `get_home_curation`이 각 행을 다시
    `home_bucket_for`에 통과시켜 이 필터와 갈리면 로그로 드러내고,
    `backend/tests/test_home_curation.py`의 경계값 테스트가 네 묶음 각각을 공용
    헬퍼(`tests.predicate_pairs.assert_predicate_matches_q`)로 임계값 양쪽 끝에서 맞춘다.

    정렬은 묶음마다 다르다(#94 코드리뷰 1) — 「진행중」·「마감임박」은 마감이
    가까운 순(오름차순), 「심사중」·「완료」는 최근에 마감된 순(내림차순)이다.
    네 묶음이 전부 같은 정렬을 쓰면 「완료」·「심사중」은 가장 오래된 건에
    영구히 고정된다 — 방금 선정된 공모전이 홈에 절대 안 오른다.
    """

    from contests.models import Contest, HomeStatusAxis

    imminent_cutoff = now + timedelta(days=HOME_IMMINENT_DEADLINE_DAYS)

    if bucket == HomeCurationBucket.ONGOING:
        return base.filter(
            status__in=Contest.Status.HOME_AXIS.where(HomeStatusAxis.OPEN), archived_at__isnull=True,
            deadline_at__gt=imminent_cutoff,
        ).order_by("deadline_at", "id")

    if bucket == HomeCurationBucket.IMMINENT:
        # 하한(`deadline_at__gte=now`)이 없으면 스캔이 아직 CLOSED로 못 옮긴
        # 마감 지난 PUBLISHED가 여기 섞여, 오름차순 정렬의 맨 앞자리(가장
        # 음수인 값)를 영구히 차지하고 진짜 D-1·D-2를 밀어낸다(#94 코드리뷰
        # 2). `home_bucket_for`가 그 구간을 IN_JUDGING으로 보내는 것과
        # 같은 경계다.
        return base.filter(
            status__in=Contest.Status.HOME_AXIS.where(HomeStatusAxis.OPEN), archived_at__isnull=True,
            deadline_at__gte=now,
            deadline_at__lte=imminent_cutoff,
        ).order_by("deadline_at", "id")

    if bucket == HomeCurationBucket.IN_JUDGING:
        return base.filter(
            Q(status__in=Contest.Status.HOME_AXIS.where(HomeStatusAxis.IN_JUDGING), archived_at__isnull=True)
            | Q(status__in=Contest.Status.HOME_AXIS.where(HomeStatusAxis.OPEN), archived_at__isnull=True, deadline_at__lt=now)
        ).order_by("-deadline_at", "-id")

    if bucket == HomeCurationBucket.COMPLETED:
        return base.filter(
            status__in=Contest.Status.HOME_AXIS.where(HomeStatusAxis.COMPLETED)
        ).order_by("-deadline_at", "-id")

    raise ValueError(f"알 수 없는 HomeCurationBucket: {bucket!r}")  # pragma: no cover
