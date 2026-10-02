"""부팅 경로를 새 프로세스에서 돌리는 도우미 — 매번 파이썬을 새로 띄우지 않는다
(2026-10-02, 시험 하나 CPU 1초 한도).

`tests/test_deployment_config.py` 는 `manage.py check` 를 별도 프로세스로 돌려야
한다 — 가드가 `config/settings.py` 임포트 시점과 `django.setup()` 이후에 걸려
있어서 같은 프로세스에서는 다시 태울 수 없다(그 파일 docstring). 예전에는
`subprocess.run([python, "manage.py", ...])` 이라 시험마다 파이썬 기동과
서드파티 임포트(pydantic·celery·sentry·Django)를 처음부터 했고, 그것만으로
한 번에 CPU 1초를 넘었다.

지금은 `multiprocessing` 의 forkserver 가 **설정과 무관한** 무거운 모듈만
미리 읽어 두고, 시험마다 거기서 fork 한 자식이 환경변수를 바꾼 뒤 `manage.py`
가 하는 일을 그대로 한다. 설정 모듈·앱·검사 등록부는 자식 안에서 처음부터
평가되므로 가드가 보는 것은 예전 서브프로세스와 같다. forkserver 는 pytest 를
임포트하지 않은 새 파이썬이라 `config.settings._RUNNING_TESTS` 도 예전처럼
거짓이다.

**자식이 쓴 CPU 는 시험 몫으로 센다.** 자식은 forkserver 의 자식이라 시험
프로세스의 `RUSAGE_CHILDREN` 에 잡히지 않는다 — 그대로 두면 한도 검사
(`tests/conftest.py`)가 비용을 못 본다. 자식이 자기 사용량을 돌려주고
`charged_cpu_seconds()` 가 그 합을 낸다.
"""

from __future__ import annotations

import contextlib
import io
import multiprocessing
import os
import resource
import subprocess
import sys
import traceback
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent

# 설정을 읽지 않고 임포트되는 것만 — 여기에 앱 모듈이나 `ninja`(임포트 시점에
# 설정을 읽는다)를 넣으면 forkserver 가 기본 설정으로 평가해 버려 가드를 다시
# 태울 수 없게 된다.
_PRELOAD = [
    "pydantic",
    "celery",
    "sentry_sdk",
    "requests",
    "django.core.management",
    "django.db.models",
    "django.urls",
    "django.http",
]

_context: multiprocessing.context.BaseContext | None = None
_charged = 0.0


def charged_cpu_seconds() -> float:
    """이 프로세스가 지금까지 forkserver 자식에게 시킨 일의 CPU 합(초)."""

    return _charged


def _get_context() -> multiprocessing.context.BaseContext:
    global _context
    if _context is None:
        context = multiprocessing.get_context("forkserver")
        context.set_forkserver_preload(_PRELOAD)
        _context = context
    return _context


def _child(argv: list[str], env: dict[str, str], conn) -> None:
    os.environ.clear()
    os.environ.update(env)
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.chdir(BACKEND_DIR)
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    stdout, stderr = io.StringIO(), io.StringIO()
    code = 0
    with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
        try:
            if argv[0] == "-c":
                exec(compile(argv[1], "<string>", "exec"), {"__name__": "__main__"})
            else:
                from django.core.management import execute_from_command_line

                execute_from_command_line(["manage.py", *argv])
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
        except BaseException:  # noqa: BLE001 - 파이썬 인터프리터가 하던 그대로 적고 1 로 끝난다
            traceback.print_exc()
            code = 1

    usage = resource.getrusage(resource.RUSAGE_SELF)
    conn.send((code, stdout.getvalue(), stderr.getvalue(), usage.ru_utime + usage.ru_stime))
    conn.close()


def run(argv: list[str], env: dict[str, str], *, timeout: float = 60) -> subprocess.CompletedProcess:
    """`python manage.py <argv>`(또는 `python -c <코드>`)를 `env` 환경으로 돌린
    결과 — `subprocess.run(..., capture_output=True, text=True)` 와 같은 모양이다."""

    global _charged
    context = _get_context()
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(argv, env, sender))
    process.start()
    sender.close()
    if not receiver.poll(timeout):
        process.kill()
        process.join()
        raise subprocess.TimeoutExpired(argv, timeout)
    code, stdout, stderr, cpu_seconds = receiver.recv()
    process.join()
    _charged += cpu_seconds
    return subprocess.CompletedProcess(argv, code, stdout, stderr)
