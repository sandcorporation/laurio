"""`scoring.adapters.OpenAIScoringAdapter` 단위 테스트 (#88, ADR-0006/0014).

`tests/test_core_adapters.py`와 같은 예외 — 이 파일도 HTTP를 거치지 않는다.
`OpenAIScoringAdapter`는 Laurio 자신의 API가 아니라 OpenAI 벤더 연동 파싱·검증
로직이다(어느 django-ninja 라우터에도 매여 있지 않다). 네트워크도 치지 않는다 —
`requests.post`를 몽키패치해 벤더 응답을 흉내낸다. 실제 벤더를 치는 검증은
`tests/test_live_adapters.py`류의 옵인 `@live_vendor` 테스트가 맡는다(이 티켓은
`OPEN_AI_API_KEY`가 있을 때만 도는 라이브 테스트를 별도로 추가한다).

이 파일이 지키는지 확인하는 것 — #88 AC 그대로:

- 모든 requirement_id에 판정이 없으면 예외가 나고 「미충족」으로 채워지지 않는다.
- 응답이 잘렸거나(finish_reason != "stop") 깨졌으면(JSON 파싱 실패 등) 예외가
  난다 — 낮은 점수로 둔갑하지 않는다.
- 프롬프트에 실린 소스가 예외 메시지로 새지 않는다(ADR-0014).
- 자격증명이 없으면 어댑터 생성 자체가 거부된다(부팅 가드가 여기 기댄다, #83).
- 실제 호출에 쓰인 모델 식별자(OpenAI 응답의 "model" 필드)가 기록된다.
"""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from scoring.adapters import (
    LLMAdapterError,
    LLMAdapterPermanentError,
    OpenAIScoringAdapter,
    RequirementInput,
    ScoringInput,
)
from scoring.checks import check_llm_adapter_mode

SECRET_SOURCE_MARKER = "__LAURIO_SUBMISSION_SOURCE_SECRET_MARKER__"


class _FakeResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def _scoring_input(*, submission_id: int = 1, requirement_ids: list[int] | None = None) -> ScoringInput:
    requirement_ids = requirement_ids if requirement_ids is not None else [10, 11]
    requirements = [
        RequirementInput(
            requirement_id=rid,
            text=f"requirement {rid}",
            grade="required",
            self_reported_met=True,
            evidence=[{"kind": "source", "value": "app.py:1"}],
        )
        for rid in requirement_ids
    ]
    return ScoringInput(
        submission_id=submission_id,
        contest_id=99,
        prompt=f"채점 프롬프트 — 소스: {SECRET_SOURCE_MARKER}",
        source_files=[],
        requirements=requirements,
    )


def _chat_completion_body(verdicts: list[dict], *, model: str = "gpt-4o-mini-2024-07-18", finish_reason: str = "stop"):
    return {
        "model": model,
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": json.dumps({"verdicts": verdicts})},
            }
        ],
    }


