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

SECRET_MESSAGE_MARKER = "__CODEMIT_SPONSOR_MESSAGE_SECRET_MARKER__"


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


def test_grade_synonyms_are_normalized_to_canonical_values(monkeypatch):
    """벤더가 스키마의 enum(["required","optional"])을 어기고 대소문자·공백·한글
    표기로 돌려줘도(#55 코드리뷰 지적 1) `contests.api`의 required 폴백에 걸려
    선택 요건이 필수로 뒤집히면 안 된다 — 여기서 정규화한다."""

    proposals = [
        {"text": "A", "grade": "Required"},
        {"text": "B", "grade": " optional "},
        {"text": "C", "grade": "필수"},
        {"text": "D", "grade": "선택"},
        {"text": "E", "grade": "옵션"},
    ]
    body = _chat_completion_body("정리했어요", proposals)
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    grades = {p.text: p.grade for p in output.proposed_requirements}
    assert grades == {
        "A": "required",
        "B": "optional",
        "C": "required",
        "D": "optional",
        "E": "optional",
    }


def test_unmapped_grade_value_does_not_silently_become_required(monkeypatch):
    """매핑되지 않는 grade 값은 `contests.api`의 required 폴백과 반대 방향인
    optional로 떨어져야 한다 — required로 우연히 뒤집히면 선택 요건이 필수가
    되어 채점 백분율과 배분 컷라인이 흔들린다(#55 코드리뷰 지적 1)."""

    proposals = [
        {"text": "타입 이상함", "grade": 123},
        {"text": "값 이상함", "grade": "urgent"},
        {"text": "None", "grade": None},
    ]
    body = _chat_completion_body("정리했어요", proposals)
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    assert all(p.grade == "optional" for p in output.proposed_requirements)


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


def test_malformed_items_before_good_ones_do_not_starve_the_cap(monkeypatch):
    """불량 항목이 앞쪽에 몰려 있어도 뒤에 있는 멀쩡한 제안이 상한(5개)에 담겨야
    한다(#55 코드리뷰 지적 2) — 상한을 필터링 *전에* 적용하면 앞의 불량 항목들만
    세다가 뒤의 정상 제안은 아예 보지도 못하고 잘려나간다."""

    bad_items = [
        "문자열 항목",
        {"grade": "required"},  # text 없음
        {"text": "   ", "grade": "required"},  # 공백뿐
        None,
        {"text": "", "grade": "optional"},
    ]
    good_items = [{"text": f"정상 항목 {i}", "grade": "required"} for i in range(6)]
    body = _chat_completion_body("정리했어요", bad_items + good_items)
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    output = OpenAIRequirementChatAdapter().respond(_chat_input())

    texts = [p.text for p in output.proposed_requirements]
    assert len(texts) == 5
    assert texts == [f"정상 항목 {i}" for i in range(5)]


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


# --- 설정: 전용 temperature 키, max_tokens (#55 코드리뷰 지적 4·5) -----------------


def test_temperature_reads_dedicated_env_var_not_scoring_shared_one(monkeypatch):
    """`LLM_OPENAI_TEMPERATURE`(scoring과 공유)를 그릴이 함께 읽으면, 문서화된
    기본값 0.7이 compose의 `:-0` 고정 때문에 배포에서 절대 적용되지 않거나,
    반대로 grill 설정을 채점에 흘려보내면 채점이 비결정적이 되어 컷라인
    (ADR-0006)이 흔들린다(#55 코드리뷰 지적 4) — 전용 키로 분리한다."""

    monkeypatch.delenv("LLM_OPENAI_TEMPERATURE", raising=False)
    monkeypatch.delenv("LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE", raising=False)

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, _chat_completion_body("네", []))

    monkeypatch.setattr("contests.requirement_chat.requests.post", fake_post)

    # scoring 전용 키만 채워도 grill의 temperature는 바뀌지 않아야 한다(기본 0.7 유지).
    monkeypatch.setenv("LLM_OPENAI_TEMPERATURE", "0")
    OpenAIRequirementChatAdapter().respond(_chat_input())
    assert captured["payload"]["temperature"] == 0.7

    # grill 전용 키를 채우면 그 값이 반영된다.
    monkeypatch.setenv("LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE", "0.3")
    OpenAIRequirementChatAdapter().respond(_chat_input())
    assert captured["payload"]["temperature"] == 0.3


