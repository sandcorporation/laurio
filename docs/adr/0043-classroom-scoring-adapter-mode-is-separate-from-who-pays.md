# 강의실 채점의 어댑터 모드는 "누구 키로 도는가"와 별개다

Status: Accepted (2026-09-11 결정)

## 문제

`classroom.scoring`(#287)은 강사 본인의 OpenAI 키로 돈다는 결정(CONTEXT.md 「Class」
— 플랫폼이 대신 내지 않는다) 때문에, 플랫폼의 `LLM_ADAPTER_MODE`/`core.llm_scoring.
get_adapter()`를 거치지 않고 `OpenAIScoringAdapter`를 매 채점마다 그 클래스의
복호화된 키로 직접 생성해 왔다. 이 결정 자체(누구 키로 도는가)는 맞다 — 문제는 그
직접 생성이 **환경과 무관하게 항상 실물 어댑터**였다는 것이다.

그 결과 dev·CI에는 강의실 채점을 돌릴 방법이 없었다: 가짜 키를 넣으면 그 키로 실제
OpenAI에 요청이 나가 401로 실패하고, 진짜 키를 넣으면 실제로 돈이 나간다. 2026-09-11
강의실 걷기에서 "제출 → 채점 완료 → 알림(#303) → 알림을 누르면 그 시도로(#329)"라는
흐름 하나를 에이전트의 브라우저 걷기로도 CI e2e로도 확인할 수 없었던 이유가 이것이다
— 다른 모든 화면은 걸어볼 수 있는데 채점만 항상 막혀 있었다.

## 결정

**"누구 키로 도는가"와 "그 키로 실제로 네트워크에 나가는가"를 서로 다른 축으로
가른다.** 후자에만 새 설정 `CLASSROOM_SCORING_ADAPTER_MODE`(#83과 같은 원칙 —
`core.adapters.check_adapter_mode`가 검증하는 fake-또는-dotted-path 값)를 둔다.

- 기본값 `fake`(배포되지 않은 환경) — `classroom.scoring.FakeClassroomScoringAdapter`를
  쓴다. 강사 키의 존재 여부는 여전히 확인하지만(`raw_key`가 비어 있으면 여전히
  `no_key`로 후보에서 빠진다 — "키가 없는 클래스는 채점되지 않는다"는 규칙은 이
  스위치가 건드리지 않는다) 그 값을 실제로 벤더에 보내지 않는다.
- 배포 환경(staging/production) — `config.settings`가 이 값이 fake면 부팅 자체를
  거부한다(다른 6개 `*_ADAPTER_MODE`와 같은 원칙, #83). 실제 값은
  `core.llm_scoring.OpenAIScoringAdapter`다 — **강사 본인의 키로 이 클래스를 그대로
  쓴다**, 바뀌는 것은 "쓰는가 마는가"가 아니라 "결정 시점에 어느 것을 골랐는지 부팅이
  검증하는가"다.

`LLM_ADAPTER_MODE`를 재사용하지 않는 이유: 그 값은 플랫폼(공모전) 자신의 자격증명
(`OPEN_AI_API_KEY`)에 묶인 스위치라, 강의실이 그 값을 공유하면 "공모전 채점을 fake로
돌리면서 강의실만 실물로 돌린다" 같은 조합을 표현할 수 없다. `LLM_REQUIREMENT_CHAT_
ADAPTER_MODE`가 이미 "같은 LLM, 다른 용도는 다른 설정 키"라는 전례를 세웠다(모듈
docstring) — 이번에도 같은 전례를 따른다.

## FakeClassroomScoringAdapter가 FakeLLMScoringAdapter를 재사용하지 않는 이유

`core.llm_scoring.FakeLLMScoringAdapter`의 결정성은 "Evidence가 소스에서 확인되는가"에
있다. 강의실 `RequirementInput`은 `evidence`가 항상 빈 리스트다(`_requirement_inputs`
— 강의실에는 자가 응답도 근거 연결도 없다, ADR-0042와 같은 전제). 그 어댑터를 그대로
쓰면 모든 체크리스트 항목이 항상 미달로 나와, "통과·미통과가 결정적으로 정해진다"는
AC를 만족시키지 못한다(둘 다 나올 수 있어야 결정적이라는 말이 뜻을 갖는다).

`FakeClassroomScoringAdapter`는 대신 체크리스트 항목의 문구(`RequirementInput.text`,
곧 `ChecklistItem.label`)가 제출된 소스에 그대로 등장하는지를 본다 — "소스 자체가
유일한 근거"라는 `classroom.scoring` 모듈 docstring의 원칙을, 강의실이 실제로 가진
텍스트(체크리스트 문구)로 흉내낸 것이다. 이 판정은 `ScoringInput.source_files`(이번에
비로소 채워 넣는다 — `OpenAIScoringAdapter`는 이 필드를 읽지 않으므로 실물 경로는
바뀌지 않는다)만 본다: `prompt`에는 체크리스트 문구 자체가 이미 나열돼 있어(`_build_
prompt`) 거기서 찾으면 소스 내용과 무관하게 항상 참이 되기 때문이다.

## Consequences

- dev·CI가 네트워크 없이 결정적으로 "제출 → 채점 완료 → 알림 → 알림 링크가 그
  시도로" 전체를 걸을 수 있게 됐다 — 이 ADR이 고치는 바로 그 결함.
- 배포 환경의 원칙은 한 글자도 바뀌지 않는다: 강사 본인의 키로 실물 OpenAI를 쓰고,
  키가 없는 클래스는 채점되지 않으며, fake 어댑터로 강의실 채점이 도는 경로는 배포
  환경에 존재하지 않는다(부팅 가드가 보증한다).
- 새 설정 값은 `core.adapters.check_adapter_mode`의 목록과 `CLAUDE.md`의 "열 값"
  문단에 함께 올라간다 — 다른 6개 어댑터 모드와 같은 감사 표면에 선다.
- 이 결정이 다시 열리는 것은 강의실이 강사 키가 아닌 다른 자격증명 모델로 옮길
  때다 — 그때는 "누구 키로 도는가" 축 자체가 바뀌므로 이 ADR의 전제가 무효가 된다.
