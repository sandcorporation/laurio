"""실시간 신호 버스 (ADR-0046) — 「바뀌었다」는 사실만 실어 나르는 새 시임 하나.

강의실이 제출·채점·알림 같은 사실을 새로고침 없이 화면에 전달하려면, 커밋 뒤에
"이 수신자에게 이런 일이 있었다"를 알리는 자리가 필요하다. 다른 외부 의존성
(스토리지·LLM·PG 등)과 같은 모양으로 갈아끼운다(ADR-0007) — 테스트용
`FakeEventBus`(기록만 한다)와 배포·dev용 Redis pub/sub(`core.events_redis.
RedisEventBus`) 둘이고, `EVENT_BUS_ADAPTER_MODE` 설정이 고른다.

**신호는 식별자만 싣는다** — `kind`(무슨 일)·`recipient_id`(누구에게)·`payload`
(대상 식별자들, 예: class_id·problem_id·submission_id). 화면은 신호를 받으면
데이터를 신호에서 직접 읽지 않고 기존 API를 다시 부른다 — 스트림은 진실의
출처가 아니다(ADR-0046 결과).

**수신자는 발행하는 자리가 정한다** — 이 모듈은 "누구에게 갈지"를 판단하지
않는다. 신호 종류(`kind`)의 이름도 이 모듈이 정하지 않는다: 강의실 전용
종류는 강의실 앱이 정의한다(`classroom.events`) — 이 모듈은 공유층
(`core`)에 있으므로 앱 경계 테스트(#269)가 강의실을 몰라야 한다.

**배포 환경의 부팅 가드가 있다**(#380) — 다른 `*_ADAPTER_MODE`(#83)와 같은
원칙으로 `IS_DEPLOYED_ENVIRONMENT`에서 fake 바인딩을 거부한다
(`config/settings.py`)와 dotted path가 가리키는 값이 깨졌을 때를 잡는
`core.checks.check_event_bus_adapter_mode`가 함께 선다. `.env.staging`/
`.env.prod`가 `core.events_redis.RedisEventBus`를 채우는 것과 같은 커밋에서
더해졌다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from django.db import transaction

from django.conf import settings

from .adapters import resolve_adapter


@dataclass(frozen=True)
class Event:
    kind: str
    recipient_id: int
    payload: dict


@runtime_checkable
class EventSubscription(Protocol):
    """`EventBus.subscribe()`가 돌려주는 구독 하나 — **비동기** 컨텍스트
    매니저다(#456). 폴링이 스레드를 쓰지 않으려면 대기 자체가 이벤트 루프
    위에서 논블로킹으로 일어나야 하고, 그러려면 `poll`이 코루틴이어야 한다
    — 스트림 하나가 스레드 하나를 붙잡지 않는다.

    `__aexit__`에서 반드시 구독을 정리한다(AC "연결을 닫으면 구독이
    정리된다") — Redis 어댑터는 여기서 pubsub을 unsubscribe·close한다."""

    async def poll(self, *, timeout: float) -> list[Event]: ...
    async def __aenter__(self) -> "EventSubscription": ...
    async def __aexit__(self, *exc_info) -> None: ...


@runtime_checkable
class EventBus(Protocol):
    def publish(self, event: Event) -> None: ...
    def subscribe(self, recipient_id: int) -> EventSubscription: ...


class _FakeSubscription:
    """fake 버스 전용 구독 — 실제로 기다리지 않는다. `poll`은 `timeout`과
    무관하게 즉시 지금까지 쌓인 것만 비워 돌려준다. SSE 뷰가 이것으로
    반복 호출해도(폴백 대기 없이) 무한 루프가 되지 않는 이유는 pytest가
    `itertools.islice`로 정해진 횟수만 다음 값을 요청하기 때문이다."""

    def __init__(self, recipient_id: int) -> None:
        self._recipient_id = recipient_id

    async def poll(self, *, timeout: float) -> list[Event]:
        queue = FakeEventBus._queues.get(self._recipient_id, [])
        FakeEventBus._queues[self._recipient_id] = []
        return queue

    async def __aenter__(self) -> "_FakeSubscription":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None


class FakeEventBus:
    """dev·테스트 전용, 네트워크 없이 결정적이다(ADR-0007과 같은 관용구).

    `storage.adapters.fake.FakeStorageAdapter._store`와 같은 이유로 **클래스
    레벨** 딕셔너리다 — `get_event_bus()`가 호출마다 새 인스턴스를 만들어도
    (`resolve_adapter`의 `fake_factory`가 매번 새 `FakeEventBus()`를 부른다)
    발행 요청과 구독 요청이 서로 다른 HTTP 요청(그래서 서로 다른 인스턴스)
    이라 값을 공유해야 하기 때문이다. `tests/conftest.py`의 autouse
    픽스처가 매 테스트 전후로 비운다."""

    _queues: dict[int, list[Event]] = {}

    #: 받는 사람마다 쌓아 두는 상한 — 배포 환경이 버스 값을 모르는 동안(#380 전)
    #: staging 도 이 fake 로 뜨는데, 구독자가 없는 gunicorn·celery 프로세스에서는
    #: 아무도 비우지 않아 신호가 영원히 쌓인다. 오래된 것부터 버린다.
    MAX_QUEUED_PER_RECIPIENT = 100

    def publish(self, event: Event) -> None:
        queue = FakeEventBus._queues.setdefault(event.recipient_id, [])
        queue.append(event)
        del queue[: -FakeEventBus.MAX_QUEUED_PER_RECIPIENT]

    def subscribe(self, recipient_id: int) -> _FakeSubscription:
        return _FakeSubscription(recipient_id)


def get_event_bus() -> EventBus:
    return resolve_adapter(
        mode=getattr(settings, "EVENT_BUS_ADAPTER_MODE", "fake"),
        fake_factory=FakeEventBus,
        not_implemented_hint=(
            "EVENT_BUS_ADAPTER_MODE 가 가리키는 dotted path를 import할 수 없다 — "
            "실물 어댑터는 core.events_redis.RedisEventBus 다(ADR-0046)."
        ),
    )


_logger = logging.getLogger(__name__)


def publish_after_commit(event: Event) -> None:
    """지금 열린 트랜잭션이 커밋된 뒤에 발행하고, **발행 실패는 경고로 남기고 넘어간다**
    (ADR-0046). 커밋되지 않은 사실이 화면에 새지 않게 하고, 커밋 뒤에는 이미 저장된
    것(Score·알림·읽음)을 버스 장애가 되돌리거나 실패로 보이게 하지 않는다 — 신호는
    빠르게 만드는 장치이지 진실의 출처가 아니고, 화면은 폴링으로 맞춰진다. 열린
    트랜잭션이 없으면 `on_commit` 이 곧바로 실행한다."""

    transaction.on_commit(lambda: _publish_safely(event))


def _publish_safely(event: Event) -> None:
    try:
        get_event_bus().publish(event)
    except Exception:  # noqa: BLE001 — 어떤 버스 오류든 화면이 폴링으로 맞춘다
        _logger.warning(
            "신호를 발행하지 못했다 (kind=%s, recipient_id=%s)",
            event.kind,
            event.recipient_id,
            exc_info=True,
        )
