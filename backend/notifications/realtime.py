"""알림 벨의 실시간 신호 (#381, ADR-0046).

강의실 알림(`CLASSROOM_NOTIFICATION_TYPES`)이 생기거나 읽음 상태가 바뀌면 그 알림을
받는 사람에게 `notification-changed` 를 보낸다. 신호는 「바뀌었으니 다시 물어봐라」는
식별자일 뿐이라 payload 가 비어 있다 — 벨은 기존 읽지 않은 수 API 를 다시 부른다.

**이 앱(공유층)이 정의한다.** 알림을 만들고 읽음을 바꾸는 자리가 이 앱이라, 신호를
강의실 앱에 두면 공유층이 기능 앱을 부르는 경계 예외가 생긴다(#269). 공모전 알림은
호출부가 강의실 알림인지 판정해 부르지 않으므로 신호를 내지 않는다.
"""

from __future__ import annotations

from core.events import Event, publish_after_commit

#: 프론트의 `classroom/lib/events/types.ts` 와 같은 문자열이다.
NOTIFICATION_CHANGED = "notification-changed"


def publish_notification_changed(*, recipient_id: int) -> None:
    """커밋 뒤에 발행한다 — 알림 생성이나 읽음 처리가 롤백되면 신호도 나가지 않는다."""

    publish_after_commit(Event(kind=NOTIFICATION_CHANGED, recipient_id=recipient_id, payload={}))
