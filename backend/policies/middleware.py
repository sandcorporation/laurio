"""요청마다 PlatformPolicy 스코프를 연다 (#145) — `policies.scope` 참고."""

from __future__ import annotations

from .scope import policy_scope


class PolicyScopeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        with policy_scope():
            return self.get_response(request)
