"""바이트 앞부분으로 content-type 을 알아낸다 (#268 후속).

**왜 필요한가.** `SubmissionAsset.content_type` 은 #241 이 만든 필드다 — 그 전에
올라간 자료는 값이 비어 있고, 그러면 다운로드 파일명에 확장자가 붙지 않는다
(`storage.filenames.build_download_filename`). staging 실측(2026-09-10): 소스
37건·시연 영상 15건이 그 상태였고, 과제 제출물은 **전부** 그랬다.

**왜 스토리지의 메타데이터를 안 읽는가.** 오브젝트에도 Content-Type 이 붙어
있지만, 그것을 읽으려면 어댑터에 조회 표면(head)을 새로 열어야 한다 —
ADR-0035 가 삭제 하나만 열면서 남긴 규율(필요한 것만 연다)을 굳이 거스를 이유가
없다. `read_object` 는 이미 계약에 있고, 형식을 아는 데 필요한 것은 앞의 몇
바이트뿐이다.

**모르면 모른다고 답한다.** 억지로 `application/octet-stream` 을 채우면
`build_download_filename` 이 그것을 "모른다"로 다시 해석해(`_UNKNOWN_CONTENT_TYPES`)
결과는 같은데 DB 에는 거짓이 남는다. 그래서 판정하지 못한 바이트에는 None 을
돌려주고, 부르는 쪽이 그 행을 건드리지 않는다.

**평문은 판정하지 않는다.** 이 플랫폼은 zip 이 아닌 단일 파일도 소스로 받는데
(#260), `app.py` 같은 평문에는 매직 바이트가 없다. "UTF-8 로 읽히면 text/plain"
같은 규칙을 두면 `.py` 파일에 `.txt` 가 붙어 **틀린 확장자**가 생긴다 — 확장자가
없는 것보다 나쁘다. 그래서 평문은 모른다고 답하고 그 행은 비워 둔다.

**표는 `storage.filenames._KNOWN_EXTENSIONS` 와 짝이다.** 저쪽이 "이 형식은 어떤
확장자인가"를 알고 이쪽이 "이 바이트는 어떤 형식인가"를 안다 — 한쪽에만 있는
형식은 백필해도 확장자가 안 붙으므로, 형식을 더할 때는 두 곳을 같이 본다.
"""

from __future__ import annotations

#: 앞에서 이만큼만 읽으면 아래 판정이 전부 성립한다. tar 의 `ustar` 표식이
#: 오프셋 257 에 있어 그것이 하한을 정한다 — 512 는 tar 블록 하나이기도 하다.
SNIFF_BYTES = 512


def sniff_content_type(head: bytes | None) -> str | None:
    """바이트 앞부분 -> content-type, 모르면 None.

    `head` 는 `SNIFF_BYTES` 만큼(또는 오브젝트가 더 짧으면 그만큼) 읽은 앞부분이다.
    """

    if not head:
        return None

    # 압축 묶음 — 이 플랫폼이 소스로 실제로 받는 것들.
    if head.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        return "application/zip"
    if head.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if head.startswith(b"7z\xbc\xaf\x27\x1c"):
        return "application/x-7z-compressed"
    if head.startswith(b"Rar!\x1a\x07"):
        return "application/vnd.rar"
    # tar 는 매직이 앞이 아니라 오프셋 257 에 있다(POSIX ustar 헤더).
    if len(head) >= 262 and head[257:262] == b"ustar":
        return "application/x-tar"

    # 영상 — 시연 영상 자료.
    if len(head) >= 12 and head[4:8] == b"ftyp":
        # ftyp 브랜드가 mp4 계열과 QuickTime 을 가른다.
        return "video/quicktime" if head[8:12] == b"qt  " else "video/mp4"
    if head.startswith(b"\x1aE\xdf\xa3"):
        # Matroska 컨테이너 — 이 플랫폼 맥락에서는 webm 이다.
        return "video/webm"
    if head.startswith(b"RIFF") and len(head) >= 12 and head[8:12] == b"AVI ":
        return "video/x-msvideo"

    # 이미지 — 스크린샷 자료(ADR-0036).
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"RIFF") and len(head) >= 12 and head[8:12] == b"WEBP":
        return "image/webp"
    if head.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"

    if head.startswith(b"%PDF-"):
        return "application/pdf"

    return None
