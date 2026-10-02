"""테스트 전용 변환 플러그인(#496) — `SOURCE_CONVERTERS`에 dotted path로 등록한다.

형식 판정은 실제 플러그인처럼 **내용**(앞머리 마법 바이트)으로 한다. 마법
바이트 뒤에 NUL을 둬 UTF-8로는 읽히지 않는, 곧 선별이 원래 버리던 파일이 된다.
"""

from __future__ import annotations

from core.source_converters import ConvertedFile, SourceConversionFailed

FAKEBIN_MAGIC = b"FAKEBIN\x00"
FAKEBAD_MAGIC = b"FAKEBAD\x00"


def fakebin(payload: str) -> bytes:
    """`MarkerConverter`가 「내 형식」으로 확정하는 바이너리 — 변환하면 `payload`가 나온다."""

    return FAKEBIN_MAGIC + payload.encode("utf-8")[::-1]


class MarkerConverter:
    format_name = "가짜 바이너리"

    def convert(self, raw: bytes, *, path: str) -> list[ConvertedFile] | None:
        if raw.startswith(FAKEBAD_MAGIC):
            raise SourceConversionFailed("가짜 바이너리를 확정했지만 해독에 실패했다.")
        if not raw.startswith(FAKEBIN_MAGIC):
            return None
        text = raw[len(FAKEBIN_MAGIC) :][::-1].decode("utf-8")
        return [ConvertedFile(name="요약.txt", content=text)]


class ExplodingConverter:
    """무엇을 받든 예상하지 못한 예외를 던진다 — 플러그인의 버그를 흉내낸다."""

    format_name = "터지는 형식"

    def convert(self, raw: bytes, *, path: str) -> list[ConvertedFile] | None:
        raise RuntimeError("플러그인 버그")


class NotAConverter:
    """계약(`format_name`·`convert`)을 갖추지 않은 클래스 — 부팅 검사가 거절해야 한다."""
