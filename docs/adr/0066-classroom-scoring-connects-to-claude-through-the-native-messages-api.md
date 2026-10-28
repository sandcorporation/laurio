# 강의실 채점 연결에 「Claude(Anthropic) 키」를 더하고, 호환 주소가 아니라 네이티브 Messages API 의 구조화 출력으로 판정을 받는다

Status: Accepted (2026-10-28 결정)

## 맥락 (#795)

강의실 채점 연결은 「OpenAI 키」(#284)와 「호환 서버」(#601, ADR-0058) 둘이었다. 사용자는 Claude Max
플랜에 붙은 Anthropic API 조직 크레딧으로 강의실 채점을 돌리기로 했다(2026-10-28).

가장 적게 바꾸는 길은 Anthropic 의 OpenAI 호환 주소(`https://api.anthropic.com/v1/`)를 「호환 서버」로
넣는 것이다. 그러나 그 호환 층은 `response_format` 의 `json_schema` 를 무시한다 — 채점의 규율(요청한
모든 체크리스트 항목에 판정이 하나씩, 정수 id·불리언·근거 문자열)을 모델이 지키리라는 보장이 없어지고,
형식을 못 지킨 응답은 실패 시도가 되어 참여자의 자동 미달 한도를 깎는다. 호환 서버의 모델 시험
호출(#602)이 거르기는 하겠지만, 거르는 것과 지키게 하는 것은 다르다.

## 결정

- **세 번째 연결 종류 `anthropic_key`** — `Class.ScoringConnectionKind.ANTHROPIC_KEY`. 저장은 OpenAI 키와
  같은 칸(`openai_api_key_encrypted`·`_last4`·`_status`)과 같은 규율이다: 소유자 전용(ADR-0055), `core.crypto`
  암호화, 끝 네 자리만 보인다, 저장 전 `GET /v1/models`(헤더 `x-api-key`, `anthropic-version: 2023-06-01`)로
  한 번 확인해 401·403 만 거절하고 닿지 못하면 「미검증」으로 저장한다(#681). 소유권 이전은 키를 비우고
  연결을 「OpenAI 키」로 돌린다 — 호환 서버와 같다. 엔드포인트는 `PUT /classes/{id}/anthropic-key`.
- **네이티브 Messages API 에 구조화 출력** — `POST /v1/messages` 에 `output_config.format =
  {"type": "json_schema", "schema": <OpenAI 와 같은 판정 스키마>}`. 2026-10-28 에 공식 문서
  (https://platform.claude.com/docs/en/build-with-claude/structured-outputs)를 읽어 정했다: GA 필드라
  베타 헤더가 없고(예전 `output_format` + `structured-outputs-2025-11-13` 은 폐기 예정), 객체마다
  `additionalProperties: false` 를 요구하며, Haiku 5.5·Sonnet 5.5·Sonnet 5·Sonnet 4.6 이 지원한다.
  **`tool_choice` 로 도구 하나를 강제하는 길은 쓰지 않는다** — Sonnet 5.5 는 강제 도구 사용(`tool`·`any`)을
  400 으로 거절한다(https://platform.claude.com/docs/en/api/errors 「Forced tool use not supported」).
  응답의 판정 JSON 은 사고 블록 뒤의 text 블록에 오므로 type 으로 찾고, `stop_reason` 이 `end_turn` 이
  아니면(`max_tokens`·`refusal`) 판정으로 쓰지 않는다(OpenAI 의 `finish_reason != "stop"` 과 같은 규율).
  판정 검증은 OpenAI 와 같은 함수(`core.llm_scoring.verdicts_from_content`)다.
- **어댑터는 따로, 스위치는 하나** — `core.llm_scoring_anthropic.AnthropicScoringAdapter`(동기 `score`·grader 의
  비동기 `score_async`·`check_key`). `CLASSROOM_SCORING_ADAPTER_MODE` 는 지금처럼 「실제로 나가는가」만 가른다:
  fake 면 연결 종류와 무관하게 fake 어댑터(ADR-0043), 아니면 연결 종류가 벤더를 고른다
  (`classroom.scoring._scoring_adapter`). 배포 env 에 새 값이 없다.
- **오류는 기존 갈래로** — 401·403 → 키 거부, 404 → 모델 거부, 402 `billing_error`·400 의 「You have reached
  your specified … API usage limits」·「credit balance」·429 의 `error.details.error_code ==
  "enforced_spend_limit_reached"` → 크레딧 소진(채점이 멈추고 소유자에게 알린다, #586), 그 밖의 429·529
  `overloaded_error` → 빈도 제한, 그 밖의 4xx → 영구 실패, 5xx·네트워크 → 일시 실패.
  (https://platform.claude.com/docs/en/api/errors · https://platform.claude.com/docs/en/api/rate-limits)
  `error.message` 는 가르는 데에만 읽고 예외 메시지에 싣지 않는다(ADR-0014).
- **모델은 Haiku·Sonnet 계열만, 기본은 Haiku** — `/v1/models?limit=1000` 의 `line`(haiku·sonnet)과
  `capabilities.structured_outputs`·`capabilities.effort` 로 거른다(문서가 id 로 계열을 추측하지 말라고
  한다). Opus 는 비용 때문에 뺀다. 기본은 `claude-haiku-5-5`, 목록을 못 읽으면 Haiku 5.5·Sonnet 5.5 두 줄.
  키를 저장할 때 기본 모델이 OpenAI 이름이면 Haiku 로 옮긴다(그 반대도).
- **추론 강도는 싣는다** — 이슈는 「확장 사고를 쓰지 않으면 싣지 않음」을 기본안으로 뒀지만, 문서를 보니
  Haiku 5.5·Sonnet 5.5 는 사고(adaptive thinking)가 **기본으로 켜져 있고** Sonnet 5.5 는 끌 수도 없다
  (https://platform.claude.com/docs/en/build-with-claude/thinking). 싣지 않으면 벤더 기본 강도(Haiku
  `medium`, Sonnet `high`)로 생각한 만큼이 출력 토큰으로 청구된다. 그래서 모든 Claude 채점 모델을 추론
  모델로 보고 강의실의 「추론 강도」(기본 「낮음」)를 `output_config.effort` 로 싣는다 — 강사가 비용 손잡이를
  쥔다. `max_tokens` 는 사고까지 함께 세므로 32,000 으로 넉넉히 둔다(상한일 뿐 쓴 만큼만 청구된다).
  `temperature` 는 싣지 않는다.
- **비용** — `classroom.scoring_cost.PRICES` 에 공식 가격표(https://platform.claude.com/docs/en/about-claude/pricing,
  2026-10-28)의 단가: Haiku 5.5 $0.10/$0.50(프롬프트 10만 토큰 초과면 그 호출 전체 5배), Sonnet 5.5·5 $2/$10,
  Sonnet 4.6 $3/$15. 출력 어림은 OpenAI 추론 모델과 같은 강도별 상수다. 사용량은 응답의 `usage`
  (입력은 캐시 읽기·쓰기까지 더해)로 센다.

## 결과

- 호환 서버로 Anthropic 을 넣는 길은 막지 않지만 권하지 않는다 — 판정 형식이 보장되지 않는다.
- 제출 소스가 Anthropic(미국)으로 나가는 새 길이 생겼다. 개인정보처리방침 5·6절은 아직 OpenAI 만 적는다 —
  연결을 고르는 화면(#796)이 열리기 전에 더해야 한다(`docs/legal/README.md` 열린 항목 15).
- 실물 Anthropic 을 치는 live 시험은 두지 않았다 — 시험은 fake 스위치와 문서 예시 모양의 녹화 응답으로 돈다.
