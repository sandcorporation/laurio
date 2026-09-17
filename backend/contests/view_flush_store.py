"""「바뀐 공모전」 집합 — 조회수 옮기기 스캔(`contests.view_flush`)이 무엇을 옮길지
아는 유일한 자리 (#446, spec #444).

`contests.view_tracking.record_view`가 Redis 누적 수를 올릴 때마다 그 Contest id를
여기 더한다. Django 캐시 API에는 SADD/SPOP 같은 집합 연산이 없다(`get`/`set`/`incr`/
`get_many`뿐이다) — 그래서 이 저장소는 `caches["sessions"]`를 쓰지 않고 작은 interface
뒤에 둔다: 운영은 그 캐시가 가리키는 것과 같은 Redis 인스턴스(`SESSION_REDIS_URL`, 키
접두어만 나눈다 — `contests.view_tracking`이 이미 그 자리를 그렇게 나눠 쓰는 것과 같은
이유로 새 Redis를 배선하지 않는다)를, 테스트는 클래스 레벨 메모리 집합을 쓴다
(`core.events.FakeEventBus`와 같은 관용구 — `tests/conftest.py`의 autouse 픽스처가 매
테스트 전후로 비운다).

**떼어 내기는 원자적이다.** `pop_all`은 Lua 스크립트(`SMEMBERS` + `DEL`을 한 EVAL로)를
써서 "지금까지 쌓인 것을 통째로 읽고 지운다"를 한 왕복으로 한다 — 그 사이에 끼어든
`mark_changed` 호출이 지워지거나, 읽은 뒤 지우는 사이에 새로 들어온 id를 놓치고
영원히 잃어버리는 경우를 없앤다(후자가 나더라도 다음 `mark_changed`가 그 id를 다시
넣으므로 최악의 경우도 "한 번 더 늦게 옮겨진다"이지 "잃어버린다"가 아니다).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from django.conf import settings


@runtime_checkable
class ChangedContestsStore(Protocol):
    def mark_changed(self, contest_id: int) -> None: ...
    def pop_all(self) -> list[int]: ...


class InMemoryChangedContestsStore:
    """테스트 전용 — 네트워크 없이 결정적이다(`core.events.FakeEventBus`와 같은 이유로
    클래스 레벨 상태: 조회를 기록하는 요청과 스캔을 돌리는 요청이 서로 다른 인스턴스라도
    값을 공유해야 한다)."""

    _ids: set[int] = set()

    def mark_changed(self, contest_id: int) -> None:
        InMemoryChangedContestsStore._ids.add(contest_id)

    def pop_all(self) -> list[int]:
        ids = list(InMemoryChangedContestsStore._ids)
        InMemoryChangedContestsStore._ids.clear()
        return ids


_CHANGED_KEY = "contestview:changed"

# 지금까지 쌓인 것을 한 왕복으로 읽고 비운다 — `pop_all`을 SMEMBERS 뒤 DEL 두 왕복으로
# 짜면 그 사이에 새로 들어온 id가 DEL에 함께 지워질 수 있다.
_POP_ALL_SCRIPT = """
local ids = redis.call('SMEMBERS', KEYS[1])
redis.call('DEL', KEYS[1])
return ids
"""


class RedisChangedContestsStore:
    """운영 구현 — `contests.view_tracking`이 조회수 자체를 저장하는 것과 같은 Redis
    인스턴스를 키 접두어로만 나눠 쓴다(`SESSION_REDIS_URL`, ADR-0018)."""

    def __init__(self) -> None:
        import redis

        self._client = redis.Redis.from_url(settings.SESSION_REDIS_URL)

    def mark_changed(self, contest_id: int) -> None:
        self._client.sadd(_CHANGED_KEY, contest_id)

    def pop_all(self) -> list[int]:
        raw_ids = self._client.eval(_POP_ALL_SCRIPT, 1, _CHANGED_KEY)
        return [int(raw_id) for raw_id in raw_ids]


def get_changed_contests_store() -> ChangedContestsStore:
    if getattr(settings, "_RUNNING_TESTS", False):
        return InMemoryChangedContestsStore()
    return RedisChangedContestsStore()
