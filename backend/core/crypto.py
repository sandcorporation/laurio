"""값을 저장 전 암호화하는 Fernet/HMAC 헬퍼.

**`verification` 앱에 있던 것을 여기로 옮겼다(#269).** 이 코드는 신원 도메인을 하나도
모른다 — 설정에서 키를 읽어 바이트를 감싸고 풀 뿐이고, 이미 `verification`·`accounts`·
`payouts` 셋이 나눠 쓰고 있었다. 강의실이 공유층(`accounts`)을 쓰되 본인확인은 쓰지
않기로 하면서(ADR-0037), 공유층이 `verification` 을 최상단에서 import 하는 이 한 줄이
경계의 유일한 최상단 위반으로 남았다. 도구를 공유층으로 옮기는 쪽이 예외를 표시해
남기는 쪽보다 정직하다.

설정 키 이름은 `VERIFICATION_ENCRYPTION_KEY` 그대로다 — 배포 환경변수가 물려 있고,
그 키가 실제로 지키는 것이 여전히 신원 정보이기 때문이다.

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
