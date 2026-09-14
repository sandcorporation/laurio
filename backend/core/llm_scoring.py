"""LLM 채점 어댑터 (#12, #88, #274, ADR-0006, ADR-0007, ADR-0014, ADR-0037).

**공유층(`core`)에 산다(#274).** 원래 `scoring.adapters`였다 — `scoring`은
공모전 가족이라(`tests/test_app_boundaries.py`), 강의실이 채점하려면 이 모듈을
부를 수 있어야 했고 그러려면 경계 규칙 A(강의실 ↮ 공모전, 예외 없음)를 넘지
않는 자리에 있어야 했다. 이 모듈은 처음부터 `core.adapters` 하나만 알고
공모전 모델을 전혀 모르는 완전 범용 코드였다 — 옮기는 것은 도구이지 규칙이
아니었다.

**`scoring.adapters`는 그대로 남아 이 모듈을 재노출한다.** `LLM_ADAPTER_MODE`가
가리키는 dotted path(`scoring.adapters.OpenAIScoringAdapter`)와
`docker/*.env.example`은 이 티켓에서 손대지 않는다 — `scoring.services.
NO_SCORING_INPUT_MODEL_VERSION`(#246)이 이미 쓰던 것과 같은 재노출 패턴이다.
새 호출자(강의실 포함)는 이 모듈(`core.llm_scoring`)을 직접 부른다.

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
from enum import Enum
from typing import Any, Protocol, runtime_checkable

import requests
from django.conf import settings

from core.adapters import resolve_adapter


@dataclass(frozen=True)
class SourceFile:
    """채점 대상으로 선별된 소스 파일 하나 (scoring.source_selection).

    `asset_id`는 이 파일이 어느 `SubmissionAsset`에서 왔는지 가리키는 정체성이다
    (#191 코드리뷰 지적) — "실제로 쓰인 자산"을 판정할 때(`scoring.services`)는
    반드시 이 값으로 판정한다. `asset_label`은 참가자가 붙인 자유 텍스트라
    서로 다른 자산이 같은 라벨을 가질 수 있어(유니크 제약이 없다) 정체성으로
    쓸 수 없다 — 프롬프트에 "어느 것을 보고 있는가"를 보여주는 **표시 용도**로만
    쓴다.
    """

    path: str
    content: str
    asset_id: int
    asset_label: str = ""


@dataclass(frozen=True)
class RequirementInput:
    """한 Requirement에 대해 LLM이 봐야 할 전부 — 자가 응답은 참고용일 뿐 신뢰하지 않는다."""

    requirement_id: int
    text: str
    grade: str
    self_reported_met: bool
    # [{"kind": str, "value": str, "asset_label": str | None}, ...] — asset_label은
    # 이 Evidence가 가리키는 자산의 라벨이다(#191). 참조가 없으면(null) None이다.
    evidence: list[dict]


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
    #: 이 채점 호출이 실제로 쓴 토큰 수(OpenAI 응답의 `usage.total_tokens`,
    #: #295) — 강의실의 채점 예산이 여기 기댄다. `FakeLLMScoringAdapter`를
    #: 포함해 이 값을 채우지 않는 호출자는 기본값 0이 그대로 남는다(공모전은
    #: 예산 기능이 없어 이 필드를 쓰지 않는다).
    total_tokens: int = 0


class LLMAdapterError(Exception):
    """LLM 호출이 실패했다(타임아웃·5xx·응답 파싱 실패 등) — 재시도 대상이다.

    scoring.services.score_submission_once가 이 예외를 잡아 ScoringAttempt로
    남기고 조용히 돌아온다. Score는 만들어지지 않으므로, 다음 스캔
    (scoring.services 의 submission-scoring 스캔)이 자동으로 다시 시도한다 — 별도의
    재시도 스케줄링 코드가 필요 없다(ADR-0003과 같은 정신: 상태가 없으면 그냥
    다시 스캔하면 된다).
    """


class LLMAdapterPermanentError(LLMAdapterError):
    """다시 호출해도 같은 결과가 나오는 실패다 — 자동 재시도 대상이 아니다(#88 코드리뷰 지적 2).

    예: 잘렸거나(finish_reason != "stop") 벤더가 명시적으로 거부한 응답, 모델명
    오타 같은 설정 오류로 인한 4xx. 네트워크 순단·5xx·429(요금 한도)는 다음
    시도에서 결과가 달라질 수 있으니 여기 포함되지 않는다 — 그런 것들은 그대로
    `LLMAdapterError`로 남아 계속 자동 재시도된다.

    `scoring.services.score_submission_once`가 이 예외를 잡으면 `ScoringAttempt.
    permanent=True`로 남기고, `submission-scoring` 스캔의 대상 조회가 그런 Submission을
    이후 스캔에서 제외한다 — 그렇지 않으면 이 Submission은 영원히 재시도만 되며
    Score 없이 배분 컷라인에서 조용히 빠진다(#88 코드리뷰 지적 2). ADR-0006이 말하는
    "이의제기는 재채점이 아니라 운영자가 근거를 보고 판단하는 절차다"와 같은 정신 —
    자동 재시도로 못 고치는 실패는 자동 재시도가 아니라 운영자의 눈에 띄어야 한다.
    """


class LLMAdapterAuthError(LLMAdapterPermanentError):
    """벤더가 자격증명 자체를 거부했다(401·403, #354·#355) — `LLMAdapterPermanentError`의
    부분집합이지만, "재시도해도 안 된다"를 넘어 "이 키를 갈아야 한다"는 사실이
    구조적으로 구별돼야 하는 자리에서만 쓴다. `scoring`(공모전)은 이 하위
    클래스를 몰라도 된다 — `except LLMAdapterPermanentError`가 그대로 잡으므로
    공모전 채점의 기존 동작은 한 글자도 바뀌지 않는다(ADR-0037의 경계, #355
    AC). `classroom.scoring`만 `except LLMAdapterAuthError`를 먼저 잡아 키
    상태를 "거부됨"으로 옮기고 그 클래스를 채점 후보에서 뺀다."""


class LLMKeyCheckStatus(str, Enum):
    """저장 시점에 벤더에게 키를 확인해 본 결과(#354) — `classroom.models.
    Class.ScoringKeyStatus`로 저장되는 값과는 어휘가 다르다(이쪽은 "이번
    확인이 어떻게 끝났는가", 저쪽은 "지금 이 클래스가 어느 상태인가"). 둘을
    같은 Enum으로 합치지 않는 이유는 저장값에는 이 결과가 아예 없는 경우
    (키가 없는 클래스)가 있어 뜻이 다르기 때문이다."""

    VALID = "valid"
    REJECTED = "rejected"
    UNVERIFIED = "unverified"


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
#: 키 확인 전용(#354) — 채점 요청과 달리 모델·프롬프트가 필요 없는 가장 값싼
#: 인증 확인 엔드포인트다.
_OPENAI_MODELS_URL = "https://api.openai.com/v1/models"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_OPENAI_DEFAULT_TEMPERATURE = 0

# celery-beat가 30초 타임아웃으로 이 앱의 internal 엔드포인트를 호출하고
# (core.tasks._call_internal), gunicorn도 --timeout을 따로 안 줬으니 기본값인
# 30초 만에 워커를 SIGKILL한다(#88 코드리뷰 지적 1). 이전 값(60초)은 단 하나의
# 느린 호출로도 그 예산을 넘겼고, 워커가 SIGKILL되면 진행 중이던 요청은
# ScoringAttempt를 남길 기회조차 없이 사라진다 — 다음 beat(60초 뒤)가 같은
# 앞머리 Submission들을 다시 집어 똑같이 죽는 사고가 반복된다. 20초로 줄여
# 프롬프트 구성·DB 조회 등 나머지 오버헤드에 10초 여유를 남긴다.
_OPENAI_REQUEST_TIMEOUT_SECONDS = 20
_OPENAI_SYSTEM_PROMPT = (
    "당신은 Laurio 공모전 제출물을 채점하는 심사 보조자입니다. 사용자 메시지에 나열된"
    " 모든 requirement_id에 대해 빠짐없이 하나씩 판정을 반환해야 합니다 — 일부를"
    " 빠뜨리면 안 됩니다."
)

# 재시도해도 같은 결과가 나오는 HTTP 상태 — 우리 쪽 요청 자체가 잘못됐다는
# 뜻이다(모델명 오타로 인한 400 등). 429(요금 한도)는 4xx여도 시간이 지나면
# 풀리므로 제외한다 — 무제한 재시도 대상인 5xx·네트워크 오류와 같은 취급이다
# (#88 코드리뷰 지적 2). 401·403(자격증명 자체의 거부)은 여기 포함되지
# 않는다 — `_OPENAI_AUTH_HTTP_STATUSES`가 따로 갈라 `LLMAdapterAuthError`로
# 던진다(#354·#355, 아래 참고).
_OPENAI_PERMANENT_HTTP_STATUSES = frozenset(range(400, 500)) - {429, 401, 403}

# 벤더가 자격증명 자체를 거부한 HTTP 상태(#354·#355) — `classroom.scoring`이
# "재시도해도 안 되는 실패" 중에서도 "이 키를 갈아야 하는 실패"만 골라 채점
# 키 상태를 "거부됨"으로 옮기려면, 그 판정이 예외 메시지 문자열 파싱이 아니라
# 타입(`LLMAdapterAuthError`)으로 이뤄져야 한다.
_OPENAI_AUTH_HTTP_STATUSES = frozenset({401, 403})


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

    `error.message`는 벤더가 쓴 자유 텍스트다 — 유효성 검증 오류가 "우리가 보낸
    값"을 그대로 인용해 설명하는 경우가 있어(예: 필드 값을 되풀이하는 문구),
    우리 프롬프트·소스의 일부를 반사할 위험이 있다(#88 코드리뷰 지적 5). 그래서
    이 메시지에는 절대 담지 않는다(ADR-0014) — 대신 상태코드와, 벤더가 고정된
    값만 쓰는 `error.type`/`error.code`(자유 텍스트가 아니라 열거형 라벨)만
    담는다.

    `error_body["error"]`가 dict라고 가정하지 않는다 — 프록시나 게이트웨이가
    `{"error": "Too Many Requests"}`처럼 문자열을 줄 수 있고, 그럴 때
    `.get("message")`를 부르면 AttributeError가 이 함수 밖으로 새어나가
    "모든 실패는 LLMAdapterError"라는 모듈 계약을 깬다(#88 코드리뷰 지적 4).
    """

    error_type = ""
    error_code = ""
    try:
        error_body = response.json()
    except ValueError:
        error_body = None
    if isinstance(error_body, dict):
        error_field = error_body.get("error")
        if isinstance(error_field, dict):
            error_type = str(error_field.get("type") or "")[:100]
            error_code = str(error_field.get("code") or "")[:100]
    base = f"OpenAI 채점 호출이 실패했다(status={response.status_code}, submission={submission_id})"
    details = ", ".join(
        part
        for part in [f"type={error_type}" if error_type else "", f"code={error_code}" if error_code else ""]
        if part
    )
    return f"{base}, {details})." if details else f"{base})."


def _parse_openai_scoring_response(
    body: dict, *, requirement_ids: list[int], submission_id: int
) -> ScoringOutput:
    """OpenAI 응답 본문을 검증하고 `ScoringOutput`으로 바꾼다.

    이 함수가 지키는 것 — 전부 예외 메시지에 submission_id·requirement_id·상태
    같은 식별자만 담고, 응답 본문이나 프롬프트 내용은 절대 담지 않는다
    (ADR-0014):

    - choices/message/content가 없으면 예외(재시도 가능 — 응답 모양 자체가
      매번 같으리라는 보장이 없다).
    - finish_reason이 "stop"이 아니면(길이 제한으로 잘렸거나 거부됐으면)
      `LLMAdapterPermanentError` — 같은 프롬프트·같은 토큰 예산이면 다시 불러도
      또 잘린다(#88 코드리뷰 지적 2). 잘린 응답을 파싱해서 낮은 점수로 내보내지
      않는다.
    - content가 JSON으로 파싱되지 않으면 예외.
    - requirement_id는 정수여야 한다 — `int()`로 강제 변환하지 않는다. 10.9를
      10으로 자르거나 True를 1로 바꾸면 엉뚱한 requirement에 판정이 붙고도
      중복·누락 검사를 전부 통과해, percentage가 모델의 실제 판정과 어긋난다
      (#88 코드리뷰 지적 3 — 이 티켓이 지키기로 한 "percentage가 판정들과
      일치한다"의 유일한 구멍이었다).
    - requirement_id가 중복되거나, 필드가 비었거나 타입이 틀리면 예외.
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
        raise LLMAdapterPermanentError(
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
            requirement_id_raw = raw["requirement_id"]
            is_met = raw["is_met"]
            reasoning = raw["reasoning"]
        except (KeyError, TypeError):
            raise LLMAdapterError(
                f"OpenAI 응답의 verdict 항목이 필드를 빠뜨렸다(submission={submission_id})."
            ) from None
        # bool은 int의 서브클래스라 isinstance(True, int)가 True다 — 명시적으로
        # 걷어낸다. int()로 강제 변환하면 10.9→10, True→1처럼 절삭·변환되어
        # 남의 requirement_id에 판정이 붙고도 아래 중복·누락 검사를 통과한다.
        if not isinstance(requirement_id_raw, int) or isinstance(requirement_id_raw, bool):
            raise LLMAdapterError(
                f"OpenAI 응답의 requirement_id가 정수가 아니다"
                f"(submission={submission_id})."
            )
        requirement_id = requirement_id_raw
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
    usage = body.get("usage") or {}
    total_tokens = usage.get("total_tokens", 0)
    if not isinstance(total_tokens, int) or isinstance(total_tokens, bool):
        # 벤더가 이상한 모양을 보내도(문자열·실수·bool) 채점 자체를 실패로 만들지
        # 않는다 — 판정은 이미 유효하게 파싱됐다. 예산 집계만 0으로 조용히 빠진다.
        total_tokens = 0
    return ScoringOutput(verdicts=verdicts, model_version=str(model_used), total_tokens=total_tokens)


class OpenAIScoringAdapter:
    """OpenAI로 실제 채점하는 실물 어댑터 (#88, #287, ADR-0006, ADR-0007, ADR-0014).

    `LLM_ADAPTER_MODE=scoring.adapters.OpenAIScoringAdapter`로 켠다
    (`core.adapters.resolve_adapter`). **공모전 채점**의 자격증명은 환경변수
    `OPEN_AI_API_KEY`에서만 읽는다 — 저장소에는 들어가지 않는다. 모델명은
    `LLM_OPENAI_MODEL`(기본 `gpt-4o-mini`), temperature는
    `LLM_OPENAI_TEMPERATURE`(기본 0)로 배포 환경마다 바꿀 수 있다 — compose의
    `environment`에 실려 컨테이너까지 전달된다(#88 코드리뷰 지적 6, docker/
    compose.staging.yaml·compose.prod.yaml).

    **강의실 채점은 `api_key` 인자로 강사 본인의 키를 직접 넘긴다**(#287) —
    플랫폼이 대신 내지 않는다는 결정(CONTEXT.md 「Class」) 때문에 `resolve_adapter`가
    부팅 시점에 한 번 고정하는 env 기반 자격증명을 쓸 수 없다. `classroom.scoring`이
    `core.adapters.get_adapter()`를 거치지 않고 이 클래스를 직접, 매 채점마다
    `Class.openai_api_key_encrypted`를 복호화해 생성한다 — env 폴백은 공모전
    경로를 그대로 두기 위해 남긴다.

    생성자가 자격증명 없이는 인스턴스화되지 않는다 — 배포 환경에서
    `LLM_ADAPTER_MODE`가 이 클래스를 가리키는데 env에 키가 없으면
    `core.adapters.check_adapter_mode`(#83)가 이 예외를 부팅 시점에 잡아 배포를
    거부한다. 그래서 자격증명 부재가 첫 채점 요청에서야 500으로 드러나지 않는다
    (강의실 경로는 이 부팅 가드 대상이 아니다 — 키가 클래스마다 다르므로 부팅
    시점에 고정할 수 있는 값이 아니다, `classroom.scoring`이 키 없음을 직접
    다룬다).
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        timeout: float = _OPENAI_REQUEST_TIMEOUT_SECONDS,
    ) -> None:
        api_key = api_key if api_key is not None else (os.environ.get("OPEN_AI_API_KEY") or "")
        if not api_key:
            raise LLMAdapterError(
                "OPEN_AI_API_KEY가 비어 있다 — 실물 OpenAI 채점 어댑터는 자격증명 없이 "
                "생성할 수 없다."
            )
        self._api_key = api_key
        self._model = model or os.environ.get("LLM_OPENAI_MODEL") or _OPENAI_DEFAULT_MODEL
        if temperature is not None:
            self._temperature = temperature
        else:
            raw_temperature = os.environ.get("LLM_OPENAI_TEMPERATURE")
            self._temperature = float(raw_temperature) if raw_temperature else _OPENAI_DEFAULT_TEMPERATURE
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
            "temperature": self._temperature,
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
            message = _describe_openai_http_error(response, submission_id=scoring_input.submission_id)
            if response.status_code in _OPENAI_AUTH_HTTP_STATUSES:
                raise LLMAdapterAuthError(message)
            if response.status_code in _OPENAI_PERMANENT_HTTP_STATUSES:
                raise LLMAdapterPermanentError(message)
            raise LLMAdapterError(message)

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

    def check_key(self) -> LLMKeyCheckStatus:
        """저장 시점에 이 키가 실제로 쓸 수 있는지 벤더에게 한 번 묻는다(#354).

        채점 호출(`/chat/completions`)이 아니라 모델 목록 조회(`/models`)를
        친다 — 프롬프트도 토큰도 쓰지 않는 가장 값싼 인증 확인이다. 401·403은
        키가 틀렸다는 확실한 신호(`REJECTED`)이고, 그 밖의 모든 실패(타임아웃·
        네트워크 오류·5xx·예상 밖의 상태)는 "확인하지 못했다"(`UNVERIFIED`)로
        묶는다 — 여기서 막으려는 것은 오타이지 벤더의 그 순간 가용성이 아니다.
        """

        try:
            response = requests.get(
                _OPENAI_MODELS_URL,
                headers={"Authorization": f"Bearer {self._api_key}"},
                timeout=self._timeout,
            )
        except requests.RequestException:
            return LLMKeyCheckStatus.UNVERIFIED

        if response.status_code in _OPENAI_AUTH_HTTP_STATUSES:
            return LLMKeyCheckStatus.REJECTED
        if response.status_code == 200:
            return LLMKeyCheckStatus.VALID
        return LLMKeyCheckStatus.UNVERIFIED


def get_adapter() -> LLMScoringAdapter:
    return resolve_adapter(
        mode=settings.LLM_ADAPTER_MODE,
        fake_factory=FakeLLMScoringAdapter,
        not_implemented_hint=(
            "LLM_ADAPTER_MODE가 가리키는 dotted path를 import할 수 없다 — 실물 "
            "어댑터는 scoring.adapters.OpenAIScoringAdapter다(#88). LLMScoringAdapter "
            "계약만 만족시키면 다른 dotted path도 쓸 수 있다(ADR-0007)."
        ),
    )
