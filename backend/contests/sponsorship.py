"""「내 공모전」의 한 행이 말하는 「다음 행동」 (#81).

`submissions.participation` 의 개최자판이다 — 같은 이유로 같은 모양을 쓴다.

**왜 백엔드가 판정하는가.** Sponsor 의 상태도 한 곳에 있지 않다: Contest.status,
Payment, Submission 수, Score 유무, Award, Handover.status, Distribution, 그리고
심판되지 않은 Appeal 이 각자 조금씩 쥐고 있다. 화면이 그것을 재파생하면 새 상태가
생겼을 때 어느 분기에도 걸리지 않고 조용히 「알 수 없음」이 된다. 값이 enum 이면
생성된 타입에 값이 하나 늘고 `tsc --noEmit` 이 프론트의 누락된 분기를 빌드타임에
잡는다.

**이 값은 강제하지 않는다.** 방어는 각 행위 엔드포인트가 자기 전제를 확인하는
것으로 이미 서 있다(Award 는 심사기간과 소유권을, 인수 확인은 Award 를). 여기
있는 것은 사고 예방이지 방어가 아니다.

**그래서 각 값은 그 행위 엔드포인트의 전제와 같은 조건에서 나와야 한다.** 조건을
두 벌로 쓰면 언젠가 갈라지고, 그때 화면은 시키는 대로 한 개최자에게 409 를
보여준다.

**이 모듈은 조회를 내지 않는다.** 판정에 필요한 사실은 호출부가
`sponsored_contest_queryset` 으로 미리 붙여 준다. 행마다 조회를 내면 한
페이지(20행)에 100 쿼리가 넘고 `get_current_policy()` 도 행마다 불리게 된다 —
`policies/services.py` 가 요청 스코프당 한 번만 부르라고 못 박아 둔 그것이다.
"""

from django.db import models
from django.db.models import Case, Count, Exists, OuterRef, Q, Value, When


class SponsorNextAction(models.TextChoices):
    """Sponsor 가 이 공모전에 대해 지금 무엇을 해야 하는가 — 또는 무엇을 기다리는가."""

    # --- 네 차례 -------------------------------------------------------------
    # 결제해야 공개된다. 초안인 채로 두면 아무 일도 일어나지 않는데, 그 사실을
    # 말해 주는 곳이 지금까지 없었다.
    PAY_TO_PUBLISH = "pay_to_publish", "결제 필요"
    # **이 화면의 핵심.** 심사기간이 남아 있다 — 지금 고르지 않으면 심사기간이
    # 지나 무응답 배분으로 넘어가고, 개최자는 고를 수 있었던 결과를 고르지 못한
    # 채 끝난다.
    JUDGE_AND_AWARD = "judge_and_award", "심사·선정"
    # 선정했고 인수를 확인하면 Escrow 가 풀린다. 확인하지 않아도 기간이 지나면
    # 풀리지만(Handover.ReleasedVia.TIMEOUT), 그때까지 개발자의 돈이 묶인다.
    ACCEPT_HANDOVER = "accept_handover", "인수 확인"

    # --- 기다리는 중: 할 일이 없다 -------------------------------------------
    AWAITING_SUBMISSIONS = "awaiting_submissions", "제출 대기"
    AWAITING_SCORING = "awaiting_scoring", "채점 대기"
    # 스토리 40 — #81 이 존재하는 이유. 「조용히 늦음」이 아니라 「보류」다.
    AWAITING_APPEAL_RULING = "awaiting_appeal_ruling", "이의 심판으로 보류"
    AWAITING_DISTRIBUTION = "awaiting_distribution", "배분 대기"
    AWAITING_PAYOUT = "awaiting_payout", "지급 대기"

    # --- 끝난 일 -------------------------------------------------------------
    NO_SUBMISSIONS = "no_submissions", "제출 없음"
    CONTEST_COMPLETE = "contest_complete", "완료"


