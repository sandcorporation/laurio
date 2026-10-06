"""채점 연결 — 한 Class 가 채점 모델에 닿는 길(#599, CONTEXT.md 「채점 연결」, ADR-0058).

강의실 채점의 세 왕복 — 채점(`classroom.scoring._scoring_adapter`), 모델 목록 조회
(`classroom.scoring_model_catalog`), 저장 시점 키 확인(`classroom.scoring.check_scoring_key`)
— 이 모두 여기서 주소(base URL)·인증 값·추론 강도를 실을지를 받는다. 강의실 경로는 OpenAI
주소를 직접 쓰지 않는다(공모전은 `core.llm_scoring` 의 기본값을 그대로 쓴다).

지금 연결 종류는 「OpenAI 키」 하나다. 호환 서버(#601)는 `Class.ScoringConnectionKind` 에
값을 하나 더하고 `connection_for` 의 분기 하나를 더한다.

**복호화는 실제로 벤더에 나갈 때만 한다**(#284) — `connection_for` 는 암호문을 쥐고 있다가
`auth_value()` 를 부를 때 푼다. 모델 목록 캐시는 `cache_identity` 로 찾으므로 캐시가 맞으면
풀지 않는다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from core.crypto import decrypt
from core.llm_scoring import OPENAI_API_BASE_URL

from .models import Class
from .scoring_models import is_reasoning_model_id

#: 「OpenAI 키」 연결의 주소 — 공모전과 같은 OpenAI API 다.
OPENAI_KEY_BASE_URL = OPENAI_API_BASE_URL


@dataclass(frozen=True)
class ScoringConnection:
    kind: str
    base_url: str
    #: 저장된 그대로의 인증 값(암호문). 저장 전 확인처럼 아직 암호문이 없으면 비고
    #: `_plain_auth` 가 평문을 쥔다.
    _encrypted_auth: str = ""
    _plain_auth: str = ""

    def auth_value(self) -> str:
        """`Authorization: Bearer` 로 실을 값 — OpenAI 키 연결이면 소유자의 키."""

        if self._plain_auth:
            return self._plain_auth
        return decrypt(self._encrypted_auth)

    @property
    def cache_identity(self) -> str:
        """이 연결이 같은 곳에 같은 자격으로 닿는가를 가리는 값(모델 목록 캐시 키) — 평문을
        담지 않는다."""

        material = f"{self.kind}|{self.base_url}|{self._encrypted_auth or self._plain_auth}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def sends_reasoning_effort(self, model_id: str) -> bool:
        """채점 요청에 추론 강도를 실을지(#402) — OpenAI 키 연결은 모델 이름이 추론 모델일 때만."""

        return is_reasoning_model_id(model_id)


def connection_for(class_obj: Class) -> ScoringConnection | None:
    """이 클래스의 채점 연결. 인증 값이 없으면(`has_scoring_key()` 가 거짓) `None` 이다."""

    if not class_obj.has_scoring_key():
        return None
    return ScoringConnection(
        kind=Class.ScoringConnectionKind.OPENAI_KEY,
        base_url=OPENAI_KEY_BASE_URL,
        _encrypted_auth=class_obj.openai_api_key_encrypted.strip(),
    )


def openai_key_connection(api_key: str) -> ScoringConnection:
    """저장하기 전의 OpenAI 키로 만든 연결 — 저장 시점 키 확인(#354)이 쓴다."""

    return ScoringConnection(
        kind=Class.ScoringConnectionKind.OPENAI_KEY,
        base_url=OPENAI_KEY_BASE_URL,
        _plain_auth=api_key,
    )
