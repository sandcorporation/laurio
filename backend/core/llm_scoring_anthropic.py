"""Claude(Anthropic) 채점 어댑터 — 강의실 「Claude(Anthropic) 키」 연결(#795, ADR-0066).

`core.llm_scoring.OpenAIScoringAdapter` 의 짝이다. 같은 입력(`ScoringInput`)을 받아 같은 출력
(`ScoringOutput`)을 내고, 같은 예외 갈래(`LLMAdapter*Error`)로 실패를 가른다 — 강의실 채점
(`classroom.scoring`)은 어느 어댑터가 돌았는지 몰라도 된다. 판정 JSON 의 검증은 OpenAI 와 같은
함수(`core.llm_scoring.verdicts_from_content`)가 한다.

**호환 주소(`https://api.anthropic.com/v1/` 의 OpenAI 호환 API)를 쓰지 않는다** — 그 주소는
`response_format` 의 json_schema 를 무시해 판정 형식이 보장되지 않는다(ADR-0066). 네이티브 Messages
API(`POST /v1/messages`)에 **구조화 출력**을 싣는다.

요청 모양 — 공식 문서를 2026-10-28 에 직접 읽고 정했다(기억으로 쓰지 않았다):

- 구조화 출력: `output_config.format = {"type": "json_schema", "schema": …}`. GA 필드라 베타 헤더가
  없다(예전 `output_format` + `structured-outputs-2025-11-13` 베타 헤더는 폐기 예정).
  스키마의 객체는 `additionalProperties: false` 여야 한다.
  https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- 추론 강도: `output_config.effort`(`low`·`medium`·`high`). Claude Haiku 5.5·Sonnet 5.5 는 사고(adaptive
  thinking)가 기본으로 켜져 있고 Sonnet 5.5 는 끌 수 없다 — 그래서 강의실의 「추론 강도」를 그대로
  effort 로 싣는다. 사고 토큰은 출력 토큰으로 청구되고 `max_tokens` 에 함께 센다.
  https://platform.claude.com/docs/en/build-with-claude/effort ·
  https://platform.claude.com/docs/en/build-with-claude/thinking
- 응답: `content` 는 사고 블록(`type: "thinking"`) 뒤에 판정 JSON 이 든 text 블록이 온다 — 첫 블록이
  아니라 type 으로 찾는다. `stop_reason` 이 `end_turn` 이 아니면(`max_tokens`·`refusal` 등) 판정으로
  쓰지 않는다.
- 오류: 몸통은 `{"type": "error", "error": {"type": …, "message": …}}`. 401 authentication_error·
  403 permission_error → 키 거부, 404 not_found_error → 모델 거부, 402 billing_error·400 의 사용 한도
  도달(「You have reached your specified … API usage limits」)·크레딧 부족(「credit balance」)·429 의
  `error.details.error_code == "enforced_spend_limit_reached"` → 크레딧 소진, 그 밖의 429·529
  overloaded_error → 빈도 제한. https://platform.claude.com/docs/en/api/errors ·
  https://platform.claude.com/docs/en/api/rate-limits
- 모델 목록: `GET /v1/models?limit=1000` 의 각 항목 `line`(haiku·sonnet·opus…)과
  `capabilities.structured_outputs`·`capabilities.effort` 로 거른다 — id 로 계열을 추측하지 않는다.
  https://platform.claude.com/docs/en/api/models/list

`error.message` 는 크레딧 소진을 가르는 데에만 읽고 예외 메시지에는 싣지 않는다(ADR-0014 — 벤더가
보낸 자유 텍스트는 우리 프롬프트를 되풀이할 수 있다).
"""

from __future__ import annotations

from typing import Any

import aiohttp
import requests

from core import llm_scoring, quality_review
from core.llm_metrics import observe_call, observe_call_async
from core.llm_scoring import (
    LLMAdapterAuthError,
    LLMAdapterError,
    LLMAdapterModelRejectedError,
    LLMAdapterPermanentError,
    LLMAdapterQuotaExhaustedError,
    LLMAdapterRateLimitedError,
    LLMAdapterTimeoutError,
    LLMKeyCheckStatus,
    ScoringInput,
    ScoringOutput,
    verdicts_from_content,
)

