"""오류 수집기로 무엇을 보내고 무엇을 버리는지(2026-09-16).

`before_send` 는 네트워크 앞단의 순수 판정이라 여기서 직접 부른다 — 진짜 소음은
「422 를 수백 건 보내 진짜 5xx 가 묻힌다」이고, 그 규칙이 깨졌는지는 이 함수로만
잴 수 있다.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.http import Http404
from ninja.errors import HttpError

from core.observability import drop_expected_error


def _hint(exc: BaseException) -> dict:
    return {"exc_info": (type(exc), exc, None)}


def test_expected_rejections_are_not_errors():
    event = {"event_id": "x"}

    assert (
        drop_expected_error(event, _hint(HttpError(422, "입력이 틀렸습니다."))) is None
    )
    assert drop_expected_error(event, _hint(HttpError(404, "없습니다."))) is None
    assert drop_expected_error(event, _hint(HttpError(403, "권한이 없습니다."))) is None
    assert drop_expected_error(event, _hint(Http404())) is None
    assert drop_expected_error(event, _hint(PermissionDenied())) is None
    assert drop_expected_error(event, _hint(SuspiciousOperation())) is None


def test_server_errors_and_unhandled_exceptions_are_sent():
    event = {"event_id": "x"}

    assert drop_expected_error(event, _hint(HttpError(500, "서버 오류"))) is event
    assert drop_expected_error(event, _hint(HttpError(503, "잠시 후"))) is event
    assert (
        drop_expected_error(event, _hint(ZeroDivisionError("division by zero")))
        is event
    )
    assert drop_expected_error(event, _hint(KeyError("missing"))) is event


def test_events_without_an_exception_pass_through():
    event = {"event_id": "x", "message": "직접 보낸 메시지"}

    assert drop_expected_error(event, {}) is event


def _celery_reconnect_hint(retries: int) -> dict:
    """celery 워커가 브로커(Redis)를 잃고 다시 붙으려 할 때 남기는 ERROR 로그 레코드.

    `celery.worker.consumer.consumer.Consumer.ensure_connected` 가 재시도마다
    부르는 것과 같은 템플릿·인자다 — Sentry 의 로깅 통합은 이 레코드를 hint 의
    `log_record` 로 넘긴다.
    """

    import logging

    from celery.worker.consumer.consumer import CONNECTION_ERROR, CONNECTION_RETRY_STEP

    record = logging.LogRecord(
        name="celery.worker.consumer.consumer",
        level=logging.ERROR,
        pathname=__file__,
        lineno=0,
        msg=CONNECTION_ERROR,
        args=(
            "redis://redis:6379/0",
            ConnectionError("Error 111 connecting to redis:6379. Connection refused."),
            CONNECTION_RETRY_STEP.format(
                when="in 2.00 seconds", retries=retries, max_retries=100
            ),
        ),
        exc_info=None,
    )
    return {"log_record": record}


def test_broker_blip_during_deploy_is_not_an_error():
    """배포가 Redis 를 바꿔 끼우는 몇 초 — 워커는 스스로 다시 붙는다(GlitchTip 오류 66).

    `deploy.sh` 의 `up -d db redis` 는 compose 에서 redis 설정이 바뀌면 컨테이너를
    다시 만들고, 그 사이 떠 있던 워커가 첫 재시도에서 ERROR 를 남긴다 — 2초 뒤
    「Connected」로 끝나는 일이 staging·prod 에 오류로 한 건씩 남았다.
    """

    event = {"event_id": "x"}

    assert drop_expected_error(event, _celery_reconnect_hint(1)) is None
    assert drop_expected_error(event, _celery_reconnect_hint(4)) is None


def test_broker_outage_that_lasts_is_still_sent():
    """재시도가 쌓이면(배포의 몇 초가 아니다) 그대로 보낸다 — 진짜 장애를 잃지 않는다."""

    event = {"event_id": "x"}

    assert drop_expected_error(event, _celery_reconnect_hint(5)) is event
    assert drop_expected_error(event, _celery_reconnect_hint(100)) is event


def _event_with_frames(*frames: dict) -> dict:
    return {
        "event_id": "x",
        "exception": {
            "values": [{"type": "ImportError", "stacktrace": {"frames": list(frames)}}]
        },
    }


_SHELL_FRAME = {
    "module": "django.core.management.commands.shell",
    "abs_path": "/usr/local/lib/python3.12/site-packages/django/core/management/commands/shell.py",
    "filename": "django/core/management/commands/shell.py",
}


def test_manage_shell_exception_is_not_sent():
    exc = ImportError("cannot import name 'X'")
    app = {"module": "billing.models", "abs_path": "/app/billing/models.py"}

    assert (
        drop_expected_error(_event_with_frames(_SHELL_FRAME, app), _hint(exc)) is None
    )
    # module·abs_path·filename 중 하나만 와도 맞는다
    for only in (
        {"module": _SHELL_FRAME["module"]},
        {"abs_path": _SHELL_FRAME["abs_path"]},
        {"filename": _SHELL_FRAME["filename"]},
    ):
        assert drop_expected_error(_event_with_frames(only), _hint(exc)) is None


def test_other_management_commands_are_still_sent():
    exc = ImportError("cannot import name 'X'")
    migrate = {
        "module": "django.core.management.commands.migrate",
        "abs_path": "/usr/local/lib/python3.12/site-packages/django/core/management/commands/migrate.py",
    }
    app_command = {
        "module": "classes.management.commands.sync",
        "abs_path": "/app/classes/management/commands/sync.py",
    }

    for frame in (migrate, app_command):
        event = _event_with_frames(frame)
        assert drop_expected_error(event, _hint(exc)) is event


def test_web_and_worker_exceptions_are_still_sent():
    exc = ValueError("boom")
    web = {
        "module": "django.core.handlers.base",
        "abs_path": "/site-packages/django/core/handlers/base.py",
    }
    worker = {
        "module": "celery.app.trace",
        "abs_path": "/site-packages/celery/app/trace.py",
    }

    for frame in (web, worker):
        event = _event_with_frames(frame)
        assert drop_expected_error(event, _hint(exc)) is event
