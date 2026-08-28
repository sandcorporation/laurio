"""실명·생년월일·CI/DI를 저장 전 암호화하는 헬퍼.

`Verification`이 다루는 값은 신원 정보이므로 평문으로 DB에 남기지 않는다(ADR-0011).
CI는 "동일인 판별"에 쓰여야 하므로 Fernet 암호문(매번 다른 IV로 비결정적) 옆에
HMAC-SHA256 해시(`ci_hash`, 결정적)를 같이 둔다 — 조회는 해시로, 열람은 복호화로.
"""

from __future__ import annotations

import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings


class DecryptionError(Exception):
    pass


def _key_bytes() -> bytes:
    key = settings.VERIFICATION_ENCRYPTION_KEY
    return key.encode() if isinstance(key, str) else key


def encrypt(value: str) -> str:
    return Fernet(_key_bytes()).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt(token: str) -> str:
    if not token:
        return ""
    try:
        return Fernet(_key_bytes()).decrypt(token.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError("stored value could not be decrypted") from exc


def ci_hash(ci: str) -> str:
    """CI에 대한 결정적 해시. 동일인 조회는 이 값으로만 한다(원문 인덱싱 금지)."""

    return hmac.new(_key_bytes(), ci.encode("utf-8"), hashlib.sha256).hexdigest()
