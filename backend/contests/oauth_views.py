"""공모전 자원(`contests.oauth.CONTESTS`)의 OAuth 뷰 — 몸은 `core.oauth_views` 다(#870).

주소 표(`config/routes.py`)가 dotted path 로 가리킬 수 있게 모듈 속성으로 둔다(#1087).
"""

from __future__ import annotations

from core.oauth_views import oauth_views

from .oauth import CONTESTS

VIEWS = oauth_views(CONTESTS)
