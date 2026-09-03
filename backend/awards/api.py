"""Award API — Sponsor가 심사기간 중 Submission 하나를 우승작으로 확정한다 (#13).

핵심 규율:

- Contest의 Sponsor 본인만 Award할 수 있다.
- 심사기간(judging_ends_at 이전)에만 가능하다 — 지난 뒤에는 거부한다. `Contest.status`
  가 아직 CLOSED로 보여도(스캔 주기만큼 늦어질 수 있다, ADR-0003) `judging_ends_at`
  을 직접 비교해 한 번 더 막는다.
- 한 Contest에 Award는 정확히 하나뿐이다. `core.transitions.claim_transition`으로
  `Contest.status`를 CLOSED -> AWARDED로 조건부 UPDATE하고, 그 UPDATE가 이겼을
  때만(rowcount==1) `Award` 행을 만든다 — 두 Submission이 동시에 Award 요청을
  보내도 하나만 통과한다.
- `Score`는 Award를 결정하지 않는다(ADR-0006/0014) — Award는 Sponsor 본인의 판단이다.
  이 엔드포인트는 Score를 전혀 조회하지 않는다.
- Award는 지식재산권 이전을 기록할 뿐, 소스 접근 권한을 여는 것(Handover, #14)이나
  Escrow 해제(#14/#15)는 하지 않는다.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import HttpRequest
from ninja import Router
from ninja.errors import HttpError

from accounts.middleware import jwt_auth
from contests.models import Contest
from core.clock import Clock
from core.transitions import claim_transition
from handovers.models import Handover
from notifications.lifecycle import notify_award_result
from policies.services import get_current_policy
from submissions.models import Submission

from .models import Award
from .schemas import AwardIn, AwardOut

router = Router(tags=["awards"])


@router.post("/contests/{contest_id}/award", response={200: AwardOut}, auth=jwt_auth)
def award_submission(request: HttpRequest, contest_id: int, payload: AwardIn):
    try:
        contest = Contest.objects.select_related("sponsor").get(id=contest_id)
    except Contest.DoesNotExist as exc:
        raise HttpError(404, "Contest를 찾을 수 없습니다.") from exc

    if contest.sponsor.user_id != request.auth_user.id:
        raise HttpError(403, "본인이 개최한 Contest만 Award할 수 있습니다.")

    try:
        submission = Submission.objects.get(id=payload.submission_id, contest=contest)
    except Submission.DoesNotExist as exc:
        raise HttpError(404, "이 Contest에 속한 Submission을 찾을 수 없습니다.") from exc

    now = Clock.now()

    if Contest.Status.HAS_AWARD(contest.status):
        raise HttpError(409, "이미 다른 Submission이 Award되었습니다.")
    if not Contest.Status.AWARDABLE(contest.status):
        # 어느 status 가 해당하는지는 Contest.Status.AWARDABLE 이 답한다(#142). JUDGING_ENDED 는 아래
        # judging_ends_at 비교와 같은 결론을, 스케줄러가 이미 반영한 경우 상태만으로 먼저 잡아준다.
        raise HttpError(409, "지금은 Award할 수 있는 상태가 아닙니다.")

    # 코드베이스 관용구와 맞춘다: 스케줄러는 `judging_ends_at <= as_of`일 때
    # CLOSED -> JUDGING_ENDED로 옮긴다(core.transitions/contests.apps) — 즉 심사
    # 기간은 "now가 judging_ends_at과 같아지는 순간"부터 이미 끝난 것으로 본다.
    # `>`를 쓰면 그 경계 순간에 스케줄러는 이미 끝났다고 보는데 Award는 아직
    # 허용해버리는 불일치가 생긴다(#13 리뷰 지적 7 — extend_judging_period의
    # `_reject_if_judging_period_is_not_extendable`도 같은 `>=`를 쓴다).
    if contest.judging_ends_at is None or now >= contest.judging_ends_at:
        # 스캔 주기만큼 틱이 아직 CLOSED -> JUDGING_ENDED를 못 옮겼더라도, 시각으로
        # 다시 한 번 막는다(AC: "심사기간이 지나면 Award가 거부된다").
        raise HttpError(403, "심사기간이 지나 Award할 수 없습니다.")

    with transaction.atomic():
        transitioned = claim_transition(
            Contest,
            contest.id,
            from_state=Contest.Status.CLOSED,
            to_state=Contest.Status.AWARDED,
            state_field="status",
            now=now,
        )
        if not transitioned:
            # 동시에 들어온 다른 요청이 먼저 이겼거나, 그 사이 스케줄러 틱이
            # JUDGING_ENDED로 옮겼다 — 어느 쪽이든 이 요청은 통과시키지 않는다.
            raise HttpError(
                409, "이미 Award되었거나 심사기간이 종료되어 Award할 수 없습니다."
            )

        try:
            award = Award.objects.create(
                contest=contest, submission=submission, awarded_at=now
            )
        except IntegrityError as exc:
            # unique(contest) 제약이 최후의 방어선이다 — 정상 경로에서는 위
            # claim_transition의 조건부 UPDATE가 이미 직렬화했으므로 도달하지
            # 않아야 한다.
            raise HttpError(409, "이미 Award되었습니다.") from exc

        # Handover(#14)는 Award와 함께 태어난다 — Sponsor의 소스 접근 권한은 이
        # 행의 존재 자체가 아니라 `awards.Award`의 존재로 판정되므로(
        # `submissions.resolvers`) 이미 이 시점에 열려 있다. 이 행은 그 뒤의
        # 인수 확인·빌드 자산·Escrow 해제 흐름이 딸릴 자리를 만들 뿐이다.
        Handover.objects.create(
            award=award,
            release_deadline_at=now
            + timedelta(days=get_current_policy().handover_acceptance_period_days),
        )

    # 트랜잭션이 커밋된 뒤에만 알린다 — notify_award_result는 내부에서 모든 예외를
    # 삼키므로(#19 AC, ADR-0009) 이 응답이 알림 실패로 막히는 일은 없다.
    notify_award_result(award)

    return 200, AwardOut(
        contest_id=contest.id, submission_id=submission.id, awarded_at=award.awarded_at
    )
