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

from .models import Contest
from .ports import APPEAL_STATE, AWARDED_SUBMISSION_ID, IS_SCORED, PAYOUT_ACTION  # 위 앱이 올린다(#1086, #1102)


class NextAction(models.TextChoices):
    """Developer 가 지금 무엇을 해야 하는가 — 또는 무엇을 기다리는가."""

    # --- 기다리는 중: 할 일이 없다 -------------------------------------------
    AWAITING_SCORING = "awaiting_scoring", "채점 대기"
    # 제출 크기가 채점 한도를 넘어 채점이 보류됐다(#989 A2) — 심사 종료 때 자동 0%. 유료 공모전은
    # 그 전까지 이의를 낼 수 있다(이의를 내면 아래 AWAITING_APPEAL_RULING).
    SCORING_HELD_SIZE = "scoring_held_size", "채점 보류(크기 초과)"
    AWAITING_JUDGING = "awaiting_judging", "심사 대기"
    AWAITING_APPEAL_RULING = "awaiting_appeal_ruling", "이의 심판 대기"
    AWAITING_DISTRIBUTION = "awaiting_distribution", "배분 대기"
    AWAITING_HANDOVER_RELEASE = "awaiting_handover_release", "인수 확인 대기"
    AWAITING_SELLER_REGISTRATION = "awaiting_seller_registration", "지급대행 등록 대기"

    # --- 네 차례 -------------------------------------------------------------
    # 마감 전(#245) — 예전 이름은 `AWAITING_DEADLINE`("마감 대기")이었다. 그 이름은
    # 거짓이었다: 마감 전에는 기다리는 것 말고도 할 일이 있다 — 자료와 체크리스트를
    # 고치는 것(제출 화면은 이미 기존 제출을 불러와 POST 대신 PUT을 스스로 골라
    # 보낸다). `contests.submission_api.update_submission`이 거절하는 유일한 시각 조건이
    # `_reject_if_past_deadline`(`Clock.now() >= contest.deadline_at`)이므로, 이
    # 값도 같은 조건(`now < contest.deadline_at`)에서 나와야 화면이 시키는 대로
    # 했는데 API가 거절하는 일이 없다.
    CAN_EDIT_SUBMISSION = "can_edit_submission", "제출물 수정 가능"
    # 마감 전인데 본인확인이 `verified`가 아닌 경우(#250, ADR-0025) — 가장 흔한
    # 실사용 경로는 2년 미이용으로 스캔이 신원만 파기한 `expired`다(#102). 이
    # 값을 두지 않으면 `CAN_EDIT_SUBMISSION`을 그대로 돌려주게 되는데,
    # `contests.submission_api.update_submission`은 그 시각 조건(`now < deadline_at`)
    # 뿐 아니라 `_require_verification`도 함께 검사한다 — 조건이 갈리면 화면은
    # "수정할 수 있습니다"라고 말하고 서버는 403을 낸다(이 파일 module docstring이
    # 경계하는 바로 그 사고이자, #250 코드리뷰가 실제로 잡아낸 것이다). 자료·
    # 요구사항 응답 자체는 여전히 읽을 수 있다 — ADR-0025가 지우는 것은 신원
    # 정보이지 제출물이 아니다.
    NEEDS_REVERIFICATION = "needs_reverification", "본인확인 필요"
    CAN_APPEAL = "can_appeal", "이의 제기 가능"
    REQUEST_PAYOUT = "request_payout", "지급 요청"
    SUBMIT_TAX_IDENTITY = "submit_tax_identity", "세무 신원 제출"

    # --- 끝난 일 -------------------------------------------------------------
    NOT_SELECTED = "not_selected", "미선정"
    PAYOUT_COMPLETE = "payout_complete", "지급 완료"
    # 무료 공모전(#417, ADR-0048) 전용 — 수상은 했지만 Handover·지급 절차 자체가
    # 없어 더 기다리거나 할 일이 없다. 유료 경로의 `AWAITING_HANDOVER_RELEASE`
    # 부터 `PAYOUT_COMPLETE`까지가 이 값 하나로 줄어든다.
    AWARDED = "awarded", "선정됨"
    # --- 다시 네 차례(실이체 재시도) -------------------------------------------
    # Seller 등록은 끝났는데(READY) 실제 이체 자체가 벤더 쪽에서 거절/미확정인
    # 경우다(#57 코드리뷰 지적 1/7, 3차) — Payout.status만 보면 두 대기가 다
    # 풀린 것처럼 보이지만 Payout.transfer_status가 FAILED다. 이 값을 두지
    # 않으면 「내 참가 현황」이 PAYOUT_COMPLETE로 잘못 말하거나
    # AWAITING_SELLER_REGISTRATION으로 잘못 되돌린다.
    RETRY_TRANSFER = "retry_transfer", "실이체 재시도 필요"
    # Payout이 이미 최종 확정(CONFIRMED)된 뒤에 실이체 실패가 뒤늦게
    # 확인된 경우다(#57 코드리뷰 지적 4, 2차 — payout.changed 웹훅이 지연
    # 도착한다) — Developer 쪽 자기 서비스 재시도 경로가 아직 없다(ADR-0008에
    # 남긴 한계). AWAITING_SELLER_REGISTRATION으로 뭉치면 "Seller 등록이
    # 안 끝났다"는 다른 사실을 말하게 되고, PAYOUT_COMPLETE로 뭉치면 이
    # 티켓이 가장 경계하는 그 거짓말이 된다.
    AWAITING_TRANSFER_RESOLUTION = "awaiting_transfer_resolution", "지급 처리 확인 중"


