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

    assert drop_expected_error(event, _hint(HttpError(422, "입력이 틀렸습니다."))) is None
    assert drop_expected_error(event, _hint(HttpError(404, "없습니다."))) is None
    assert drop_expected_error(event, _hint(HttpError(403, "권한이 없습니다."))) is None
    assert drop_expected_error(event, _hint(Http404())) is None
    assert drop_expected_error(event, _hint(PermissionDenied())) is None
    assert drop_expected_error(event, _hint(SuspiciousOperation())) is None


def test_server_errors_and_unhandled_exceptions_are_sent():
    event = {"event_id": "x"}

    assert drop_expected_error(event, _hint(HttpError(500, "서버 오류"))) is event
    assert drop_expected_error(event, _hint(HttpError(503, "잠시 후"))) is event
    assert drop_expected_error(event, _hint(ZeroDivisionError("division by zero"))) is event
    assert drop_expected_error(event, _hint(KeyError("missing"))) is event


def test_events_without_an_exception_pass_through():
    event = {"event_id": "x", "message": "직접 보낸 메시지"}

    assert drop_expected_error(event, {}) is event