ANTHROPIC_API_BASE_URL = "https://api.anthropic.com/v1"
#: 요청 헤더 `anthropic-version` — 문서의 예시가 쓰는 안정 판이다.
ANTHROPIC_VERSION = "2023-06-01"
_MESSAGES_PATH = "/messages"
_MODELS_PATH = "/models"

#: 출력 상한 — 사고 토큰이 여기 함께 센다(문서 「effort」). 「높음」의 어림(15,000,
#: `classroom.scoring_cost.REASONING_OUTPUT_TOKENS`)보다 넉넉히 잡아 판정이 잘리지 않게 한다.
#: 상한일 뿐이라 실제 쓴 만큼만 청구된다.
SCORING_MAX_TOKENS = 32_000

_REQUEST_TIMEOUT_SECONDS = 20

#: 채점에 쓰는 계열 — Opus 는 비용 때문에 뺀다(#795).
SCORING_MODEL_LINES = frozenset({"haiku", "sonnet"})

_AUTH_STATUSES = frozenset({401, 403})
_MODEL_REJECTED_STATUS = 404
_BILLING_STATUS = 402
_RATE_LIMIT_STATUSES = frozenset({429, 529})
_SPEND_CAP_ERROR_CODE = "enforced_spend_limit_reached"
#: 400 의 `error.message` 가운데 「충전·한도를 올려야 풀린다」를 뜻하는 머리말 — 소문자로 견준다.
_QUOTA_MESSAGE_MARKERS = (
    "you have reached your specified api usage limits",
    "you have reached your specified workspace api usage limits",
    "credit balance",
)

_SYSTEM_PROMPT = llm_scoring._OPENAI_SYSTEM_PROMPT + (
    # 문서(구조화 출력)는 「단계별 추론을 적게 하는 속성」이 reasoning_extraction 거절을 부를 수 있다고
    # 한다 — 근거는 짧은 설명이라고 못 박는다.
    " 근거는 판정의 이유를 짧게 설명하는 한두 문장으로 씁니다."
)


def _verdict_schema(*, allow_unverifiable: bool = False) -> dict:
    """OpenAI 와 같은 판정 스키마(`core.llm_scoring._openai_verdict_response_schema` 의 `schema`) —
    Anthropic 은 이름·strict 없이 스키마만 받는다. 강의실은 「확인 불가」를 받는 쪽이다(#811)."""

    return llm_scoring._openai_verdict_response_schema(allow_unverifiable=allow_unverifiable)["schema"]


def _headers(api_key: str, *, json_body: bool) -> dict[str, str]:
    headers = {"x-api-key": api_key, "anthropic-version": ANTHROPIC_VERSION}
    if json_body:
        headers["content-type"] = "application/json"
    return headers


def _error_fields(response: Any) -> tuple[str, str, str]:
    """(error.type, error.details.error_code, error.message 소문자) — 모양이 다르면 빈 값."""

    try:
        body = response.json()
    except ValueError:
        return "", "", ""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "", "", ""
    details = error.get("details")
    code = details.get("error_code") if isinstance(details, dict) else ""
    message = error.get("message")
    return (
        str(error.get("type") or "")[:100],
        str(code or "")[:100],
        message.lower() if isinstance(message, str) else "",
    )


def _pick_error(status: int, error_type: str, error_code: str, message: str) -> type[LLMAdapterError]:
    if status in _AUTH_STATUSES:
        return LLMAdapterAuthError
    if status == _MODEL_REJECTED_STATUS:
        return LLMAdapterModelRejectedError
    if status == _BILLING_STATUS or error_code == _SPEND_CAP_ERROR_CODE:
        return LLMAdapterQuotaExhaustedError
    if status == 400 and any(marker in message for marker in _QUOTA_MESSAGE_MARKERS):
        return LLMAdapterQuotaExhaustedError
    if status in _RATE_LIMIT_STATUSES:
        return LLMAdapterRateLimitedError
    if 400 <= status < 500:
        return LLMAdapterPermanentError
    return LLMAdapterError


