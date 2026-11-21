"""강의실 채점 grader 를 띄운다(#584, ADR-0059) — `classroom.grader` 의 상주 프로세스.

`docker compose` 의 `grader` 서비스가 이 명령 하나를 돈다. SIGTERM·SIGINT 이면 새 후보를
그만 잡고 하던 채점을 끝낸 뒤 종료한다.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from django.conf import settings
from django.core.management.base import BaseCommand

from core import llm_metrics
from core.heartbeat import start_heartbeat

from classroom.grader import Grader


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "강의실 채점 grader 상주 프로세스 — DB 의 큐에서 시도를 집어 비동기로 채점한다."

    def handle(self, *args, **options):
        asyncio.run(self._run())

    async def _run(self) -> None:
        # 이 프로세스의 LLM 지표를 긁게 연다(#585) — grader 는 단일 프로세스라 합산이 필요 없다. 0 이면 끈다.
        if settings.CLASSROOM_GRADER_METRICS_PORT:
            llm_metrics.serve(settings.CLASSROOM_GRADER_METRICS_PORT)
        # `/api/health` 의 생존 신호(#949) — 채점 루프와 따로 스레드로 낸다(LLM 호출이 길어도 멈추지 않게).
        start_heartbeat("grader")
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()

        def on_signal(sig: signal.Signals) -> None:
            # 종료 코드 0 의 재시작이 되풀이될 때 누가 보냈는지 로그로 남긴다(#1192) — 정상 종료는 신호 하나뿐이다.
            logger.warning("grader: %s 를 받았다 — 하던 채점을 끝내고 종료한다(종료 코드 0)", sig.name)
            stop.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, on_signal, sig)
        await Grader().run_forever(stop)
