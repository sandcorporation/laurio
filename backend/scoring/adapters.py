"""LLM 채점 어댑터 (#12, #88, ADR-0006, ADR-0007, ADR-0014).

PG·스토리지와 같은 원칙(ADR-0007): 실제 LLM 벤더를 인터페이스 뒤에 두고 환경별로
갈아끼운다. dev/CI는 `LLM_ADAPTER_MODE=fake`(기본값)로 `FakeLLMScoringAdapter`에
바인딩되어 네트워크 없이 결정적으로 채점 플로우 전체를 돈다.

`OpenAIScoringAdapter`(#88)가 실물 어댑터다 — `LLM_ADAPTER_MODE`를 그 dotted
path(`scoring.adapters.OpenAIScoringAdapter`)로 설정하면 `core.adapters.
resolve_adapter`가 골라 쓴다. 이 값이 돈을 가르는 컷라인의 유일한 근거이므로
(#88), 이 어댑터가 지키는 규율은 세 가지다:

1. 요청에 실린 모든 Requirement에 대한 판정이 응답에 없으면 예외를 던진다 —
   빠진 것을 「미충족」으로 조용히 채우지 않는다.
2. 응답이 잘렸거나(finish_reason != "stop") JSON으로 파싱되지 않으면 예외를
   던진다 — 벤더 장애를 낮은 점수로 둔갑시키지 않는다.
3. 예외 메시지는 submission_id·requirement_id·상태코드 같은 식별자만 담는다.
   프롬프트에 실린 제출 소스는 절대 담지 않는다(ADR-0014) — `ScoringInput.
   prompt`나 벤더 응답 본문을 그대로 문자열화해 예외 메시지에 넣지 않는다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

import requests
from django.conf import settings

from core.adapters import resolve_adapter


@dataclass(frozen=True)
class SourceFile:
    """채점 대상으로 선별된 소스 파일 하나 (scoring.source_selection)."""

    path: str
    content: str


@dataclass(frozen=True)
class RequirementInput:
    """한 Requirement에 대해 LLM이 봐야 할 전부 — 자가 응답은 참고용일 뿐 신뢰하지 않는다."""

    requirement_id: int
    text: str
    grade: str
    self_reported_met: bool
    evidence: list[dict]  # [{"kind": str, "value": str}, ...]


@dataclass(frozen=True)
class ScoringInput:
    submission_id: int
    contest_id: int
    prompt: str
    source_files: list[SourceFile]
    requirements: list[RequirementInput]


@dataclass(frozen=True)
class RequirementVerdict:
    requirement_id: int
    is_met: bool
    reasoning: str


@dataclass(frozen=True)
class ScoringOutput:
    verdicts: list[RequirementVerdict]
    model_version: str


class LLMAdapterError(Exception):
    """LLM 호출이 실패했다(타임아웃·5xx·응답 파싱 실패 등) — 재시도 대상이다.

    scoring.services.score_submission_once가 이 예외를 잡아 ScoringAttempt로
    남기고 조용히 돌아온다. Score는 만들어지지 않으므로, 다음 스캔
    (scoring.services.run_pending_scoring)이 자동으로 다시 시도한다 — 별도의
    재시도 스케줄링 코드가 필요 없다(ADR-0003과 같은 정신: 상태가 없으면 그냥
    다시 스캔하면 된다).
    """


@runtime_checkable
class LLMScoringAdapter(Protocol):
    model_version: str

    def score(self, scoring_input: ScoringInput) -> ScoringOutput: ...


class FakeLLMScoringAdapter:
    """dev/test 전용. 네트워크 없이 결정적으로 채점한다.

    실제 LLM이 "Evidence가 주장을 뒷받침하는지"와 "소스에 그 기능이 실재하는지"를
    함께 읽고 판단하는 것을, 결정적인 규칙으로 흉내낸다(ADR-0014):

    1. Evidence가 하나도 연결되지 않은 자가 응답은 무조건 미달이다.
    2. Evidence가 있으면, 그 값(소스 위치·데모 경로·타임스탬프 등)이 채점 대상으로
       선별된 소스 텍스트 안에 실제로 등장하는지 본다. 등장하지 않으면 "근거를
       찾지 못했다"로 미달 처리한다.

    자가 응답(self_reported_met)은 절대 참조하지 않는다 — 이게 이 어댑터가
    증명해야 하는 핵심이다: 자가 응답만으로는 점수가 나오지 않는다.

    `settings.LLM_FAKE_RAISING_SUBMISSION_IDS`에 submission_id가 있으면
    `LLMAdapterError`를 던져 벤더 장애를 흉내낸다 — 재시도 경로 테스트용.
    """

    model_version = "fake-llm-v1"

    def score(self, scoring_input: ScoringInput) -> ScoringOutput:
        if scoring_input.submission_id in settings.LLM_FAKE_RAISING_SUBMISSION_IDS:
            raise LLMAdapterError(
                f"fake LLM adapter가 submission={scoring_input.submission_id} 채점에 "
                "실패했다(설정으로 강제된 실패 시나리오)."
            )

        haystack = "\n".join(f.content for f in scoring_input.source_files)
        verdicts: list[RequirementVerdict] = []
        for requirement in scoring_input.requirements:
            grounded = any(
                evidence.get("value", "").strip()
                and evidence["value"].strip() in haystack
                for evidence in requirement.evidence
            )
            is_met = bool(requirement.evidence) and grounded
            if not requirement.evidence:
                reasoning = "Evidence가 연결되지 않아 미달로 판정했다."
            elif not grounded:
                reasoning = "연결된 Evidence의 근거를 소스에서 찾지 못해 미달로 판정했다."
            else:
                reasoning = "Evidence가 소스에서 확인되어 충족으로 판정했다."
            verdicts.append(
                RequirementVerdict(
                    requirement_id=requirement.requirement_id,
                    is_met=is_met,
                    reasoning=reasoning,
                )
            )
        return ScoringOutput(verdicts=verdicts, model_version=self.model_version)


_OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_OPENAI_REQUEST_TIMEOUT_SECONDS = 60
_OPENAI_SYSTEM_PROMPT = (
    "당신은 Laurio 공모전 제출물을 채점하는 심사 보조자입니다. 사용자 메시지에 나열된"
    " 모든 requirement_id에 대해 빠짐없이 하나씩 판정을 반환해야 합니다 — 일부를"
    " 빠뜨리면 안 됩니다."
)


def _openai_verdict_response_schema() -> dict:
    """OpenAI Structured Outputs용 JSON 스키마.

    `strict: True`가 타입은 강제하지만(정수·불리언·문자열, 필수 키), 요청에 실린
    requirement_id를 빠짐없이 채웠는지·중복 없이 채웠는지는 스키마가 보장하지
    못한다 — 그건 `_parse_openai_scoring_response`가 응답을 받은 뒤 직접 확인한다.
    """

    return {
        "name": "scoring_verdicts",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "verdicts": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "requirement_id": {"type": "integer"},
                            "is_met": {"type": "boolean"},
                            "reasoning": {"type": "string"},
                        },
                        "required": ["requirement_id", "is_met", "reasoning"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["verdicts"],
            "additionalProperties": False,
        },
    }


def _describe_openai_http_error(response: Any, *, submission_id: int) -> str:
    """벤더가 명시적으로 거부했을 때(4xx/5xx)의 예외 메시지를 만든다.

    OpenAI 에러 응답의 `error.message`는 벤더가 작성한 텍스트(요금 한도·모델명
    오류 등)이지 우리가 보낸 프롬프트가 아니다 — 그래도 방어적으로 300자로
    자른다. 우리가 보낸 프롬프트·소스는 이 메시지 어디에도 넣지 않는다(ADR-0014).
    """

    vendor_message = ""
    try:
        error_body = response.json()
        if isinstance(error_body, dict):
            vendor_message = str(error_body.get("error", {}).get("message", ""))[:300]
    except ValueError:
        vendor_message = ""
    base = f"OpenAI 채점 호출이 실패했다(status={response.status_code}, submission={submission_id})."
    return f"{base} {vendor_message}".strip() if vendor_message else base


def _parse_openai_scoring_response(
    body: dict, *, requirement_ids: list[int], submission_id: int
) -> ScoringOutput:
    """OpenAI 응답 본문을 검증하고 `ScoringOutput`으로 바꾼다.

    이 함수가 지키는 것 — 전부 예외 메시지에 submission_id·requirement_id·상태
    같은 식별자만 담고, 응답 본문이나 프롬프트 내용은 절대 담지 않는다
    (ADR-0014):

    - choices/message/content가 없으면 예외.
    - finish_reason이 "stop"이 아니면(길이 제한으로 잘렸거나 거부됐으면) 예외 —
      잘린 응답을 파싱해서 낮은 점수로 내보내지 않는다.
    - content가 JSON으로 파싱되지 않으면 예외.
    - requirement_id가 중복되거나, 요청에 없던 필드가 비었거나 타입이 틀리면 예외.
    - 요청에 실은 requirement_id 중 하나라도 응답에 없으면 예외 — 「미충족」으로
      조용히 채우지 않는다(#88 AC).
    """

    try:
        choice = body["choices"][0]
    except (KeyError, IndexError, TypeError):
        raise LLMAdapterError(
            f"OpenAI 응답에 choices가 없다(submission={submission_id})."
        ) from None

    finish_reason = choice.get("finish_reason") if isinstance(choice, dict) else None
    if finish_reason != "stop":
        raise LLMAdapterError(
            f"OpenAI 응답이 정상 종료되지 않았다(finish_reason={finish_reason!r}, "
            f"submission={submission_id}) — 잘렸거나 거부된 응답을 점수로 쓸 수 없다."
        )

    try:
        content = choice["message"]["content"]
    except (KeyError, TypeError):
        raise LLMAdapterError(
            f"OpenAI 응답에 message.content가 없다(submission={submission_id})."
        ) from None

    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        raise LLMAdapterError(
            f"OpenAI 응답 content가 유효한 JSON이 아니다(submission={submission_id})."
        ) from None

    raw_verdicts = parsed.get("verdicts") if isinstance(parsed, dict) else None
    if not isinstance(raw_verdicts, list):
        raise LLMAdapterError(
            f"OpenAI 응답에 verdicts 배열이 없다(submission={submission_id})."
        )

    verdict_by_id: dict[int, RequirementVerdict] = {}
    for raw in raw_verdicts:
        if not isinstance(raw, dict):
            raise LLMAdapterError(
                f"OpenAI 응답의 verdict 항목이 객체가 아니다(submission={submission_id})."
            )
        try:
            requirement_id = int(raw["requirement_id"])
            is_met = raw["is_met"]
            reasoning = raw["reasoning"]
        except (KeyError, TypeError, ValueError):
            raise LLMAdapterError(
                f"OpenAI 응답의 verdict 항목이 필드를 빠뜨렸다(submission={submission_id})."
            ) from None
        if not isinstance(is_met, bool):
            raise LLMAdapterError(
                f"OpenAI 응답의 is_met이 boolean이 아니다(requirement_id={requirement_id}, "
                f"submission={submission_id})."
            )
        if not isinstance(reasoning, str) or not reasoning.strip():
            raise LLMAdapterError(
                f"OpenAI 응답의 reasoning이 비어 있다(requirement_id={requirement_id}, "
                f"submission={submission_id})."
            )
        if requirement_id in verdict_by_id:
            raise LLMAdapterError(
                f"OpenAI 응답에 requirement_id={requirement_id}가 중복됐다"
                f"(submission={submission_id})."
            )
        verdict_by_id[requirement_id] = RequirementVerdict(
            requirement_id=requirement_id, is_met=is_met, reasoning=reasoning.strip()
        )

    missing = [rid for rid in requirement_ids if rid not in verdict_by_id]
    if missing:
        raise LLMAdapterError(
            f"OpenAI 응답이 일부 requirement에 대한 판정을 빠뜨렸다"
            f"(missing_requirement_ids={missing}, submission={submission_id}) — "
            "미충족으로 채우지 않고 채점 자체를 실패로 남긴다."
        )

    model_used = body.get("model") or "unknown"
    verdicts = [verdict_by_id[rid] for rid in requirement_ids]
    return ScoringOutput(verdicts=verdicts, model_version=str(model_used))


class OpenAIScoringAdapter:
    """OpenAI로 실제 채점하는 실물 어댑터 (#88, ADR-0006, ADR-0007, ADR-0014).

    `LLM_ADAPTER_MODE=scoring.adapters.OpenAIScoringAdapter`로 켠다
    (`core.adapters.resolve_adapter`). 자격증명은 환경변수
    `OPEN_AI_API_KEY`에서만 읽는다 — 저장소에는 들어가지 않는다.

    생성자가 자격증명 없이는 인스턴스화되지 않는다 — 배포 환경에서
    `LLM_ADAPTER_MODE`가 이 클래스를 가리키는데 키가 없으면
    `core.adapters.check_adapter_mode`(#83)가 이 예외를 부팅 시점에 잡아 배포를
    거부한다. 그래서 자격증명 부재가 첫 채점 요청에서야 500으로 드러나지 않는다.
    """

    def __init__(self, *, model: str | None = None, timeout: float = _OPENAI_REQUEST_TIMEOUT_SECONDS) -> None:
        api_key = os.environ.get("OPEN_AI_API_KEY") or ""
        if not api_key:
            raise LLMAdapterError(
                "OPEN_AI_API_KEY가 비어 있다 — 실물 OpenAI 채점 어댑터는 자격증명 없이 "
                "생성할 수 없다."
            )
        self._api_key = api_key
        self._model = model or os.environ.get("LLM_OPENAI_MODEL") or _OPENAI_DEFAULT_MODEL
        self._timeout = timeout
        # 부팅 가드(core.adapters.check_adapter_mode)의 isinstance(LLMScoringAdapter)
        # 검사가 요구하는 자리 — 실제 호출에 쓰인 모델 식별자는 매 score() 호출마다
        # OpenAI 응답의 "model" 필드에서 새로 읽어 ScoringOutput.model_version으로
        # 돌려준다(별칭으로 요청해도 응답은 구체 버전을 돌려주므로 그쪽이 감사에 더
        # 정확하다, #88 AC).
        self.model_version = self._model

    def score(self, scoring_input: ScoringInput) -> ScoringOutput:
        requirement_ids = [r.requirement_id for r in scoring_input.requirements]
        payload = {
            "model": self._model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": scoring_input.prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": _openai_verdict_response_schema(),
            },
        }

        try:
            response = requests.post(
                _OPENAI_CHAT_COMPLETIONS_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self._timeout,
            )
        except requests.RequestException as exc:
            raise LLMAdapterError(
                f"OpenAI 채점 호출이 네트워크 오류로 실패했다({type(exc).__name__}, "
                f"submission={scoring_input.submission_id})."
            ) from None

        if response.status_code != 200:
            raise LLMAdapterError(
                _describe_openai_http_error(response, submission_id=scoring_input.submission_id)
            )

        try:
            body = response.json()
        except ValueError:
            raise LLMAdapterError(
                f"OpenAI 응답이 JSON이 아니다(submission={scoring_input.submission_id})."
            ) from None

        try:
            return _parse_openai_scoring_response(
                body,
                requirement_ids=requirement_ids,
                submission_id=scoring_input.submission_id,
            )
        except LLMAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - 예상 못한 응답 모양도 조용히 죽지 않아야 한다.
            raise LLMAdapterError(
                f"OpenAI 응답을 파싱하는 중 예상치 못한 오류가 났다({type(exc).__name__}, "
                f"submission={scoring_input.submission_id})."
            ) from None


def get_adapter() -> LLMScoringAdapter:
    return resolve_adapter(
        mode=settings.LLM_ADAPTER_MODE,
        fake_factory=FakeLLMScoringAdapter,
        not_implemented_hint=(
            "실제 LLM 연동은 아직 구현되지 않았다 — LLMScoringAdapter 계약만 만족시키는 "
            "dotted path를 LLM_ADAPTER_MODE에 설정하면 된다 (ADR-0007)."
        ),
    )