def test_request_payload_includes_max_tokens(monkeypatch):
    """max_tokens가 없으면 장황한 생성이 20초 타임아웃을 먼저 터뜨리고(과금은
    그대로 나가고) 재시도해도 같은 프롬프트라 재현된다(#55 코드리뷰 지적 5)."""

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, _chat_completion_body("네", []))

    monkeypatch.setattr("contests.requirement_chat.requests.post", fake_post)

    OpenAIRequirementChatAdapter().respond(_chat_input())

    assert isinstance(captured["payload"].get("max_tokens"), int)
    assert captured["payload"]["max_tokens"] > 0


# --- 대화 이력 상한 (#55 코드리뷰 지적 3) -------------------------------------------


def test_huge_history_does_not_balloon_the_prompt_sent_to_vendor(monkeypatch):
    """200턴 가드만으로는 gpt-4o-mini의 128k 컨텍스트를 지키지 못한다 — 이력이
    쌓일수록 프롬프트가 무한정 자라면 어느 순간부터 매 턴
    context_length_exceeded로 실패하고, 그 실패조차 이력에 쌓여 이력을 줄일
    경로가 없는 Contest는 AI grill이 영구히 죽는다(#55 코드리뷰 지적 3). 프롬프트
    문자 수 자체가 이력 크기와 무관하게 예산 안에 머물러야 한다."""

    from contests.requirement_chat import ChatTurn

    huge_history = [
        ChatTurn(role="sponsor" if i % 2 == 0 else "assistant", content="가" * 2000)
        for i in range(200)
    ]

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, _chat_completion_body("네", []))

    monkeypatch.setattr("contests.requirement_chat.requests.post", fake_post)

    chat_input = _chat_input()
    chat_input = RequirementChatInput(
        contest_id=chat_input.contest_id,
        contest_title=chat_input.contest_title,
        latest_message=chat_input.latest_message,
        history=huge_history,
        existing_requirements=chat_input.existing_requirements,
    )

    OpenAIRequirementChatAdapter().respond(chat_input)

    user_message = captured["payload"]["messages"][-1]["content"]
    # 200턴 * 2000자 = 40만자를 그대로 실었다면 이 상한을 훌쩍 넘는다.
    assert len(user_message) < 100_000


def test_select_recent_history_keeps_most_recent_turn_even_if_it_alone_exceeds_budget():
    from contests.requirement_chat import ChatTurn, _select_recent_history

    huge_turn = ChatTurn(role="sponsor", content="가" * 1_000_000)
    selected, omitted = _select_recent_history([huge_turn])

    assert selected == [huge_turn]
    assert omitted == 0


def test_select_recent_history_prefers_recent_turns_when_over_budget():
    from contests.requirement_chat import ChatTurn, _select_recent_history

    history = [ChatTurn(role="sponsor", content="가" * 2000) for _ in range(200)]
    selected, omitted = _select_recent_history(history)

    assert omitted > 0
    assert len(selected) < len(history)
    # 남은 턴은 항상 "가장 최근" 쪽이어야 한다 — 잘리는 건 오래된 쪽이다.
    assert selected == history[len(history) - len(selected):]


# --- 2차 코드리뷰: 확정 체크리스트도 예산에 넣는다 (#55 2차 코드리뷰 지적 1) --------


def test_huge_existing_requirements_does_not_balloon_the_prompt_sent_to_vendor(monkeypatch):
    """이력만 예산을 두고 확정 체크리스트(`existing_requirements`)에 상한이
    없으면, 이력 예산이 막으려던 바로 그 실패 모드(128k 컨텍스트 초과 -> 매 턴
    context_length_exceeded -> 사과 응답만 반복)가 다른 문으로 그대로 들어온다.
    `contests.api.add_requirement`에 개수 제한이 없으므로 어댑터 쪽에서 막아야
    한다."""

    from contests.requirement_chat import ExistingRequirement

    huge_existing = [
        ExistingRequirement(text=f"확정된 요건 {i} " + "가" * 480, grade="required")
        for i in range(300)
    ]

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, _chat_completion_body("네", []))

    monkeypatch.setattr("contests.requirement_chat.requests.post", fake_post)

    chat_input = _chat_input()
    chat_input = RequirementChatInput(
        contest_id=chat_input.contest_id,
        contest_title=chat_input.contest_title,
        latest_message=chat_input.latest_message,
        history=chat_input.history,
        existing_requirements=huge_existing,
    )

    OpenAIRequirementChatAdapter().respond(chat_input)

    user_message = captured["payload"]["messages"][-1]["content"]
    # 300개 * 약 500자 = 15만자를 그대로 실었다면 이 상한을 훌쩍 넘는다.
    assert len(user_message) < 100_000


