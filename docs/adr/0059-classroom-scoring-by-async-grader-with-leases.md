# 강의실 채점은 임대로 집고 잠금 없이 기다리는 상주 grader 가 한다

Status: Accepted (2026-10-07 결정)

이 결정은 #584 에서 내렸고 ADR-0056 의 「채점은 Celery 워커 안에서」를 잇는다(채점하는 길만 바꿨고, 내부 HTTP 를 거치지 않는다는 판단·벤더 3분은 그대로다).

ADR-0056 은 강의실 채점을 Celery 태스크 하나로 옮겨 벤더를 3분까지 기다리게 했다. 그 모양에는
한계가 있었다(#582 에서 알게 된 제약): `_score_one` 이 **행 잠금 트랜잭션을 쥔 채** 벤더를
기다린다. 채점 워커 동시성 8 이면 풀러(pgbouncer)의 서버 연결 20 중 8 을 최대 3분씩 쥔다. 동시성을
수십~수백으로 올리면 풀이 바로 마른다. prod Postgres 는 `idle_in_transaction_session_timeout`·
`statement_timeout` 이 0(꺼짐), `max_connections` 100 이다.

**채점하는 길은 `manage.py grader` 상주 프로세스 하나다.** 통째로 바꿨다.

- **DB 가 큐다.** 즉시 채점과 60초 스캔은 「큐에 넣은 시각」(`ClassroomSubmission.scoring_queued_at`)
  만 찍는다(`classroom.scoring.enqueue_scoring`, 시각이 비었을 때만). 브로커도 채점 큐도 없다.
  `celery-scoring` 서비스와 큐 `classroom-scoring`, 태스크 `classroom.score_attempt` 는 걷었다.
  grader 가 0.5초마다 큐에 있는 후보를 읽는다(스캔과 같은 후보 조건 `pending_scoring`).
- **임대로 집고 잠금 없이 기다린다.** ① 조건부 UPDATE 하나(`claim_attempt`)로 시도에 「누가
  (`scoring_lease_owner`)·언제까지(`scoring_lease_until`)」 임대를 찍는다 — 큐에 있고, 채점되지
  않았고, 임대가 비었거나 만료됐을 때만. 자동 커밋이라 짧다. ② 벤더를 비동기 HTTP 로 부른다 — 이
  동안 DB 연결도 트랜잭션도 행 잠금도 없다. ③ `conclude_scoring` 이 행을 잠그고 **임대가 아직 내
  것인지** 확인한 뒤 결과를 쓰고 임대를 놓는다 — 짧은 트랜잭션 하나.
- **「두 번 불러도 벤더 한 번」은 임대가 지킨다.** 둘이 동시에 집으려 해도 UPDATE 에 이기는 쪽은
  하나다. 전에는 같은 보장을 행 잠금(`select_for_update(skip_locked)`)이 벤더 호출 내내 쥐고
  있어서 지켰다. 임대가 만료돼(grader 가 죽거나 너무 늦었다) 다른 grader 가 집은 뒤에 앞 grader 의
  결과가 도착하면 ③의 확인에서 걸려 **버려진다**(`lease_lost`) — 벤더 비용은 났지만 `ClassroomScore`
  는 하나다.
- **임대 시간 = 벤더 180초 + 여유 60초**(`SCORING_LEASE`, 240초). grader 가 죽으면 이 시각이 지난 뒤
  다시 줍힌다. 전에 큐 창 5분이 하던 일(잃은 태스크 되찾기)을 임대 만료가 한다. 실패한 시도는
  처리를 마치며 큐 시각과 임대를 같은 트랜잭션에서 비워, 다음 60초 스캔 tick 에 다시 큐에 들어간다
  (전과 같은 간격).
- **동시성: 전역 64 + 채점 연결(클래스)당 8**, 설정값(`CLASSROOM_GRADER_GLOBAL_LIMIT`·
  `CLASSROOM_GRADER_PER_CONNECTION_LIMIT`)이고 grader 프로세스 안의 상한이다 — grader 는 하나만
  띄운다. 벤더를 기다리는 것은 코루틴이라 64건이 스레드 64개가 아니다. DB 일은 작은 스레드 풀
  (16)에서 하고 그때마다 연결을 닫는다. 한 클래스의 줄이 다른 클래스를 굶기지 않도록, 상한에 닿은
  클래스는 후보 조회에서 뺀다. 속도 제한 429 는 #586 규칙 그대로다(60번까지 실패로 안 센다).
- **임대가 닳지 않게.** 임대는 집는 순간부터 가므로 소스 준비(저장소 clone)·스레드 대기가 길면 벤더를
  기다리기 전에 닳을 수 있다. 그래서 grader 는 자기가 처리 중인 시도를 후보에서 빼고(만료돼도 자기 것을
  다시 집지 않는다), **벤더를 부르기 직전에 임대를 다시 늘린다**(`extend_lease`, 내 임대일 때만 조건부
  UPDATE — 실패하면 벤더를 부르지 않는다).
- **DB 연결은 정확히 하나다**(사용자 결정). DB 일은 스레드 하나(`grader-db`)에서만 하고 그 스레드가
  Django 연결 하나를 계속 쥔다 — 작업마다 닫지 않고, 작업 **전**에 `close_old_connections()` 로 죽은
  연결을 걷고, `OperationalError`/`InterfaceError` 면 닫고 한 번 다시 한다. 그 스레드에는 짧은 DB 일만
  둔다: 알림이 내는 실시간 신호(Redis)는 `core.events.collect_instead_of_publishing` 으로 커밋 뒤에
  모아 별도 작은 풀(`grader-events`)에서 보낸다. 소스 준비는 앞(DB)·뒤(소스) 절반으로 갈라, 뒤 절반
  (clone·스토리지·문법 검사)은 **DB 를 쓰지 않는** 소스 풀(`CLASSROOM_GRADER_SOURCE_THREADS` 기본 8)에서
  돈다 — 시험이 「DB 스레드 밖 쿼리 0번·연결 1개」를 못 박는다. 상주 루프는 결과를 쌓지 않는다.
- **잠긴 행을 기다리지 않는다**(전환·롤백 리허설). DB 스레드가 하나뿐이라 잠금 대기 하나가 grader 전체를
  멈춘다 — 옛 채점 워커가 벤더를 기다리며 행 잠금을 쥔 동안 grader 의 임대 UPDATE 가 몇 분 서 있었다.
  임대 집기는 `SELECT … FOR UPDATE SKIP LOCKED`(그 행만) 후 UPDATE 라 잠긴 행을 건너뛰고(다음 바퀴에 다시),
  임대 연장·결과 쓰기는 트랜잭션 안의 `lock_timeout`(`CLASSROOM_GRADER_LOCK_TIMEOUT_MS` 2초)에 걸리면
  연장은 `False`, 결과 쓰기는 `lock_busy` 를 돌려주고 grader 가 임대가 내 것인 동안 같은 결과를 다시 쓴다
  (`CLASSROOM_GRADER_LOCK_RETRY_SECONDS` 30초 — 그 사이 DB 스레드는 다른 시도를 처리한다). 그래도 못 쓰면
  결과를 버리고 임대 만료 뒤 다시 줍는다.
- **바깥으로 나가는 응답은 상한이 있다.** 본문은 조각으로 읽어 `SAFE_OUTBOUND_RESPONSE_MAX_BYTES`(2MB)를
  넘으면 끊고(`RESPONSE_FAILED` — 닿았으니 연결 불가가 아니다, 동기·비동기 둘 다), 연결 단계는 전체
  타임아웃과 따로 `SAFE_OUTBOUND_CONNECT_TIMEOUT_SECONDS`(10초)다. 배포 grader 에는 `mem_limit: 1g` 가 있다.
- **벤더 호출은 비동기 HTTP(aiohttp)다 — OpenAI 도 호환 서버도.** 호환 서버는 `core.safe_outbound`
  의 보장을 비동기에서도 그대로 지킨다(`SafeOutbound.arequest`): 풀어서 확인한 IP 로만 연결하는
  리졸버(연결기가 이름을 다시 풀지 못한다), 원래 이름으로 SNI·인증서 검증, 리다이렉트 안 따라감,
  환경 프록시 안 탐, 주소 풀기·공인 판정·CA 갈아끼우기. 공모전 채점은 동기 `requests` 어댑터를 그대로
  쓴다(`OpenAIScoringAdapter.score`) — 같은 어댑터에 `score_async` 가 더해졌고 요청 모양·응답 분류는
  같은 함수를 쓴다.
- **SIGTERM** 이면 새 후보를 그만 잡고 하던 채점은 끝낸다(`stop_grace_period` 4분 — 임대 시간과
  같다). 죽으면 임대 만료 뒤 다시 줍힌다.
- **dev·CI 도 grader 를 띄운다**(운영과 같은 길). dev compose·CI 의 e2e 스택에 `grader` 서비스가
  있고, 제출 뒤 0.5초 안에 줍는다. pytest 는 상주 프로세스가 없으므로 `CLASSROOM_GRADER_INLINE`
  이 켜져 큐에 넣는 자리에서 한 시도를 같은 세 걸음(임대·준비·결과)으로 동기 채점하고(벤더만 동기
  길), grader 의 「한 바퀴」(`classroom.grader.run_round`)가 비동기 길을 시험한다.
- **배포는 검증 뒤에.** 이 PR 은 `hold` 라벨로 열려 병합 큐가 데려가지 않는다 — 사람이 dev 에서 검증한
  뒤 뗀다. 배포의 첫 실행은 옛 `celery-scoring` 컨테이너(compose 에서 사라져 고아가 된다)를 4분 기다려
  멈추고 지운 뒤 grader 를 띄운다(`deploy.sh` `retire_scoring_worker`).

## 고려한 대안

- **채점 워커 동시성만 올린다.** 행 잠금 트랜잭션을 벤더 호출 내내 쥐는 모양이라 풀이 마른다.
- **Celery gevent/asyncio 풀.** 태스크 안에서 여전히 트랜잭션을 쥔다. 잠금을 풀어야 하는 것은 같다.
- **Redis 에 큐·임대를 둔다.** 임대와 결과 쓰기를 한 DB 에서 다루는 편이 「임대가 아직 내 것인가」를
  한 트랜잭션으로 확인하기 쉽다. 브로커를 하나 덜 믿는다.

## 알아 둘 것

- 지표는 #585 가 붙인다 — 여기서는 시도마다 로그 한 줄(`grader: submission=… status=…`)이다.
- 연결당 상한은 프로세스 안의 값이라 grader 가 둘 뜨면 곱절이다. 「벤더 한 번」은 그대로 임대가 지킨다.
