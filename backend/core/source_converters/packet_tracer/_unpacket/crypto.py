# 원본: Unpacket Decipher/pt_crypto.py(해독)와 repacket.py(역방향) (MIT, 커밋 54cb6d6).
# 바꾼 것: 압축 해제 상한, 실패를 PacketTracerDecodeError 하나로 모음, 역방향 함수
# 하나로 합침(테스트 픽스처용). 형식: 바이트 XOR → Twofish-EAX(고정 키) → XOR →
# zlib(Qt qCompress, 앞 4바이트가 원래 크기).
import struct
import zlib

from .eax import EAX
from .twofish import Twofish

_KEY = bytes([137]) * 16
_IV = bytes([16]) * 16
_TAG_SIZE = 16


class PacketTracerDecodeError(Exception):
    """EAX 태그는 맞았지만(= Packet Tracer 파일이다) 그 뒤가 깨졌다."""


def _deobf_stage1(data: bytes) -> bytes:
    L = len(data)
    return bytes(data[L - 1 - i] ^ (L - i * L & 0xFF) for i in range(L))


def _obf_stage1(data: bytes) -> bytes:
    L = len(data)
    output = bytearray(L)
    for i in range(L):
        output[L - 1 - i] = data[i] ^ ((L - i * L) & 0xFF)
    return bytes(output)


def _xor_stage2(data: bytes) -> bytes:
    # XOR 이라 대칭이다 — 해독과 역방향이 같은 함수다.
    L = len(data)
    return bytes(b ^ (L - i & 0xFF) for i, b in enumerate(data))


def is_authentic(pkt: bytes) -> tuple[bool, bytes]:
    """EAX 태그가 맞는가 — 맞으면 (True, 복호화된 바이트). 고정 키라 「이 파일이
    Packet Tracer 가 쓴 것인가」를 확정적으로 가른다(쓰레기 입력은 여기서 떨어진다)."""

    if len(pkt) <= _TAG_SIZE:
        return False, b""
    stage1 = _deobf_stage1(pkt)
    eax = EAX(Twofish(_KEY).encrypt)
    try:
        return True, eax.decrypt(nonce=_IV, ciphertext=stage1[:-_TAG_SIZE], tag=stage1[-_TAG_SIZE:])
    except ValueError:
        return False, b""


def decompress(decrypted: bytes, *, max_bytes: int) -> bytes:
    """`is_authentic` 이 낸 바이트를 XML 로 — 해제 결과가 `max_bytes` 를 넘으면 그
    자리에서 멈추고 실패로 본다(원본의 수십 배로 부푸는 입력이 메모리를 먹지 않게)."""

    stage2 = _xor_stage2(decrypted)
    if len(stage2) < 4:
        raise PacketTracerDecodeError("압축 머리가 없다.")
    size = struct.unpack(">I", stage2[:4])[0]
    if size > max_bytes:
        raise PacketTracerDecodeError(f"풀면 {size}바이트라 상한({max_bytes})을 넘는다.")
    inflater = zlib.decompressobj()
    try:
        xml = inflater.decompress(stage2[4:], max_bytes + 1)
    except zlib.error as exc:
        raise PacketTracerDecodeError(f"압축을 풀 수 없다({exc}).") from None
    if len(xml) > max_bytes or inflater.unconsumed_tail:
        raise PacketTracerDecodeError(f"풀린 크기가 상한({max_bytes})을 넘는다.")
    return xml[:size]


def encrypt_xml(xml: bytes, *, declared_size: int | None = None) -> bytes:
    """역방향 — 테스트가 손으로 쓴 XML 로 `.pkt` 픽스처를 만든다. `declared_size` 는
    압축 머리의 크기를 속인 파일(해제 상한 시험용)을 만들 때만 쓴다."""

    size = len(xml) if declared_size is None else declared_size
    stage2 = _xor_stage2(struct.pack(">I", size) + zlib.compress(xml))
    ciphertext, tag = EAX(Twofish(_KEY).encrypt).encrypt(nonce=_IV, plaintext=stage2)
    return _obf_stage1(ciphertext + tag)
