"""`contests.requirement_chat.OpenAIRequirementChatAdapter` 단위 테스트 (#55, ADR-0007/0014).

`tests/test_openai_scoring_adapter.py`와 같은 예외 — 이 파일도 HTTP를 거치지
않는다. django-ninja 라우터가 아니라 OpenAI 벤더 연동 파싱·검증 로직만 검증하며,
`requests.post`를 몽키패치해 벤더 응답을 흉내낸다. 실제 벤더를 치는 검증은
`tests/test_requirement_chat_openai_live.py`(옵인 `@live_vendor`)가 맡는다.

이 파일이 지키는지 확인하는 것 — #55 AC와, 모듈 독스트링이 설명하는 "채점과는
반대로 관대하게 파싱한다"는 설계 그대로:

- reply 문자열을 뽑아낼 수 있으면(JSON 파싱 성공·finish_reason == "stop") 형식을
  살짝 벗어난 부분(proposed_requirements 필드 누락·타입 불일치·개별 항목 결함)은
  예외 없이 건너뛰고 대화를 이어간다 — 화면이 죽지 않는다(#55 AC).
- reply 자체를 뽑아낼 수 없으면(JSON 아님·choices 없음·잘림·응답 없음) 예외가
  난다 — `contests.api.send_requirement_chat_message`가 이걸 잡아 사과 응답으로
  감성한다.
- 예외 메시지에 Sponsor 발화나 자격증명이 새지 않는다(ADR-0014).
- 자격증명이 없으면 어댑터 생성 자체가 거부된다(부팅 가드가 여기 기댄다, #83).
- 실제 호출에 쓰인 모델 식별자가 기록된다.
"""

from __future__ import annotations

import json

import pytest
from django.test import override_settings

from contests.checks import check_llm_requirement_chat_adapter_mode
from contests.requirement_chat import (
    ChatTurn,
    ExistingRequirement,
    OpenAIRequirementChatAdapter,
    RequirementChatAdapterError,
    RequirementChatInput,
)

SECRET_MESSAGE_MARKER = "__LAURIO_SPONSOR_MESSAGE_SECRET_MARKER__"


class _FakeResponse:
    def __init__(self, status_code: int, json_data) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.text = json.dumps(json_data) if json_data is not None else ""

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


def _chat_input(*, contest_id: int = 1, latest_message: str | None = None) -> RequirementChatInput:
    return RequirementChatInput(
        contest_id=contest_id,
        contest_title="심야 배달 매칭 서비스",
        latest_message=latest_message or f"로그인 기능이 필요합니다. {SECRET_MESSAGE_MARKER}",
        history=[ChatTurn(role="sponsor", content="시작합니다")],
        existing_requirements=[ExistingRequirement(text="다크 모드 지원", grade="optional")],
    )


def _chat_completion_body(
    reply: str | None,
    proposals,
    *,
    model: str = "gpt-4o-mini-2024-07-18",
    finish_reason: str = "stop",
    omit_reply: bool = False,
    omit_proposals: bool = False,
):
    content: dict = {}
    if not omit_reply:
        content["reply"] = reply
    if not omit_proposals:
        content["proposed_requirements"] = proposals
    return {
        "model": model,
        "choices": [
            {
                "finish_reason": finish_reason,
                "message": {"content": json.dumps(content)},
            }
        ],
    }


