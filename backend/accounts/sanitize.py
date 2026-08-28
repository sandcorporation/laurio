"""사용자 입력 자유 서식 sanitize.

ADR-0012: JWT-in-localStorage 결정은 세 보완책이 한 묶음이며 하나라도 빠지면 결정
자체가 무효다. 그중 하나가 "사용자 입력 서식(특히 Developer 프로필 자기소개)의
sanitize 강제"다. 태그를 하나도 허용하지 않는 순수 텍스트로 정리해, 저장된 자기소개가
다른 사용자의 브라우저에서 스크립트로 실행될 경로를 원천 차단한다.
"""

from __future__ import annotations

from html import unescape

import bleach

_ALLOWED_TAGS: list[str] = []
_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {}


def sanitize_free_text(value: str) -> str:
    """자유 서식 텍스트에서 HTML/스크립트를 제거하고 순수 텍스트만 남긴다.

    `bleach.clean`은 안전한 HTML 문자열을 만드는 게 목적이라 태그를 하나도 허용하지
    않아도 남는 텍스트의 `& < >` 를 `&amp; &lt; &gt;` 로 실체 참조(entity) 인코딩한다.
    태그를 전부 걷어낸 뒤에는 그 텍스트가 다시 HTML로 파싱될 일이 없으므로(마크업이
    남아있지 않다), 인코딩된 실체 참조를 그대로 저장하면 "Rock & Roll" 같은 평범한
    글이 저장·재저장을 거칠 때마다 "Rock &amp;amp; Roll" 처럼 중첩 오염된다. 태그
    제거 후 `unescape`로 원래 문자로 되돌려, 위험한 마크업만 걷어내고 순수 문장부호는
    그대로 보존한다.
    """

    if not value:
        return value
    cleaned = bleach.clean(
        value, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES, strip=True
    )
    return unescape(cleaned).strip()