def sponsored_contest_queryset(base, *, as_of, policy):
    """판정에 필요한 사실을 **한 질의로** 붙인다 (#81).

    전부 `Exists` 서브쿼리다 — `Count` 로 하면 조인이 곱해져 행이 늘고,
    `distinct=True` 로 막아도 질의가 무거워진다. 실제 조인은
    `submission_count` 하나뿐이다.
    """

    from appeals.models import Appeal
    from distributions.models import DistributionShare
    from distributions.services import SETTLED_PAYOUT_STATUSES, distribution_due_q
    from payouts.models import Payout
    from scoring.models import Score

    return base.select_related("award__handover", "distribution").annotate(
        submission_count=Count("submissions", distinct=True),
        has_any_score=Exists(Score.objects.filter(submission__contest=OuterRef("pk"))),
        has_pending_appeal=Exists(
            Appeal.objects.filter(
                submission__contest=OuterRef("pk"), status=Appeal.Status.PENDING
            )
        ),
        # transfer_status가 FAILED면 CONFIRMED라도 실이체가 실제로는 아직
        # 안 나간 것이다(#57 코드리뷰 지적 4/7/8, 3차의 결과로 생긴
        # Payout.transfer_status 축 — status는 원장 확정 사실이라 되돌리지
        # 않지만(ADR-0004), 이 축을 안 보면 뒤늦게 실이체가 실패로 확인된
        # Contest도 "완료"라고 말하게 된다). Sponsor에게 지급 상세를 보여주지
        # 않는다는 설계 의도(위 주석)는 그대로 지키되, "완료"라는 판정 자체는
        # 진실이어야 한다.
        has_confirmed_payout=Exists(
            Payout.objects.filter(
                handover__award__contest=OuterRef("pk"), status=Payout.Status.CONFIRMED
            ).exclude(transfer_status=Payout.TransferStatus.FAILED)
        ),
        # 배분은 만들어졌는데 아직 정산되지 않은 몫이 남아 있는가. 「배분 행이
        # 생겼다」와 「돈이 실제로 갔다」는 다르다 — 지급이 전부 실패해 매 스캔
        # 재시도되는 중에도 앞의 조건은 참이다.
        #
        # `payouts__status__in=SETTLED_PAYOUT_STATUSES`만으로는 CONFIRMED인데
        # transfer_status가 FAILED인 Payout도 "정산됨"으로 잡는다(코드리뷰
        # 지적 7, 4차 — 지난 라운드에 Award 경로(has_confirmed_payout)만
        # 고치고 이 배분 경로는 놓쳤다). 두 조건을 하나의 Q로 묶어 **같은
        # 관련 Payout 행**에 함께 걸어야 한다 — exclude를 두 번 나눠 걸면
        # 서로 다른 Payout 행에 각각 적용될 수 있어 원하는 "정산됨 AND
        # 실이체 실패 아님"이라는 단일 행의 조건이 되지 않는다.
        has_unsettled_share=Exists(
            DistributionShare.objects.filter(
                distribution__contest=OuterRef("pk")
            ).exclude(
                Q(payouts__status__in=SETTLED_PAYOUT_STATUSES)
                & ~Q(payouts__transfer_status=Payout.TransferStatus.FAILED)
            )
        ),
        # 배분 시각이 왔는가. 스캔·이의 큐가 쓰는 것과 **같은 조건**이다
        # (`distribution_due_q`) — 세 벌로 쓰면 개최자 화면은 보류라는데 이의
        # 큐는 아니라고 하는 날이 온다.
        is_distribution_due=Case(
            When(distribution_due_q(as_of, policy), then=Value(True)),
            default=Value(False),
            output_field=models.BooleanField(),
        ),
    )