@pytest.fixture(autouse=True)
def _openai_api_key(monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", "sk-test-key-do-not-leak")


# --- 생성자 — 자격증명 -----------------------------------------------------------


def test_construction_raises_when_credential_is_missing(monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)

    with pytest.raises(RequirementChatAdapterError):
        OpenAIRequirementChatAdapter()


def test_construction_succeeds_with_credential():
    adapter = OpenAIRequirementChatAdapter()
    assert adapter.model_version  # 기본 모델명이 채워져 있다.


# --- 정상 경로 ---------------------------------------------------------------------


def test_respond_returns_reply_and_proposals_and_records_actual_model(monkeypatch):
    body = _chat_completion_body(
        "로그인 화면에 어떤 필드가 필요한가요?",
        [
            {"text": "이메일/비밀번호 로그인 지원", "grade": "required"},
            {"text": "다크 모드 지원(선택)", "grade": "optional"},
        ],
        model="gpt-4o-mini-2024-07-18",
    )

    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    adapter = OpenAIRequirementChatAdapter()
    output = adapter.respond(_chat_input())

    assert output.reply == "로그인 화면에 어떤 필드가 필요한가요?"
    assert [(p.text, p.grade) for p in output.proposed_requirements] == [
        ("이메일/비밀번호 로그인 지원", "required"),
        ("다크 모드 지원(선택)", "optional"),
    ]
    assert output.model_version == "gpt-4o-mini-2024-07-18"


def test_respond_sends_history_and_existing_requirements_in_prompt(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, _chat_completion_body("질문입니다", []))

    monkeypatch.setattr("contests.requirement_chat.requests.post", fake_post)

    adapter = OpenAIRequirementChatAdapter()
    adapter.respond(_chat_input())

    user_message = captured["payload"]["messages"][-1]["content"]
    assert "다크 모드 지원" in user_message  # 확정된 체크리스트가 프롬프트에 실린다.
    assert "시작합니다" in user_message  # 대화 이력이 프롬프트에 실린다.


# --- AC: 형식을 살짝 벗어나도 reply가 있으면 대화를 이어간다(예외를 던지지 않는다) --


def test_missing_proposed_requirements_field_falls_back_to_empty_list(monkeypatch):
    body = _chat_completion_body("네, 알겠습니다", None, omit_proposals=True)
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    assert output.reply == "네, 알겠습니다"
    assert output.proposed_requirements == []


def test_proposed_requirements_not_a_list_falls_back_to_empty_list(monkeypatch):
    body = _chat_completion_body("네, 알겠습니다", "이건 배열이 아니라 문자열입니다")
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    assert output.proposed_requirements == []


def test_malformed_proposal_items_are_skipped_not_raising(monkeypatch):
    body = _chat_completion_body(
        "몇 가지 제안을 정리했어요",
        [
            {"text": "정상 항목", "grade": "required"},
            "문자열 항목 — 객체가 아니다",
            {"grade": "required"},  # text 없음
            {"text": "   ", "grade": "required"},  # text가 공백뿐
            {"text": "grade가 이상함", "grade": 123},  # grade가 문자열이 아님
            None,
        ],
    )
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    assert output.reply == "몇 가지 제안을 정리했어요"  # 대화 자체는 살아남는다.
    texts = [p.text for p in output.proposed_requirements]
    assert "정상 항목" in texts
    assert "grade가 이상함" in texts  # text가 있으면 grade 결함만으로 항목 전체를 버리지 않는다.
    assert len(output.proposed_requirements) == 2


def test_empty_proposed_requirements_array_is_valid(monkeypatch):
    body = _chat_completion_body("추가로 제안할 게 없어요", [])
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    assert output.proposed_requirements == []


def test_overly_long_reply_is_truncated_not_raising(monkeypatch):
    huge_reply = "가" * 10_000
    body = _chat_completion_body(huge_reply, [])
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    assert len(output.reply) <= 4000


def test_too_many_proposals_are_capped_not_raising(monkeypatch):
    proposals = [{"text": f"항목 {i}", "grade": "required"} for i in range(20)]
    body = _chat_completion_body("많은 제안이 있어요", proposals)
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    assert len(output.proposed_requirements) <= 5


# --- reply 자체를 뽑을 수 없으면 예외 — 대화를 만들어낼 재료가 없다 -----------------


def test_missing_reply_field_raises(monkeypatch):
    body = _chat_completion_body(None, [], omit_reply=True)
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    with pytest.raises(RequirementChatAdapterError):
        OpenAIRequirementChatAdapter().respond(_chat_input())


def test_blank_reply_raises(monkeypatch):
    body = _chat_completion_body("   ", [])
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    with pytest.raises(RequirementChatAdapterError):
        OpenAIRequirementChatAdapter().respond(_chat_input())


def test_truncated_response_raises(monkeypatch):
    body = _chat_completion_body("잘린 응답", [], finish_reason="length")
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    with pytest.raises(RequirementChatAdapterError) as exc_info:
        OpenAIRequirementChatAdapter().respond(_chat_input())

    assert "length" in str(exc_info.value)


def test_malformed_json_content_raises(monkeypatch):
    malformed_body = {
        "model": "gpt-4o-mini",
        "choices": [{"finish_reason": "stop", "message": {"content": "{not valid json"}}],
    }
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, malformed_body)
    )

    with pytest.raises(RequirementChatAdapterError):
        OpenAIRequirementChatAdapter().respond(_chat_input())


