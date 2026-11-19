"""클래스 기준 채점 모델 카탈로그 — 조회·캐시 (#401).

**강사 본인의 키로 실제로 쓸 수 있는 모델만 보여준다**(CONTEXT.md 「채점
모델」) — 그래서 목록 API가 전역이 아니라 클래스 기준이다. 키가 없거나
거부됐거나 벤더 조회가 실패하면 `classroom.scoring_models.
FALLBACK_SCORING_MODEL_CHOICES`와 「조회하지 못했다」는 이유를 돌려준다.

**같은 키의 조회 결과는 캐시한다** — 고르는 화면은 5분까지 믿고, 비용 어림은 하루 묵은
값도 쓰며 캐시가 없으면 벤더에 묻지 않고 작은 목록으로 어림한다(#982,
`cached_scoring_model_catalog`). 5분은 #401 AC "같은 키로 두 번 물으면 벤더를 한 번만
부른다"에서 왔다 — 캐시 키는 채점 연결(#599)의 종류·주소·암호화된
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

import time
from dataclasses import dataclass
from typing import TypedDict

from django.conf import settings
from django.core.cache import cache

from core.adapters import is_fake_adapter_binding
from core.llm_scoring import list_openai_models
from core.llm_scoring_anthropic import FAKE_MODELS_BODY, list_anthropic_scoring_models, scoring_model_ids_from

from .models import Class
from .scoring_connection import FAKE_COMPATIBLE_MODEL_IDS, ScoringConnection, connection_for
from .scoring_models import ScoringModelChoice, build_catalog, build_claude_catalog, fallback_choices_for

_CACHE_KEY_PREFIX = "classroom:scoring-models:"
#: 모델 고르는 화면(`get_scoring_model_catalog`)이 이 나이까지만 믿고, 넘으면 벤더에 다시 묻는다.
_FRESH_SECONDS = 300
#: 비용 어림(`cached_scoring_model_catalog`)은 이 나이까지 묵은 목록도 쓴다(#982) — 캐시 키가
#: 연결(종류·주소·암호문)이라 키를 바꾸면 저절로 갈리고, 남는 것은 「그 사이 벤더가 모델을
#: 더하거나 뺐다」뿐이다. 그 차이는 어림 줄 몇 개이고, 고르는 화면이 5분마다 바로잡는다.
_STALE_SECONDS = 24 * 60 * 60


class _CachedModelIds(TypedDict):
    ids: list[str]
    #: 벤더에게 받은 시각(`time.time()`) — 고르는 화면이 「5분 안」을 이것으로 가른다.
    fetched_at: float


def _now() -> float:
    return time.time()

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
        _store(connection, model_ids)


def _store(connection: ScoringConnection, model_ids: list[str]) -> None:
    entry: _CachedModelIds = {"ids": list(model_ids), "fetched_at": _now()}
    cache.set(_CACHE_KEY_PREFIX + connection.cache_identity, entry, timeout=_STALE_SECONDS)


def _cached(connection: ScoringConnection) -> _CachedModelIds | None:
    entry = cache.get(_CACHE_KEY_PREFIX + connection.cache_identity)
    # 예전 모양(목록만)은 조회 시각을 몰라 없는 것으로 본다.
    if not isinstance(entry, dict) or not isinstance(entry.get("ids"), list):
        return None
    return entry


@dataclass(frozen=True)
class ScoringModelCatalog:
    models: tuple[ScoringModelChoice, ...]
    #: "live"(벤더에게 실제로 물어 걸렀다) | "fallback"(저장소의 작은 목록) |
    #: "manual"(호환 서버가 목록을 주지 않았다 — 모델 이름을 직접 넣는다, #601).
    source: str
    #: `source`가 "fallback"일 때만 뜻이 있다 — "no_api_key" | "fetch_failed" |
    #: "not_cached"(비용 어림이 벤더에 묻지 않았다 — `cached_scoring_model_catalog`, #982).
    #: 벤더가 401·403으로 거절한 경우도 "fetch_failed"로 묶는다: 이 API는
    #: 키 상태(`Class.openai_api_key_status`)를 바꾸지 않는다 — 그건
    #: `classroom.api.set_class_openai_key`가 저장 시점에 이미 하는 일이다.
    unavailable_reason: str | None = None


def _fallback(reason: str, kind: str = Class.ScoringConnectionKind.OPENAI_KEY) -> ScoringModelCatalog:
    return ScoringModelCatalog(models=fallback_choices_for(kind), source="fallback", unavailable_reason=reason)


def get_scoring_model_catalog(class_obj: Class) -> ScoringModelCatalog:
    """모델 고르는 화면·저장 검증이 쓴다 — 5분 넘은 목록이면 벤더에게 다시 묻는다(요청 안 왕복)."""

    connection = connection_for(class_obj)
    if connection is None:
        return _fallback("no_api_key", class_obj.scoring_connection_kind)

    # 연결(종류·주소·암호문)이 같으면 같은 목록이다 — 캐시가 맞으면 인증 값을 풀지 않는다.
    entry = _cached(connection)
    if entry is not None and _now() - entry["fetched_at"] < _FRESH_SECONDS:
        return _live_catalog(connection, entry["ids"])

    vendor_ids = _list_vendor_models(connection)
    # 호환 서버·Claude 키는 빈 목록도 「받지 못했다」로 본다 — Claude 는 벤더가 이미 걸렀으니 빈
    # 목록이면 쓸 모델이 없다는 뜻이고, 작은 목록으로 물러선다.
    if vendor_ids is None or (not vendor_ids and connection.kind != Class.ScoringConnectionKind.OPENAI_KEY):
        if connection.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
            return ScoringModelCatalog(models=(), source="manual", unavailable_reason="no_model_list")
        return _fallback("fetch_failed", connection.kind)
    _store(connection, vendor_ids)
    return _live_catalog(connection, vendor_ids)


def cached_scoring_model_catalog(class_obj: Class) -> ScoringModelCatalog:
    """비용 어림(#591)이 쓴다 — **벤더에게 묻지 않는다**(#982).

    고르는 화면이 받아 둔 목록이면 하루까지 묵었어도 그대로 쓰고, 없으면 조회하지 못했을 때와
    같은 작은 목록(`fallback_choices_for`)이다. 비용 어림은 화면을 열 때마다 불리고(MCP 읽기
    도구도), 한산한 뒤 첫 요청이 벤더 왕복(1~2.5초)을 기다리던 것이 GlitchTip 127 이었다.
    fake 스위치(dev·CI)는 네트워크가 없으니 고정 목록을 그대로 쓴다."""

    connection = connection_for(class_obj)
    if connection is None:
        return _fallback("no_api_key", class_obj.scoring_connection_kind)
    entry = _cached(connection)
    if entry is not None:
        return _live_catalog(connection, entry["ids"])
    if is_fake_adapter_binding(settings.CLASSROOM_SCORING_ADAPTER_MODE):
        fake_ids = _list_vendor_models(connection)
        if fake_ids:
            return _live_catalog(connection, fake_ids)
    if connection.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        return ScoringModelCatalog(models=(), source="manual", unavailable_reason="no_model_list")
    return _fallback("not_cached", connection.kind)


def _live_catalog(connection: ScoringConnection, vendor_ids: list[str]) -> ScoringModelCatalog:
    if connection.kind == Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        return ScoringModelCatalog(models=_unfiltered_choices(vendor_ids), source="live")
    if connection.kind == Class.ScoringConnectionKind.ANTHROPIC_KEY:
        return ScoringModelCatalog(models=tuple(build_claude_catalog(vendor_ids)), source="live")
    return ScoringModelCatalog(models=tuple(build_catalog(vendor_ids)), source="live")
