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
import re
import unicodedata
from urllib.parse import quote

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
    # 스크린샷(#264, ADR-0036) — png/jpeg/webp/gif는 표준 mimetypes 테이블에도
    # 있지만, 이 파일의 앞선 항목들과 같은 이유(환경마다 답이 갈릴 수 있다)로
    # 여기 못박아 둔다.
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


#: 이름에 쓰지 않는 문자. 헤더 인젝션(따옴표·개행)과 경로 조작(`/` `\\` `..`)을
#: 한 번에 막는다 — 이 이름은 `Content-Disposition` 에도 실리고 사용자의 파일
#: 시스템에도 떨어진다.
_UNSAFE_IN_NAME = re.compile(r'[\x00-\x1f\x7f"\\/:*?<>|]+')

#: 사람 이름·라벨이 길어도 파일명이 감당할 만한 길이로 자른다.
_MAX_BASE_NAME = 60


def safe_download_base_name(text: str | None, *, fallback: str = DEFAULT_DOWNLOAD_BASENAME) -> str:
    """사람이 정한 문자열 -> 파일명에 써도 되는 기본 이름 (#268 후속).

    **#241 은 "원본 파일명을 그대로 싣지 않는다"를 정했고 그 판단은 그대로다** —
    업로드된 파일이 자기 이름을 헤더에 직접 밀어 넣는 길은 열지 않는다. 여는 것은
    다른 것이다: **플랫폼이 아는 맥락**(누구의 제출물인가)으로 이름을 조립한다.
    출제자 한 사람이 제출자 서른 명의 소스를 내려받는데 전부 `download.py` 로 떨어지면
    받는 순간 누구 것인지 알 수 없다 — 그 자리가 #241 이 보지 못한 자리다.

    그 대신 이스케이프를 진짜로 한다. 여기서 위험한 문자를 걷고,
    `content_disposition` 이 RFC 5987 로 싣는다.
    """

    if not text:
        return fallback

    # 자모 분리된 한글(NFD, macOS 업로드에서 흔하다)을 합친다 — 그러지 않으면
    # 파일명이 눈으로는 같은데 바이트가 달라진다.
    cleaned = unicodedata.normalize("NFC", text)
    cleaned = _UNSAFE_IN_NAME.sub(" ", cleaned)
    # 앞뒤 점은 숨김 파일(.name)과 상위 경로(..)를 만든다.
    cleaned = re.sub(r"\s+", " ", cleaned).strip().strip(".")
    cleaned = cleaned[:_MAX_BASE_NAME].strip()
    return cleaned or fallback


def content_disposition(filename: str) -> str:
    """`Content-Disposition` 헤더 값 — 항상 `attachment` 이고 이름을 둘로 싣는다.

    `filename=` 은 ASCII 만 이해하는 오래된 클라이언트를 위한 폴백이고,
    `filename*=UTF-8''...` 이 진짜 이름이다(RFC 5987). 한글 이름이 들어오면
    폴백 쪽은 거의 다 지워지므로, 비면 `download` 로 되돌린다 — 이름이 없는 것보다
    확장자만이라도 있는 편이 낫다는 #241 의 판단 그대로다.

    **이 값을 문자열 조립으로 다시 만들지 마라.** 어댑터 둘이 각자 만들던 동안
    그 안에는 사용자 문자열이 들어갈 수 없다는 전제가 숨어 있었다 — 이제 들어간다.
    """

    # **확장자를 떼고 이름만 ASCII 로 만든다.** 통째로 걸러 버리면 한글 이름은
    # 이름이 사라지고 확장자만 남아 `.py` 라는 **숨김 파일**이 된다 — 직접 그렇게
    # 만들어 보고 잡았다. 이름이 비면 `download` 로 되돌린다: 확장자만이라도
    # 살리는 것이 #241 의 판단 그대로다.
    stem, dot, extension = filename.rpartition(".")
    if not dot:
        stem, extension = filename, ""
    ascii_stem = unicodedata.normalize("NFKD", stem).encode("ascii", "ignore").decode("ascii")
    ascii_stem = _UNSAFE_IN_NAME.sub("", ascii_stem).strip(" .") or DEFAULT_DOWNLOAD_BASENAME
    ascii_name = f"{ascii_stem}.{extension}" if extension else ascii_stem
    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename, safe='')}"


def is_unknown_content_type(content_type: str | None) -> bool:
    """이 값이 형식을 말해 주지 않는가 (#268 후속).

    백필(`storage.management.commands.backfill_asset_content_types`)이 스토리지에
    기록된 형식을 쓸지 바이트로 판정할지 가를 때 이 판정을 쓴다 — 여기와 저기가
    "모른다"의 목록을 따로 들면, 백필이 `application/octet-stream` 을 채워 넣고
    이 파일이 그걸 다시 "모른다"로 읽는 어긋남이 생긴다.
    """

    if not content_type:
        return True
    return content_type.split(";", 1)[0].strip().lower() in _UNKNOWN_CONTENT_TYPES


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