def classify_error(response: Any, *, context: str) -> LLMAdapterError:
    """200 이 아닌 응답을 예외로 — 메시지에는 상태·`error.type`·`error_code` 만 싣는다."""

    error_type, error_code, message = _error_fields(response)
    details = ", ".join(p for p in (f"type={error_type}" if error_type else "", f"code={error_code}" if error_code else "") if p)
    text = f"Anthropic 호출이 실패했다(status={response.status_code}, {context}"
    text += f", {details})." if details else ")."
    error = _pick_error(response.status_code, error_type, error_code, message)(text)
    error.status_code = response.status_code
    error.vendor_error_type = error_type
    error.vendor_error_code = error_code
    return error


def _round_trip(method: str, url: str, *, api_key: str, timeout: float, json_body: dict | None, context: str) -> Any:
    kwargs: dict[str, Any] = {"headers": _headers(api_key, json_body=json_body is not None), "timeout": timeout}
    if json_body is not None:
        kwargs["json"] = json_body
    send = requests.post if method == "POST" else requests.get
    try:
        response = send(url, **kwargs)
    except requests.RequestException as exc:
        error = LLMAdapterTimeoutError if isinstance(exc, requests.Timeout) else LLMAdapterError
        raise error(f"Anthropic 호출이 네트워크 오류로 실패했다({type(exc).__name__}, {context}).") from None
    if response.status_code == 200:
        return response
    raise classify_error(response, context=context)


async def _round_trip_async(
    method: str, url: str, *, api_key: str, timeout: float, json_body: dict | None, context: str, transport=None
) -> Any:
    kwargs: dict[str, Any] = {"headers": _headers(api_key, json_body=json_body is not None), "timeout": timeout}
    if json_body is not None:
        kwargs["json"] = json_body
    try:
        # 기본 길은 OpenAI 와 같은 aiohttp 왕복이다(주소가 고정된 벤더라 푼 IP 고정이 필요 없다).
        response = await (transport or llm_scoring._aiohttp_request)(method, url, **kwargs)
    except (aiohttp.ClientError, TimeoutError, OSError) as exc:
        error = LLMAdapterTimeoutError if isinstance(exc, TimeoutError) else LLMAdapterError
        raise error(f"Anthropic 호출이 네트워크 오류로 실패했다({type(exc).__name__}, {context}).") from None
    if response.status_code == 200:
        return response
    raise classify_error(response, context=context)


