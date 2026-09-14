"""compose 내부 서비스 이름으로 들어온 요청을 TLS 프록시를 거친 요청처럼 다룬다.

prod 는 TLS 를 앞단 리버스 프록시가 종단하고 `SECURE_PROXY_SSL_HEADER`(X-Forwarded-Proto)로 원래
스킴을 받는다. 그런데 세 앱의 BFF 와 이벤트 스트림 중계는 compose 네트워크 안에서 `backend`·
`events` 를 **직접** 부른다 — 프록시를 거치지 않으니 그 헤더가 없고, `SECURE_SSL_REDIRECT` 가
`301 → https://backend:8000/...` 을 돌려준다. 평문 gunicorn 에 TLS 로 붙으려던 fetch 는 연결
시간 초과로 죽는다(2026-09-14 prod 카카오 로그인이 통째로 막혔다).

**왜 이것이 우회로가 아닌가.** 이 이름들은 compose 네트워크 안에서만 풀린다. 앱 포트는 호스트의
127.0.0.1 에만 열려 있고(`docker/compose.prod.yaml`), 공개 프록시는 언제나 공개 도메인을 Host 로
넘기므로 인터넷에서 온 요청이 Host 를 `backend` 로 바꿔 이 예외를 탈 길이 없다. 내부 API 경로를
리다이렉트에서 빼 둔 `SECURE_REDIRECT_EXEMPT`(Celery → `/api/internal/`)와 같은 신뢰 경계를, 경로
대신 호출자가 쓰는 이름으로 넓힌 것이다.
"""

from __future__ import annotations

from django.conf import settings


class InternalServiceHostMiddleware:
    """`SecurityMiddleware` 앞에 둔다 — 그래야 리다이렉트 판단 전에 스킴이 정해진다."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        header = getattr(settings, "SECURE_PROXY_SSL_HEADER", None)
        if header and not request.META.get(header[0]):
            host = request.META.get("HTTP_HOST", "").rsplit(":", 1)[0].strip().lower()
            if host in settings.INTERNAL_SERVICE_HOSTS:
                request.META[header[0]] = header[1]
        return self.get_response(request)
