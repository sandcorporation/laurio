"""주소 표 — 어느 앱의 라우터·뷰가 어느 주소에 붙는가(#1087).

`config/api.py`·`config/urls.py` 가 이 표대로 전체 주소를 짓고, 앱 시험은 같은 표에서 제 앱 줄만 골라
앱별 주소(`tests/app_urls.py`)를 짓는다. 그래서 이 모듈은 앱을 import 하지 않는다 — 값은 dotted path 다.

**순서가 뜻이다.** 같은 주소를 두 라우터가 잡으면 먼저 붙은 쪽이 이긴다(공모전 연결된 앱이 공모전
라우터보다 먼저인 까닭, #870).
"""

from __future__ import annotations

from collections.abc import Iterable
from importlib import import_module
from typing import Any, NamedTuple

from django.urls import URLPattern, URLResolver, path
from ninja import NinjaAPI, Router


class Mount(NamedTuple):
    """`/api/<prefix>` 아래에 붙는 ninja 라우터."""

    prefix: str
    router: str

    @property
    def app(self) -> str:
        return self.router.split(".", 1)[0]


class View(NamedTuple):
    """ninja 밖의 Django 뷰 — `route` 는 맨 앞 `/` 없는 Django 경로다."""

    route: str
    view: str

    @property
    def app(self) -> str:
        return self.view.split(".", 1)[0]


API_ROUTERS: tuple[Mount, ...] = (
    Mount("", "accounts.api.router"),
    Mount("", "verification.api.router"),
    # 공모전 연결된 앱(#870)은 공모전 라우터보다 먼저 — 아니면 `/contests/{contest_id}` 가
    # `/contests/connected-apps` 를 먼저 잡아 422 를 낸다.
    Mount("/contests", "contests.connected_app_api.router"),
    Mount("", "contests.api.router"),
    Mount("", "payments.api.router"),
    Mount("", "contests.submission_api.router"),
    Mount("", "awards.api.router"),
    Mount("", "handovers.api.router"),
    Mount("", "payouts.api.router"),
    Mount("", "appeals.api.router"),
    Mount("/notifications", "notifications.api.public_router"),
    Mount("/ledger", "ledger.api.router"),
    Mount("/classroom", "classroom.api.router"),
    Mount("/classroom", "classroom.template_api.router"),
    Mount("/classroom", "classroom.connected_app_api.router"),
    Mount("/internal", "core.api.router"),
    Mount("/internal/notifications", "notifications.api.router"),
    Mount("/internal/scoring", "scoring.api.router"),
    # 운영자 표면(#43, ADR-0019). InternalAuth 와 다르다 — 저쪽은 Celery beat 가 부르는
    # 자동 스캔 전용이고, 사람이 판단하는 행위는 전부 이 접두어 아래에서 신원과 함께
    # 이루어진다. 라우터 자체가 기본 거부이며 Origin 검증 미들웨어가 경로 접두어로
    # 걸려 있다.
    Mount("/operator", "accounts.operator_api.router"),
    Mount("/operator", "appeals.api.operator_router"),
    Mount("/operator", "payouts.api.operator_router"),
    Mount("/operator", "policies.api.operator_router"),
    Mount("/operator", "policies.runtime_settings_api.runtime_settings_router"),
    Mount("/operator", "contests.operator_api.operator_router"),
    Mount("/operator", "verification.operator_api.operator_router"),
    Mount("/operator", "classroom.template_operator_api.operator_router"),
    Mount("/operator", "classroom.usage_operator_api.usage_operator_router"),
    Mount("/operator", "notifications.operator_api.operator_router"),
    Mount("/operator", "ops_metrics.operator_api.ops_metrics_operator_router"),
    Mount("/storage", "storage.api.router"),
)

URL_VIEWS: tuple[View, ...] = (
    View("api/classroom/mcp", "classroom.mcp.mcp_endpoint"),
    View("api/classroom/oauth/metadata/protected-resource", "classroom.oauth_views.protected_resource_metadata"),
    View("api/classroom/oauth/metadata/authorization-server", "classroom.oauth_views.authorization_server_metadata"),
    View("api/classroom/oauth/register", "classroom.oauth_views.register"),
    View("api/classroom/oauth/token", "classroom.oauth_views.token"),
    View("api/classroom/oauth/revoke", "classroom.oauth_views.revoke"),
    View("api/contests/mcp", "contests.mcp.mcp_endpoint"),
    View("api/contests/oauth/metadata/protected-resource", "contests.oauth_views.VIEWS.protected_resource_metadata"),
    View(
        "api/contests/oauth/metadata/authorization-server",
        "contests.oauth_views.VIEWS.authorization_server_metadata",
    ),
    View("api/contests/oauth/register", "contests.oauth_views.VIEWS.register"),
    View("api/contests/oauth/token", "contests.oauth_views.VIEWS.token"),
    View("api/contests/oauth/revoke", "contests.oauth_views.VIEWS.revoke"),
)


def resolve(dotted: str) -> object:
    """`모듈.속성[.속성…]` — 가장 긴 모듈 앞부분을 import 하고 나머지를 속성으로 따라간다."""

    parts = dotted.split(".")
    for n in range(len(parts) - 1, 0, -1):
        try:
            obj: object = import_module(".".join(parts[:n]))
        except ModuleNotFoundError:
            continue
        for attr in parts[n:]:
            obj = getattr(obj, attr)
        return obj
    raise ImportError(dotted)


class CodemitAPI(NinjaAPI):
    """OpenAPI 스키마를 한 번만 만든다 — 라우터는 import 때 다 붙고 그 뒤로 바뀌지 않는다.

    ninja 는 `/api/openapi.json` 요청마다 엔드포인트 전부(지금 197개)의 pydantic 스키마를 다시 만든다.
    로컬 CPU 0.4초, CI 1.5초 남짓이고 엔드포인트 수에 비례해 는다. 시험 CPU 한도(#1014)를 넘은 까닭이다.
    """

    _openapi_cache: dict[str, Any]

    def get_openapi_schema(
        self,
        *,
        path_prefix: str | None = None,
        path_params: dict[str, Any] | None = None,
    ) -> Any:  # noqa: ANN401 — ninja 의 서명 그대로(스키마는 JSON 덩어리다)
        if path_prefix is None:
            path_prefix = self.get_root_path(path_params or {})
        cache = self.__dict__.setdefault("_openapi_cache", {})
        if path_prefix not in cache:
            cache[path_prefix] = super().get_openapi_schema(path_prefix=path_prefix)
        return cache[path_prefix]


def build_api(mounts: Iterable[Mount]) -> CodemitAPI:
    """표의 라우터를 붙인 API — 예외 처리기도 여기서 단다(앱별 시험 주소도 같은 처리기를 쓴다)."""

    from storage.policy import StorageAccessDenied

    api = CodemitAPI(title="Codemit API", version="0.1.0")
    for mount in mounts:
        router = resolve(mount.router)
        if not isinstance(router, Router):
            raise TypeError(f"{mount.router} 은 ninja Router 가 아니다")
        api.add_router(mount.prefix, router)

    @api.exception_handler(StorageAccessDenied)
    def storage_access_denied(request, exc: StorageAccessDenied):
        return api.create_response(request, {"detail": str(exc)}, status=403)

    return api


def view_patterns(views: Iterable[View]) -> list[URLPattern | URLResolver]:
    out: list[URLPattern | URLResolver] = []
    for v in views:
        view = resolve(v.view)
        if not callable(view):
            raise TypeError(f"{v.view} 은 뷰가 아니다")
        out.append(path(v.route, view))
    return out