def next_action_for(submission) -> str:
    """이 Submission 에 대해 Developer 가 지금 할 일(또는 기다리는 것)을 하나 고른다.

    호출부는 `Submission` 을 관련 객체와 함께 미리 가져와야 한다 — 이 함수는
    행마다 새 조회를 내지 않는다(목록이 N+1 이 되면 참가가 쌓일수록 느려진다).
    위 앱(채점·이의·선정·지급)의 관계는 그 앱이 `ports.NEXT_ACTION_RELATIONS` 에 올린
    것을 `select_related(*related(NEXT_ACTION_RELATIONS))` 로 당긴다(#1102).
    마감 전 분기가 보는 `developer__user__verification` 도 같은 규율이다 —
    호출부가 select_related 로 미리 당겨 둬야 한다(`contests.submission_api`의
    `get_my_submission`·`get_submission`·`list_my_participation` 참고).
    """

    contest = submission.contest
    now = Clock.now()

    # 마감 전 — 아직 제출물을 고칠 수 있다(#245)... **단, 본인확인이 열려
    # 있을 때만이다(#250).** `contests.submission_api.update_submission`이 시각
    # 조건(`_reject_if_past_deadline`)과 `_require_verification`을 **함께**
    # 검사하므로, 이 함수도 같은 두 조건을 함께 봐야 한다 — 하나만 보면
    # 화면은 "수정할 수 있습니다"라고 말하고 서버는 403을 낸다. 조건은
    # 글자 그대로 같은 판정처(`Contest.Status.SUBMISSION_REQUIRES_
    # VERIFICATION`)를 재사용한다 — 두 벌로 쓰면 이 모듈의 docstring이
    # 경계하는 바로 그 사고가 난다.
    if now < contest.deadline_at:
        # 무료 공모전(#416, ADR-0048)은 본인확인 자체를 요구하지 않는다 —
        # `contests.submission_api._require_verification_unless_free`와 같은
        # 예외를 여기서도 지켜야 한다. 지키지 않으면 본인확인을 한 적 없는
        # 무료 공모전 제출자가 마감 전인데도 NEEDS_REVERIFICATION을 받는다
        # (본인확인이 verified가 아니므로) — 화면은 "본인확인이 필요하다"고
        # 말하는데 서버는 애초에 본인확인 없이 이미 받아 준 제출이다.
        if (
            not contest.is_free
            and Contest.Status.SUBMISSION_REQUIRES_VERIFICATION(contest.status)
            and not _owner_identity_is_verified(submission)
        ):
            return NextAction.NEEDS_REVERIFICATION
        return NextAction.CAN_EDIT_SUBMISSION

    if not IS_SCORED.get()(submission):
        from .scoring_hold import is_size_held

        if is_size_held(submission):
            if APPEAL_STATE.get()(submission) == "pending":
                return NextAction.AWAITING_APPEAL_RULING
            return NextAction.SCORING_HELD_SIZE
        return NextAction.AWAITING_SCORING

    # 채점이 끝났다 — 이의가 여기서 갈린다.
    appeal = APPEAL_STATE.get()(submission)
    if appeal == "pending":
        return NextAction.AWAITING_APPEAL_RULING

    payout_action = PAYOUT_ACTION.get()(submission)
    if payout_action is not None:
        return payout_action

    # 아직 돈이 걸린 단계에 닿지 않았다 — 이의를 낼 수 있는지 본다. 조건은
    # `appeals.api.create_appeal` 의 전제와 같다: 채점이 끝났고(위에서 확인),
    # 아직 이의가 없고, 기한(심사기간 종료) 안이다. **무료 공모전은 여기서도
    # 제외한다**(#417, ADR-0048) — `appeals.api.create_appeal`이 `contest.
    # is_free`를 보고 404로 거절하므로, 조건을 두 벌로 쓰지 않으려면 여기도
    # 같은 예외를 져야 한다.
    if not contest.is_free and appeal == "none" and contest.appeal_window_open(now):
        return NextAction.CAN_APPEAL

    if _is_awarded_to_someone_else(submission):
        return NextAction.NOT_SELECTED

    if contest.judging_window_open(now):
        return NextAction.AWAITING_JUDGING

    # 무료 공모전은 여기서 배분으로 넘어가지 않는다(#417) — 상금·Escrow가
    # 없으므로 「무응답 N일」이 지나도 나눠 줄 돈이 없다. 심사 기간 안에
    # 수상하지 않았다는 것은 곧 「수상 없이 끝났다」이고, 참가자 전원에게
    # 그 사실은 같다(아무도 선정되지 않았다).
    if contest.is_free:
        return NextAction.NOT_SELECTED

    return NextAction.AWAITING_DISTRIBUTION


def _is_awarded_to_someone_else(submission) -> bool:
    awarded_id = AWARDED_SUBMISSION_ID.get()(submission.contest)
    return awarded_id is not None and awarded_id != submission.id


def _owner_identity_is_verified(submission) -> bool:
    """이 Submission 주인의 본인확인이 지금 `verified` 인가(#250).

    `verification.models.Verification.is_verified`와 같은 질문을 다시 묻는다 —
    다만 여기서는 새 조회를 내지 않는다(모듈 docstring). `getattr(user,
    "verification", None)`이 안전한 이유는 `Verification.user`가
    `related_name="verification"`인 역방향 OneToOne이라, 행이 없으면 Django가
    `RelatedObjectDoesNotExist`(`AttributeError`의 서브클래스)를 던지고 `getattr`
    의 기본값이 그것을 그대로 삼키기 때문이다 — 이 함수 바로 위 `AWAITING_SCORING`
    분기의 `hasattr(submission, "score")`와 같은 관용구다.
    """

    verification = getattr(submission.developer.user, "verification", None)
    return verification is not None and verification.is_verified






