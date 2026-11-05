"""연결된 앱의 OAuth 엔드포인트 — 메타데이터·등록·토큰·회수 (ADR-0052, #512, #870).

django-ninja 가 아니라 평범한 Django 뷰인 이유: 이 다섯은 규격이 응답 모양을 정한다 —
RFC 6749 §5.2 의 `{"error": ...}` 본문, `application/x-www-form-urlencoded` 요청,
`Cache-Control: no-store`. ninja 의 스키마 검증 오류(422)로 답하면 클라이언트가 읽지
못한다. 로그인한 사용자가 부르는 동의·목록·끊기는 각 기능 앱에 있다
(`classroom.connected_app_api`, `contests.connected_app_api`).

자원(`core.oauth.OAuthResource`)마다 한 벌을 `oauth_views(resource)` 로 만든다 — 강의실과
공모전의 엔드포인트는 같은 몸에 범위만 다르다.

인증이 없는 엔드포인트라 CSRF 를 끈다 — 쿠키를 읽지 않으므로 지킬 것이 없다.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

from . import oauth

View = Callable[[HttpRequest], HttpResponse]


def _json(body: dict, status: int = 200) -> JsonResponse:
    response = JsonResponse(body, status=status, json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = "no-store"
    return response


def _method_not_allowed(allowed: str) -> HttpResponse:
    response = HttpResponse(status=405)
    response["Allow"] = allowed
    return response


@dataclass(frozen=True)
class OAuthViews:
    protected_resource_metadata: View
    authorization_server_metadata: View
    register: View
    token: View
    revoke: View


def oauth_views(resource: oauth.OAuthResource) -> OAuthViews:
    def _error(error: oauth.OAuthError) -> JsonResponse:
        response = _json(error.as_body(), status=error.status)
        if error.status == 401:
            response["WWW-Authenticate"] = f'Basic realm="{resource.realm}"'
        return response

    def protected_resource_metadata(request: HttpRequest) -> HttpResponse:
        if request.method != "GET":
            return _method_not_allowed("GET")
        return JsonResponse(resource.protected_resource_metadata(resource.public_origin(request)))

    def authorization_server_metadata(request: HttpRequest) -> HttpResponse:
        if request.method != "GET":
            return _method_not_allowed("GET")
        return JsonResponse(resource.authorization_server_metadata(resource.public_origin(request)))

    @csrf_exempt
    def register(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return _method_not_allowed("POST")
        try:
            metadata = json.loads(request.body or b"")
        except (ValueError, UnicodeDecodeError):
            return _error(oauth.OAuthError("invalid_client_metadata", "등록 요청을 JSON 으로 읽을 수 없습니다."))
        try:
            return _json(oauth.register_client(resource, metadata), status=201)
        except oauth.OAuthError as error:
            return _error(error)

    @csrf_exempt
    def token(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return _method_not_allowed("POST")
        form = request.POST
        origin = resource.public_origin(request)
        try:
            client = oauth.authenticate_client(*oauth.client_credentials_from(request, form))
            grant_type = form.get("grant_type")
            if grant_type == "authorization_code":
                return _json(oauth.exchange_code(resource, client, form, origin))
            if grant_type == "refresh_token":
                return _json(oauth.refresh(resource, client, form, origin))
            raise oauth.OAuthError("unsupported_grant_type", "지원하지 않는 grant_type 입니다.")
        except oauth.OAuthError as error:
            return _error(error)

    @csrf_exempt
    def revoke(request: HttpRequest) -> HttpResponse:
        if request.method != "POST":
            return _method_not_allowed("POST")
        form = request.POST
        try:
            client = oauth.authenticate_client(*oauth.client_credentials_from(request, form))
        except oauth.OAuthError as error:
            return _error(error)
        oauth.revoke_token(client, form)
        return HttpResponse(status=200)

    return OAuthViews(
        protected_resource_metadata=protected_resource_metadata,
        authorization_server_metadata=authorization_server_metadata,
        register=register,
        token=token,
        revoke=revoke,
    )
