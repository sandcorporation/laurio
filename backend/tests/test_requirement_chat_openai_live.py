"""`contests.requirement_chat.OpenAIRequirementChatAdapter`가 실제 OpenAI를 치는
live 테스트 (#55).

`tests/test_scoring_openai_live.py`(#88)와 같은 원칙 — `tests/live.py`의 규율
그대로 **응답 값이 아니라 계약을 지키는가**만 본다:

- 첫 턴(막연한 한마디)에서도 500이 나지 않고 `reply`가 채워진다.
- 구체적인 발화를 주면 `proposed_requirements`에 최소 하나 이상의 제안이 온다.
- 실제로 호출에 쓰인 모델 식별자가 채워진다(OpenAI 응답의 "model" 필드).

`@live_vendor`라 기본 스위트에서 제외되고, `OPEN_AI_API_KEY`가 없으면 skip된다.
staging 서브 호스트가 아직 없어(#52) 이 테스트가 "staging에서 실제로 한 번
대화가 끝까지 도는 것을 확인"의 대체 증거다 — dev에서 실제 자격증명으로 직접
확인했다.
"""

from __future__ import annotations

from contests.requirement_chat import ChatTurn, ExistingRequirement, RequirementChatInput
from tests.live import live_vendor, require_live_credential


@live_vendor
def test_openai_requirement_chat_adapter_replies_to_a_vague_first_turn():
    require_live_credential("OPEN_AI_API_KEY")

    # 지연 임포트: OpenAIRequirementChatAdapter()가 생성 시점에 OPEN_AI_API_KEY를
    # 읽으므로, require_live_credential의 skip이 먼저 평가된 뒤에 임포트해야
    # 자격증명 없는 실행에서도 이 테스트 파일 자체는 수집(collect)이 깨지지 않는다.
    from contests.requirement_chat import OpenAIRequirementChatAdapter

    adapter = OpenAIRequirementChatAdapter()

    chat_input = RequirementChatInput(
        contest_id=1,
        contest_title="심야 배달 매칭 서비스",
        latest_message="뭘 만들어야 할지 아직 잘 모르겠어요.",
        history=[],
        existing_requirements=[],
    )

    output = adapter.respond(chat_input)

    assert output.reply.strip()
    assert output.model_version.strip()


@live_vendor
def test_openai_requirement_chat_adapter_proposes_requirements_for_a_concrete_turn():
    require_live_credential("OPEN_AI_API_KEY")

    from contests.requirement_chat import OpenAIRequirementChatAdapter

    adapter = OpenAIRequirementChatAdapter()

    chat_input = RequirementChatInput(
        contest_id=1,
        contest_title="심야 배달 매칭 서비스",
        latest_message=(
            "로그인 화면에 이메일/비밀번호 입력 필드가 있어야 하고, 다크 모드는 "
            "있으면 좋겠지만 필수는 아닙니다."
        ),
        history=[ChatTurn(role="sponsor", content="심야에 배달 기사와 주문을 매칭하는 서비스입니다.")],
        existing_requirements=[ExistingRequirement(text="회원가입 기능", grade="required")],
    )

    output = adapter.respond(chat_input)

    assert output.reply.strip()
    assert output.model_version.strip()
    assert isinstance(output.proposed_requirements, list)
    for proposal in output.proposed_requirements:
        assert proposal.text.strip()
        assert proposal.grade in ("required", "optional")
