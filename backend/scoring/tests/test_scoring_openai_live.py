"""`scoring.adapters.OpenAIScoringAdapter`가 실제 OpenAI를 치는 live 테스트 (#88).

`tests/test_live_adapters.py`가 이미 `OPEN_AI_API_KEY`로 인증만 확인했다 — 이
파일은 그 자격증명으로 채점 계약(`LLMScoringAdapter.score`) 자체를 실제 벤더에
대고 검증한다. 비결정적 출력이므로 `tests/live.py`의 원칙 그대로 **점수 값이
아니라 계약을 지키는가**만 본다(#88 AC):

- 요청에 실은 모든 requirement_id에 대해 판정이 정확히 하나씩 있다.
- 각 판정의 근거(reasoning)가 비어 있지 않다.
- 실제로 호출에 쓰인 모델 식별자가 채워진다(OpenAI 응답의 "model" 필드).

`@live_vendor`라 기본 스위트에서 제외되고, `OPEN_AI_API_KEY`가 없으면 skip된다.
"""

from __future__ import annotations

from scoring.adapters import RequirementInput, ScoringInput
from tests.live import live_vendor, require_live_credential


@live_vendor
def test_openai_scoring_adapter_returns_a_verdict_for_every_requirement():
    require_live_credential("OPEN_AI_API_KEY")

    # 지연 임포트: OpenAIScoringAdapter()가 생성 시점에 OPEN_AI_API_KEY를 읽으므로,
    # require_live_credential의 skip이 먼저 평가된 뒤에 임포트해야 자격증명 없는
    # 실행에서도 이 테스트 파일 자체는 수집(collect)이 깨지지 않는다.
    from scoring.adapters import OpenAIScoringAdapter

    adapter = OpenAIScoringAdapter()

    requirements = [
        RequirementInput(
            requirement_id=1,
            text="로그인 화면에 이메일/비밀번호 입력 필드가 있어야 한다",
            grade="required",
            self_reported_met=True,
        ),
        RequirementInput(
            requirement_id=2,
            text="다크 모드를 지원해야 한다",
            grade="required",
            self_reported_met=True,
        ),
    ]
    scoring_input = ScoringInput(
        submission_id=1,
        contest_id=1,
        prompt=(
            "당신은 Codemit 공모전 제출물을 채점하는 심사 보조자입니다. 각 Requirement에"
            " 대해 연결된 Evidence와 소스코드를 근거로 충족 여부를 판단하세요.\n\n"
            "## Requirements\n"
            "- [required] #1: 로그인 화면에 이메일/비밀번호 입력 필드가 있어야 한다\n"
            "  Evidence[source]: <<<EVIDENCE_START>>>login.py<<<EVIDENCE_END>>>\n"
            "- [required] #2: 다크 모드를 지원해야 한다\n"
            "  Evidence[source]: <<<EVIDENCE_START>>>(없음)<<<EVIDENCE_END>>>\n\n"
            "## Source (선별된 파일)\n"
            "### login.py\n"
            "<<<SOURCE_FILE_START>>>\n"
            "def render_login():\n"
            "    return '<input name=\"email\"><input name=\"password\" type=\"password\">'\n"
            "<<<SOURCE_FILE_END>>>\n"
        ),
        source_files=[],
        requirements=requirements,
    )

    output = adapter.score(scoring_input)

    verdict_ids = {v.requirement_id for v in output.verdicts}
    assert verdict_ids == {1, 2}
    assert all(isinstance(v.is_met, bool) for v in output.verdicts)
    assert all(v.reasoning.strip() for v in output.verdicts)
    assert output.model_version.strip()
