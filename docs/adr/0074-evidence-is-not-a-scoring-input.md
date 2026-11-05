# 확인 위치(Evidence)는 판정 입력이 아니다 — 제출자가 개최자에게 주는 선택 안내

Status: Accepted (2026-11-05 결정)

ADR-0014 의 「각 Requirement 자가 응답에는 그것을 뒷받침하는 증거를 지정해야 하며, 증거가 없거나 소스에서 근거를
찾지 못한 항목은 미달로 처리한다」와 #259 의 「Evidence 종류별로 채점기가 확인하는 방법」을 대체한다. ADR-0014 의
나머지(소스를 제출 시점에 받는다, Award 전까지 Sponsor 에게 소스를 닫는다)와 ADR-0006(1회 채점·불변 스냅샷)은 그대로다.

## 맥락 (#909, 대표 실사용 피드백 3)

- 채점 프롬프트가 「(a) 연결된 Evidence 가 주장을 뒷받침하는지 … Evidence 가 없으면 반드시 미달」로 지시했다. 결과로
  기능을 다 만들어 낸 제출도 확인 위치를 비워 두면 필수 항목이 미달이 될 수 있었고, 화면은 「이대로 제출하면 미달로
  채점됩니다」로 제출자를 몰았다.
- 대표 의도: Evidence 는 **제출자가 개최자에게 「이 항목은 여기서 보세요」라고 알려 주는 선택 안내**다. 판정과 끊는다.
- 「근거」라는 말은 이미 AI 의 판정 근거(Score reasoning)와 완성도 근거를 가리킨다. Evidence 화면 이름까지 「근거」면
  「AI 판정에 쓰인다」는 인상이 남는다.

## 결정

1. **Score·완성도 프롬프트에 Evidence 를 싣지 않는다.** `scoring.services._build_prompt` 는 Requirement·자가 응답
   (참고용)·선별된 소스만 싣고, 「소스코드에 그 기능이 실재하는지로 판단, 자가 응답은 참고용, 소스에서 찾지 못하면
   미달」로 지시한다. Evidence 지시·구분자 언급·종류별 확인 문단·항목별 `Evidence` 줄을 걷었다.
   `core.llm_scoring.RequirementInput.evidence` 와 `_requirement_inputs` 의 Evidence prefetch 도 지웠다. 완성도
   (`scoring.quality`)는 Score 프롬프트의 제출물 절을 다시 쓰므로 함께 빠진다.
2. **회귀 시험으로 고정한다** — 같은 제출에 확인 위치를 붙였을 때와 뗐을 때 Score·완성도 프롬프트가 바이트 단위로
   같다(`test_check_locations_do_not_change_score_or_quality_prompt_by_a_single_byte`).
3. **흉내 채점기(`FakeLLMScoringAdapter`)는 Requirement 문구가 선별된 소스에 있으면 충족**으로 본다 — 강의실 흉내
   (`FakeClassroomScoringAdapter`)와 같은 규칙이다. 확인 위치가 없다고 자동 미달이 되지 않는다.
4. **화면 이름은 「확인 위치」**다 — 버튼·셈에 명사 하나로 붙는다(「+ 확인 위치 추가」, 「확인 위치 a/b」). 비어 있어도
   경고하지 않는다. 채움률은 계산을 그대로 두고 「채움률 N% — 확인 위치 a/b, 권장 자료 c/3」로 이름만 맞춘다.
5. **코드 식별자·DB·API 는 그대로** — `Evidence`, `evidence_*`, kind 값, 요청·응답의 `evidence` 필드. API 를 깨지 않는다.

## 결과

- 이미 만들어진 Score·완성도는 불변 스냅샷이라 옛 프롬프트(Evidence 포함)를 그대로 갖는다. 다시 채점하지 않는다.
- `core.prompt_safety.UNTRUSTED_BLOCK_MARKERS` 의 `<<<EVIDENCE_*>>>` 는 남긴다. 채점 프롬프트가 더는 만들지 않지만, 옛
  Score 프롬프트에 있는 구분자라 참가자 텍스트에 심어지면 계속 지운다 — 남겨 두는 값이 없다.
- 확인 위치가 판정과 무관해지면서 「체크만 채운 제출이 달성률 100%」를 막는 것은 오직 「소스에 실재하는가」다 —
  ADR-0014 가 소스를 받게 한 이유 그대로다.
