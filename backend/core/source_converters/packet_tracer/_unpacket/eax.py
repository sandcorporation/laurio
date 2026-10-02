# 원본: Unpacket Decipher/eax.py (MIT, 커밋 54cb6d6) — 복호화 전에 태그를 먼저
# 검증하도록 decrypt 의 순서를 바꿨다(이 꾸러미의 __init__ 참고).
from typing import Callable

from .cmac import BLOCK_SIZE, CMAC, xor_bytes
from .ctr import CTR


def _omac_with_prefix(cmac: CMAC, prefix: int, data: bytes) -> bytes:
    # 16바이트 접두: [0, 0, ..., prefix]
    P = b'\x00' * (BLOCK_SIZE - 1) + bytes([prefix])
    return cmac.digest(P + data)


class EAX:
    def __init__(self, encrypt_block: Callable[[bytes], bytes]):
        self.encrypt_block = encrypt_block
        self.cmac = CMAC(encrypt_block)

    def encrypt(self, nonce: bytes, plaintext: bytes, aad: bytes = b''):
        # OMAC_0 = CMAC(0x00 || nonce)
        n_tag = _omac_with_prefix(self.cmac, 0x00, nonce)

        # OMAC_1 = CMAC(0x01 || aad)
        h_tag = _omac_with_prefix(self.cmac, 0x01, aad)

        # CTR 는 n_tag 에서 시작한다
        ctr = CTR(self.encrypt_block, n_tag)
        ciphertext = ctr.process(plaintext)

        # OMAC_2 = CMAC(0x02 || ciphertext)
        c_tag = _omac_with_prefix(self.cmac, 0x02, ciphertext)

        # 최종 TAG = n_tag ⊕ h_tag ⊕ c_tag
        tag = xor_bytes(xor_bytes(n_tag, h_tag), c_tag)

        return ciphertext, tag

    def decrypt(self, nonce: bytes, ciphertext: bytes, tag: bytes, aad: bytes = b''):
        n_tag = _omac_with_prefix(self.cmac, 0x00, nonce)
        h_tag = _omac_with_prefix(self.cmac, 0x01, aad)
        c_tag = _omac_with_prefix(self.cmac, 0x02, ciphertext)

        # 태그부터 본다 — 맞지 않으면 CTR 로 풀어 볼 이유가 없다.
        expected_tag = xor_bytes(xor_bytes(n_tag, h_tag), c_tag)
        if expected_tag != tag:
            raise ValueError("EAX authentication failed")

        ctr = CTR(self.encrypt_block, n_tag)
        return ctr.process(ciphertext)
