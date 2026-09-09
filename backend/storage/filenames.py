"""저장된 content-type으로부터 다운로드 파일명을 만든다 (#241, ADR-0005).

브라우저는 presigned GET URL에 `Content-Disposition: attachment`만 있고
`filename`이 없으면 URL의 마지막 경로 조각(서버가 만든 32자리 hex object_key)을
파일명으로 쓴다 — 확장자가 없는 정체불명의 이름이 떨어지는 원인이 이것이다
(#241).

**원본 파일명은 쓰지 않는다.** 사용자가 정한 문자열을 응답 헤더에 그대로 실으려면
RFC 5987 이스케이프(줄바꿈·따옴표·비ASCII)가 필요한 자리가 새로 생긴다 — 그 비용
대신 **일반적인 이름**을 받아들이기로 했다(#241 결정). 그래서 이름은 언제나
`DEFAULT_DOWNLOAD_BASENAME`(플랫폼이 정한 고정 문자열)이고, 그 뒤에 붙는 확장자만
업로드 발급 시점에 받아 자산에 남긴 content-type에서 유도한다.

content-type을 모르거나(기존에 올라간 자산 — 이 필드가 생기기 전 행) 확장자를
알 수 없는 값이면 확장자 없이 그 이름 그대로 내려간다 — 다운로드 자체는 실패하지
않는다(#241 AC).
"""

from __future__ import annotations

import mimetypes

#: 다운로드 파일명의 고정된 기본 이름. 사용자 입력을 담지 않는다(#241 결정) — 이
#: 값 자체가 무엇을 보여주는 자료인지 말하지는 않지만, 확장자가 그 형식을 말해준다.
DEFAULT_DOWNLOAD_BASENAME = "download"

# "모른다"로 취급하는 content-type — 확장자를 억지로 붙이지 않는다.
# "application/octet-stream"은 storage.adapters.base.DEFAULT_CONTENT_TYPE(#238)이
# "형식을 모르는 바이트"에 붙이는 값 그대로다 — mimetypes가 이걸 ".bin"으로
# 번역해 주지만, 그건 "실제로 모른다"를 "안다"처럼 보이게 할 뿐이다.
_UNKNOWN_CONTENT_TYPES = frozenset({"", "application/octet-stream", "binary/octet-stream"})

# 이 플랫폼이 실제로 받는 종류(제출 소스 zip, 시연 영상, 빌드 자산)를 먼저
# 못박아 둔다 — `mimetypes.guess_extension`은 OS의 mime.types도 함께 읽어
# 환경마다(dev/CI/staging) 답이 갈릴 수 있다("application/x-zip-compressed"가
# 대표적으로 표준 라이브러리만으로는 None이다).
_KNOWN_EXTENSIONS: dict[str, str] = {
    "application/zip": ".zip",
    "application/x-zip-compressed": ".zip",
    "application/gzip": ".gz",
    "application/x-gzip": ".gz",
    "application/x-tar": ".tar",
    "application/x-7z-compressed": ".7z",
    "application/vnd.rar": ".rar",
    "application/x-rar-compressed": ".rar",
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
    "video/x-msvideo": ".avi",
    "application/pdf": ".pdf",
}


def _extension_for(content_type: str | None) -> str:
    if not content_type:
        return ""

    # 브라우저가 보내는 content-type에 매개변수가 붙을 수 있다(예:
    # "text/plain; charset=utf-8") — 형식 판정에는 그 앞부분만 쓴다.
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in _UNKNOWN_CONTENT_TYPES:
        return ""

    known = _KNOWN_EXTENSIONS.get(normalized)
    if known is not None:
        return known

    return mimetypes.guess_extension(normalized) or ""


def build_download_filename(
    content_type: str | None, *, base_name: str = DEFAULT_DOWNLOAD_BASENAME
) -> str:
    """항상 이름을 낸다 — content-type을 모르면 확장자만 빠진다(#241 AC)."""

    return f"{base_name}{_extension_for(content_type)}"
