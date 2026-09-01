"""「내 참가 현황」의 한 행이 말하는 「다음 행동」 (#74).

Developer 의 상태는 한 곳에 있지 않다 — Contest.status, Score 존재 여부, Award,
Appeal.status, Handover.status, Payout.status 가 각자 조금씩 쥐고 있다. 그것을
곱하면 참가자가 읽을 수 없는 수의 조합이 나온다. 그래서 여기서 **하나의 값**으로
번역한다.

**왜 백엔드가 판정하는가.** 화면이 원시 상태에서 재파생하면, 나중에 새 상태가
생겼을 때 어느 분기에도 걸리지 않고 조용히 "알 수 없음" 으로 떨어진다 — 이
저장소가 반복해서 겪은 모양이다. 값이 enum 이면 생성된 타입에 값이 하나 늘고
`tsc --noEmit` 이 프론트의 누락된 분기를 빌드타임에 잡는다. 그 안전망을 쓰려면
판정이 여기 있어야 한다.

**HATEOAS 가 아니다.** 하이퍼미디어 링크를 내려주면 클라이언트가 어휘를 몰라도
되지만 런타임 JSON 이라 타입체커가 볼 것이 없다. 그리고 이 저장소는 프론트와
백엔드가 같은 CI 로 함께 나가므로 분리할 배포 주기가 없다. 취하는 것은 HATEOAS
의 절반 — "무엇이 지금 가능한가를 서버가 판단한다" — 이고, 그건 링크 없이도
가진다. 운영자 지급 큐의 `blocked_on` 이 이미 그 모양이다.

**이 값은 강제하지 않는다.** 응답의 필드는 클라이언트가 무시할 수 있다. 방어는
각 행위 엔드포인트가 자기 전제를 확인하는 것으로 이미 서 있다(지급 요청은
Escrow 해제를, 이의 제기는 채점 완료와 중복 아님을). 여기 있는 것은 사고
예방이지 방어가 아니다 — #67 이 "화면이 폼을 주지 않는 것과 서버가 거절하는
것은 둘 다 필요하다" 고 적은 그 구분이다.

**그래서 각 값은 그 행위 엔드포인트의 전제와 같은 조건에서 나와야 한다.** 조건을
두 벌로 쓰면 언젠가 갈라지고, 그때 화면은 시키는 대로 한 사용자에게 409 를
보여준다.
"""

from django.db import models

from core.clock import Clock


class NextAction(models.TextChoices):
    """Developer 가 지금 무엇을 해야 하는가 — 또는 무엇을 기다리는가."""

    # --- 기다리는 중: 할 일이 없다 -------------------------------------------
    AWAITING_DEADLINE = "awaiting_deadline", "마감 대기"
    AWAITING_SCORING = "awaiting_scoring", "채점 대기"
    AWAITING_JUDGING = "awaiting_judging", "심사 대기"
    AWAITING_APPEAL_RULING = "awaiting_appeal_ruling", "이의 심판 대기"
    AWAITING_DISTRIBUTION = "awaiting_distribution", "배분 대기"
    AWAITING_HANDOVER_RELEASE = "awaiting_handover_release", "인수 확인 대기"
    AWAITING_SELLER_REGISTRATION = "awaiting_seller_registration", "지급대행 등록 대기"

    # --- 네 차례 -------------------------------------------------------------
    CAN_APPEAL = "can_appeal", "이의 제기 가능"
    REQUEST_PAYOUT = "request_payout", "지급 요청"
    SUBMIT_TAX_IDENTITY = "submit_tax_identity", "세무 신원 제출"

    # --- 끝난 일 -------------------------------------------------------------
    NOT_SELECTED = "not_selected", "미선정"
    PAYOUT_COMPLETE = "payout_complete", "지급 완료"