def test_existing_requirements_budget_omission_is_visible_in_the_prompt(monkeypatch):
    """예산에 걸려 항목이 잘렸다면 그 사실이 프롬프트 문구에 드러나야 한다 —
    조용히 사라지면 AI가 왜 이미 확정된 항목을 다시 제안하는지 알 길이 없다."""

    from contests.requirement_chat import ExistingRequirement

    huge_existing = [
        ExistingRequirement(text=f"확정된 요건 {i} " + "가" * 480, grade="required")
        for i in range(300)
    ]

    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, _chat_completion_body("네", []))

    monkeypatch.setattr("contests.requirement_chat.requests.post", fake_post)

    chat_input = _chat_input()
    chat_input = RequirementChatInput(
        contest_id=chat_input.contest_id,
        contest_title=chat_input.contest_title,
        latest_message=chat_input.latest_message,
        history=chat_input.history,
        existing_requirements=huge_existing,
    )

    OpenAIRequirementChatAdapter().respond(chat_input)

    user_message = captured["payload"]["messages"][-1]["content"]
    assert "생략됨" in user_message


def test_select_requirements_within_budget_keeps_most_recent():
    from contests.requirement_chat import ExistingRequirement, _select_requirements_within_budget

    existing = [
        ExistingRequirement(text="요건 " + "가" * 400, grade="required") for _ in range(200)
    ]
    selected, omitted = _select_requirements_within_budget(existing)

    assert omitted > 0
    assert len(selected) < len(existing)
    assert selected == existing[len(existing) - len(selected):]


def test_select_requirements_within_budget_keeps_lone_huge_item():
    from contests.requirement_chat import ExistingRequirement, _select_requirements_within_budget

    huge = ExistingRequirement(text="가" * 1_000_000, grade="required")
    selected, omitted = _select_requirements_within_budget([huge])

    assert selected == [huge]
    assert omitted == 0


# --- 2차 코드리뷰: max_tokens가 자기 계산의 최악값보다 커야 한다 (지적 2) -----------


def test_max_tokens_exceeds_worst_case_reply_and_proposals_token_estimate():
    """reply(_MAX_REPLY_LENGTH) + proposals(_MAX_PROPOSALS_PER_TURN * 500자)를
    정상적으로 다 채우는 응답이 finish_reason="length"로 잘리면 안 된다 — 잘리면
    _MAX_REPLY_LENGTH의 사후 절단이 아니라 그 턴 전체가 예외로 죽는다(#55 2차
    코드리뷰 지적 2)."""

    from contests import requirement_chat as m

    worst_case_chars = m._MAX_REPLY_LENGTH + m._MAX_PROPOSALS_PER_TURN * 500
    # 한글 기준 1토큰≈1.5자로 보수적으로 잡은 최악값 — 코드리뷰가 지적한 계산과
    # 같은 추정치다.
    worst_case_tokens = worst_case_chars / 1.5

    assert m._OPENAI_MAX_TOKENS > worst_case_tokens


def test_request_payload_max_tokens_matches_module_constant(monkeypatch):
    captured = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResponse(200, _chat_completion_body("네", []))

    monkeypatch.setattr("contests.requirement_chat.requests.post", fake_post)

    OpenAIRequirementChatAdapter().respond(_chat_input())

    from contests.requirement_chat import _OPENAI_MAX_TOKENS

    assert captured["payload"]["max_tokens"] == _OPENAI_MAX_TOKENS


# --- 2차 코드리뷰: 매핑 안 되는 grade는 조용히 넘어가지 않는다 (지적 3) -------------


def test_unmapped_grade_logs_a_warning(monkeypatch, caplog):
    """방향(optional로 떨어뜨리기)은 타당하지만, 벤더가 응답 스키마의 enum을
    어기고 있다는 사실 자체는 로그로 남아야 한다 — 안 그러면 아무도 모른다."""

    body = _chat_completion_body(
        "정리했어요", [{"text": "필수 항목처럼 보이는데", "grade": "mandatory"}]
    )
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    with caplog.at_level("WARNING", logger="contests.requirement_chat"):
        OpenAIRequirementChatAdapter().respond(_chat_input())

    assert any("mandatory" in record.getMessage() for record in caplog.records)


def test_known_grade_values_do_not_log_a_warning(monkeypatch, caplog):
    body = _chat_completion_body(
        "정리했어요", [{"text": "정상", "grade": "required"}]
    )
    monkeypatch.setattr(
        "contests.requirement_chat.requests.post", lambda *a, **k: _FakeResponse(200, body)
    )

    with caplog.at_level("WARNING", logger="contests.requirement_chat"):
        OpenAIRequirementChatAdapter().respond(_chat_input())

    assert caplog.records == []


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
