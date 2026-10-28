"""클래스 기준 채점 모델 카탈로그 — 조회·캐시 (#401).

**강사 본인의 키로 실제로 쓸 수 있는 모델만 보여준다**(CONTEXT.md 「채점
모델」) — 그래서 목록 API가 전역이 아니라 클래스 기준이다. 키가 없거나
거부됐거나 벤더 조회가 실패하면 `classroom.scoring_models.
FALLBACK_SCORING_MODEL_CHOICES`와 「조회하지 못했다」는 이유를 돌려준다.

**같은 키의 조회 결과는 짧게(분 단위) 캐시한다**(#401 AC "같은 키로 두 번
물으면 벤더를 한 번만 부른다") — 캐시 키는 채점 연결(#599)의 종류·주소·암호화된
값의 해시다(`ScoringConnection.cache_identity`): 원문 키를
캐시 키에 쓰지 않고, 그래도 키를 바꾸면(=암호문이 바뀌면) 캐시가 갈린다.
Fernet 암호화는 매 호출 비결정적(#284)이라 같은 클래스가 같은 키를 계속
쓰는 동안에는 저장된 암호문이 그대로라 캐시가 안정적으로 맞는다.

**배포되지 않은 환경(dev·CI)은 이 조회도 네트워크로 나가지 않는다**
(`classroom.scoring` 모듈 docstring, #340, ADR-0043과 같은 원칙) —
`CLASSROOM_SCORING_ADAPTER_MODE`가 fake(기본값)면 실제 `/v1/models`를 치는
대신 고정된 모델 id 목록을 규칙으로 거른 걸 "live"로 돌려준다. 채점 호출
자체(`classroom.scoring._scoring_adapter`)와 같은 스위치를 쓴다 — 스위치
하나가 "이 클래스 채점 관련 벤더 호출이 실제로 나가는가"를 전부 가른다.

**호환 서버(#601)는 거르지 않는다** — 그 서버가 내놓는 이름을 그대로 보여 주고(OpenAI 이름
규칙은 OpenAI 의 것이다), 목록을 주지 않거나 받지 못하면 `source="manual"` 로 모델 이름을
직접 넣게 한다(기본 목록은 OpenAI 모델이라 그 서버에 뜻이 없다).

**Claude(Anthropic) 키(#795)는 벤더가 `line`·`capabilities` 로 거른 목록이다** — Haiku·Sonnet 계열에
구조화 출력·추론 강도를 받는 모델만(`core.llm_scoring_anthropic.scoring_model_ids_from`). fake 스위치에서는
문서 예시 모양의 몸통(`FAKE_MODELS_BODY`)을 같은 거름으로 돌린다. 조회하지 못하면 Claude 의 작은 목록
(`ANTHROPIC_FALLBACK_SCORING_MODEL_CHOICES`)이다.
"""

from __future__ import annotations

from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache

from core.adapters import is_fake_adapter_binding
from core.llm_scoring import list_openai_models
from core.llm_scoring_anthropic import FAKE_MODELS_BODY, list_anthropic_scoring_models, scoring_model_ids_from

from .models import Class
from .scoring_connection import FAKE_COMPATIBLE_MODEL_IDS, ScoringConnection, connection_for
from .scoring_models import ScoringModelChoice, build_catalog, build_claude_catalog, fallback_choices_for

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


def _list_vendor_models(connection: ScoringConnection) -> list[str] | None:
    compatible = connection.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER
    anthropic = connection.kind == Class.ScoringConnectionKind.ANTHROPIC_KEY
    if is_fake_adapter_binding(settings.CLASSROOM_SCORING_ADAPTER_MODE):
        if anthropic:
            return scoring_model_ids_from(FAKE_MODELS_BODY)
        return list(FAKE_COMPATIBLE_MODEL_IDS if compatible else _FAKE_VENDOR_MODEL_IDS)
    if anthropic:
        return list_anthropic_scoring_models(connection.auth_value())
    return list_openai_models(
        connection.auth_value(), base_url=connection.base_url, transport=connection.transport()
    )


def _unfiltered_choices(model_ids: list[str]) -> tuple[ScoringModelChoice, ...]:
    return tuple(
        ScoringModelChoice(id=model_id, label=model_id, context_window=None, is_reasoning_model=False)
        for model_id in dict.fromkeys(model_ids)
    )


def remember_model_ids(connection: ScoringConnection, model_ids: list[str] | None) -> None:
    """저장할 때 이미 받은 목록을 캐시에 둔다 — 화면이 곧바로 같은 서버에 다시 묻지 않게."""

    if model_ids:
        cache.set(_CACHE_KEY_PREFIX + connection.cache_identity, model_ids, timeout=_CACHE_TTL_SECONDS)


@dataclass(frozen=True)
class ScoringModelCatalog:
    models: tuple[ScoringModelChoice, ...]
    #: "live"(벤더에게 실제로 물어 걸렀다) | "fallback"(저장소의 작은 목록) |
    #: "manual"(호환 서버가 목록을 주지 않았다 — 모델 이름을 직접 넣는다, #601).
    source: str
    #: `source`가 "fallback"일 때만 뜻이 있다 — "no_api_key" | "fetch_failed".
    #: 벤더가 401·403으로 거절한 경우도 "fetch_failed"로 묶는다: 이 API는
    #: 키 상태(`Class.openai_api_key_status`)를 바꾸지 않는다 — 그건
    #: `classroom.api.set_class_openai_key`가 저장 시점에 이미 하는 일이다.
    unavailable_reason: str | None = None


def _fallback(reason: str, kind: str = Class.ScoringConnectionKind.OPENAI_KEY) -> ScoringModelCatalog:
    return ScoringModelCatalog(models=fallback_choices_for(kind), source="fallback", unavailable_reason=reason)


def get_scoring_model_catalog(class_obj: Class) -> ScoringModelCatalog:
    connection = connection_for(class_obj)
    if connection is None:
        return _fallback("no_api_key", class_obj.scoring_connection_kind)

    # 연결(종류·주소·암호문)이 같으면 같은 목록이다 — 캐시가 맞으면 인증 값을 풀지 않는다.
    cache_key = _CACHE_KEY_PREFIX + connection.cache_identity
    vendor_ids = cache.get(cache_key)
    compatible = connection.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER
    if vendor_ids is None:
        vendor_ids = _list_vendor_models(connection)
        # 호환 서버·Claude 키는 빈 목록도 「받지 못했다」로 본다 — Claude 는 벤더가 이미 걸렀으니 빈
        # 목록이면 쓸 모델이 없다는 뜻이고, 작은 목록으로 물러선다.
        if vendor_ids is None or (not vendor_ids and connection.kind != Class.ScoringConnectionKind.OPENAI_KEY):
            if compatible:
                return ScoringModelCatalog(models=(), source="manual", unavailable_reason="no_model_list")
            return _fallback("fetch_failed", connection.kind)
        cache.set(cache_key, vendor_ids, timeout=_CACHE_TTL_SECONDS)

    if compatible:
        return ScoringModelCatalog(models=_unfiltered_choices(vendor_ids), source="live")

    if connection.kind == Class.ScoringConnectionKind.ANTHROPIC_KEY:
        return ScoringModelCatalog(models=tuple(build_claude_catalog(vendor_ids)), source="live")
    return ScoringModelCatalog(models=tuple(build_catalog(vendor_ids)), source="live")