def next_action_for(submission) -> str:
    """이 Submission 에 대해 Developer 가 지금 할 일(또는 기다리는 것)을 하나 고른다.

    호출부는 `Submission` 을 관련 객체와 함께 미리 가져와야 한다 — 이 함수는
    행마다 새 조회를 내지 않는다(목록이 N+1 이 되면 참가가 쌓일수록 느려진다).
    """

    contest = submission.contest
    now = Clock.now()

    # 마감 전 — 제출은 끝났고 기다리는 것 말고 할 일이 없다. Contest.status 가
    # 아직 PUBLISHED 여도 시각이 지났으면 스캔이 아직 안 돈 것뿐이므로,
    # `submissions.resolvers` 가 그러듯 시각을 직접 본다.
    if now < contest.deadline_at:
        return NextAction.AWAITING_DEADLINE

    if not hasattr(submission, "score"):
        return NextAction.AWAITING_SCORING

    # 채점이 끝났다 — 이의가 여기서 갈린다.
    appeal = getattr(submission, "appeal", None)
    if appeal is not None and appeal.status == appeal.Status.PENDING:
        return NextAction.AWAITING_APPEAL_RULING

    payout_action = _payout_action(submission)
    if payout_action is not None:
        return payout_action

    # 아직 돈이 걸린 단계에 닿지 않았다 — 이의를 낼 수 있는지 본다. 조건은
    # `appeals.api.create_appeal` 의 전제와 같다: 채점이 끝났고(위에서 확인),
    # 아직 이의가 없고, 기한(심사기간 종료) 안이다.
    if appeal is None and within_appeal_window(contest, now):
        return NextAction.CAN_APPEAL

    if _is_awarded_to_someone_else(submission):
        return NextAction.NOT_SELECTED

    if contest.judging_ends_at is not None and now < contest.judging_ends_at:
        return NextAction.AWAITING_JUDGING

    return NextAction.AWAITING_DISTRIBUTION


def within_appeal_window(contest, now) -> bool:
    """이의 제기 기한은 심사기간 종료다 (#74).

    `Score` 는 Award 를 결정하지 않으므로(ADR-0006/0014 — Award 엔드포인트는
    Score 를 조회조차 하지 않는다) 점수가 돈을 정하는 곳은 배분의 컷라인
    하나뿐이고, `judging_ends_at` 이면 배분은 아직 대기를 시작도 안 했다.

    **이 값은 Sponsor 의 유료 연장으로 미뤄진다.** 그러면 Developer 의 이의 창도
    함께 늘어난다 — 유리한 방향이라 해롭지 않지만 아무도 그렇게 결정한 적은
    없으므로, 그 결합이 여기 있다는 것을 적어 둔다.
    """

    return contest.judging_ends_at is None or now < contest.judging_ends_at


def _is_awarded_to_someone_else(submission) -> bool:
    award = getattr(submission.contest, "award", None)
    return award is not None and award.submission_id != submission.id


def _payout_action(submission):
    """돈이 걸린 단계 — 각 값이 대응하는 엔드포인트의 전제와 같은 조건에서 나온다."""

    from handovers.models import Handover
    from payouts.models import Payout

    award = getattr(submission.contest, "award", None)
    if award is None or award.submission_id != submission.id:
        return None

    handover = getattr(award, "handover", None)
    if handover is None:
        return None

    # `payouts.api.request_payout` 이 요구하는 것과 같은 조건이다.
    if handover.status != Handover.Status.RELEASED:
        return NextAction.AWAITING_HANDOVER_RELEASE

    payout = Payout.objects.filter(handover=handover).order_by("-created_at").first()
    if payout is None:
        return NextAction.REQUEST_PAYOUT

    # `submit_payout_identity` 와 `retry_seller_registration` 이 각자 요구하는
    # 상태 그대로다 — 앞은 Developer 가 주민등록번호를 내야 하는 「네 차례」이고,
    # 뒤는 지급대행사 쪽 등록을 기다리는 중이다(ADR-0020: 둘은 다른 것을
    # 기다리고, 둘 다 실패가 아니다).
    if payout.status == Payout.Status.CONFIRMED_IDENTITY_PENDING:
        return NextAction.SUBMIT_TAX_IDENTITY
    if payout.status == Payout.Status.CONFIRMED_SELLER_PENDING:
        return NextAction.AWAITING_SELLER_REGISTRATION
    if payout.status == Payout.Status.CONFIRMED:
        return NextAction.PAYOUT_COMPLETE

    return NextAction.AWAITING_SELLER_REGISTRATION
