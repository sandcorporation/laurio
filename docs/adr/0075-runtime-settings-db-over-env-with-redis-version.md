# 운영 설정 — 공모전 AI 키·모델 값은 DB 가 env 를 이기고, Redis 버전 번호로 재시작 없이 퍼진다

Status: Accepted (2026-11-05 결정)

## 맥락

- 공모전 AI(채점·완성도·요구사항 대화)의 플랫폼 키 `OPEN_AI_API_KEY` 와 모델·temperature 는 운영 `.env` 에만
  있었다. 키를 바꾸려면 대장이 서버 `.env` 를 고치고 컨테이너를 다시 띄워야 했다.
- 대표 지시(2026-11-05): 이 값들을 Operator 화면에서 넣고 바꾸고, 바꾼 값은 **재시작 없이** 모든 프로세스에
  곧바로 반영한다.
- 값을 읽는 프로세스가 여럿이다 — gunicorn 워커 여럿, celery-worker(beat 포함), grader, events. `CACHES["default"]`
  는 LocMem 이라 프로세스마다 따로다. 같은 `x-backend-env` Redis(`SESSION_REDIS_URL`, DB 1)는 모두가 본다.

## 결정

1. **저장.** `policies.RuntimeSetting`(키→값, 단일 키당 한 행)과 append-only `policies.RuntimeSettingChange`.
   비밀(`OPEN_AI_API_KEY`)은 `core.crypto`(Fernet, `VERIFICATION_ENCRYPTION_KEY`)로 암호화한 토큰만 둔다 —
   **새 암호화 키를 만들지 않는다**(키가 하나 늘면 배포 부팅 검사·백업 복원·회전 절차가 함께 는다). 화면에 보일
   끝 4자리는 `last4` 에 따로 둔다(12자보다 짧은 값은 끝자리를 보이지 않는다). 이력은 누가·언제·어느 설정·
   (비밀이면) 끝 4자리 표시 변화만 남긴다.
2. **우선순위.** DB 에 행이 있으면 그 값, 없으면 지금까지의 env 값. 배포 직후 표가 비어 있으면 운영 동작은 그대로다.
   `.env` → DB 옮기기 스크립트는 두지 않는다. 「지우기」는 행을 지워 env 로 돌아간다.
3. **캐시·무효화 — Redis 버전 번호 + 프로세스 내 캐시.** 프로세스마다 DB 값을 메모리에 쥐고, 읽을 때마다
   Redis 의 정수 하나(`codemit:runtime-settings:version`)만 본다. 쥔 버전과 같으면 메모리 값, 다르면 DB 를 다시
   읽는다. 저장·지우기는 트랜잭션이 커밋된 뒤(`on_commit`) 버전을 `INCR` 한다.
   - Redis 를 못 읽으면 30초(`FALLBACK_TTL_SECONDS`) 동안 쥔 값을 쓰고 그 뒤 DB 를 다시 본다. 그 30초 동안 Redis
     를 다시 두드리지 않는다(연결 상한 0.3초가 요청마다 쌓이지 않게).
   - Redis 가 읽혀도 60초(`MAX_AGE_SECONDS`)가 지나면 DB 를 다시 본다 — 버전을 올리던 순간 Redis 가 끊겼거나
     Redis 가 비워져 버전이 되돌아간 경우의 상한이다. 프로세스 하나에 1분에 한 번 작은 SELECT 하나다.
   - DB 를 못 읽으면(마이그레이션 전·연결 실패) 쥔 값, 없으면 env 로 물러난다. 요청을 깨지 않는다.
   - 비동기 문맥(이벤트 루프 안)에서는 ORM 을 부르지 않고 쥔 값·env 를 쓴다.
   - pytest 에는 Redis 가 없어 `RUNTIME_SETTINGS_VERSION_STORE=memory`(프로세스 안 흉내)를 쓴다.
