"""참가자 화면의 돈 걸린 단계 — 지급(Payout)의 Hold 를 참가자의 다음 할 일(NextAction)로 옮긴다(#130, #177).
`contests.submission_participation` 이 `contests.ports.PAYOUT_ACTION` 으로 부른다(#1086 에서 그 모듈에서 옮겼다).
"""

from __future__ import annotations

from contests.submission_participation import NextAction
from handovers.models import Handover

from .models import Payout, TaxIdentity
from .progress import HoldKind, assert_covers_all_kinds, hold_of

#: 「다음 행동」 목록이 `ContestSubmission` 에서 함께 당길 관계 — `payout_action` 이 보는 인수 행(#1102)
NEXT_ACTION_RELATIONS = ("contest__award__handover",)


# Hold → NextAction 번역표 (#130). 판정은 `payouts.progress.hold_of` 가 한다 — 여기서
# 원시 상태를 다시 읽으면 세 렌더러가 갈린다. 표는 HoldKind 전체를 덮어야 한다(로드 시 검사).
def _payout_actions():
    table = {
        HoldKind.REQUESTED: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.IDENTITY: NextAction.SUBMIT_TAX_IDENTITY,
        HoldKind.IDENTITY_RECORDED: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.SELLER_CONTACT: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.SELLER_AUTH: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.SELLER_REVIEW: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.SELLER_REJECTED: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.SELLER_PENDING: NextAction.AWAITING_SELLER_REGISTRATION,
        # 자력 회복 스캔이 포기해 Operator 의 차례가 된 상태(#178) — SELLER_REJECTED와
        # 같은 이유로 같은 값에 묶는다: Developer 관점에서는 둘 다 "지급대행 등록이
        # 여전히 안 끝났고 지금은 내가 할 게 없다"는 같은 사실이다.
        HoldKind.SELLER_REGISTRATION_STUCK: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.TRANSFER_CONFIRMING: NextAction.AWAITING_SELLER_REGISTRATION,
        HoldKind.TRANSFER_RETRY: NextAction.RETRY_TRANSFER,
        HoldKind.TRANSFER_RETRY_IDENTITY_RECORDED: NextAction.RETRY_TRANSFER,
        HoldKind.TRANSFER_OPERATOR: NextAction.AWAITING_TRANSFER_RESOLUTION,
        HoldKind.COMPLETE: NextAction.PAYOUT_COMPLETE,
        # 벤더가 거절해 이 시도가 끝났다 — 실제로 가능한 행동은 새 지급 요청이다
        # (#130 — 전에는 fallthrough 가 「지급대행 등록 대기」라고 잘못 말했다).
        HoldKind.FAILED: NextAction.REQUEST_PAYOUT,
        HoldKind.UNKNOWN: NextAction.AWAITING_TRANSFER_RESOLUTION,
    }
    assert_covers_all_kinds(table, name="participation._payout_actions")
    return table


def payout_action(submission):
    """돈이 걸린 단계 — Award·Handover 경로와 Distribution 경로 중 이 submission 이
    속한 쪽으로 Payout 을 찾고, 있으면 Hold 로 넘긴다(#177).

    **Award 가 있는 Contest 에는 Distribution 이 없다** — Distribution 은 Sponsor 가
    기한 내 Award 하지 않았을 때만 일어나는 배분이다(CONTEXT.md 「Distribution」).
    그래서 두 경로는 배타적이고, `award` 유무로 어느 쪽을 볼지 가른다. 판정 자체는
    어느 경로든 같은 `payouts.progress.hold_of` 하나가 한다 — Award 경로와
    Distribution 경로가 지급 단계 여부를 각자 적지 않는다(#177 AC).
    """

    award = getattr(submission.contest, "award", None)
    if award is not None:
        if award.submission_id != submission.id:
            return None
        if submission.contest.is_free:
            # 무료 공모전(#417)은 Handover 자체가 없다 — Escrow 해제·지급
            # 절차 없이 수상으로 끝난다.
            return NextAction.AWARDED
        handover = getattr(award, "handover", None)
        if handover is None:
            return None
        # `payouts.api.request_payout` 이 요구하는 것과 같은 조건이다.
        if handover.status != Handover.Status.RELEASED:
            return NextAction.AWAITING_HANDOVER_RELEASE
        payout = Payout.objects.filter(handover=handover).order_by("-created_at").first()
        if payout is None:
            # Award 경로는 Developer 가 직접 요청한다 — `POST .../payout` 이
            # 있다(request_payout). 이 갈래의 동작은 #177 이전과 그대로다.
            return NextAction.REQUEST_PAYOUT
    else:
        # Award 가 없다 — Distribution 대상일 수 있다(#177). 컷라인을 통과하지
        # 못한 Submission 은 애초에 `DistributionShare` 가 없으므로(수상하지
        # 않은 Developer 에게 링크를 넓히지 않는다, #177 AC) 여기서 그대로 빠진다.
        distribution_share = getattr(submission, "distribution_share", None)
        if distribution_share is None:
            return None
        payout = (
            Payout.objects.filter(distribution_share=distribution_share)
            .order_by("-created_at")
            .first()
        )
        if payout is None:
            # Distribution 경로는 Developer 가 요청하지 않는다 — 내부 스캔이
            # 자동으로 Payout 을 만든다(`distributions.services`, #16). 여기서
            # REQUEST_PAYOUT 을 돌려주면 `POST /contests/{id}/payout` 이 Award
            # 를 요구해(`_get_owned_handover`) 곧바로 404 를 내는 버튼을 보여주게
            # 된다 — 눌러 봐야 서버가 거절하는 버튼은 만들지 않는다(#177 AC).
            # 스캔이 아직 이 몫을 처리하지 않은 그 짧은 사이는 배분을 기다리는
            # 중이라는 말이 그대로 사실이므로 None 을 돌려 `AWAITING_DISTRIBUTION`
            # 으로 자연스럽게 떨어지게 둔다.
            return None

    has_identity = TaxIdentity.objects.filter(payout=payout).exists()
    hold = hold_of(payout, seller=payout.seller, has_identity=has_identity)
    return _payout_actions()[hold.kind]