@pytest.fixture(autouse=True)
def _openai_api_key(monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", "sk-test-key-do-not-leak")


# --- 생성자 — 자격증명 -----------------------------------------------------------


def test_construction_raises_when_credential_is_missing(monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)

    with pytest.raises(LLMAdapterError):
        OpenAIScoringAdapter()


def test_construction_succeeds_with_credential():
    adapter = OpenAIScoringAdapter()
    assert adapter.model_version  # 기본 모델명이 채워져 있다.


# --- 정상 경로 ---------------------------------------------------------------------


def test_score_returns_verdicts_and_records_actual_model_from_response(monkeypatch):
    body = _chat_completion_body(
        [
            {"requirement_id": 10, "is_met": True, "reasoning": "소스에서 확인됨"},
            {"requirement_id": 11, "is_met": False, "reasoning": "근거를 찾지 못함"},
        ],
        model="gpt-4o-mini-2024-07-18",
    )

    def fake_post(url, headers=None, json=None, timeout=None):
        return _FakeResponse(200, body)

    monkeypatch.setattr("scoring.adapters.requests.post", fake_post)

    adapter = OpenAIScoringAdapter()
    output = adapter.score(_scoring_input(requirement_ids=[10, 11]))

    assert output.model_version == "gpt-4o-mini-2024-07-18"
    assert {v.requirement_id: v.is_met for v in output.verdicts} == {10: True, 11: False}
    assert all(v.reasoning for v in output.verdicts)


def test_score_reports_total_tokens_from_usage(monkeypatch):
    """강의실 채점 예산(#295)이 이 값에 기댄다 — 응답의 `usage.total_tokens`를
    그대로 옮겨 담는다."""

    body = _chat_completion_body([{"requirement_id": 10, "is_met": True, "reasoning": "ok"}])
    body["usage"] = {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    output = adapter.score(_scoring_input(requirement_ids=[10]))

    assert output.total_tokens == 120


def test_score_defaults_total_tokens_to_zero_when_usage_is_missing(monkeypatch):
    body = _chat_completion_body([{"requirement_id": 10, "is_met": True, "reasoning": "ok"}])

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    output = adapter.score(_scoring_input(requirement_ids=[10]))

    assert output.total_tokens == 0


# --- AC: 누락된 판정은 예외 — 「미충족」으로 조용히 채우지 않는다 -------------------


def test_missing_verdict_for_a_requirement_raises_not_silently_filled(monkeypatch):
    body = _chat_completion_body(
        [{"requirement_id": 10, "is_met": True, "reasoning": "ok"}]
        # requirement_id=11에 대한 판정이 아예 없다.
    )

    monkeypatch.setattr(
        "scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10, 11]))

    assert "11" in str(exc_info.value)


def test_duplicate_verdict_for_same_requirement_raises(monkeypatch):
    body = _chat_completion_body(
        [
            {"requirement_id": 10, "is_met": True, "reasoning": "a"},
            {"requirement_id": 10, "is_met": False, "reasoning": "b"},
            {"requirement_id": 11, "is_met": True, "reasoning": "c"},
        ]
    )

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError):
        adapter.score(_scoring_input(requirement_ids=[10, 11]))


def test_empty_reasoning_raises(monkeypatch):
    body = _chat_completion_body(
        [
            {"requirement_id": 10, "is_met": True, "reasoning": "   "},
            {"requirement_id": 11, "is_met": True, "reasoning": "ok"},
        ]
    )

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError):
        adapter.score(_scoring_input(requirement_ids=[10, 11]))


def test_non_boolean_is_met_raises(monkeypatch):
    body = _chat_completion_body(
        [
            {"requirement_id": 10, "is_met": "true", "reasoning": "ok"},
            {"requirement_id": 11, "is_met": True, "reasoning": "ok"},
        ]
    )

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError):
        adapter.score(_scoring_input(requirement_ids=[10, 11]))


def test_float_requirement_id_is_rejected_not_truncated(monkeypatch):
    """`int(10.9)`는 예외 없이 10을 돌려준다 — 강제 변환하면 이 응답이 실제로는
    requirement_id=10에 대한 답인지, 존재하지 않는 값을 잘못 준 것인지 구분할
    수 없게 되고, 중복·누락 검사를 그대로 통과해 percentage가 모델의 실제
    판정과 어긋난다(#88 코드리뷰 지적 3)."""

    body = _chat_completion_body(
        [
            {"requirement_id": 10.9, "is_met": True, "reasoning": "ok"},
            {"requirement_id": 11, "is_met": True, "reasoning": "ok"},
        ]
    )

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError):
        adapter.score(_scoring_input(requirement_ids=[10, 11]))


def test_boolean_requirement_id_is_rejected():
    """`bool`은 `int`의 서브클래스라 `isinstance(True, int)`가 참이고
    `int(True) == 1`이다 — requirement_id=1이 실재하면 그 판정을 덮어쓴다
    (#88 코드리뷰 지적 3)."""

    from scoring.adapters import _parse_openai_scoring_response

    body = {
        "model": "gpt-4o-mini",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "content": json.dumps(
                        {"verdicts": [{"requirement_id": True, "is_met": True, "reasoning": "ok"}]}
                    )
                },
            }
        ],
    }

    with pytest.raises(LLMAdapterError):
        _parse_openai_scoring_response(body, requirement_ids=[1], submission_id=1)


# --- AC: 잘리거나 깨진 응답은 소리 내어 실패한다 — 낮은 점수로 둔갑하지 않는다 -----


def test_truncated_response_raises_instead_of_scoring_low(monkeypatch):
    body = _chat_completion_body(
        [{"requirement_id": 10, "is_met": True, "reasoning": "ok"}],
        finish_reason="length",
    )

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    assert "length" in str(exc_info.value)
    # 잘린 응답은 다시 불러도 또 잘린다(같은 프롬프트·토큰 예산) — 자동 재시도
    # 대상이 아니라 LLMAdapterPermanentError여야 다음 스캔이 건너뛴다(#88 코드리뷰
    # 지적 2).
    assert isinstance(exc_info.value, LLMAdapterPermanentError)


def test_malformed_json_content_raises(monkeypatch):
    malformed_body = {
        "model": "gpt-4o-mini",
        "choices": [{"finish_reason": "stop", "message": {"content": "{not valid json"}}],
    }

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, malformed_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError):
        adapter.score(_scoring_input(requirement_ids=[10]))


def test_response_missing_choices_raises(monkeypatch):
    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, {"model": "gpt-4o-mini"}))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError):
        adapter.score(_scoring_input(requirement_ids=[10]))


def test_non_json_response_body_raises(monkeypatch):
    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, None))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError):
        adapter.score(_scoring_input(requirement_ids=[10]))