4. **AI 클라이언트.** `core.llm_scoring.OpenAIScoringAdapter`(공모전, `product="contest"`)와
   `contests.requirement_chat.OpenAIRequirementChatAdapter` 가 env 대신 `policies.runtime_settings.setting_value`
   를 거친다. 두 어댑터는 원래 호출마다 새로 만들어지고(`get_adapter`·`get_requirement_chat_adapter`, 전역·
   `lru_cache` 없음) 키를 생성자에서 읽으므로 celery·grader 같은 오래 사는 프로세스도 다음 호출부터 새 키다.
   **강의실(`product="classroom"`)은 읽지 않는다** — 강사 BYOK 키·모델을 인자로 받고 나머지는 지금처럼 env 다.
5. **화면으로 옮긴 것**: `OPEN_AI_API_KEY`(비밀)·`LLM_OPENAI_MODEL`·`LLM_OPENAI_TEMPERATURE`·
   `LLM_REQUIREMENT_CHAT_OPENAI_TEMPERATURE`. **더 옮긴 한도·주기 값은 없다** — 후보(`SAFE_OUTBOUND_*`·
   `CLASSROOM_GRADER_*`)는 강의실 grader 와 바깥 호출 전체에 걸려 이 티켓의 범위(공모전 AI) 밖이고, 공모전 AI 의
   타임아웃(20초)은 env 가 아니라 코드 상수다.
   **넣지 않는 것**: DB·Redis 접속, 시크릿·서명·암호화 키, OAuth·결제·웹훅 비밀, 도메인·Origin·쿠키(바뀌면
   프로세스가 다시 떠야 하거나, 화면에서 바뀌면 그 화면 자체를 잠글 수 있다), 어댑터 모드(`*_ADAPTER_MODE` —
   배포 부팅 검사가 있다), 제품 스위치(`CODEMIT_CONTEST_PRODUCT_ENABLED`·`CODEMIT_PAID_CONTEST_PRODUCT_ENABLED`
   — 배포·법무 결정에 묶여 있다).
6. **API·권한.** `/api/operator/runtime-settings`(GET, 일반 등급도), `/changes`(GET), `/{key}`(POST 저장),
   `/{key}/clear`(POST), `/{key}/test`(POST 연결 시험). 쓰기는 `SuperuserOperatorAuth`. 응답에는 `configured`·
   끝 4자리·출처(db·env·none)·기본값·변경 시각·변경자만 나간다. 비운 입력의 저장은 기존 값을 유지한다.
   연결 시험은 강의실 키 확인과 같은 왕복(`/v1/models`)이고 결과 낱말(ok·invalid_key·unavailable)만 돌려준다.
   `LLM_ADAPTER_MODE` 가 fake 면 흉내(`sk-` 로 시작하는 20자 이상만 통과)다.
7. **새는 길.** 입력 스키마는 제약 없는 문자열이다 — 검증 422 가 입력 원문을 되싣지 않게 모양 검사는 서비스가
   원문 없는 문구로 한다. 로그에는 키 이름·운영자 id 만 쓴다. Sentry 는 이미 요청 본문을 보내지 않는다
   (`max_request_body_size="never"`, `scrub_secrets` 가 `request.data` 를 지운다).

## 고른 이유와 버린 것

- **LocMem `default` 캐시**: 워커마다 갈려 저장한 워커 말고는 옛 값이 남는다. 버렸다.
- **Redis 에 값 자체를 캐시**: 복호화한 키가 Redis 에 평문으로 앉거나, 암호문을 두면 결국 프로세스마다 복호화한다.
  버전 번호 하나면 Redis 에는 비밀이 오지 않는다.
- **pub/sub 으로 무효화 신호**: 구독 스레드를 프로세스마다(gunicorn sync 워커·grader·celery) 띄워야 하고, 끊긴
  동안의 신호는 잃는다. 버전 번호는 읽을 때 확인하므로 놓칠 신호가 없다.
- **TTL 만**: 짧게 잡으면 요청마다 DB, 길게 잡으면 「곧바로 반영」이 깨진다.

## 결과

- 대장은 키를 Operator 「운영 설정」(`/settings`)에서 바꾼다. `.env` 는 폴백으로 남는다.
- 배포 직후 표는 비어 있고 공모전 AI 는 `.env` 키로 그대로 돈다.
- 받아들임 시험: `backend/tests/test_runtime_settings.py`, `operator/lib/runtime-settings/view.test.ts`,
  `frontend/e2e/operator/runtime-settings.spec.ts`.