def sponsor_next_action_for(contest, *, now) -> str:
    """이 Contest 에 대해 Sponsor 가 지금 할 일(또는 기다리는 것)을 하나 고른다.

    `contest` 는 `sponsored_contest_queryset` 이 붙인 annotation 을 갖고 있어야
    한다. 이 함수는 조회를 내지 않는다.
    """

    from contests.models import Contest

    if Contest.Status.PAYABLE(contest.status):
        return SponsorNextAction.PAY_TO_PUBLISH

    if Contest.Status.SUBMITTABLE(contest.status) and now < contest.deadline_at:
        return SponsorNextAction.AWAITING_SUBMISSIONS

    # 선정이 끝났으면 그 뒤의 흐름만 남는다 — 채점 상태는 더 이상 개최자가
    # 기다릴 것이 아니다.
    award = getattr(contest, "award", None)
    if award is not None:
        return _awarded_action(contest, award)

    # 마감은 됐는데 아무도 안 냈다. 「심사하세요」는 거짓말이고, 「기다리는 중」도
    # 아니다 — 올 것이 더 없다.
    if contest.submission_count == 0:
        return SponsorNextAction.NO_SUBMISSIONS

    # 마감 시각은 지났는데 스캔이 아직 CLOSED 로 옮기지 않았다.
    if Contest.Status.SUBMITTABLE(contest.status):
        return SponsorNextAction.AWAITING_SCORING

    if Contest.Status.AWARDABLE(contest.status) and _within_judging_window(contest, now):
        # **채점을 이 아래 단계들의 게이트로 쓰지 않는다.** 「하나라도 채점됨」을
        # 바깥 조건으로 두면, 채점이 영영 성공하지 못하는 공모전은 배분이 끝난
        # 뒤에도 계속 「채점 대기」라고 말한다. 그래서 이 안내는 **심사 창
        # 안에만** 있다.
        #
        # 심사 창 안에서도 채점은 「보여줄 것이 아직 없다」는 안내일 뿐이고,
        # 심사 자체를 막지 않는다 — `POST /contests/{id}/award` 도 심사 비교
        # 화면도 Score 를 조회조차 하지 않는다(ADR-0006/0014).
        if not contest.has_any_score:
            return SponsorNextAction.AWAITING_SCORING
        return SponsorNextAction.JUDGE_AND_AWARD

    # 심사기간이 지났다 — 무응답 배분의 차례다.
    if getattr(contest, "distribution", None) is not None:
        # 배분 행이 생겼다고 돈이 간 것은 아니다. 지급이 전부 실패해 매 스캔
        # 재시도되는 중에도 그 행은 있다 — 그때 「완료」라고 하면 개최자는
        # 끝났다고 믿는다. Award 경로가 `Payout.Status.CONFIRMED` 를 확인하고서야
        # 완료라고 하는 것과 같은 기준이다.
        if contest.has_unsettled_share:
            return SponsorNextAction.AWAITING_PAYOUT
        return SponsorNextAction.CONTEST_COMPLETE

    if contest.has_pending_appeal and contest.is_distribution_due:
        return SponsorNextAction.AWAITING_APPEAL_RULING

    return SponsorNextAction.AWAITING_DISTRIBUTION


def _awarded_action(contest, award) -> str:
    from handovers.models import Handover

    handover = getattr(award, "handover", None)
    if handover is None:
        # Award 는 됐는데 Handover 가 아직 없다 — 만들어지는 중이다.
        return SponsorNextAction.ACCEPT_HANDOVER

    # `handovers.api.accept_handover` 가 받는 상태 그대로다.
    if handover.status != Handover.Status.RELEASED:
        return SponsorNextAction.ACCEPT_HANDOVER

    # Escrow 는 풀렸다 — 남은 것은 개발자 쪽 지급 절차이고 Sponsor 가 할 일은
    # 없다. 지급 상태를 개최자에게 자세히 보여주지 않는 것은 의도다: 수취인
    # 등록도 주민등록번호도 개최자가 알 일이 아니다.
    if contest.has_confirmed_payout:
        return SponsorNextAction.CONTEST_COMPLETE
    return SponsorNextAction.AWAITING_PAYOUT


def _within_judging_window(contest, now) -> bool:
    return contest.judging_ends_at is None or now < contest.judging_ends_at
