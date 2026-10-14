"""모델 시험 호출 — 호환 서버의 모델이 채점 형식을 지키는지 고를 때 확인한다(#602, ADR-0058).

호환 서버의 모델은 이름만으로 채점에 쓸 수 있는지 알 수 없다 — 구조화된 판정(`json_schema`)을
지키지 못하는 모델을 고르면 학생 시도마다 「형식 깨짐」 실패가 쌓인다. 그래서 소유자·강사가
모델을 고를 때(클래스 기본·문제별) 짧은 고정 프롬프트로 채점과 **같은 어댑터·같은 요청 모양**
(`classroom.scoring._scoring_adapter` → `json_schema` 판정 하나)을 한 번 보내 본다.

- 결과는 (연결, 모델, 추론 여부) 단위로 캐시한다 — 같은 선택을 다시 해도 서버에 다시 묻지 않는다.
  통과만 캐시한다: 실패는 소유자가 서버를 고친 뒤 바로 다시 고를 수 있어야 한다.
- 「OpenAI 키」 연결은 시험하지 않는다 — 이름으로 판단한다(모델 목록이 이미 걸렀다).
- fake 스위치(dev·CI)에서는 네트워크로 나가지 않는다 — 채점과 같은 스위치(ADR-0043)라
  `FakeClassroomScoringAdapter` 가 판정을 흉내 낸다. 거부되는 화면을 dev 에서도 볼 수 있게
  `FAKE_FORMAT_FAILING_MODEL_IDS` 의 이름은 형식을 못 지킨 것으로 친다.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.cache import cache

from core.adapters import is_fake_adapter_binding
from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterError,
    LLMAdapterModelRejectedError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterRateLimitedError,
    LLMAdapterUnreachableError,
    RequirementInput,
    ScoringInput,
    SourceFile,
)

from .models import Class
from core.safe_outbound import OutboundReason

from .scoring_connection import AUTH_FAILED, REFUSAL_MESSAGES, ScoringConnection

#: 시험 호출은 HTTP 요청(모델 저장) 안에서 돈다 — 채점의 3분이 아니라 gunicorn 요청 안에 든다.
PROBE_TIMEOUT_SECONDS = 20

_CACHE_KEY_PREFIX = "classroom:scoring-model-probe:"
#: 통과한 결과를 하루 둔다 — 그 사이 서버의 모델이 바뀌면 채점이 「모델 거부」·실패로 알린다.
_CACHE_TTL_SECONDS = 24 * 60 * 60

PROBE_REQUIREMENT_ID = 1
PROBE_SOURCE = 'print("hello")\n'
#: 시험 호출의 고정 프롬프트 — 채점 프롬프트(`classroom.scoring._build_prompt`)와 같은 꼴로 짧게.
PROBE_PROMPT = "\n".join(
    [
        "문제 제목: 인사 출력",
        "",
        "아래 체크리스트 항목마다 제출된 소스를 직접 읽고 충족 여부를 판정하세요. "
        "모든 requirement_id에 대해 빠짐없이 판정을 반환해야 합니다. "
        "판정 근거(reasoning)는 한국어 문장으로 쓰세요.",
        "",
        "체크리스트:",
        f"- requirement_id={PROBE_REQUIREMENT_ID} (필수): hello 를 출력한다",
        "",
        "제출 형식: source",
        "제출된 소스:",
        PROBE_SOURCE,
    ]
)

#: dev·CI 에서 형식을 못 지키는 것으로 치는 모델 이름 — `FAKE_COMPATIBLE_MODEL_IDS` 에도 있다.
FAKE_FORMAT_FAILING_MODEL_IDS = ("tinyllama-1.1b-chat",)

FORMAT_FAILED = "format_failed"
MODEL_NOT_FOUND = "model_not_found"
BUSY = "busy"

PROBE_MESSAGES: dict[str, str] = {
    FORMAT_FAILED: (
        "이 모델은 시험 판정에서 채점 형식(구조화된 판정)을 지키지 못했습니다 — 다른 모델을 골라주세요."
    ),
    MODEL_NOT_FOUND: "서버가 이 모델을 찾지 못했습니다 — 모델 이름을 확인해주세요.",
    BUSY: "서버가 지금 요청을 받지 않습니다(요청 한도) — 잠시 뒤 다시 골라주세요.",
    AUTH_FAILED: REFUSAL_MESSAGES[AUTH_FAILED],
    OutboundReason.UNREACHABLE: REFUSAL_MESSAGES[OutboundReason.UNREACHABLE],
}


class ScoringModelProbeFailed(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

    @property
    def message(self) -> str:
        return PROBE_MESSAGES[self.reason]


def _cache_key(connection: ScoringConnection, model_id: str, reasoning_effort: str | None) -> str:
    material = f"{connection.cache_identity}|{model_id}|{'reasoning' if reasoning_effort else 'plain'}"
    return _CACHE_KEY_PREFIX + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _probe_input() -> ScoringInput:
    return ScoringInput(
        submission_id=0,
        contest_id=0,
        prompt=PROBE_PROMPT,
        source_files=[SourceFile(path="probe", content=PROBE_SOURCE, asset_id=0)],
        requirements=[
            RequirementInput(
                requirement_id=PROBE_REQUIREMENT_ID,
                text="hello",
                grade="필수",
                self_reported_met=False,
                evidence=[],
            )
        ],
    )


def ensure_model_keeps_scoring_format(
    connection: ScoringConnection | None, model_id: str, *, reasoning_effort: str | None
) -> bool:
    """이 연결로 이 모델이 채점 판정 하나를 형식대로 돌려주는지 확인한다 — 못 하면
    `ScoringModelProbeFailed`(이유별 화면 문장). 호환 서버가 아니면 아무것도 하지 않는다.

    `reasoning_effort` 는 채점 때 실릴 값 그대로다(추론 모델이면 강도, 아니면 `None`) — 추론 모델
    요청은 `temperature` 대신 `reasoning_effort` 를 실어 서버가 받는 모양이 다르다.

    돌려주는 값은 「이번에 실제로 서버에 물어 통과했는가」다 — 연결 확인 시각(#671)을 그때만 민다.
    호환 서버가 아니거나 캐시가 답했으면 거짓."""

    if connection is None or connection.kind != Class.ScoringConnectionKind.COMPATIBLE_SERVER:
        return False
    key = _cache_key(connection, model_id, reasoning_effort)
    if cache.get(key):
        return False
    if is_fake_adapter_binding(settings.CLASSROOM_SCORING_ADAPTER_MODE) and model_id in FAKE_FORMAT_FAILING_MODEL_IDS:
        raise ScoringModelProbeFailed(FORMAT_FAILED)

    from .scoring import _scoring_adapter  # 순환 임포트를 피한다 — scoring 이 이 모듈보다 무겁다.

    probe = _probe_input()
    adapter = _scoring_adapter(
        connection=connection, model=model_id, reasoning_effort=reasoning_effort, timeout=PROBE_TIMEOUT_SECONDS
    )
    try:
        output = adapter.score(probe)
    except LLMAdapterAuthError:
        raise ScoringModelProbeFailed(AUTH_FAILED) from None
    except LLMAdapterModelRejectedError:
        raise ScoringModelProbeFailed(MODEL_NOT_FOUND) from None
    except LLMAdapterUnreachableError:
        raise ScoringModelProbeFailed(OutboundReason.UNREACHABLE) from None
    except (LLMAdapterQuotaExhaustedError, LLMAdapterRateLimitedError):
        raise ScoringModelProbeFailed(BUSY) from None
    except LLMAdapterError:
        raise ScoringModelProbeFailed(FORMAT_FAILED) from None
    if [v.requirement_id for v in output.verdicts] != [PROBE_REQUIREMENT_ID]:
        raise ScoringModelProbeFailed(FORMAT_FAILED)
    cache.set(key, True, timeout=_CACHE_TTL_SECONDS)
    return True
