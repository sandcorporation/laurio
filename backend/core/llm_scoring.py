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
import json as _json
import os
from dataclasses import dataclass
from enum import Enum
from collections.abc import Awaitable, Callable
from typing import Any, Literal, Protocol, runtime_checkable

import aiohttp
import requests
from django.conf import settings

from core.adapters import resolve_adapter
from core import quality_review
from core.llm_metrics import observe_call, observe_call_async
from core.safe_outbound import AsyncResponse, OutboundRefused, read_limited_async


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
    # Evidence(화면 이름 「확인 위치」)는 싣지 않는다 — 판정 입력이 아니다(#909, ADR-0074).


@dataclass(frozen=True)
class ScoringInput:
    submission_id: int
    contest_id: int
    prompt: str
    source_files: list[SourceFile]
    requirements: list[RequirementInput]


#: 강의실 판정의 세 값(#811, ADR-0067). 공모전 판정은 이 값을 쓰지 않는다(`RequirementVerdict.verdict` 가 None).
VERDICT_MET = "met"
VERDICT_UNMET = "unmet"
VERDICT_UNVERIFIABLE = "unverifiable"
VERDICT_VALUES = (VERDICT_MET, VERDICT_UNMET, VERDICT_UNVERIFIABLE)


@dataclass(frozen=True)
class RequirementVerdict:
    requirement_id: int
    is_met: bool
    reasoning: str
    #: 세 갈래 판정(#811) — 어댑터를 `allow_unverifiable=True` 로 만든 강의실 채점만 채운다. 공모전은 None.
    #: 채워졌으면 `is_met` 은 `verdict == "met"` 이다(확인 불가는 충족이 아니다).
    verdict: str | None = None


@dataclass(frozen=True)
class ScoringOutput:
    verdicts: list[RequirementVerdict]
    model_version: str
    #: 이 채점 호출이 실제로 쓴 토큰 수(OpenAI 응답의 `usage.total_tokens`,
    #: #295) — 강의실의 채점 사용량이 여기 기댄다. `FakeLLMScoringAdapter`를
    #: 포함해 이 값을 채우지 않는 호출자는 기본값 0이 그대로 남는다. 누적하는 곳은
    #: 강의실 채점 사용량뿐이고, 호출 로그(`core.llm_metrics`)는 모든 제품(공모전 채점
    #: 포함)에서 이 값을 남긴다.
    total_tokens: int = 0
    #: 입력·출력 토큰(`usage.prompt_tokens`·`completion_tokens`, #585) — 지표가 센다. 없으면 0.
    input_tokens: int = 0
    output_tokens: int = 0


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


class LLMAdapterModelRejectedError(LLMAdapterPermanentError):
    """벤더가 **모델**을 그 키로 쓸 수 없다고 거부했다(모델 없음·접근 불가,
    #403) — `LLMAdapterAuthError`와 같은 자리(`LLMAdapterPermanentError`의
    부분집합)이지만 사유가 다르다: 키 자체가 아니라 그 키로 이 모델에 닿을
    권한이 없다는 뜻이라, 키 상태를 "거부됨"으로 옮기지 않는다(CONTEXT.md
    「채점 모델」 "몰래 다른 모델로 대신 채점하지 않는다"). `scoring`(공모전)은
    이 하위 클래스를 몰라도 된다 — `except LLMAdapterPermanentError`가 그대로
    잡으므로 공모전 채점의 기존 동작은 바뀌지 않는다(ADR-0037의 경계).
    `classroom.scoring`만 `except LLMAdapterModelRejectedError`를 먼저 잡아
    그 Problem의 채점 모델을 "이 키로 쓸 수 없음"으로 남기고 채점 후보에서
    뺀다."""


class LLMAdapterQuotaExhaustedError(LLMAdapterError):
    """벤더가 이 키의 크레딧이 바닥났다고 답했다(429 `insufficient_quota`, #586) — 일시
    실패(`LLMAdapterError`)의 부분집합이다. 시간이 지나도 저절로 풀리지 않고 키 주인이
    충전해야 풀린다는 점이 다른 429 와 갈린다. `scoring`(공모전)은 이 하위 클래스를 몰라도
    된다 — `except LLMAdapterError` 가 그대로 잡아 지금처럼 재시도한다(ADR-0037 의 경계).
    `classroom.scoring` 만 먼저 잡아 그 클래스의 채점을 멈춘다(채점 대기 사유 「키」)."""


class LLMAdapterRateLimitedError(LLMAdapterError):
    """벤더가 요청 빈도 제한에 걸렸다고 답했다(크레딧 소진이 아닌 429, #586) — 잠시 뒤
    저절로 풀린다. 공모전은 이 하위 클래스를 모른 채 `LLMAdapterError` 로 재시도한다.
    `classroom.scoring` 은 이 실패를 일정 시간 동안 실패 한도에 세지 않는다."""


class LLMAdapterTimeoutError(LLMAdapterError):
    """벤더가 정해진 시간 안에 답하지 않았다(#585) — 일시 실패의 하위 예외라 이 클래스를 모르는
    호출자는 지금처럼 다룬다. 지표의 결과 라벨 `timeout` 이 이것이다."""


