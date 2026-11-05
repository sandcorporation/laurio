"""시연 영상 링크(`SubmissionAsset.Kind.VIDEO_LINK`, #910)의 모양 검사.

backend 가 정본이고 frontend(`frontend/lib/submissions/video-link.ts`)가 같은 규칙으로 미리 막는다.
"""

from urllib.parse import urlsplit

VIDEO_LINK_MAX_LENGTH = 2000  # `SubmissionAsset.value` 와 같다(DEMO_URL 과 같은 상한).
VIDEO_LINK_SHAPE_MESSAGE = (
    "시연 영상 링크는 http:// 또는 https:// 로 시작하는 주소여야 하고 "
    "사용자 정보(아이디:비밀번호@)를 담을 수 없습니다."
)


def is_safe_video_link(value: str) -> bool:
    if not value or len(value) > VIDEO_LINK_MAX_LENGTH:
        return False
    try:
        parts = urlsplit(value)
        host = parts.hostname
        parts.port  # noqa: B018 — 잘못된 포트는 여기서 ValueError
    except ValueError:
        return False
    if parts.scheme not in ("http", "https") or not host:
        return False
    # `user:pass@host` — netloc 의 `@` 로 가른다(빈 사용자 정보 `@host` 도 거절).
    return "@" not in parts.netloc
