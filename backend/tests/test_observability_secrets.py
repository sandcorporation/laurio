"""오류 이벤트에 키·토큰이 실려 나가지 않는다(#590).

GlitchTip 이벤트의 프레임 지역 변수에 강사 OpenAI 키(`Authorization: Bearer`)·
`X-Internal-Token`·이용자 로그인 토큰이 평문으로 실렸다. 여기서는 운영과 **같은 설정**
(`sentry_init_options`)으로 SDK 를 켜되 전송만 흉내 내 보내질 이벤트를 잡고, 그 안에
비밀 값이 없음을 본다. 비밀 값은 시험마다 새로 만들고, 실패해도 값을 출력하지 않도록
불리언으로만 단언한다.
"""

from __future__ import annotations

import io
import json
import secrets
from wsgiref.util import setup_testing_defaults

import pytest
import sentry_sdk
from django.core.handlers.wsgi import WSGIHandler
from django.core.signals import request_finished, request_started
from django.db import close_old_connections
from django.urls import path
from sentry_sdk.transport import Transport

from core.observability import sentry_init_options, tag_error_scope


def _boom(request):
    raise RuntimeError("처리되지 않은 오류")


urlpatterns = [path("boom/", _boom)]


@pytest.fixture
def captured_events():
    """운영 설정으로 SDK 를 켜고, 네트워크 대신 이벤트 dict 를 모은다."""

    events: list[dict] = []

    class _CaptureTransport(Transport):
        def capture_envelope(self, envelope):
            event = envelope.get_event()
            if event is not None:
                events.append(event)

    options = sentry_init_options("http://public@glitchtip.invalid/1")
    sentry_sdk.init(**{**options, "transport": _CaptureTransport})
    try:
        yield events
    finally:
        sentry_sdk.get_global_scope().set_client(None)


def _contains(event: dict, *values: str) -> bool:
    body = json.dumps(event, ensure_ascii=False, default=str)
    return any(value in body for value in values)


def _call_vendor(api_key: str, internal_token: str) -> None:
    # 채점 경로·`call_internal` 이 들고 있던 모양 그대로의 지역 변수들.
    raw_key = api_key
    headers = {"Authorization": f"Bearer {raw_key}", "X-Internal-Token": internal_token}
    assert headers
    raise RuntimeError("벤더가 거절했다")


def test_local_variables_holding_keys_are_not_sent(captured_events):
    api_key = f"sk-test-{secrets.token_hex(16)}"
    internal_token = secrets.token_hex(16)

    with sentry_sdk.isolation_scope():
        try:
            _call_vendor(api_key, internal_token)
        except RuntimeError:
            sentry_sdk.capture_exception()

    assert len(captured_events) == 1
    event = captured_events[0]
    frames = event["exception"]["values"][0]["stacktrace"]["frames"]
    assert any(frame.get("function") == "_call_vendor" for frame in frames)
    leaked = _contains(event, api_key, internal_token)
    assert not leaked


def test_request_credential_headers_are_not_sent(captured_events, settings):
    # 헤더는 SDK 의 WSGI 미들웨어가 실으므로 테스트 클라이언트가 아니라 운영과 같은
    # `WSGIHandler` 를 직접 부른다(Django 통합이 그 `__call__` 을 감싼다).
    settings.ROOT_URLCONF = __name__
    internal_token = secrets.token_hex(16)
    login_token = secrets.token_hex(16)
    environ = {
        "PATH_INFO": "/boom/",
        "REQUEST_METHOD": "GET",
        "HTTP_X_INTERNAL_TOKEN": internal_token,
        "HTTP_AUTHORIZATION": f"Bearer {login_token}",
        "HTTP_COOKIE": f"codemit_access={login_token}",
        "wsgi.input": io.BytesIO(b""),
    }
    setup_testing_defaults(environ)
    statuses: list[str] = []

    # 테스트 클라이언트처럼 요청 앞뒤의 DB 연결 정리를 뗀다 — 이 시험은 DB 를 쓰지 않는다.
    request_started.disconnect(close_old_connections)
    request_finished.disconnect(close_old_connections)
    try:
        WSGIHandler()(environ, lambda status, headers, exc_info=None: statuses.append(status))
    finally:
        request_started.connect(close_old_connections)
        request_finished.connect(close_old_connections)

    assert statuses == ["500 Internal Server Error"]
    assert len(captured_events) == 1
    event = captured_events[0]
    assert event["request"]["url"].endswith("/boom/")
    assert event["request"]["headers"]  # 헤더 묶음 자체는 남는다(Host 등)
    leaked = _contains(event, internal_token, login_token)
    assert not leaked


def test_entry_points_tag_identifiers_only(captured_events):
    with sentry_sdk.isolation_scope():
        tag_error_scope("classroom_scoring", class_id=5, problem_id=12, scoring_model=None)
        sentry_sdk.capture_exception(RuntimeError("x"))

    event = captured_events[0]
    assert event["tags"]["class_id"] == "5"
    assert event["tags"]["problem_id"] == "12"
    assert event["contexts"]["classroom_scoring"] == {"class_id": 5, "problem_id": 12}