# --- 벤더 거부(4xx/5xx)와 네트워크 오류 --------------------------------------------


def test_non_200_status_raises_llm_adapter_error(monkeypatch):
    error_body = {"error": {"message": "rate limit exceeded", "type": "rate_limit_error"}}

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(429, error_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    assert "429" in str(exc_info.value)
    # 429(요금 한도)는 시간이 지나면 풀린다 — 영구 실패로 분류해 다음 스캔에서
    # 영원히 건너뛰면 안 된다(#88 코드리뷰 지적 2).
    assert not isinstance(exc_info.value, LLMAdapterPermanentError)


def test_400_status_raises_permanent_error(monkeypatch):
    error_body = {"error": {"message": "model not found", "type": "invalid_request_error"}}

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(400, error_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterPermanentError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    assert "400" in str(exc_info.value)


def test_401_status_raises_permanent_error(monkeypatch):
    error_body = {"error": {"message": "invalid api key", "type": "invalid_request_error"}}

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(401, error_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterPermanentError):
        adapter.score(_scoring_input(requirement_ids=[10]))


def test_500_status_does_not_raise_permanent_error(monkeypatch):
    error_body = {"error": {"message": "internal error", "type": "server_error"}}

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(500, error_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    assert not isinstance(exc_info.value, LLMAdapterPermanentError)


def test_vendor_error_field_as_plain_string_does_not_crash(monkeypatch):
    """프록시·게이트웨이가 `error`를 dict가 아니라 문자열로 주는 경우
    (`{"error": "Too Many Requests"}`) — `.get("message")`를 부르면 AttributeError가
    나서 "모든 실패는 LLMAdapterError"라는 모듈 계약을 깬다(#88 코드리뷰 지적 4)."""

    error_body = {"error": "Too Many Requests"}

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(503, error_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    # AttributeError가 아니라 LLMAdapterError여야 하고, 상태코드는 남아 있어야 한다.
    assert isinstance(exc_info.value, LLMAdapterError)
    assert "503" in str(exc_info.value)


def test_network_error_raises_llm_adapter_error(monkeypatch):
    import requests

    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("scoring.adapters.requests.post", raise_connection_error)

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    # 네트워크 순단은 다음 시도에서 결과가 달라질 수 있다 — 영구 실패가 아니다.
    assert not isinstance(exc_info.value, LLMAdapterPermanentError)


# --- AC: 제출 소스가 예외 메시지로 새지 않는다(ADR-0014) --------------------------


def test_source_never_leaks_into_exception_message_on_malformed_response(monkeypatch):
    malformed_body = {
        "model": "gpt-4o-mini",
        "choices": [{"finish_reason": "stop", "message": {"content": "{not valid json"}}],
    }

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, malformed_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    assert SECRET_SOURCE_MARKER not in str(exc_info.value)


def test_credential_never_leaks_into_exception_message_on_missing_verdict(monkeypatch):
    body = _chat_completion_body([])  # requirement_id=10에 대한 판정이 아예 없다.

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(200, body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    assert "sk-test-key-do-not-leak" not in str(exc_info.value)


def test_source_never_leaks_into_exception_message_on_http_error(monkeypatch):
    """벤더의 error.message는 자유 텍스트라 우리가 보낸 값을 반사할 수 있다
    (#88 코드리뷰 지적 5) — 그래서 마커를 error.message **안에** 심는다. 마커가
    다른 곳(예: 픽스처가 마커를 안 쓰는 곳)에만 있으면, 구현이 message를
    그대로 노출해도 이 테스트는 우연히 통과한다 — 그건 테스트가 아니다."""

    error_body = {
        "error": {
            "message": f"Invalid request — offending value: {SECRET_SOURCE_MARKER}",
            "type": "invalid_request_error",
        }
    }

    monkeypatch.setattr("scoring.adapters.requests.post", lambda *a, **k: _FakeResponse(400, error_body))

    adapter = OpenAIScoringAdapter()
    with pytest.raises(LLMAdapterError) as exc_info:
        adapter.score(_scoring_input(requirement_ids=[10]))

    assert SECRET_SOURCE_MARKER not in str(exc_info.value)


# --- AC: 배포 환경에서 자격증명이 없으면 부팅 자체가 거부된다(#83 부팅 가드) --------


def test_deployed_boot_check_rejects_openai_adapter_without_credential(monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)

    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True,
        LLM_ADAPTER_MODE="scoring.adapters.OpenAIScoringAdapter",
    ):
        errors = check_llm_adapter_mode(None)

    assert [e.id for e in errors] == ["core.E002"]


def test_deployed_boot_check_passes_when_openai_adapter_has_credential():
    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True,
        LLM_ADAPTER_MODE="scoring.adapters.OpenAIScoringAdapter",
    ):
        errors = check_llm_adapter_mode(None)

    assert errors == []
