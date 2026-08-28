"""사용자 입력 자유 서식 sanitize.

ADR-0012: JWT-in-localStorage 결정은 세 보완책이 한 묶음이며 하나라도 빠지면 결정
자체가 무효다. 그중 하나가 "사용자 입력 서식(특히 Developer 프로필 자기소개)의
sanitize 강제"다. 태그를 하나도 허용하지 않는 순수 텍스트로 정리해, 저장된 자기소개가
다른 사용자의 브라우저에서 스크립트로 실행될 경로를 원천 차단한다.
"""

from __future__ import annotations

import bleach

_ALLOWED_TAGS: list[str] = []
_ALLOWED_ATTRIBUTES: dict[str, list[str]] = {}


def sanitize_free_text(value: str) -> str:
    """자유 서식 텍스트에서 HTML/스크립트를 제거하고 순수 텍스트만 남긴다."""

    if not value:
        return value
    cleaned = bleach.clean(
        value, tags=_ALLOWED_TAGS, attributes=_ALLOWED_ATTRIBUTES, strip=True
    )
    return cleaned.strip()
