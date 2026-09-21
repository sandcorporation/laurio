"""요청마다 id 를 붙여 로그·오류·응답을 한 줄로 잇는다(2026-09-21).

**왜.** prod 로그는 이제 Loki 에 30일 남는다(CLAUDE.md 「운영」). 그런데 로그 한 줄이
어느 요청에서 나왔는지 모르면, GlitchTip 의 오류 하나를 보고 그 앞뒤 로그를 찾을 길이
없다 — 같은 시각에 요청이 여럿이면 시각으로는 가를 수 없다. 그래서 요청이 들어오는
순간 id 를 정해 **세 곳에 같은 값**을 싣는다:

- 그 요청 동안 나온 **모든 로그 레코드**(`record.request_id` — 레코드 팩토리가 붙이므로
  핸들러·로거와 무관하게 빠지는 줄이 없다),
- **GlitchTip 태그** `request_id`(오류 화면에서 그 값으로 Loki 를 찾는다),
- **응답 헤더** `X-Request-ID`(브라우저·BFF 에서 보이는 값이 로그와 같다).

**들어온 값을 믿는 범위.** 앞단(BFF 등)이 `X-Request-ID` 를 주면 그대로 쓴다 — 여러
서비스를 지나는 한 요청을 같은 id 로 잇기 위해서다. 다만 모양이 맞을 때만이다(영숫자·
`._-`, 64자 이하). 이 값은 로그를 잇는 데만 쓰이고 권한과 무관하므로, 위조돼도 잃는 것은
그 요청의 로그 연결뿐이다 — 모양만 막아 로그 주입(개행 등)을 끊는다.

**동기·비동기 둘 다 받는다.** 이벤트 서비스(ASGI)의 실시간 신호 스트림은 비동기 뷰라,
동기 전용 미들웨어를 두면 그 요청이 스레드로 옮겨져 스트림이 흔들린다.
"""

from __future__ import annotations

import logging
import re
import uuid
from contextvars import ContextVar

from asgiref.sync import iscoroutinefunction, markcoroutinefunction
from django.core.signals import request_finished

HEADER = "X-Request-ID"
_META_KEY = "HTTP_X_REQUEST_ID"
_VALID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_current: ContextVar[str | None] = ContextVar("codemit_request_id", default=None)


def current_request_id() -> str | None:
    """지금 처리 중인 요청의 id. 요청 밖(관리 명령·Celery)이면 None."""

    return _current.get()


def _choose(incoming: str | None) -> str:
    if incoming and _VALID.match(incoming):
        return incoming
    return uuid.uuid4().hex


def _tag_sentry(request_id: str) -> None:
    # 오류 수집이 꺼져 있어도(dev·CI) 이 호출은 아무 일도 하지 않는다.
    import sentry_sdk

    sentry_sdk.set_tag("request_id", request_id)


def install_log_record_factory() -> None:
    """모든 로그 레코드에 `request_id` 를 붙인다 — 요청 밖이면 `"-"`.

    필터가 아니라 **레코드 팩토리**로 하는 이유: 필터는 그것을 단 핸들러를 지나는
    레코드에만 붙어, 다른 핸들러(오류 수집기의 브레드크럼, 테스트의 캡처)로 가는 같은
    레코드에는 값이 없다. 팩토리는 레코드가 만들어지는 순간 한 번 붙인다. 두 번 불러도
    겹쳐 감싸지 않는다.
    """

    previous = logging.getLogRecordFactory()
    if getattr(previous, "_codemit_request_id", False):
        return

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        record.request_id = _current.get() or "-"
        return record

    factory._codemit_request_id = True  # type: ignore[attr-defined]
    logging.setLogRecordFactory(factory)


class RequestIdMiddleware:
    """가장 바깥에 둔다 — 체인 중간에서 나간 응답(301·403 등)에도 헤더가 붙고, 그 사이의
    로그도 전부 같은 id 를 갖는다."""

    sync_capable = True
    async_capable = True

    def __init__(self, get_response):
        self.get_response = get_response
        self._async = iscoroutinefunction(get_response)
        if self._async:
            markcoroutinefunction(self)

    def _begin(self, request) -> str:
        request_id = _choose(request.META.get(_META_KEY))
        _current.set(request_id)
        request.request_id = request_id
        _tag_sentry(request_id)
        return request_id

    # **여기서 id 를 지우지 않는다.** 처음에는 체인이 돌아오자마자 되돌렸는데, Django 는
    # 4xx·5xx 응답의 경고(`django.request` 의 「Not Found」 등)를 **미들웨어 체인이 끝난
    # 뒤에** 찍는다 — 그 줄이 id 없이(`-`) 나갔다. 정확히 그 줄이 사후 진단에서 제일
    # 먼저 찾는 줄이다. 그래서 요청이 완전히 끝나는 `request_finished` 에서 지운다.
    def __call__(self, request):
        if self._async:
            return self.__acall__(request)
        request_id = self._begin(request)
        response = self.get_response(request)
        response[HEADER] = request_id
        return response

    async def __acall__(self, request):
        request_id = self._begin(request)
        response = await self.get_response(request)
        response[HEADER] = request_id
        return response


def _clear_on_finish(**kwargs) -> None:
    # 다음 요청이 새 값을 정하기 전까지, 요청 밖에서 나온 로그가 지난 요청의 id 를 달지 않게.
    _current.set(None)


request_finished.connect(_clear_on_finish, dispatch_uid="codemit.request_id.clear")
