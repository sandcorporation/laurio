"""앱 시험의 주소 — 그 앱과 그 앱이 쓰는 아래 앱의 라우터·뷰만 붙인다(#1087).

`<앱>/tests/urls.py` 가 `urlpatterns = urlpatterns_for("<앱>")` 한 줄로 이것을 부르고, 루트 conftest 가 그 앱
폴더의 시험마다 `ROOT_URLCONF` 를 그 모듈로 바꾼다. 아래 앱은 앱 의존 선언 표(`app_deps.toml`)의 `uses` 닫힘이다 —
강의실 시험이 로그인(accounts)을 부르는 것은 되고, 위 앱·옆 앱의 주소는 404 다. 그래서 앱 시험이 닿는 앱은 늘
`app_deps.py affected` 가 그 앱을 다시 돌게 하는 앱뿐이다. 앱 사이 흐름은 `tests/integration/` 에서 전체
주소(`config.urls`)로 시험한다. 주소 표는 `config/routes.py` 하나다.
"""

from __future__ import annotations

import tomllib
from functools import cache

from django.conf import settings
from django.urls import URLPattern, URLResolver, path

from config.routes import API_ROUTERS, URL_VIEWS, build_api, view_patterns


@cache
def _uses() -> dict[str, list[str]]:
    table = tomllib.loads((settings.BASE_DIR / "app_deps.toml").read_text(encoding="utf-8"))
    return {app: list(row.get("uses", [])) for app, row in table.items()}


def below(app: str) -> frozenset[str]:
    uses = _uses()
    out: set[str] = set()
    stack = [app]
    while stack:
        x = stack.pop()
        if x not in out:
            out.add(x)
            stack += uses.get(x, [])
    return frozenset(out)


def urlpatterns_for(app: str) -> list[URLPattern | URLResolver]:
    apps = below(app)
    api = build_api(m for m in API_ROUTERS if m.app in apps)
    return [*view_patterns(v for v in URL_VIEWS if v.app in apps), path("api/", api.urls)]
