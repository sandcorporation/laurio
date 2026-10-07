"""강의실 채점 grader 를 띄운다(#584, ADR-0059) — `classroom.grader` 의 상주 프로세스.

`docker compose` 의 `grader` 서비스가 이 명령 하나를 돈다. SIGTERM·SIGINT 이면 새 후보를
그만 잡고 하던 채점을 끝낸 뒤 종료한다.
"""

from __future__ import annotations

import asyncio
import signal

from django.core.management.base import BaseCommand

from classroom.grader import Grader


class Command(BaseCommand):
    help = "강의실 채점 grader 상주 프로세스 — DB 의 큐에서 시도를 집어 비동기로 채점한다."

    def handle(self, *args, **options):
        asyncio.run(self._run())

    async def _run(self) -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await Grader().run_forever(stop)
