"""JWT 인증과 CSP를 담당하는 미들웨어 (ADR-0012).

이 두 가지가 미들웨어에 있어야 하는 이유: 테스트가 Django 테스트 클라이언트로
전체 요청 스택(URLconf + 미들웨어 + 라우터)을 통과해야만 실제 운영과 같은 경로를
검증한 게 된다. `ninja.testing.TestClient`는 라우터를 직접 호출해 미들웨어를
건너뛰므로 이 프로젝트에서는 쓰지 않는다.
"""

from __future__ import annotations

from django.contrib.auth import get_user_model

from core.observability import set_sentry_user_id  # APP-BOUNDARY-EXCEPTION: 공유층 core 의 오류 수집 도우미다

from .tokens import TokenError, decode_token


class JWTAuthenticationMiddleware:
    """`Authorization: Bearer <access token>`을 읽어 `request.auth_user`를 채운다.

    토큰이 없거나 무효(서명 실패·만료·블랙리스트)여도 요청을 막지 않는다 — 인증이
    필요한 개별 엔드포인트가 `request.auth_user`가 비어 있으면 401을 낸다. 공개
    엔드포인트는 이 미들웨어의 존재를 신경 쓸 필요가 없다.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.auth_user = None
        header = request.META.get("HTTP_AUTHORIZATION", "")
        if header.startswith("Bearer "):
            token = header[len("Bearer ") :].strip()
            try:
                payload = decode_token(token, expected_type="access")
            except TokenError:
                payload = None
            if payload is not None:
                User = get_user_model()
                # `is_active=True`를 걸러 탈퇴(#100, ADR-0025)한 계정을 즉시
                # 무효화한다 — 탈퇴는 유예 없이 실행되므로, 이미 발급된 액세스
                # 토큰이 만료 전이어도 다음 요청부터 곧바로 익명이 된다.
                # `core.operator_auth.OperatorAuth`가 세션 인증에서 쓰는 것과
                # 같은 장치를 여기 JWT 경로에도 건다.
                request.auth_user = User.objects.filter(
                    pk=int(payload["sub"]), is_active=True
                ).first()

        # 오류가 나면 누구에게 났는지 알아야 한다 — 다만 내부 id 하나만 붙인다
        # (이메일·이름은 보내지 않는다, core/observability.py).
        set_sentry_user_id(request.auth_user.pk if request.auth_user else None)

        return self.get_response(request)


class ContentSecurityPolicyMiddleware:
    """모든 응답에 CSP 헤더를 붙인다 (ADR-0012 보완책).

    JWT를 localStorage에 두는 대신 XSS로 스크립트가 주입돼도 외부로 데이터를
    실어나르거나 임의 스크립트를 실행할 수 있는 여지를 좁힌다.
    """

    POLICY = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "frame-ancestors 'none'"
    )

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.setdefault("Content-Security-Policy", self.POLICY)
        return response


def jwt_auth(request) -> object | None:
    """django-ninja `auth=` 콜백. 미들웨어가 채운 `auth_user`를 그대로 신뢰한다."""

    return getattr(request, "auth_user", None)
