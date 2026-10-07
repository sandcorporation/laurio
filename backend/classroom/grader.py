"""강의실 채점 grader — 비동기 상주 프로세스 (#584, ADR-0059).

`manage.py grader` 가 돌린다. 브로커가 없다 — **DB 가 큐다**: 즉시 채점과 60초 스캔이
`ClassroomSubmission.scoring_queued_at` 을 찍으면(`classroom.scoring.enqueue_scoring`) 이
프로세스가 1초마다 후보를 읽어 임대를 집고 채점한다.

**동시성.** 전역 `CLASSROOM_GRADER_GLOBAL_LIMIT`(64)건, 채점 연결(클래스)당
`CLASSROOM_GRADER_PER_CONNECTION_LIMIT`(8)건 — 둘 다 설정값이고 이 **프로세스 안**의 상한이다
(grader 는 한 개만 띄운다; 둘이 떠도 「두 번 불러도 벤더 한 번」은 임대가 지킨다). 벤더를 기다리는
건 코루틴이라 64건이 스레드 64개가 아니다.

**DB 연결은 정확히 하나다.** DB 일(임대 집기·읽기·결과 쓰기)은 **스레드 하나**(`grader-db`)에서만
한다 — 그 스레드가 Django 연결 하나를 계속 쥐고(작업마다 닫지 않는다) 매 작업 **전에**
`close_old_connections()` 로 죽은 연결을 걷으며, `OperationalError`/`InterfaceError` 로 실패하면
연결을 닫고 한 번 다시 한다(DB 재시작·pgbouncer 교체 뒤 죽은 연결). 풀러(pgbouncer) 서버 연결 20 중
grader 몫은 그래서 최대 1 이다. 그 스레드에는 **짧은 DB 일만** 둔다: 알림이 내는 실시간 신호(버스·
Redis)는 DB 스레드에서 보내지 않고 모아(`core.events.collect_instead_of_publishing`) 별도 작은
풀(`grader-events`)에서 보낸다. 소스 읽기(스토리지·저장소 clone, 문법 검사, 최대 수십 MB·수 초)는
**DB 를 쓰지 않는** 따로 둔 풀(`CLASSROOM_GRADER_SOURCE_THREADS`, 기본 8)에서 돌고 — DB 에서 미리 꺼낸
값만 받는다(시험이 못 박는다: DB 스레드가 아닌 스레드에서 쿼리는 0번). 벤더를 기다리는 동안은 DB
연결도 트랜잭션도 없다.

**임대가 닳지 않게.** 임대(240초)는 집는 순간부터 가므로 소스 준비·스레드 대기가 길면 벤더를 기다리기
전에 거의 닳는다. 그래서 ① 이 grader 가 처리 중인 시도는 후보에서 뺀다(만료돼도 자기 것을 다시 집지
않는다) ② 벤더를 부르기 직전에 임대를 다시 늘린다(`extend_lease`, 내 임대일 때만 — 실패하면 벤더를
부르지 않는다).

**SIGTERM** 이면 새 후보를 그만 잡고 하던 채점은 끝낸다(`stop_grace_period` 4분). 죽으면 임대가
만료된 뒤 다시 줍힌다.

시험·dev 시임: `run_round()` 가 한 바퀴(큐가 빌 때까지 집어 끝까지)를 돌고, `grade_inline()`
이 한 시도를 동기로 채점한다(`CLASSROOM_GRADER_INLINE`, pytest 만 — 동기 벤더 길이라 벤더를
`requests` 로 흉내 내는 시험이 그대로 돈다).
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from functools import partial
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

from django.conf import settings
from django.db import InterfaceError, OperationalError, close_old_connections, connection, connections

from core.clock import Clock
from core.events import publish_all
from core.llm_scoring import LLMAdapterError

from . import scoring
from .scoring import Concluded, PreparedScoring, VendorOutcome

logger = logging.getLogger(__name__)

#: 코루틴 하나가 벤더를 기다리는 시간의 바깥 한도 — 어댑터의 타임아웃(180초)이 먼저 걸리지만
#: 연결이 이상하게 걸려도 임대(240초) 안에서 끝나도록 한 번 더 감싼다.
VENDOR_OUTER_TIMEOUT_SECONDS = scoring.CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS + 15


def _keep_connection_open() -> None:
    """DB 스레드가 시작할 때 — 이 스레드의 연결은 `CONN_MAX_AGE` 로 닫지 않는다. 기본값(0)이면 작업마다
    `close_old_connections()` 가 연결을 닫아 매번 다시 연다. 이 스레드의 연결 객체에만 적용한다."""

    connection.settings_dict = {**connection.settings_dict, "CONN_MAX_AGE": None}


def new_owner() -> str:
    return f"{socket.gethostname()[:30]}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


class Grader:
    def __init__(
        self,
        *,
        global_limit: int | None = None,
        per_connection_limit: int | None = None,
        poll_seconds: float | None = None,
        owner: str | None = None,
    ) -> None:
        self.global_limit = global_limit or settings.CLASSROOM_GRADER_GLOBAL_LIMIT
        self.per_connection_limit = per_connection_limit or settings.CLASSROOM_GRADER_PER_CONNECTION_LIMIT
        self.poll_seconds = poll_seconds if poll_seconds is not None else settings.CLASSROOM_GRADER_POLL_SECONDS
        self.owner = owner or new_owner()
        #: 결과는 `run_round`(시험·수동)에서만 모은다 — 상주 루프가 영원히 쌓지 않는다.
        self.results: list[dict] = []
        self._collect = False
        self._tasks: set[asyncio.Task] = set()
        self._active_ids: set[int] = set()
        self._per_class: Counter[int] = Counter()
        # DB 스레드는 하나뿐이다 — 여럿이면 연결도 여럿이 된다(사용자 결정: grader 의 DB 연결은 정확히 1개).
        self._pool = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="grader-db", initializer=_keep_connection_open
        )
        self._source_pool = ThreadPoolExecutor(
            max_workers=settings.CLASSROOM_GRADER_SOURCE_THREADS, thread_name_prefix="grader-source"
        )
        # 실시간 신호를 버스로 보내는 작은 풀 — DB 를 쓰지 않는다.
        self._events_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="grader-events")

    # --- DB 일은 스레드 풀에서, 끝나면 연결을 닫는다 -------------------------------------------

    async def _db(self, fn, *args, **kwargs):
        """DB 스레드(하나)에서 돌린다 — 그 스레드의 연결을 계속 쓰므로 작업 **전**에 죽은 연결을 걷고,
        연결이 끊겨 실패하면 닫고 한 번 다시 한다."""

        def _run():
            close_old_connections()
            try:
                return fn(*args, **kwargs)
            except (OperationalError, InterfaceError):
                connections.close_all()
                return fn(*args, **kwargs)

        return await asyncio.get_running_loop().run_in_executor(self._pool, _run)

    async def _write(self, fn, *args, **kwargs):
        """결과 쓰기 — 행이 다른 연결에 잠겨 `lock_busy` 면 임대가 내 것인 동안 같은 결과를 잠시 뒤 다시
        쓴다(그 사이 DB 스레드는 다른 시도를 처리한다). `CLASSROOM_GRADER_LOCK_RETRY_SECONDS` 가 지나면
        포기한다 — 임대가 만료된 뒤 다시 줍힌다."""

        deadline = asyncio.get_running_loop().time() + settings.CLASSROOM_GRADER_LOCK_RETRY_SECONDS
        while True:
            result = await self._db(fn, *args, **kwargs)
            if result.get("status") != "lock_busy" or asyncio.get_running_loop().time() >= deadline:
                if result.get("status") == "lock_busy":
                    logger.warning("grader: 결과를 쓰지 못했다(행이 계속 잠겨 있다) — 임대 만료 뒤 다시 줍는다: %s", result)
                return result
            await asyncio.sleep(1.0)

    async def _source(self, fn, *args, **kwargs):
        """소스 읽기 풀 — **DB 를 쓰지 않는다**(받는 값은 DB 에서 미리 꺼낸 것뿐). 시험이 못 박는다."""

        return await asyncio.get_running_loop().run_in_executor(self._source_pool, partial(fn, *args, **kwargs))

    async def _publish(self, events: list) -> None:
        if events:
            await asyncio.get_running_loop().run_in_executor(self._events_pool, publish_all, events)

    # --- 줍기 ----------------------------------------------------------------------------

    @property
    def active(self) -> int:
        return len(self._tasks)

    async def pick(self) -> int:
        """집을 수 있는 만큼 임대를 집어 채점을 시작한다. 시작한 건수를 돌려준다."""

        free = self.global_limit - self.active
        if free <= 0:
            return 0
        as_of = await self._db(Clock.now)
        full = [cid for cid, n in self._per_class.items() if n >= self.per_connection_limit]
        candidates = await self._db(
            scoring.next_candidates,
            as_of,
            limit=free,
            exclude_class_ids=full,
            exclude_ids=set(self._active_ids),
        )
        started = 0
        for submission_id, class_id in candidates:
            if self.active >= self.global_limit or self._per_class[class_id] >= self.per_connection_limit:
                continue
            if not await self._db(scoring.claim_attempt, submission_id, owner=self.owner, as_of=as_of):
                continue
            self._per_class[class_id] += 1
            self._active_ids.add(submission_id)
            task = asyncio.create_task(self._process(submission_id, class_id, as_of))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
            started += 1
        return started

    async def _process(self, submission_id: int, class_id: int, as_of) -> None:
        owner = self.owner
        events: list = []
        try:
            prepared = await self._db(
                scoring.prepare_claimed_head, submission_id, owner=owner, as_of=as_of
            )
            if not isinstance(prepared, Concluded):
                prepared = await self._source(scoring.prepare_tail, prepared)
            if isinstance(prepared, Concluded):
                result = await self._write(
                    scoring.conclude_scoring,
                    submission_id,
                    owner=owner,
                    apply=prepared.apply,
                    events_out=events,
                )
            elif not await self._db(self._extend, submission_id):
                # 준비가 너무 길어 임대가 다른 grader 에게 넘어갔다 — 벤더를 부르지 않는다.
                result = {"submission_id": submission_id, "status": "lease_lost"}
            else:
                outcome = await self._vendor(prepared)
                result = await self._write(scoring.finish_scoring, prepared, outcome, events_out=events)
        except Exception as exc:  # noqa: BLE001 - 한 시도의 실패가 나머지를 막으면 안 된다.
            result = await self._write(
                scoring.record_unexpected_failure, submission_id, owner=owner, exc=exc, events_out=events
            )
        finally:
            self._active_ids.discard(submission_id)
            self._per_class[class_id] -= 1
            if not self._per_class[class_id]:
                del self._per_class[class_id]
        await self._publish(events)  # 커밋된 뒤에, DB 스레드가 아닌 곳에서
        if self._collect:
            self.results.append(result)
        logger.info(
            "grader: submission=%s class=%s status=%s active=%s",
            submission_id,
            class_id,
            result.get("status"),
            self.active - 1,
        )

    def _extend(self, submission_id: int) -> bool:
        return scoring.extend_lease(submission_id, owner=self.owner, as_of=Clock.now())

    @staticmethod
    async def _vendor(prepared: PreparedScoring) -> VendorOutcome:
        try:
            return await asyncio.wait_for(
                scoring.call_vendor_async(prepared), timeout=VENDOR_OUTER_TIMEOUT_SECONDS
            )
        except TimeoutError:
            return VendorOutcome(error=LLMAdapterError("벤더 응답을 시간 안에 받지 못했다(grader 한도)."))

    # --- 루프 ----------------------------------------------------------------------------

    async def run_forever(self, stop: asyncio.Event) -> None:
        """`stop` 이 서기 전까지 줍는다. 서면 새로 잡지 않고 하던 채점을 끝낸 뒤 돌아온다."""

        logger.info(
            "grader 시작: owner=%s 전역 %s·연결당 %s", self.owner, self.global_limit, self.per_connection_limit
        )
        failures = 0
        while not stop.is_set():
            try:
                await self.pick()
                failures = 0
            except Exception:  # noqa: BLE001 - DB 가 잠깐 끊겨도(부팅 중 마이그레이션 포함) 루프는 산다.
                failures += 1
                if failures == 1:
                    logger.exception("grader: 후보를 읽다 예외 — 간격을 늘려 다시 읽는다")
                else:
                    logger.warning("grader: 후보를 읽지 못했다(%s번째)", failures)
            # 실패가 이어지면 간격을 늘린다(최대 10초) — 마이그레이션이 끝나기 전에 뜬 grader 가 로그를 채우지 않게.
            wait = min(self.poll_seconds * (2 ** min(failures, 5)), 10) if failures else self.poll_seconds
            try:
                await asyncio.wait_for(stop.wait(), timeout=wait)
            except TimeoutError:
                pass
        logger.info("grader 종료 신호: 하던 채점 %s건을 끝낸다", self.active)
        await self.drain()
        self._shutdown_pools()

    def _shutdown_pools(self) -> None:
        # DB 스레드가 쥔 연결을 그 스레드에서 닫고 풀을 끝낸다.
        self._pool.submit(connections.close_all).result()
        self._pool.shutdown(wait=True)
        self._source_pool.shutdown(wait=True)
        self._events_pool.shutdown(wait=True)

    async def drain(self) -> None:
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)

    async def run_round(self) -> list[dict]:
        """한 바퀴 — 루프와 같게 집고, 하나가 끝날 때마다(또는 간격마다) 다시 집어, 큐가 비고 하던 것이
        모두 끝날 때까지 돈다."""

        self._collect = True
        while True:
            await self.pick()
            if not self._tasks:
                break
            await asyncio.wait(set(self._tasks), timeout=self.poll_seconds, return_when=asyncio.FIRST_COMPLETED)
        self._shutdown_pools()
        return self.results


def run_round(**kwargs) -> list[dict]:
    """동기 시임(시험·수동 점검) — grader 의 한 바퀴를 돌려 결과 목록을 돌려준다."""

    return asyncio.run(Grader(**kwargs).run_round())


def grade_inline(submission_id: int) -> dict | None:
    """한 시도를 이 자리에서 동기로 채점한다(`CLASSROOM_GRADER_INLINE`, pytest 만). 임대를 집지
    못하면 `None`. 세 걸음(임대·준비·결과)은 상주 grader 와 같은 함수다 — 벤더만 동기 길이다."""

    owner = f"inline-{uuid.uuid4().hex[:8]}"
    as_of = Clock.now()
    if not scoring.claim_attempt(submission_id, owner=owner, as_of=as_of):
        return None
    try:
        prepared = scoring.prepare_claimed_attempt(submission_id, owner=owner, as_of=as_of)
        if isinstance(prepared, Concluded):
            return scoring.conclude_scoring(submission_id, owner=owner, apply=prepared.apply)
        if not scoring.extend_lease(submission_id, owner=owner, as_of=Clock.now()):
            return {"submission_id": submission_id, "status": "lease_lost"}
        outcome = scoring.call_vendor_sync(prepared)
        return scoring.finish_scoring(prepared, outcome)
    except Exception as exc:  # noqa: BLE001
        return scoring.record_unexpected_failure(submission_id, owner=owner, exc=exc)