class LLMAdapterUnreachableError(LLMAdapterError):
    """호환 서버에 닿지 않았다(#603) — 이름이 풀리지 않거나, 연결이 서지 않거나, 인증서가
    맞지 않거나, 막힌 주소로 풀렸거나, 리다이렉트로 답했다(`core.safe_outbound.OutboundRefused.
    reached` 가 거짓). 일시 실패의 하위 예외라 이 클래스를 모르는 호출자는 지금처럼 다룬다.
    `classroom.scoring` 은 먼저 잡아 그 클래스의 채점을 멈춘다 — 서버 주인이 고쳐야 풀린다.
    닿았는데 늦거나 몸통이 깨진 것은 이 예외가 아니다(보통 `LLMAdapterError`)."""


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

    실제 LLM이 "소스에 그 기능이 실재하는지"를 읽고 판단하는 것을, 결정적인 규칙으로
    흉내낸다: Requirement 문구가 채점 대상으로 선별된 소스 텍스트 안에 그대로 등장하면
    충족, 아니면 미달이다. Evidence(확인 위치)는 판정 입력이 아니다(#909, ADR-0074) —
    연결이 없다고 자동 미달이 되지 않는다. `prompt` 가 아니라 `source_files` 에서 찾는다 —
    프롬프트에는 Requirement 문구가 이미 나열돼 있어 거기서 찾으면 늘 참이 된다.

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
            needle = requirement.text.strip()
            is_met = bool(needle) and needle in haystack
            reasoning = (
                "Requirement 문구가 소스에서 확인되어 충족으로 판정했다."
                if is_met
                else "Requirement 문구를 소스에서 찾지 못해 미달로 판정했다."
            )
            verdicts.append(
                RequirementVerdict(
                    requirement_id=requirement.requirement_id,
                    is_met=is_met,
                    reasoning=reasoning,
                )
            )
        return ScoringOutput(verdicts=verdicts, model_version=self.model_version)

    def review_quality(self, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        """공모전 완성도(#884) 흉내 — 네트워크 없이 결정적으로 0~5 를 낸다. 공모전의 완성도 입력에는
        Requirement 문구가 함께 실려 「문구가 소스에 있나」로는 갈리지 않으므로, 제출·항목 id 로 정한
        1~5 를 준다 — 같은 입력이면 늘 같은 값이고, 제출마다 값이 달라 정렬을 시험할 수 있다."""

        scores = tuple(
            quality_review.QualityItemScore(
                item_id=item.item_id,
                label=item.label,
                required=item.required,
                score=1 + (quality_input.submission_id * 7 + item.item_id * 3) % 5,
                reasoning="흉내 어댑터가 제출·항목 번호로 정한 점수다.",
            )
            for item in quality_input.items
        )
        return quality_review.QualityOutput(scores=scores, model_version=self.model_version)

    async def review_quality_async(self, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        return self.review_quality(quality_input)


#: OpenAI API 의 base URL. 공모전 채점은 언제나 이 주소를 쓴다. 강의실 채점은 클래스의
#: 채점 연결(`classroom.scoring_connection`, #599)이 주소를 넘긴다 — 「OpenAI 키」 연결은
#: 이 값 그대로다. 아래 두 경로는 이 base 뒤에 붙는다.
OPENAI_API_BASE_URL = "https://api.openai.com/v1"
_CHAT_COMPLETIONS_PATH = "/chat/completions"
#: 키 확인 전용(#354) — 채점 요청과 달리 모델·프롬프트가 필요 없는 가장 값싼
#: 인증 확인 엔드포인트다.
_MODELS_PATH = "/models"


#: 벤더 왕복을 대신 보내는 함수(#601) — `core.safe_outbound.SafeOutbound.request` 모양
#: (`method, url, *, headers, timeout, json`). 주지 않으면 `requests` 로 바로 나간다(OpenAI).
#: 강의실의 「호환 서버」 연결은 강사가 적은 주소라 안전한 바깥 호출을 넘긴다(ADR-0058).
Transport = Callable[..., Any]

#: `Transport` 의 비동기 판(#584) — `SafeOutbound.arequest` 모양, 코루틴을 돌려준다.
AsyncTransport = Callable[..., Awaitable[Any]]


def _endpoint(base_url: str | None, path: str) -> str:
    return (base_url or OPENAI_API_BASE_URL).rstrip("/") + path

_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"
_OPENAI_DEFAULT_TEMPERATURE = 0

# celery worker(beat 가 쏜 스캔)가 30초 타임아웃으로 이 앱의 internal 엔드포인트를 호출한다
# (core.tasks.call_internal). 그때는 gunicorn sync 워커도 30초 만에 워커를
# SIGKILL했다(#88 코드리뷰 지적 1 — gthread 로 바꾼 #725 뒤로는 요청이 길다고
# 죽이지 않는다, config/gunicorn.conf.py). 이전 값(60초)은 단 하나의
# 느린 호출로도 그 예산을 넘겼고, 부른 쪽이 끊으면 다음 beat(60초 뒤)가 같은
# 앞머리 Submission들을 다시 집어 똑같이 넘는 일이 반복된다. 20초로 줄여
# 프롬프트 구성·DB 조회 등 나머지 오버헤드에 10초 여유를 남긴다. 강의실 채점은
# 이 예산 밖(Celery 워커 안)에서 돌아 자기 값(180초)을 넘긴다(#582, ADR-0056 —
# `classroom.scoring.CLASSROOM_SCORING_VENDOR_TIMEOUT_SECONDS`). 키 확인·모델 목록
# 조회는 사람이 기다리는 요청 안이라 이 값을 그대로 쓴다.
_OPENAI_REQUEST_TIMEOUT_SECONDS = 20
_OPENAI_SYSTEM_PROMPT = (
    # 공모전과 강의실이 함께 쓴다 — 제품 이름을 적지 않는다(무엇을 채점하는지는
    # 사용자 메시지가 말한다). 근거는 사람이 읽는 화면에 그대로 나가므로 언어를
    # 여기서도 못 박는다: 지시가 없으면 영어 소스를 읽은 모델이 근거를 영어로 쓴다.
    "당신은 Codemit 제출물을 채점하는 채점 보조자입니다. 사용자 메시지에 나열된"
    " 모든 requirement_id에 대해 빠짐없이 하나씩 판정을 반환해야 합니다 — 일부를"
    " 빠뜨리면 안 됩니다. 판정 근거(reasoning)는 소스가 어느 언어로 쓰였든 반드시"
    " 한국어로 씁니다."
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

# 벤더가 "그 모델을 이 키로 쓸 수 없다"고 거부한 상태(#403) — OpenAI 문서와
# 실제 응답 모두 400·404가 섞여 있어(모델 오타·미지원은 400, 존재하지 않는
# 모델은 404가 흔하다) 상태 코드 하나로는 못 가른다. `error.code`(벤더가
# 자유 텍스트가 아니라 고정된 값만 쓰는 필드, ADR-0014와 같은 이유로
# `error.message`는 예외 판정에 쓰지 않는다)가 "model_not_found"일 때만
# `LLMAdapterModelRejectedError`로 올린다 — 이 코드 이름은 라이브 벤더
# 호출로 재확인하지 않았다(#403 Further Notes, `test_scoring_openai_live.py`류의
# 옵인 라이브 테스트가 있으면 그쪽에서 확인한다).
_OPENAI_MODEL_REJECTION_HTTP_STATUSES = frozenset({400, 404})
_OPENAI_MODEL_REJECTION_ERROR_CODES = frozenset({"model_not_found"})

# 크레딧 소진(#586) — 같은 429 라도 빈도 제한과 갈라야 한다. 판정은 `error.type`·`error.code`
# (벤더가 고정된 값만 쓰는 라벨)로만 한다. OpenAI 는 `type=insufficient_quota` 에 `code` 를
# `insufficient_quota` 로 주기도, `credit_balance_exhausted` 로 주기도 한다(2026-10-06 실제 응답은
# 뒤의 것) — 둘 중 하나라도 맞으면 소진이다.
_OPENAI_RATE_LIMIT_HTTP_STATUS = 429
_OPENAI_QUOTA_EXHAUSTED_LABELS = frozenset({"insufficient_quota", "credit_balance_exhausted"})


#: 강의실 판정 프롬프트(#811)는 `classroom.scoring._build_prompt` 가 사용자 메시지에 싣는다 — 「확인할 수 없는
#: 것」의 목록이 강의실 모듈(`classroom.gradability_hint`)에 있고 core 는 강의실을 모른다. 여기는 스키마뿐이다.


def _openai_verdict_response_schema(*, allow_unverifiable: bool = False) -> dict:
    """OpenAI Structured Outputs용 JSON 스키마.

    `allow_unverifiable=True`(강의실, #811)면 `is_met` 대신 `verdict`(met·unmet·unverifiable)를 받는다 —
    둘을 함께 받으면 서로 어긋나는 응답을 어느 쪽으로 읽을지 정해야 해 하나만 둔다. `is_met` 은 파서가
    `verdict` 에서 만든다. 공모전(기본값)은 지금 그대로 `is_met` 이다.

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
                            **(
                                {"verdict": {"type": "string", "enum": list(VERDICT_VALUES)}}
                                if allow_unverifiable
                                else {"is_met": {"type": "boolean"}}
                            ),
                            "reasoning": {"type": "string"},
                        },
                        "required": ["requirement_id", "verdict" if allow_unverifiable else "is_met", "reasoning"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["verdicts"],
            "additionalProperties": False,
        },
    }


def _extract_openai_error_fields(response: Any) -> tuple[str, str]:
    """벤더 오류 응답의 `error.type`·`error.code`(자유 텍스트가 아니라
    벤더가 고정된 값만 쓰는 열거형 라벨)만 뽑는다 — `error.message`는 여기서
    다루지 않는다(아래 `_describe_openai_http_error` docstring 참고).

    `error_body["error"]`가 dict라고 가정하지 않는다 — 프록시나 게이트웨이가
    `{"error": "Too Many Requests"}`처럼 문자열을 줄 수 있고, 그럴 때
    `.get("type")`을 부르면 AttributeError가 이 함수 밖으로 새어나가 "모든
    실패는 LLMAdapterError"라는 모듈 계약을 깬다(#88 코드리뷰 지적 4)."""

    try:
        error_body = response.json()
    except ValueError:
        error_body = None
    if isinstance(error_body, dict):
        error_field = error_body.get("error")
        if isinstance(error_field, dict):
            error_type = str(error_field.get("type") or "")[:100]
            error_code = str(error_field.get("code") or "")[:100]
            return error_type, error_code
    return "", ""


def _describe_openai_http_error(
    response: Any, *, context: str, error_type: str = "", error_code: str = ""
) -> str:
    """벤더가 명시적으로 거부했을 때(4xx/5xx)의 예외 메시지를 만든다.

    `error.message`는 벤더가 쓴 자유 텍스트다 — 유효성 검증 오류가 "우리가 보낸
    값"을 그대로 인용해 설명하는 경우가 있어(예: 필드 값을 되풀이하는 문구),
    우리 프롬프트·소스의 일부를 반사할 위험이 있다(#88 코드리뷰 지적 5). 그래서
    이 메시지에는 절대 담지 않는다(ADR-0014) — 대신 상태코드와, 벤더가 고정된
    값만 쓰는 `error.type`/`error.code`만 담는다. 호출자가 이미
    `_extract_openai_error_fields`로 뽑아 뒀으면(`score`가 모델 거부 판정에
    쓰려고 먼저 부른다) 다시 파싱하지 않게 그대로 받는다 — 생략하면 이 함수가
    직접 뽑는다.

    `context`는 이 왕복이 무엇이었는지 가리키는 식별자뿐이다(#469 —
    `_openai_round_trip`이 채점(submission=…)·키 확인·모델 목록 조회 셋에
    같은 이 함수를 쓴다) — 벤더 원문은 여전히 담지 않는다.
    """

    if not error_type and not error_code:
        error_type, error_code = _extract_openai_error_fields(response)
    base = f"OpenAI 호출이 실패했다(status={response.status_code}, {context})"
    details = ", ".join(
        part
        for part in [f"type={error_type}" if error_type else "", f"code={error_code}" if error_code else ""]
        if part
    )
    return f"{base}, {details})." if details else f"{base})."


def _classify_openai_error(response: Any, *, context: str) -> Exception:
    """벤더 응답을 일곱 갈래(정상·권한 거부·모델 거부·크레딧 소진·빈도 제한·영구 실패·
    일시 실패) 중 성공이 아닌 여섯으로 갈라 그에 맞는 예외를 만든다(#469, #586) — 성공(200)은
    `_openai_round_trip`이 이 함수를 부르지 않는다."""

    error_type, error_code = _extract_openai_error_fields(response)
    message = _describe_openai_http_error(
        response, context=context, error_type=error_type, error_code=error_code
    )
    error = _pick_openai_error(response.status_code, error_type, error_code)(message)
    # 지표·로그(#585)가 읽는다 — 벤더가 고정된 값만 쓰는 `type`/`code` 와 상태코드뿐이다(본문 아님).
    error.status_code = response.status_code
    error.vendor_error_type = error_type
    error.vendor_error_code = error_code
    return error


def _pick_openai_error(status_code: int, error_type: str, error_code: str) -> type[LLMAdapterError]:
    if status_code in _OPENAI_AUTH_HTTP_STATUSES:
        return LLMAdapterAuthError
    if status_code in _OPENAI_MODEL_REJECTION_HTTP_STATUSES and error_code in _OPENAI_MODEL_REJECTION_ERROR_CODES:
        return LLMAdapterModelRejectedError
    if status_code == _OPENAI_RATE_LIMIT_HTTP_STATUS:
        if {error_type, error_code} & _OPENAI_QUOTA_EXHAUSTED_LABELS:
            return LLMAdapterQuotaExhaustedError
        return LLMAdapterRateLimitedError
    if status_code in _OPENAI_PERMANENT_HTTP_STATUSES:
        return LLMAdapterPermanentError
    return LLMAdapterError


def _round_trip_request(
    api_key: str, timeout: float, json_body: dict | None
) -> tuple[dict[str, str], dict[str, Any]]:
    # 호환 서버는 인증 값을 비워 둘 수 있다(#601) — 그때는 헤더를 싣지 않는다.
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    kwargs: dict[str, Any] = {"headers": headers, "timeout": timeout}
    if json_body is not None:
        headers["Content-Type"] = "application/json"
        kwargs["json"] = json_body
    return headers, kwargs


def _refused_error(exc: OutboundRefused, context: str) -> Exception:
    detail = f", {context}" if context else ""
    error = LLMAdapterError if exc.reached else LLMAdapterUnreachableError
    return error(f"호환 서버 호출이 실패했다({exc.reason.value}{detail}).")


def _openai_round_trip(
    method: str,
    url: str,
    *,
    api_key: str,
    timeout: float,
    json_body: dict | None = None,
    context: str = "",
    transport: Transport | None = None,
) -> Any:
    """벤더(OpenAI) 왕복 하나 — 헤더·타임아웃·예외 변환을 여기 한 곳이 갖는다
    (#469). 채점(`OpenAIScoringAdapter.score`)·키 확인(`OpenAIScoringAdapter.
    check_key`)·모델 목록 조회(`list_openai_models`) 셋이 모두 이 함수를
    거친다 — 셋이 각자 헤더·타임아웃을 다시 쓰지 않는다.

    성공(200)이면 응답을 그대로 돌려준다. 그 밖은 `_classify_openai_error`가
    가른 예외를 던진다 — 호출자는 그 타입만 본다. 네트워크 자체가 실패하면
    (타임아웃·연결 끊김) 재시도해도 결과가 달라질 수 있으니 `LLMAdapterError`
    (일시 실패)로 옮겨 던진다."""

    _, kwargs = _round_trip_request(api_key, timeout, json_body)

    if transport is not None:
        try:
            response = transport(method, url, **kwargs)
        except OutboundRefused as exc:
            raise _refused_error(exc, context) from None
        if response.status_code == 200:
            return response
        raise _classify_openai_error(response, context=context)

    # `requests.post`/`requests.get`을 이름으로 부른다 — `requests.request`가
    # 아니다: 기존 테스트(#469 이전부터)가 전부 `requests.post`/`.get` 이름을
    # 직접 monkeypatch해 왔고, 그 경계는 이번 티켓의 범위가 아니다.
    send = requests.post if method == "POST" else requests.get
    try:
        response = send(url, **kwargs)
    except requests.RequestException as exc:
        detail = f", {context}" if context else ""
        error = LLMAdapterTimeoutError if isinstance(exc, requests.Timeout) else LLMAdapterError
        raise error(
            f"OpenAI 호출이 네트워크 오류로 실패했다({type(exc).__name__}{detail})."
        ) from None

    if response.status_code == 200:
        return response
    raise _classify_openai_error(response, context=context)


async def _aiohttp_request(
    method: str, url: str, *, headers: dict[str, str], timeout: float, json: Any = None
) -> AsyncResponse:
    """OpenAI 로 나가는 비동기 왕복(#584) — 주소가 고정된 OpenAI 라 푼 IP 고정은 필요 없다."""

    body = None if json is None else _json.dumps(json).encode("utf-8")
    async with aiohttp.ClientSession(
        trust_env=False,
        timeout=aiohttp.ClientTimeout(
            total=timeout, sock_connect=min(settings.SAFE_OUTBOUND_CONNECT_TIMEOUT_SECONDS, timeout)
        ),
    ) as session:
        async with session.request(method, url, headers=headers, data=body) as response:
            return AsyncResponse(
                response.status,
                await read_limited_async(response, settings.SAFE_OUTBOUND_RESPONSE_MAX_BYTES),
            )


async def _openai_round_trip_async(
    method: str,
    url: str,
    *,
    api_key: str,
    timeout: float,
    json_body: dict | None = None,
    context: str = "",
    transport: AsyncTransport | None = None,
) -> Any:
    """`_openai_round_trip` 의 비동기 판(#584) — 헤더·분류는 같은 함수를 쓴다. 호환 서버는 안전한
    바깥 호출의 비동기 길(`SafeOutbound.arequest`)을, OpenAI 는 aiohttp 로 바로 나간다."""

    _, kwargs = _round_trip_request(api_key, timeout, json_body)
    try:
        response = await (transport or _aiohttp_request)(method, url, **kwargs)
    except OutboundRefused as exc:
        raise _refused_error(exc, context) from None
    except (aiohttp.ClientError, TimeoutError, OSError) as exc:
        detail = f", {context}" if context else ""
        error = LLMAdapterTimeoutError if isinstance(exc, TimeoutError) else LLMAdapterError
        raise error(
            f"OpenAI 호출이 네트워크 오류로 실패했다({type(exc).__name__}{detail})."
        ) from None
    if response.status_code == 200:
        return response
    raise _classify_openai_error(response, context=context)


def _parse_openai_scoring_response(
    body: dict, *, requirement_ids: list[int], submission_id: int, allow_unverifiable: bool = False
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

    verdict_by_id = verdicts_from_content(
        content,
        requirement_ids=requirement_ids,
        submission_id=submission_id,
        vendor="OpenAI",
        allow_unverifiable=allow_unverifiable,
    )

    model_used = body.get("model") or "unknown"
    verdicts = [verdict_by_id[rid] for rid in requirement_ids]
    usage = body.get("usage") or {}
    total_tokens = usage.get("total_tokens", 0)
    if not isinstance(total_tokens, int) or isinstance(total_tokens, bool):
        # 벤더가 이상한 모양을 보내도(문자열·실수·bool) 채점 자체를 실패로 만들지
        # 않는다 — 판정은 이미 유효하게 파싱됐다. 예산 집계만 0으로 조용히 빠진다.
        total_tokens = 0
    return ScoringOutput(
        verdicts=verdicts,
        model_version=str(model_used),
        total_tokens=total_tokens,
        input_tokens=_usage_count(usage, "prompt_tokens"),
        output_tokens=_usage_count(usage, "completion_tokens"),
    )


def verdicts_from_content(
    content: Any,
    *,
    requirement_ids: list[int],
    submission_id: int,
    vendor: str,
    allow_unverifiable: bool = False,
) -> dict[int, RequirementVerdict]:
    """판정 JSON(`{"verdicts": [...]}`) 문자열을 검증해 requirement_id 별 판정으로 바꾼다 — OpenAI
    (`message.content`)와 Anthropic(`content` 의 text 블록, #795) 응답이 같은 규율을 쓴다. 규율은
    `_parse_openai_scoring_response` docstring 그대로다(정수 id·중복·빠짐·빈 근거는 예외, 예외 메시지에
    본문을 싣지 않는다). `vendor` 는 예외 메시지의 벤더 이름뿐이다.

    `allow_unverifiable`(강의실, #811)이면 항목마다 `verdict`(세 값 중 하나)를 읽어 `is_met` 을 만든다 —
    `verdict` 키가 없으면 `is_met` 으로 읽는다(옛 모양의 응답·녹화본). 꺼져 있으면(공모전) `verdict` 를
    보지도 요구하지도 않는다."""

    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        raise LLMAdapterError(
            f"{vendor} 응답 content가 유효한 JSON이 아니다(submission={submission_id})."
        ) from None

    raw_verdicts = parsed.get("verdicts") if isinstance(parsed, dict) else None
    if not isinstance(raw_verdicts, list):
        raise LLMAdapterError(
            f"{vendor} 응답에 verdicts 배열이 없다(submission={submission_id})."
        )

    verdict_by_id: dict[int, RequirementVerdict] = {}
    for raw in raw_verdicts:
        if not isinstance(raw, dict):
            raise LLMAdapterError(
                f"{vendor} 응답의 verdict 항목이 객체가 아니다(submission={submission_id})."
            )
        verdict: str | None = None
        try:
            requirement_id_raw = raw["requirement_id"]
            if allow_unverifiable and "verdict" in raw:
                verdict = raw["verdict"]
                is_met = verdict == VERDICT_MET
            else:
                is_met = raw["is_met"]
            reasoning = raw["reasoning"]
        except (KeyError, TypeError):
            raise LLMAdapterError(
                f"{vendor} 응답의 verdict 항목이 필드를 빠뜨렸다(submission={submission_id})."
            ) from None
        # bool은 int의 서브클래스라 isinstance(True, int)가 True다 — 명시적으로
        # 걷어낸다. int()로 강제 변환하면 10.9→10, True→1처럼 절삭·변환되어
        # 남의 requirement_id에 판정이 붙고도 아래 중복·누락 검사를 통과한다.
        if not isinstance(requirement_id_raw, int) or isinstance(requirement_id_raw, bool):
            raise LLMAdapterError(
                f"{vendor} 응답의 requirement_id가 정수가 아니다"
                f"(submission={submission_id})."
            )
        requirement_id = requirement_id_raw
        if allow_unverifiable and "verdict" in raw and verdict not in VERDICT_VALUES:
            raise LLMAdapterError(
                f"{vendor} 응답의 verdict가 정해진 값이 아니다(requirement_id={requirement_id}, "
                f"submission={submission_id})."
            )
        if allow_unverifiable and verdict is None and isinstance(is_met, bool):
            verdict = VERDICT_MET if is_met else VERDICT_UNMET
        if not isinstance(is_met, bool):
            raise LLMAdapterError(
                f"{vendor} 응답의 is_met이 boolean이 아니다(requirement_id={requirement_id}, "
                f"submission={submission_id})."
            )
        if not isinstance(reasoning, str) or not reasoning.strip():
            raise LLMAdapterError(
                f"{vendor} 응답의 reasoning이 비어 있다(requirement_id={requirement_id}, "
                f"submission={submission_id})."
            )
        if requirement_id in verdict_by_id:
            raise LLMAdapterError(
                f"{vendor} 응답에 requirement_id={requirement_id}가 중복됐다"
                f"(submission={submission_id})."
            )
        verdict_by_id[requirement_id] = RequirementVerdict(
            requirement_id=requirement_id, is_met=is_met, reasoning=reasoning.strip(), verdict=verdict
        )

    missing = [rid for rid in requirement_ids if rid not in verdict_by_id]
    if missing:
        raise LLMAdapterError(
            f"{vendor} 응답이 일부 requirement에 대한 판정을 빠뜨렸다"
            f"(missing_requirement_ids={missing}, submission={submission_id}) — "
            "미충족으로 채우지 않고 채점 자체를 실패로 남긴다."
        )

    return verdict_by_id

def _usage_count(usage: Any, key: str) -> int:
    value = usage.get(key, 0) if isinstance(usage, dict) else 0
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


class OpenAIScoringAdapter:
    """OpenAI로 실제 채점하는 실물 어댑터 (#88, #287, ADR-0006, ADR-0007, ADR-0014).

    `LLM_ADAPTER_MODE=scoring.adapters.OpenAIScoringAdapter`로 켠다
    (`core.adapters.resolve_adapter`). **공모전 채점**의 자격증명은 환경변수
    `OPEN_AI_API_KEY`에서만 읽는다 — 저장소에는 들어가지 않는다. 모델명은
    `LLM_OPENAI_MODEL`(기본 `gpt-4o-mini`), temperature는
    `LLM_OPENAI_TEMPERATURE`(기본 0)로 배포 환경마다 바꿀 수 있다 — compose의
    `environment`에 실려 컨테이너까지 전달된다(#88 코드리뷰 지적 6, docker/
    compose.prod.yaml).

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
        #: 추론 모델(GPT-5 계열)의 판정 전 추론 강도(#402) — "low"|"medium"|
        #: "high". **주지 않으면(`None`, 기본값) 지금 동작 그대로다**:
        #: `temperature`를 보내고 이 값은 요청에 실리지 않는다. 공모전
        #: (`scoring`)은 이 인자를 한 번도 주지 않으므로 공모전 채점은 이
        #: 티켓으로 한 글자도 달라지지 않는다 — `classroom.scoring`만 채점
        #: 모델이 추론 모델일 때 이 값을 넘긴다.
        reasoning_effort: str | None = None,
        timeout: float = _OPENAI_REQUEST_TIMEOUT_SECONDS,
        #: 이 어댑터가 부를 API 의 base URL(#599). 주지 않으면 OpenAI 다 — 공모전은 이 인자를
        #: 주지 않는다. 강의실은 채점 연결이 주는 주소를 넘긴다.
        base_url: str | None = None,
        #: 왕복을 대신 보내는 함수(#601, `Transport`). 강의실의 호환 서버 연결만 준다 — 그
        #: 연결은 인증 값을 비워 둘 수 있어 빈 키로도 만들어진다.
        transport: Transport | None = None,
        #: `transport` 의 비동기 판(#584) — grader 가 `score_async` 에서 쓴다.
        async_transport: AsyncTransport | None = None,
        #: 지표·호출별 로그의 제품 라벨(#585) — 공모전은 주지 않아 `contest`, 강의실이 `classroom` 을 준다.
        product: str = "contest",
        #: 호출별 로그에 실리는 식별 번호(클래스·문제 등) — 지표 라벨이 아니다. 본문·키를 담지 않는다.
        log_context: dict | None = None,
        #: 판정에 「확인 불가」를 받는가(#811, ADR-0067) — 강의실만 True 로 준다. 공모전은 주지 않아
        #: 스키마·파서가 지금 그대로(`is_met`)다.
        allow_unverifiable: bool = False,
    ) -> None:
        # 공모전은 운영 설정(#922, ADR-0075 — DB 가 있으면 DB, 없으면 env)을 거친다. 어댑터는
        # 호출마다 새로 만들어지므로(`get_adapter`) 키·모델을 바꾸면 다음 호출부터 새 값이다.
        # 강의실(`product="classroom"`)은 강사 키·모델을 인자로 받고 나머지는 지금처럼 env 다.
        read = _runtime_setting if product == "contest" else _env_setting
        api_key = api_key if api_key is not None else (read("OPEN_AI_API_KEY") or "")
        if not api_key and transport is None:
            raise LLMAdapterError(
                "OPEN_AI_API_KEY가 비어 있다 — 실물 OpenAI 채점 어댑터는 자격증명 없이 "
                "생성할 수 없다."
            )
        self._api_key = api_key
        self._model = model or read("LLM_OPENAI_MODEL") or _OPENAI_DEFAULT_MODEL
        if temperature is not None:
            self._temperature = temperature
        else:
            raw_temperature = read("LLM_OPENAI_TEMPERATURE")
            self._temperature = float(raw_temperature) if raw_temperature else _OPENAI_DEFAULT_TEMPERATURE
        self._reasoning_effort = reasoning_effort
        self._timeout = timeout
        self._base_url = base_url
        self._transport = transport
        self._async_transport = async_transport
        self._product = product
        self._log_context = dict(log_context or {})
        self._allow_unverifiable = allow_unverifiable
        # 부팅 가드(core.adapters.check_adapter_mode)의 isinstance(LLMScoringAdapter)
        # 검사가 요구하는 자리 — 실제 호출에 쓰인 모델 식별자는 매 score() 호출마다
        # OpenAI 응답의 "model" 필드에서 새로 읽어 ScoringOutput.model_version으로
        # 돌려준다(별칭으로 요청해도 응답은 구체 버전을 돌려주므로 그쪽이 감사에 더
        # 정확하다, #88 AC).
        self.model_version = self._model

    def _scoring_payload(self, scoring_input: ScoringInput) -> dict:
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _OPENAI_SYSTEM_PROMPT},
                {"role": "user", "content": scoring_input.prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": _openai_verdict_response_schema(allow_unverifiable=self._allow_unverifiable),
            },
        }
        # 추론 모델은 temperature를 받지 않고 reasoning_effort를 받는다
        # (#402) — 둘 다 요청에 함께 실으면 벤더가 temperature를 거부한다.
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        else:
            payload["temperature"] = self._temperature
        return payload

    def _scoring_output(self, response: Any, scoring_input: ScoringInput) -> ScoringOutput:
        requirement_ids = [r.requirement_id for r in scoring_input.requirements]
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
                allow_unverifiable=self._allow_unverifiable,
            )
        except LLMAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - 예상 못한 응답 모양도 조용히 죽지 않아야 한다.
            raise LLMAdapterError(
                f"OpenAI 응답을 파싱하는 중 예상치 못한 오류가 났다({type(exc).__name__}, "
                f"submission={scoring_input.submission_id})."
            ) from None

    def _observe_args(self, scoring_input: ScoringInput) -> dict:
        context = {"submission_id": scoring_input.submission_id, **self._log_context}
        if self._product == "contest":
            context["contest_id"] = scoring_input.contest_id
        return {
            "product": self._product,
            "model": self._model,
            "custom": self._base_url is not None,
            "reasoning_effort": self._reasoning_effort,
            "context": context,
        }

    def score(self, scoring_input: ScoringInput) -> ScoringOutput:
        with observe_call(**self._observe_args(scoring_input)) as call:
            response = _openai_round_trip(
                "POST",
                _endpoint(self._base_url, _CHAT_COMPLETIONS_PATH),
                api_key=self._api_key,
                timeout=self._timeout,
                json_body=self._scoring_payload(scoring_input),
                context=f"submission={scoring_input.submission_id}",
                transport=self._transport,
            )
            output = self._scoring_output(response, scoring_input)
            call.succeed(output)
            return output

    async def score_async(self, scoring_input: ScoringInput) -> ScoringOutput:
        """`score` 의 비동기 판(#584) — 같은 요청·같은 분류, 기다리는 동안 스레드를 쥐지 않는다.
        강의실 grader 가 쓴다(공모전은 `score` 그대로)."""

        async with observe_call_async(**self._observe_args(scoring_input)) as call:
            response = await _openai_round_trip_async(
                "POST",
                _endpoint(self._base_url, _CHAT_COMPLETIONS_PATH),
                api_key=self._api_key,
                timeout=self._timeout,
                json_body=self._scoring_payload(scoring_input),
                context=f"submission={scoring_input.submission_id}",
                transport=self._async_transport,
            )
            output = self._scoring_output(response, scoring_input)
            call.succeed(output)
            return output

    # --- 완성도(#883, ADR-0072) — 판정과 같은 왕복·같은 오류 분류, 스키마·검증만 다르다 ---------------

    def _quality_payload(self, quality_input: quality_review.QualityInput) -> dict:
        payload: dict[str, object] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": quality_review.QUALITY_SYSTEM_PROMPT},
                {"role": "user", "content": quality_input.prompt},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": quality_review.QUALITY_SCHEMA_NAME,
                    "strict": True,
                    "schema": quality_review.response_schema(),
                },
            },
        }
        if self._reasoning_effort is not None:
            payload["reasoning_effort"] = self._reasoning_effort
        else:
            payload["temperature"] = self._temperature
        return payload

    def _quality_output(self, response: Any, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        sid = quality_input.submission_id
        try:
            body = response.json()
        except ValueError:
            raise LLMAdapterError(f"OpenAI 응답이 JSON이 아니다(submission={sid}).") from None
        choices = body.get("choices") if isinstance(body, dict) else None
        choice = choices[0] if isinstance(choices, list) and choices and isinstance(choices[0], dict) else None
        if choice is None:
            raise LLMAdapterError(f"OpenAI 응답에 choices가 없다(submission={sid}).")
        if choice.get("finish_reason") != "stop":
            raise LLMAdapterPermanentError(
                f"OpenAI 응답이 정상 종료되지 않았다(finish_reason={choice.get('finish_reason')!r}, submission={sid})."
            )
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        try:
            scores = quality_review.parse_content(content, items=quality_input.items, submission_id=sid)
        except quality_review.QualityResponseError as exc:
            raise LLMAdapterError(str(exc)) from None
        usage = body.get("usage") or {}
        return quality_review.QualityOutput(
            scores=tuple(scores),
            model_version=str(body.get("model") or "unknown"),
            total_tokens=_usage_count(usage, "total_tokens"),
            input_tokens=_usage_count(usage, "prompt_tokens"),
            output_tokens=_usage_count(usage, "completion_tokens"),
        )

    def _quality_observe_args(self, quality_input: quality_review.QualityInput) -> dict:
        return {
            "product": self._product,
            "model": self._model,
            "custom": self._base_url is not None,
            "reasoning_effort": self._reasoning_effort,
            "context": {"submission_id": quality_input.submission_id, "kind": "quality", **self._log_context},
        }

    def review_quality(self, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        with observe_call(**self._quality_observe_args(quality_input)) as call:
            response = _openai_round_trip(
                "POST",
                _endpoint(self._base_url, _CHAT_COMPLETIONS_PATH),
                api_key=self._api_key,
                timeout=self._timeout,
                json_body=self._quality_payload(quality_input),
                context=f"submission={quality_input.submission_id}",
                transport=self._transport,
            )
            output = self._quality_output(response, quality_input)
            call.succeed(output)
            return output

    async def review_quality_async(self, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        async with observe_call_async(**self._quality_observe_args(quality_input)) as call:
            response = await _openai_round_trip_async(
                "POST",
                _endpoint(self._base_url, _CHAT_COMPLETIONS_PATH),
                api_key=self._api_key,
                timeout=self._timeout,
                json_body=self._quality_payload(quality_input),
                context=f"submission={quality_input.submission_id}",
                transport=self._async_transport,
            )
            output = self._quality_output(response, quality_input)
            call.succeed(output)
            return output

    def check_key(self) -> LLMKeyCheckStatus:
        """저장 시점에 이 키가 실제로 쓸 수 있는지 벤더에게 한 번 묻는다(#354).

        채점 호출(`/chat/completions`)이 아니라 모델 목록 조회(`/models`)를
        친다 — 프롬프트도 토큰도 쓰지 않는 가장 값싼 인증 확인이다. 401·403은
        키가 틀렸다는 확실한 신호(`REJECTED`)이고, 그 밖의 모든 실패(타임아웃·
        네트워크 오류·5xx·예상 밖의 상태)는 "확인하지 못했다"(`UNVERIFIED`)로
        묶는다 — 여기서 막으려는 것은 오타이지 벤더의 그 순간 가용성이 아니다.
        """

        try:
            _openai_round_trip(
                "GET",
                _endpoint(self._base_url, _MODELS_PATH),
                api_key=self._api_key,
                timeout=self._timeout,
                context="key-check",
                transport=self._transport,
            )
        except LLMAdapterAuthError:
            return LLMKeyCheckStatus.REJECTED
        except LLMAdapterError:
            return LLMKeyCheckStatus.UNVERIFIED
        return LLMKeyCheckStatus.VALID


def list_openai_models(
    api_key: str,
    *,
    base_url: str | None = None,
    timeout: float = _OPENAI_REQUEST_TIMEOUT_SECONDS,
    transport: Transport | None = None,
) -> list[str] | None:
    """이 키로 `/v1/models`를 조회해 모델 id 목록을 돌려준다(#401) —
    `classroom.scoring_model_catalog`가 이 목록을 규칙으로 거른다
    (`classroom.scoring_models.build_catalog`).

    실패(네트워크 오류·타임아웃·거부·5xx·예상 밖의 응답 모양)는 전부 `None`
    이다 — 호출자가 "키 없음"과 "조회 실패"를 이미 구별해 쥐고 있으므로,
    이 함수는 그 둘을 가르지 않고 성공/실패만 말한다(`OpenAIScoringAdapter.
    check_key`가 REJECTED/UNVERIFIED를 가르는 것과 다른 자리 — 이 함수는
    모델 목록이 필요할 뿐 키 상태를 판정하지 않는다).

    `base_url`을 주지 않으면 OpenAI 다(#599) — 강의실은 채점 연결의 주소를 넘긴다.

    `check_key`와 같은 왕복(`_openai_round_trip`, GET `/v1/models`)을 쓴다
    (#469) — 둘은 실제로 같은 응답에서 나온다. 다만 몸통 파싱은 이 함수만
    한다: `check_key`는 상태 코드만 보고, 이 함수는 응답 몸통의 `data`
    배열까지 봐야 하기 때문이다."""

    try:
        response = _openai_round_trip(
            "GET",
            _endpoint(base_url, _MODELS_PATH),
            api_key=api_key,
            timeout=timeout,
            context="model-list",
            transport=transport,
        )
    except LLMAdapterError:
        return None

    try:
        body = response.json()
    except ValueError:
        return None

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return None

    return [item["id"] for item in data if isinstance(item, dict) and isinstance(item.get("id"), str)]


def _env_setting(key: str) -> str | None:
    return os.environ.get(key) or None


def _runtime_setting(key: str) -> str | None:
    # 늦은 임포트 — policies 가 core 를 임포트한다(순환을 피한다). 둘 다 공유층이다.
    from policies.runtime_settings import setting_value

    return setting_value(key)


def probe_openai_key(api_key: str) -> Literal["ok", "invalid_key", "unavailable"]:
    """운영 설정의 연결 시험(#922) — 강의실 키 확인(`check_key`, 모델 목록 조회)과 같은 왕복이다.

    결과 낱말만 돌려준다. 응답 본문·예외 문구는 넘기지 않는다(키가 섞일 수 있다). 모델·temperature 는
    이 호출에 쓰이지 않으므로 운영 설정을 읽지 않게 직접 준다.
    """

    status = OpenAIScoringAdapter(
        api_key=api_key, model=_OPENAI_DEFAULT_MODEL, temperature=_OPENAI_DEFAULT_TEMPERATURE
    ).check_key()
    return {
        LLMKeyCheckStatus.VALID: "ok",
        LLMKeyCheckStatus.REJECTED: "invalid_key",
    }.get(status, "unavailable")


def fake_probe_openai_key(api_key: str) -> Literal["ok", "invalid_key", "unavailable"]:
    """흉내 — 실물처럼 모양이 틀린 키는 거절한다(`sk-` 로 시작하고 20자 이상이어야 통과)."""

    return "ok" if api_key.startswith("sk-") and len(api_key) >= 20 else "invalid_key"


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