def test_response_missing_choices_raises(monkeypatch):
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post",
        lambda *a, **k: _FakeResponse(200, {"model": "gpt-4o-mini"}),
    )

    with pytest.raises(RequirementChatAdapterError):
        OpenAIRequirementChatAdapter().respond(_chat_input())


def test_non_json_response_body_raises(monkeypatch):
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, None)
    )

    with pytest.raises(RequirementChatAdapterError):
        OpenAIRequirementChatAdapter().respond(_chat_input())


# --- 벤더 거부(4xx/5xx)와 네트워크 오류 — "재시도할 수 있다"(#55 AC)는 대화창에서 -----


def test_non_200_status_raises(monkeypatch):
    error_body = {"error": {"message": "rate limit exceeded", "type": "rate_limit_error"}}
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(429, error_body)
    )

    with pytest.raises(RequirementChatAdapterError) as exc_info:
        OpenAIRequirementChatAdapter().respond(_chat_input())

    assert "429" in str(exc_info.value)


def test_vendor_error_field_as_plain_string_does_not_crash(monkeypatch):
    error_body = {"error": "Too Many Requests"}
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(503, error_body)
    )

    with pytest.raises(RequirementChatAdapterError) as exc_info:
        OpenAIRequirementChatAdapter().respond(_chat_input())

    assert "503" in str(exc_info.value)


def test_network_error_raises(monkeypatch):
    import requests

    def raise_connection_error(*args, **kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr("contests.requirement_chat.requests.post", raise_connection_error)

    with pytest.raises(RequirementChatAdapterError):
        OpenAIRequirementChatAdapter().respond(_chat_input())


# --- AC: Sponsor 발화·자격증명이 예외 메시지로 새지 않는다(ADR-0014) ---------------


def test_sponsor_message_never_leaks_into_exception_message_on_http_error(monkeypatch):
    error_body = {
        "error": {
            "message": f"Invalid request — offending value: {SECRET_MESSAGE_MARKER}",
            "type": "invalid_request_error",
        }
    }
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(400, error_body)
    )

    with pytest.raises(RequirementChatAdapterError) as exc_info:
        OpenAIRequirementChatAdapter().respond(_chat_input())

    assert SECRET_MESSAGE_MARKER not in str(exc_info.value)


def test_credential_never_leaks_into_exception_message(monkeypatch):
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post",
        lambda *a, **k: _FakeResponse(200, {"model": "gpt-4o-mini"}),
    )

    with pytest.raises(RequirementChatAdapterError) as exc_info:
        OpenAIRequirementChatAdapter().respond(_chat_input())

    assert "sk-test-key-do-not-leak" not in str(exc_info.value)


# --- AC: 배포 환경에서 자격증명이 없으면 부팅 자체가 거부된다(#83 부팅 가드) --------


def test_deployed_boot_check_rejects_openai_adapter_without_credential(monkeypatch):
    monkeypatch.delenv("OPEN_AI_API_KEY", raising=False)

    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True,
        LLM_REQUIREMENT_CHAT_ADAPTER_MODE="contests.requirement_chat.OpenAIRequirementChatAdapter",
    ):
        errors = check_llm_requirement_chat_adapter_mode(None)

    assert [e.id for e in errors] == ["core.E002"]


def test_deployed_boot_check_passes_when_openai_adapter_has_credential():
    with override_settings(
        IS_DEPLOYED_ENVIRONMENT=True,
        LLM_REQUIREMENT_CHAT_ADAPTER_MODE="contests.requirement_chat.OpenAIRequirementChatAdapter",
    ):
        errors = check_llm_requirement_chat_adapter_mode(None)

    assert errors == []
