"""강의실의 OAuth 엔드포인트 — 메타데이터·등록·토큰·회수 (ADR-0052, #512).

몸은 `core.oauth_views` 에 있다(#870). 여기서는 강의실 자원(`classroom.oauth.CLASSROOM`)으로
한 벌을 만들어 `config/urls.py` 가 예전 이름 그대로 마운트하게 한다. 로그인한 강사가 부르는
동의·목록·끊기는 `classroom.connected_app_api` 에 있다.
"""

from __future__ import annotations

from core.oauth_views import oauth_views

from .oauth import CLASSROOM

_VIEWS = oauth_views(CLASSROOM)

protected_resource_metadata = _VIEWS.protected_resource_metadata
authorization_server_metadata = _VIEWS.authorization_server_metadata
register = _VIEWS.register
token = _VIEWS.token
revoke = _VIEWS.revoke
