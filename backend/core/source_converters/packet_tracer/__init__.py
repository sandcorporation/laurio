"""Packet Tracer 변환 플러그인 (#497, #495) — 학생이 낸 `.pkt` 를 장비·결선·설정
요약 텍스트로 채점자에게 보낸다.

**판정은 EAX 인증 태그로 확정한다.** 형식이 고정 키 Twofish-EAX 라 태그가 맞으면
그 파일은 Packet Tracer 가 쓴 것이고, 쓰레기 입력은 태그 검증에서 확정적으로
떨어진다. 태그가 맞은 뒤의 실패(압축 해제·XML)와, 이름이 `.pkt` 인데 태그가 맞지
않는 파일(깨졌거나 잘렸다)은 `SourceConversionFailed` 로 「열 수 없는 Packet Tracer
파일」 줄을 남긴다 — 학생이 `.pkt` 를 냈다는 사실 자체가 채점자에게 보여야 한다.

**누구를 검사하나.** 해독은 순수 파이썬 Twofish 라 느리다(실측 약 250KB/s) —
UTF-8 로 못 읽는 바이너리마다 태그를 계산하지 않도록, 이름이 `.pkt` 이거나
확장자가 없는 파일(단일 파일 업로드는 선별 안에서 이름이 `source` 다)만 본다.
입력은 `MAX_INPUT_BYTES` 까지만 해독하고, 그보다 큰 `.pkt` 는 열 수 없는 파일로
남긴다. 해독은 Unpacket 에서 들여온 코드다(`_unpacket`, MIT).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from core.source_converters import ConvertedFile, SourceConversionFailed

from ._unpacket.crypto import PacketTracerDecodeError, decompress, is_authentic
from .summary import summarize

#: 해독할 입력의 상한 — 학생 과제는 보통 40~250KB 다. 이 크기면 해독이 수 초 안에
#: 끝나 선별의 시간 상한(`core.source_selection.CONVERTER_TIMEOUT_SECONDS`) 안에 든다.
MAX_INPUT_BYTES = 600_000

#: 압축 해제 상한 — 실측 85KB 파일이 약 1MB XML 로 풀린다.
MAX_XML_BYTES = 8_000_000


def _is_candidate(path: str) -> bool:
    name = path.rsplit("/", 1)[-1].lower()
    return name.endswith(".pkt") or "." not in name


class PacketTracerConverter:
    format_name = "Packet Tracer"

    def convert(self, raw: bytes, *, path: str) -> list[ConvertedFile] | None:
        if not _is_candidate(path):
            return None
        if len(raw) > MAX_INPUT_BYTES:
            if path.lower().endswith(".pkt"):
                raise SourceConversionFailed(f"{len(raw)}바이트라 해독 상한({MAX_INPUT_BYTES})을 넘는다.")
            return None

        authentic, decrypted = is_authentic(raw)
        if not authentic:
            # 이름이 `.pkt` 인데 태그가 맞지 않으면 깨졌거나 잘린 Packet Tracer 파일이다 —
            # 「설정이 없다」로 읽히지 않게 줄을 남긴다. 확장자 없는 파일은 그냥 남의 형식이다.
            if path.lower().endswith(".pkt"):
                raise SourceConversionFailed("EAX 인증 태그가 맞지 않는다(깨졌거나 잘린 파일).")
            return None
        try:
            xml = decompress(decrypted, max_bytes=MAX_XML_BYTES)
        except PacketTracerDecodeError as exc:
            raise SourceConversionFailed(str(exc)) from None
        # 고정 키라 누구나 태그가 맞는 파일을 만들 수 있다 — 엔티티 확장을 쓰는
        # XML(billion laughs)은 파싱하기 전에 거절한다. Packet Tracer 는 DTD 를 쓰지 않는다.
        if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
            raise SourceConversionFailed("DTD 가 든 XML 은 읽지 않는다.")
        try:
            text = summarize(xml)
        except ET.ParseError as exc:
            raise SourceConversionFailed(f"XML 을 읽을 수 없다({exc}).") from None
        return [ConvertedFile(name="요약.txt", content=text)]
