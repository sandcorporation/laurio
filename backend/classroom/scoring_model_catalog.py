"""클래스 기준 채점 모델 카탈로그 — 조회·캐시 (#401).

**강사 본인의 키로 실제로 쓸 수 있는 모델만 보여준다**(CONTEXT.md 「채점
모델」) — 그래서 목록 API가 전역이 아니라 클래스 기준이다. 키가 없거나
거부됐거나 벤더 조회가 실패하면 `classroom.scoring_models.
FALLBACK_SCORING_MODEL_CHOICES`와 「조회하지 못했다」는 이유를 돌려준다.

**같은 키의 조회 결과는 짧게(분 단위) 캐시한다**(#401 AC "같은 키로 두 번
물으면 벤더를 한 번만 부른다") — 캐시 키는 암호화된 값의 해시다: 원문 키를
캐시 키에 쓰지 않고, 그래도 키를 바꾸면(=암호문이 바뀌면) 캐시가 갈린다.
Fernet 암호화는 매 호출 비결정적(#284)이라 같은 클래스가 같은 키를 계속
쓰는 동안에는 저장된 암호문이 그대로라 캐시가 안정적으로 맞는다.

**배포되지 않은 환경(dev·CI)은 이 조회도 네트워크로 나가지 않는다**
(`classroom.scoring` 모듈 docstring, #340, ADR-0043과 같은 원칙) —
`CLASSROOM_SCORING_ADAPTER_MODE`가 fake(기본값)면 실제 `/v1/models`를 치는
대신 고정된 모델 id 목록을 규칙으로 거른 걸 "live"로 돌려준다. 채점 호출
자체(`classroom.scoring._scoring_adapter`)와 같은 스위치를 쓴다 — 스위치
하나가 "이 클래스 채점 관련 벤더 호출이 실제로 나가는가"를 전부 가른다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from core.adapters import is_fake_adapter_binding
from core.crypto import decrypt
from core.llm_scoring import list_openai_models

from .models import Class
from .scoring_models import FALLBACK_SCORING_MODEL_CHOICES, ScoringModelChoice, build_catalog

_CACHE_KEY_PREFIX = "classroom:scoring-models:"
_CACHE_TTL_SECONDS = 300

#: dev·CI(`CLASSROOM_SCORING_ADAPTER_MODE=fake`)에서 실제 벤더 대신 쓰는 고정
#: 목록 — 4o·4.1 계열과 추론 모델(gpt-5.5, gpt-5, gpt-5-mini)을 섞어, 키를 넣으면
#: "live" 카탈로그가 어떻게 보이는지(추론 강도 칸 포함)를 네트워크 없이도
#: 확인할 수 있게 한다.
_FAKE_VENDOR_MODEL_IDS = (
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "gpt-5.5",
    "gpt-5",
    "gpt-5-mini",
)


def _list_vendor_models(api_key: str) -> list[str] | None:
    if is_fake_adapter_binding(settings.CLASSROOM_SCORING_ADAPTER_MODE):
        return list(_FAKE_VENDOR_MODEL_IDS)
    return list_openai_models(api_key)


@dataclass(frozen=True)
class ScoringModelCatalog:
    models: tuple[ScoringModelChoice, ...]
    #: "live"(벤더에게 실제로 물어 걸렀다) | "fallback"(저장소의 작은 목록).
    source: str
    #: `source`가 "fallback"일 때만 뜻이 있다 — "no_api_key" | "fetch_failed".
    #: 벤더가 401·403으로 거절한 경우도 "fetch_failed"로 묶는다: 이 API는
    #: 키 상태(`Class.openai_api_key_status`)를 바꾸지 않는다 — 그건
    #: `classroom.api.set_class_openai_key`가 저장 시점에 이미 하는 일이다.
    unavailable_reason: str | None = None


def _fallback(reason: str) -> ScoringModelCatalog:
    return ScoringModelCatalog(
        models=FALLBACK_SCORING_MODEL_CHOICES, source="fallback", unavailable_reason=reason
    )


def _cache_key(encrypted_key: str) -> str:
    return _CACHE_KEY_PREFIX + hashlib.sha256(encrypted_key.encode("utf-8")).hexdigest()


def get_scoring_model_catalog(class_obj: Class) -> ScoringModelCatalog:
    if not class_obj.has_scoring_key():
        return _fallback("no_api_key")

    encrypted = class_obj.openai_api_key_encrypted
    cache_key = _cache_key(encrypted)
    vendor_ids = cache.get(cache_key)
    if vendor_ids is None:
        vendor_ids = _list_vendor_models(decrypt(encrypted))
        if vendor_ids is None:
            return _fallback("fetch_failed")
        cache.set(cache_key, vendor_ids, timeout=_CACHE_TTL_SECONDS)

    return ScoringModelCatalog(models=tuple(build_catalog(vendor_ids)), source="live")