def _usage_int(usage: Any, key: str) -> int:
    value = usage.get(key, 0) if isinstance(usage, dict) else 0
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def parse_messages_response(
    body: Any, *, requirement_ids: list[int], submission_id: int, allow_unverifiable: bool = False
) -> ScoringOutput:
    """Messages API 응답 → `ScoringOutput`. 잘렸거나 거절한 응답은 판정으로 쓰지 않는다."""

    if not isinstance(body, dict):
        raise LLMAdapterError(f"Anthropic 응답이 객체가 아니다(submission={submission_id}).")
    stop_reason = body.get("stop_reason")
    if stop_reason != "end_turn":
        raise LLMAdapterPermanentError(
            f"Anthropic 응답이 정상 종료되지 않았다(stop_reason={stop_reason!r}, "
            f"submission={submission_id}) — 잘렸거나 거절된 응답을 점수로 쓸 수 없다."
        )
    blocks = body.get("content")
    texts = [
        block.get("text")
        for block in (blocks if isinstance(blocks, list) else [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    if not texts:
        raise LLMAdapterError(f"Anthropic 응답에 text 블록이 없다(submission={submission_id}).")
    verdict_by_id = verdicts_from_content(
        texts[0],
        requirement_ids=requirement_ids,
        submission_id=submission_id,
        vendor="Anthropic",
        allow_unverifiable=allow_unverifiable,
    )
    usage = body.get("usage") or {}
    # 입력은 캐시 읽기·쓰기까지 모두 더한 것이 프롬프트 전체다(문서 「rate limits」) — 채점은 캐시를
    # 쓰지 않지만 벤더가 실어 보내면 사용량에서 빠뜨리지 않는다.
    input_tokens = sum(
        _usage_int(usage, key) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
    )
    output_tokens = _usage_int(usage, "output_tokens")
    return ScoringOutput(
        verdicts=[verdict_by_id[rid] for rid in requirement_ids],
        model_version=str(body.get("model") or "unknown"),
        total_tokens=input_tokens + output_tokens,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class AnthropicScoringAdapter:
    """Claude 로 채점하는 실물 어댑터(#795). 강의실의 「Claude(Anthropic) 키」 연결에서만 쓴다 —
    `classroom.scoring._scoring_adapter` 가 연결 종류로 고른다. 공모전 경로는 이 어댑터를 모른다.

    인자는 `OpenAIScoringAdapter` 와 같은 모양으로 받는다(`_scoring_adapter` 가 한 벌의 인자로
    둘 중 하나를 만든다). `base_url`·`transport` 는 받기만 하고 쓰지 않는다 — 주소는 Anthropic 으로
    고정이고 강사가 적은 주소가 아니라 안전한 바깥 호출을 거칠 이유가 없다."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        reasoning_effort: str | None = None,
        timeout: float = _REQUEST_TIMEOUT_SECONDS,
        base_url: str | None = None,
        transport=None,
        async_transport=None,
        product: str = "classroom",
        log_context: dict | None = None,
        #: 판정에 「확인 불가」를 받는가(#811) — `OpenAIScoringAdapter` 와 같은 인자. 강의실이 True 로 준다.
        allow_unverifiable: bool = False,
    ) -> None:
        if not api_key:
            raise LLMAdapterError("Anthropic 채점 어댑터는 키 없이 만들 수 없다.")
        del base_url, transport  # 위 docstring — 주소는 고정이다.
        self._api_key = api_key
        self._model = model
        self._reasoning_effort = reasoning_effort
        self._timeout = timeout
        self._async_transport = async_transport
        self._product = product
        self._log_context = dict(log_context or {})
        self._allow_unverifiable = allow_unverifiable
        self.model_version = model

    def _payload(self, scoring_input: ScoringInput) -> dict:
        output_config: dict[str, Any] = {
            "format": {"type": "json_schema", "schema": _verdict_schema(allow_unverifiable=self._allow_unverifiable)}
        }
        if self._reasoning_effort is not None:
            output_config["effort"] = self._reasoning_effort
        return {
            "model": self._model,
            "max_tokens": SCORING_MAX_TOKENS,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": scoring_input.prompt}],
            "output_config": output_config,
        }

    def _output(self, response: Any, scoring_input: ScoringInput) -> ScoringOutput:
        try:
            body = response.json()
        except ValueError:
            raise LLMAdapterError(f"Anthropic 응답이 JSON이 아니다(submission={scoring_input.submission_id}).") from None
        try:
            return parse_messages_response(
                body,
                requirement_ids=[r.requirement_id for r in scoring_input.requirements],
                submission_id=scoring_input.submission_id,
                allow_unverifiable=self._allow_unverifiable,
            )
        except LLMAdapterError:
            raise
        except Exception as exc:  # noqa: BLE001 - 예상 못한 응답 모양도 조용히 죽지 않아야 한다.
            raise LLMAdapterError(
                f"Anthropic 응답을 파싱하는 중 예상치 못한 오류가 났다({type(exc).__name__}, "
                f"submission={scoring_input.submission_id})."
            ) from None

    def _observe_args(self, scoring_input: ScoringInput) -> dict:
        return {
            "product": self._product,
            "model": self._model,
            "custom": False,
            "reasoning_effort": self._reasoning_effort,
            "context": {"submission_id": scoring_input.submission_id, **self._log_context},
        }

    def score(self, scoring_input: ScoringInput) -> ScoringOutput:
        with observe_call(**self._observe_args(scoring_input)) as call:
            response = _round_trip(
                "POST",
                ANTHROPIC_API_BASE_URL + _MESSAGES_PATH,
                api_key=self._api_key,
                timeout=self._timeout,
                json_body=self._payload(scoring_input),
                context=f"submission={scoring_input.submission_id}",
            )
            output = self._output(response, scoring_input)
            call.succeed(output)
            return output

    async def score_async(self, scoring_input: ScoringInput) -> ScoringOutput:
        async with observe_call_async(**self._observe_args(scoring_input)) as call:
            response = await _round_trip_async(
                "POST",
                ANTHROPIC_API_BASE_URL + _MESSAGES_PATH,
                api_key=self._api_key,
                timeout=self._timeout,
                json_body=self._payload(scoring_input),
                context=f"submission={scoring_input.submission_id}",
                transport=self._async_transport,
            )
            output = self._output(response, scoring_input)
            call.succeed(output)
            return output

    # --- 완성도(#883, ADR-0072) ------------------------------------------------------------

    def _quality_payload(self, quality_input: quality_review.QualityInput) -> dict:
        output_config: dict[str, Any] = {"format": {"type": "json_schema", "schema": quality_review.response_schema()}}
        if self._reasoning_effort is not None:
            output_config["effort"] = self._reasoning_effort
        return {
            "model": self._model,
            "max_tokens": SCORING_MAX_TOKENS,
            "system": quality_review.QUALITY_SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": quality_input.prompt}],
            "output_config": output_config,
        }

    def _quality_output(self, response: Any, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        sid = quality_input.submission_id
        try:
            body = response.json()
        except ValueError:
            raise LLMAdapterError(f"Anthropic 응답이 JSON이 아니다(submission={sid}).") from None
        if not isinstance(body, dict):
            raise LLMAdapterError(f"Anthropic 응답이 객체가 아니다(submission={sid}).")
        if body.get("stop_reason") != "end_turn":
            raise LLMAdapterPermanentError(
                f"Anthropic 응답이 정상 종료되지 않았다(stop_reason={body.get('stop_reason')!r}, submission={sid})."
            )
        blocks = body.get("content")
        texts = [
            block.get("text")
            for block in (blocks if isinstance(blocks, list) else [])
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        if not texts:
            raise LLMAdapterError(f"Anthropic 응답에 text 블록이 없다(submission={sid}).")
        try:
            scores = quality_review.parse_content(texts[0], items=quality_input.items, submission_id=sid)
        except quality_review.QualityResponseError as exc:
            raise LLMAdapterError(str(exc)) from None
        usage = body.get("usage") or {}
        input_tokens = sum(
            _usage_int(usage, key) for key in ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        )
        output_tokens = _usage_int(usage, "output_tokens")
        return quality_review.QualityOutput(
            scores=tuple(scores),
            model_version=str(body.get("model") or "unknown"),
            total_tokens=input_tokens + output_tokens,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def _quality_observe_args(self, quality_input: quality_review.QualityInput) -> dict:
        return {
            "product": self._product,
            "model": self._model,
            "custom": False,
            "reasoning_effort": self._reasoning_effort,
            "context": {"submission_id": quality_input.submission_id, "kind": "quality", **self._log_context},
        }

    def review_quality(self, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        with observe_call(**self._quality_observe_args(quality_input)) as call:
            response = _round_trip(
                "POST",
                ANTHROPIC_API_BASE_URL + _MESSAGES_PATH,
                api_key=self._api_key,
                timeout=self._timeout,
                json_body=self._quality_payload(quality_input),
                context=f"submission={quality_input.submission_id}",
            )
            output = self._quality_output(response, quality_input)
            call.succeed(output)
            return output

    async def review_quality_async(self, quality_input: quality_review.QualityInput) -> quality_review.QualityOutput:
        async with observe_call_async(**self._quality_observe_args(quality_input)) as call:
            response = await _round_trip_async(
                "POST",
                ANTHROPIC_API_BASE_URL + _MESSAGES_PATH,
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
        """저장 전 키 확인 — `GET /v1/models`(토큰을 쓰지 않는다). 401·403 만 거부, 그 밖의 실패는
        「확인하지 못했다」(#681 의 미검증 저장)."""

        try:
            _round_trip(
                "GET",
                ANTHROPIC_API_BASE_URL + _MODELS_PATH,
                api_key=self._api_key,
                timeout=_REQUEST_TIMEOUT_SECONDS,
                json_body=None,
                context="key-check",
            )
        except LLMAdapterAuthError:
            return LLMKeyCheckStatus.REJECTED
        except LLMAdapterError:
            return LLMKeyCheckStatus.UNVERIFIED
        return LLMKeyCheckStatus.VALID


def _supported(capabilities: Any, name: str) -> bool:
    """`capabilities` 가 없으면(null) 거르지 않는다 — 문서상 null 일 수 있다."""

    if not isinstance(capabilities, dict):
        return True
    entry = capabilities.get(name)
    return not isinstance(entry, dict) or entry.get("supported") is not False


def scoring_model_ids_from(body: Any) -> list[str] | None:
    """`/v1/models` 몸통에서 채점에 쓸 모델 id 만 — Haiku·Sonnet 계열(`line`)이고 구조화 출력과
    추론 강도(effort)를 받는 것. 몸통 모양이 다르면 `None`. 순서는 벤더 순서(최신 먼저) 그대로다."""

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return None
    ids = [
        item["id"]
        for item in data
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("line") in SCORING_MODEL_LINES
        and item.get("lifecycle", "active") != "retired"
        and _supported(item.get("capabilities"), "structured_outputs")
        and _supported(item.get("capabilities"), "effort")
    ]
    return list(dict.fromkeys(ids))


def list_anthropic_scoring_models(api_key: str, *, timeout: float = _REQUEST_TIMEOUT_SECONDS) -> list[str] | None:
    """이 키로 쓸 수 있는 채점 모델 id — 실패(거부·네트워크·모양)는 `None`(`list_openai_models` 와 같은
    약속)."""

    try:
        response = _round_trip(
            "GET",
            f"{ANTHROPIC_API_BASE_URL}{_MODELS_PATH}?limit=1000",
            api_key=api_key,
            timeout=timeout,
            json_body=None,
            context="model-list",
        )
        body = response.json()
    except (LLMAdapterError, ValueError):
        return None
    return scoring_model_ids_from(body)


#: 테스트·fake 스위치가 쓰는 `/v1/models` 몸통 — 문서의 예시 응답 모양(2026-10-28)을 따른다. Opus(비용)와
#: effort 를 받지 않는 Haiku 4.5 가 걸러지는 것이 네트워크 없이 보이게 섞었다.
def _fake_model(model_id: str, line: str, *, effort: bool = True) -> dict:
    return {
        "type": "model",
        "id": model_id,
        "display_name": model_id,
        "line": line,
        "lifecycle": "active",
        "capabilities": {"structured_outputs": {"supported": True}, "effort": {"supported": effort}},
    }


FAKE_MODELS_BODY: dict = {
    "data": [
        _fake_model("claude-opus-5-5", "opus"),
        _fake_model("claude-sonnet-5-5", "sonnet"),
        _fake_model("claude-haiku-5-5", "haiku"),
        _fake_model("claude-sonnet-5", "sonnet"),
        _fake_model("claude-haiku-4-5-20251001", "haiku", effort=False),
    ],
    "has_more": False,
    "first_id": "claude-opus-5-5",
    "last_id": "claude-haiku-4-5-20251001",
}

__all__ = [
    "ANTHROPIC_API_BASE_URL",
    "AnthropicScoringAdapter",
    "FAKE_MODELS_BODY",
    "list_anthropic_scoring_models",
    "parse_messages_response",
    "scoring_model_ids_from",
]
