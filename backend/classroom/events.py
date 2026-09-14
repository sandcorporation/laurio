"""강의실이 정의하는 실시간 신호 종류 (ADR-0046).

버스 자체(`core.events`)는 공유층에 있고 "누가 무엇을 받는가"를 모른다 —
신호 종류의 이름과 "누구에게 보낼지"는 발행하는 자리(이 앱)가 정한다(#269,
앱 경계 테스트가 강의실을 몰라야 하는 방향과 같은 이유).

지금은 `ATTEMPT_SCORED` 하나뿐이다. 이후 티켓(#381~#383)이 `attempt-submitted`·
`notification-changed`를 더할 자리도 여기다 — 새 신호 종류를 추가하고 발행
자리 하나를 더하는 것으로 끝나야, 버스·SSE 엔드포인트·BFF·프론트 훅을 매번
다시 설계하지 않는다(디스패치 노트 "그 버스/스트림 훅을 그렇게 설계하라").
"""

from __future__ import annotations

from core.events import Event, get_event_bus

#: 그 시도의 `ClassroomScore`가 생겼다 — 정상 채점이든 실패 상한에 의한
#: 플랫폼 자동 미달이든 매번 정확히 한 번(#379 AC). 그 시도를 낸 참여자에게만
#: 간다 — 강사·다른 참여자에게는 가지 않는다(#379 AC "그 참여자에게만").
ATTEMPT_SCORED = "attempt-scored"


def publish_attempt_scored(submission) -> None:
    """`classroom.scoring`이 `ClassroomScore`를 만드는 두 자리(정상 채점·
    `_finalize_platform_failure`) 모두에서 부른다.

    **내보내진 참여자에게는 보내지 않는다**(#379 AC, CONTEXT.md 「ClassMember」
    User Story 9 "내보내진 참여자는 새 신호를 받지 않아도 괜찮다") — 지난
    시도는 기존 API로 여전히 읽히므로, 실시간 신호만 조용히 거른다.

    **트랜잭션이 커밋된 뒤에 발행한다**(ADR-0046 결정) — 이 함수를 부르는
    두 자리 모두 `ClassroomScore.objects.create(...)`가 이미 자신을 감싸던
    원자 블록을 빠져나온(또는 애초에 감싸지 않은, `_finalize_platform_failure`)
    뒤라, 호출 시점에는 그 행이 이미 커밋되어 있다 — `notify_safely`가 같은
    자리에서 `transaction.on_commit` 없이도 이 규율을 지키는 것과 같은
    이유다(요청 전체를 감싸는 바깥 트랜잭션이 없다, `ATOMIC_REQUESTS` 미설정)."""

    member = submission.member
    if member.expelled_at is not None:
        return

    problem = submission.problem
    get_event_bus().publish(
        Event(
            kind=ATTEMPT_SCORED,
            recipient_id=member.user_id,
            payload={
                "class_id": problem.classroom_id,
                "problem_id": problem.id,
                "submission_id": submission.id,
            },
        )
    )
