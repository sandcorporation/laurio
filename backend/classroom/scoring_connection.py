"""채점 연결 — 한 Class 가 채점 모델에 닿는 길(#599, CONTEXT.md 「채점 연결」, ADR-0058).

강의실 채점의 세 왕복 — 채점(`classroom.scoring._scoring_adapter`), 모델 목록 조회
(`classroom.scoring_model_catalog`), 저장 시점 키 확인(`classroom.scoring.check_scoring_key`)
— 이 모두 여기서 주소(base URL)·인증 값·추론 강도를 실을지를 받는다. 강의실 경로는 OpenAI
주소를 직접 쓰지 않는다(공모전은 `core.llm_scoring` 의 기본값을 그대로 쓴다).

연결 종류는 둘이다 — 「OpenAI 키」와 「호환 서버」(#601, ADR-0058). 호환 서버는 강사가 적은
주소라 모든 왕복이 `core.safe_outbound.SafeOutbound` 를 거친다(`ScoringConnection.transport`):
https·공인 IP 만, 푼 IP 로 직접 붙고, 리다이렉트를 따라가지 않는다. 저장할 때는
`probe_compatible_server` 가 그 서버의 모델 목록을 한 번 받아 닿는지·인증이 맞는지 본다.

**복호화는 실제로 벤더에 나갈 때만 한다**(#284) — `connection_for` 는 암호문을 쥐고 있다가
`auth_value()` 를 부를 때 푼다. 모델 목록 캐시는 `cache_identity` 로 찾으므로 캐시가 맞으면
풀지 않는다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from urllib.parse import urlsplit

from django.conf import settings

from core.adapters import is_fake_adapter_binding
from core.crypto import decrypt
from core.llm_scoring import OPENAI_API_BASE_URL, Transport
from core.safe_outbound import OutboundReason, OutboundRefused, SafeOutbound

from .models import Class
from .scoring_models import is_reasoning_model_id, matches_naming_rule

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
        if not self._encrypted_auth:
            return ""  # 인증 값을 비워 둔 호환 서버
        return decrypt(self._encrypted_auth)

    def transport(self) -> Transport | None:
        """왕복을 보낼 길 — 호환 서버는 강사가 적은 주소라 안전한 바깥 호출(#600)로만 나간다.
        OpenAI 키 연결은 `None`(그대로 `requests`)."""

        if self.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
            return SafeOutbound().request
        return None

    @property
    def cache_identity(self) -> str:
        """이 연결이 같은 곳에 같은 자격으로 닿는가를 가리는 값(모델 목록 캐시 키) — 평문을
        담지 않는다."""

        material = f"{self.kind}|{self.base_url}|{self._encrypted_auth or self._plain_auth}"
        return hashlib.sha256(material.encode("utf-8")).hexdigest()

    def accepts_model_name(self, model_id: str) -> bool:
        """채점 시점에 이 모델 이름을 받는가 — OpenAI 키 연결은 OpenAI 이름 규칙으로, 호환
        서버는 그 서버의 이름이라 거르지 않는다(#601, 비어 있지만 않으면)."""

        if self.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
            return bool(model_id.strip())
        return matches_naming_rule(model_id)

    def sends_reasoning_effort(self, model_id: str) -> bool:
        """채점 요청에 추론 강도를 실을지(#402) — OpenAI 키 연결은 모델 이름이 추론 모델일 때만.
        호환 서버는 싣지 않는다(이름 규칙이 OpenAI 것이 아니다 — 켜는 스위치는 #602)."""

        if self.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
            return False
        return is_reasoning_model_id(model_id)


def connection_for(class_obj: Class) -> ScoringConnection | None:
    """이 클래스의 채점 연결. 인증 값이 없으면(`has_scoring_key()` 가 거짓) `None` 이다."""

    if not class_obj.has_scoring_key():
        return None
    if class_obj.scoring_connection_kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        return ScoringConnection(
            kind=Class.ScoringConnectionKind.COMPATIBLE_SERVER,
            base_url=class_obj.scoring_server_url.strip(),
            _encrypted_auth=class_obj.openai_api_key_encrypted.strip(),
        )
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


# --- 호환 서버 -----------------------------------------------------------------------------

#: 저장을 거부한 이유 — 안전한 바깥 호출의 이유(`OutboundReason`)에 「인증 실패」를 더한다.
AUTH_FAILED = "auth_failed"

#: 거부 이유별 화면 문장(#601) — 저장 API 의 422 `detail` 로 그대로 나간다.
REFUSAL_MESSAGES: dict[str, str] = {
    OutboundReason.NOT_HTTPS: "https:// 로 시작하는 주소만 받습니다.",
    OutboundReason.NOT_PUBLIC: "공인 주소로 열린 서버만 받습니다 — 사설·내부 주소는 받지 않습니다.",
    OutboundReason.DNS_FAILED: "주소의 이름을 찾지 못했습니다 — 철자를 확인해주세요.",
    OutboundReason.CERTIFICATE: "서버 인증서를 확인하지 못했습니다 — 정식 인증서가 있어야 합니다(자체 서명은 안 됩니다).",
    OutboundReason.UNREACHABLE: "서버에 닿지 않습니다 — 서버가 켜져 있고 바깥에서 열려 있는지 확인해주세요.",
    OutboundReason.RESPONSE_FAILED: "서버가 제때 답하지 않았습니다 — 서버가 요청을 처리하고 있는지 확인해주세요.",
    OutboundReason.REDIRECT: "서버가 다른 주소로 넘기려 했습니다 — 넘어가는 최종 주소를 넣어주세요.",
    OutboundReason.OFFLINE: "지금은 바깥 서버에 닿을 수 없습니다.",
    AUTH_FAILED: "서버가 인증 값을 거절했습니다 — Bearer 값을 확인해주세요.",
}

#: dev·CI(fake 스위치)에서 호환 서버가 내놓는 것으로 치는 모델 목록 — OpenAI 이름 규칙에 맞지
#: 않는 이름을 섞어, 목록을 거르지 않는다는 것이 네트워크 없이도 보이게 한다.
FAKE_COMPATIBLE_MODEL_IDS = ("llama-3.1-8b-instruct", "qwen2.5-coder-32b-instruct", "gpt-4o-mini")


class CompatibleServerRefused(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

    @property
    def message(self) -> str:
        return REFUSAL_MESSAGES.get(self.reason, REFUSAL_MESSAGES[OutboundReason.UNREACHABLE])


def normalize_server_url(url: str) -> str:
    return url.strip().rstrip("/")


def server_host(url: str) -> str:
    """화면이 보이는 호스트(포트가 있으면 붙인다) — 공동 강사도 읽는 값이다."""

    parts = urlsplit(url)
    host = parts.hostname or ""
    return f"{host}:{parts.port}" if parts.port else host


def compatible_server_connection(url: str, auth_value: str) -> ScoringConnection:
    """저장하기 전의 호환 서버 연결 — 저장 시점 확인이 쓴다."""

    return ScoringConnection(
        kind=Class.ScoringConnectionKind.COMPATIBLE_SERVER,
        base_url=normalize_server_url(url),
        _plain_auth=auth_value,
    )


def probe_compatible_server(url: str, auth_value: str) -> list[str] | None:
    """저장할 때 이 서버에 한 번 닿아 본다(#601) — 모델 목록(`GET …/models`)을 받는다.

    거부·실패는 `CompatibleServerRefused`(이유별). 401·403 은 인증 실패다. 닿았는데 목록을
    주지 않으면(그 밖의 상태·모양이 다른 몸통) `None` — 저장은 되고 모델 이름을 직접 넣는다.
    목록은 OpenAI 이름 규칙으로 거르지 않는다.

    fake 스위치(dev·CI)에서는 주소 모양만 보고(`SafeOutbound.check`) 나가지 않는다 — 채점
    어댑터·모델 목록 조회와 같은 스위치다(ADR-0043)."""

    outbound = SafeOutbound()
    try:
        outbound.check(url)
    except OutboundRefused as exc:
        raise CompatibleServerRefused(exc.reason) from None
    if is_fake_adapter_binding(settings.CLASSROOM_SCORING_ADAPTER_MODE):
        return list(FAKE_COMPATIBLE_MODEL_IDS)

    headers = {"Authorization": f"Bearer {auth_value}"} if auth_value else {}
    try:
        response = outbound.get(f"{normalize_server_url(url)}/models", headers=headers, timeout=15)
    except OutboundRefused as exc:
        raise CompatibleServerRefused(exc.reason) from None
    if response.status_code in (401, 403):
        raise CompatibleServerRefused(AUTH_FAILED)
    if response.status_code != 200:
        return None
    return model_ids_from(response)


def model_ids_from(response) -> list[str] | None:
    try:
        body = response.json()
    except ValueError:
        return None
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return None
    ids = [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]
    return list(dict.fromkeys(ids)) or None
