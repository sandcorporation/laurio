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
"""

from django.db import models

from core.clock import Clock


class SponsorNextAction(models.TextChoices):
    """Sponsor 가 이 공모전에 대해 지금 무엇을 해야 하는가 — 또는 무엇을 기다리는가."""

    # --- 네 차례 -------------------------------------------------------------
    # 결제해야 공개된다. 초안인 채로 두면 아무 일도 일어나지 않는데, 그 사실을
    # 말해 주는 곳이 지금까지 없었다.
    PAY_TO_PUBLISH = "pay_to_publish", "결제 필요"
    # **이 화면의 핵심.** 채점이 끝났고 심사기간이 남아 있다 — 지금 고르지 않으면
    # 심사기간이 지나 무응답 배분으로 넘어가고, 개최자는 고를 수 있었던 결과를
    # 고르지 못한 채 끝난다.
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


def sponsor_next_action_for(contest, *, submission_count: int) -> str:
    """이 Contest 에 대해 Sponsor 가 지금 할 일(또는 기다리는 것)을 하나 고른다.

    호출부는 `award__handover` · `distribution` 을 미리 가져와야 한다 — 이 함수는
    행마다 새 조회를 내지 않는다(공모전이 쌓일수록 목록이 느려진다). 다만 이의
    보류 판정만은 조회를 낸다: 그 조건이 배분 스캔의 후보 질의와 **같은 곳에서**
    나와야 하기 때문이다(아래 참조).
    """

    from contests.models import Contest

    now = Clock.now()

    if contest.status == Contest.Status.DRAFT:
        return SponsorNextAction.PAY_TO_PUBLISH

    if contest.status == Contest.Status.PUBLISHED and now < contest.deadline_at:
        return SponsorNextAction.AWAITING_SUBMISSIONS

    award = getattr(contest, "award", None)
    if award is not None:
        return _awarded_action(award)

    # 마감은 됐는데 아무도 안 냈다. 「심사하세요」는 거짓말이고, 「기다리는 중」도
    # 아니다 — 올 것이 더 없다.
    if submission_count == 0:
        return SponsorNextAction.NO_SUBMISSIONS

    # 채점이 **하나라도** 끝나야 심사 비교 화면에 보여줄 것이 생긴다.
    #
    # **「전부 채점됨」을 요구하지 않는다.** 그렇게 두면 한 건의 채점이 계속
    # 실패할 때 개최자는 심사기간이 지나도록 「심사하세요」를 듣지 못하고, 고를
    # 수 있었던 결과를 못 고른 채 무응답 배분으로 넘어간다. Award 는 Score 를
    # 조회조차 하지 않으므로(ADR-0006/0014) 심사 자체는 언제든 가능하다 —
    # 화면이 API 가 허용하는 행위를 감추면 안 된다.
    if not _any_scored(contest):
        return SponsorNextAction.AWAITING_SCORING

    if contest.status == Contest.Status.CLOSED and _within_judging_window(contest, now):
        return SponsorNextAction.JUDGE_AND_AWARD

    # 심사기간이 지났다 — 무응답 배분의 차례다.
    if getattr(contest, "distribution", None) is not None:
        return SponsorNextAction.CONTEST_COMPLETE

    if _held_by_appeal(contest):
        return SponsorNextAction.AWAITING_APPEAL_RULING

    return SponsorNextAction.AWAITING_DISTRIBUTION


def _awarded_action(award) -> str:
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
    # 등록·주민등록번호는 개발자와 지급대행사 사이의 일이다.
    from payouts.models import Payout

    payout = (
        Payout.objects.filter(handover=handover).order_by("-created_at").first()
    )
    if payout is not None and payout.status == Payout.Status.CONFIRMED:
        return SponsorNextAction.CONTEST_COMPLETE
    return SponsorNextAction.AWAITING_PAYOUT


def _any_scored(contest) -> bool:
    from submissions.models import Submission

    return Submission.objects.filter(contest=contest, score__isnull=False).exists()


def _within_judging_window(contest, now) -> bool:
    return contest.judging_ends_at is None or now < contest.judging_ends_at


def _held_by_appeal(contest) -> bool:
    """이 공모전의 배분이 심판되지 않은 이의 때문에 멈춰 있는가 (스토리 40).

    판정을 `distributions.services` 에서 가져온다 — 「막고 있다」를 이의 쪽에서
    말할 때 쓰는 것과 **같은 함수**다. 두 벌로 쓰면 개최자 화면은 보류라는데
    이의 큐는 아니라고 하는 날이 온다.
    """

    from appeals.models import Appeal
    from distributions.services import is_holding_distribution

    pending = (
        Appeal.objects.filter(
            submission__contest=contest, status=Appeal.Status.PENDING
        )
        .select_related("submission")
        .first()
    )
    return pending is not None and is_holding_distribution(pending)
