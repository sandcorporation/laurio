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

from django.db import transaction

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

    **트랜잭션이 커밋된 뒤에 발행한다**(ADR-0046 결정) — `transaction.
    on_commit`을 쓴다. `_score_one`(즉시 채점·스캔이 공유하는 행 처리,
    #378)이 시도당 Score 하나를 지키는 잠금 때문에 `score_classroom_
    submission_once` 호출 전체를 `transaction.atomic()`으로 감싸므로,
    이 함수를 부르는 두 자리(성공 경로·`_finalize_platform_failure`) 모두
    지금은 열린 트랜잭션 **안**이다 — 여기서 바로 발행하면 그 트랜잭션이
    나중에 롤백돼도(#378 `_score_one`이 예외를 밖으로 던지지 않고 잡긴
    하지만) 신호는 이미 나간 뒤가 된다. `on_commit`은 지금 열린 트랜잭션이
    없으면 즉시 실행하므로(HTTP 시임으로 직접 두들기는 미래의 호출자에게도)
    양쪽 다 안전하다.

    **pytest가 이 콜백을 보려면 `django_capture_on_commit_callbacks(execute=
    True)`로 감싸야 한다** — pytest-django는 테스트 전체를 하나의 바깥
    트랜잭션(끝나면 롤백)으로 감싸서 돌리므로, 그 안에서 등록된
    `on_commit` 콜백은 실제 커밋이 없으면 실행되지 않는다(테스트가 실제로
    이 함수를 거치는 요청을 그 컨텍스트 매니저 밖에서만 부르면 발행 자체가
    조용히 스킵된 것처럼 보인다 — 실패가 아니라 실행되지 않은 것이다)."""

    member = submission.member
    if member.expelled_at is not None:
        return

    problem = submission.problem
    event = Event(
        kind=ATTEMPT_SCORED,
        recipient_id=member.user_id,
        payload={
            "class_id": problem.classroom_id,
            "problem_id": problem.id,
            "submission_id": submission.id,
        },
    )
    transaction.on_commit(lambda: get_event_bus().publish(event))
