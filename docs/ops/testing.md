# 테스트

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

운영에서 Operator 세션은 실제 Redis 에 산다(#43, ADR-0018). **다만 테스트는 그렇지
않다** — 세션 캐시가 LocMem 이라 pytest 에는 `db` 하나면 된다(아래 「테스트는 서로를
밟지 않는다」). 인프라는 compose 가 주고 pytest 는 호스트에서 붙는 구조는 그대로다.

**HTTP가 유일한 시임이다.** 테스트는 마운트된 django-ninja API를 전체 요청 스택(URLconf +
미들웨어 + 라우터)을 통해 호출한다. 모델 메서드나 서비스 클래스를 직접 부르지 않고, 라우터를
직접 호출하는 `ninja.testing.TestClient`도 쓰지 않는다 — 미들웨어를 건너뛰기 때문이다.

시간은 시임이 아니라 주입 가능한 의존성이다(티켓 02, ADR-0003).

**`backend` pytest를 dev 컨테이너 안에서 돌리지 마라.** `docker compose -f
docker/compose.dev.yaml exec backend uv run pytest`(또는 컨테이너 안 셸에서 직접)로
돌리면 12건 안팎이 실패한다 — 회귀가 아니라 어댑터 불일치다. 테스트는
`STORAGE_BACKEND=fake`(기본값)를 기대하는데, dev compose의 backend 서비스는
`STORAGE_BACKEND=s3`로 실제 MinIO를 물려서 띄운다(업로드 e2e가 실물 스토리지를
쳐야 하기 때문 — FE-09, #34). 항상 호스트에서 돌린다:

```bash
scripts/test.sh backend tests/test_x.py   # 호스트에서 돈다 — 포트는 dev-env.sh 가 고른다
```

dev compose의 `db` 서비스는 호스트 포트로 이미 노출돼 있으므로 호스트의 `uv run
pytest`가 그 DB에 직접 붙는다 — 컨테이너를 거칠 이유가 없다.

**`seed_e2e_*` 관리 명령도 마찬가지다 — 호스트에서 돌린다.** 같은 어댑터 불일치이고,
증상이 훨씬 헷갈린다: 시드는 제출물 소스를 **Fake 스토리지**에 쓰는데 컨테이너의
backend 는 `STORAGE_BACKEND=s3` 로 MinIO 를 물고 있어, 채점 스캔이 그 소스를 못 찾아
(`source_not_found`) Score 를 남기지 않는다. 그러면 시드가 다음 줄에서
**「아직 채점되지 않은 Submission은 이의제기할 수 없습니다」**로 죽는다 — 스토리지
이야기는 어디에도 안 나온다. 실제로 이 오류를 스토리지가 아니라 채점 결함으로 한 번
쫓았다.

```bash
cd backend && CODEMIT_DB_PORT=55432 uv run python manage.py seed_e2e_operator_appeal
```

**`seed_demo_contests` 는 반대다 — 스토리지를 실물로 물려 돌린다**(#253). 이 시드는
제출물 소스를 스토리지에 **실제로 쓰고**, 그 뒤 컨테이너의 backend(=MinIO)가 그것을
읽어 채점한다. fake 로 돌리면 오브젝트가 명령과 함께 사라져 채점이 소스를 못 찾고,
결국 상한에 걸려 **「플랫폼이 채점하지 못했다」 0%** 만 남는다(ADR-0031) — staging 에서
데모 14건이 통째로 그 상태였다. 시드가 fake 를 감지하면 경고하지만, 처음부터 이렇게
돌린다:

```bash
cd backend && CODEMIT_DB_PORT=55432 \
  STORAGE_BACKEND=s3 STORAGE_BUCKET=codemit-dev \
  STORAGE_ENDPOINT_URL=http://127.0.0.1:19000 \
  STORAGE_PUBLIC_ENDPOINT_URL=http://127.0.0.1:19000 \
  STORAGE_ACCESS_KEY=codemit STORAGE_SECRET_KEY=codemit-secret STORAGE_REGION=us-east-1 \
  uv run python manage.py seed_demo_contests
```

**그리고 채점이 한 번 돈 뒤에는 다시 심을 수 없다.** `Score.submission` 이 PROTECT 라
데모 Contest 삭제가 `ProtectedError` 로 막히고, append-only 우회는 배포 환경에서
거부된다(#240) — 즉 staging 에서는 재시드가 통째로 불가능하다. 시드가 스스로 「멱등하다」고
적어 둔 계약이 그 지점에서 깨져 있다.

**강의실 데모는 `seed_demo_classroom` 이 심는다 — 그리고 이쪽은 다시 심을 수 있다.**
한 강사 계정에 화면의 갈래가 전부 보이는 한 벌을 만든다(진행중 클래스 둘·보관된 것
하나, 초안과 열린 문제, 내보내진 참여자, 시도가 쌓인 제출과 통과·미통과가 섞인 채점,
사용량이 쌓인 클래스, 공개된 문제·클래스 템플릿). 출력에 가입 링크와 템플릿
공유 코드가 나온다.

**알림도 심는다**(#341) — 참여자에게 시도마다 채점 완료.
채점을 실제로 돌리지 않아 스캔이 알림을 만들 기회가 없었던 자리를, `ClassroomScore`
를 만드는 그 자리마다 스캔(`classroom.scoring`)이 부르는 것과 같은 알림 함수를
불러 채운다 — 문구·링크(#329)가 스캔이 실제로 만드는 것과 같은 모양이 된다.

```bash
cd backend && CODEMIT_DB_PORT=55432 uv run python manage.py seed_demo_classroom --email <계정>
# staging 에서는
ssh sub 'docker exec codemit-staging-backend-1 python manage.py seed_demo_classroom --email <계정>'
```

**채점을 돌리지 않고 `ClassroomScore` 를 직접 만든다** — 데모를 심는 데 강사의 OpenAI
키를 태울 이유가 없고, 통과·미통과를 의도대로 배치해야 화면의 모든 갈래가 보인다.
같은 이유로 클래스에 키를 넣지 않는다. 제출은 **저장소 형식만** 심는다 — 소스 형식은
값이 스토리지 object_key 라 실제 오브젝트를 함께 써야 하고, 그러지 않으면 화면이 없는
파일을 가리킨다(#253 이 겪은 실패다).

**재시드가 되는 이유는 `ClassroomScore` 를 먼저 걷기 때문이다.** 위 공모전과 똑같이
`ClassroomScore.submission` 이 PROTECT 라 클래스를 그냥 지우면 막힌다. 이 명령은
`[데모]` 로 시작하는 **그 강사의** 클래스에 달린 Score 만 QuerySet 으로 먼저 지운다
(append-only 가드가 인스턴스 `delete()` 에만 걸려 있다). 범위가 그 접두어로 닫혀
있다는 것이 이 우회의 근거 전부이므로 그 필터를 넓히면 근거가 사라진다 — 실데이터의
Score 는 어떤 경로로도 닿지 않는다. `--purge-only` 로 걷어내기만 할 수도 있다.

**e2e 가 남긴 것이 dev 화면을 덮으면 걷어낸다**(#183). Contest 는 스위트 시작에 저절로
걷히지만(`global-setup.ts` 가 세 정리를 순서대로 부른다 — 실행 토큰별 큐, 네임스페이스별
Contest, 그리고 기준데이터), 스위트를 한동안 안 돌렸다면 손으로 한 번 부른다:

```bash
cd backend && CODEMIT_DB_PORT=55432 uv run python manage.py prune_e2e_junk
```

이름이 `e2e`·`[e2e` 로 시작하는 Category·DeliverableType 을 지우고 플랫폼 정책을 기준값
(모델 필드 기본값)으로 되돌린다. **정책 변경 이력은 남긴다** — 감사 추적이다(ADR-0023).
다만 e2e 종류에 달린 변경 이력은 그 종류와 **함께 지운다**:
`DeliverableTypeChange.deliverable_type` 이 PROTECT 라 그러지 않으면 종류를 지울 수 없고,
실측에서 e2e 종류 127개 중 108개가 그런 이력을 달고 있었다. 살아남은 Contest 가 참조 중인
것은 건너뛰고 이름을 stderr 로 알린다. 청소가 스위트를 빨갛게 만들면 「테스트가 깨졌다」와
구별되지 않으므로, `global-setup.ts` 도 이 정리만은 실패를 삼키고 경고만 남긴다.

실측으로 산출물 종류 132개(진짜는 5개)·카테고리 24개(진짜는 4개)가 쌓여 개최 화면의
요구형태 목록이 통째로 묻혔고, 플랫폼 수수료율이 e2e 가 남긴 324bps 라 dev 에서 확인한 실수령액이 실제 정책과 달랐다.

**Contest 를 먼저 걷어야 기준데이터가 풀린다** — `Contest.category` 가 PROTECT 라서다.
`global-setup.ts` 의 순서가 그래서 그 순서다.

**스위트는 기본으로 병렬 실행된다**(#104). `pyproject.toml` 의 `addopts` 가 `-n auto` 를
준다 — 실측(이 머신, 당시 1192건 — 지금 2482건 통과·1건 skip(요청 id·배포 JSON 로그·prod 지표를 더한 로깅·모니터링 4단계까지, 2026-09-21). Assignment 가 #205~#212 로
1312건에서 1377건까지, staging 검증이 낳은 #214~#217 로 1388건까지, 저장소만으로
제출하고 채점 시점에 박제하는 #218~#220 으로 1407건까지, 채점 상한과 화면 열한 개
(#213·#221~#231)로 1463건까지, 종류 게이트(#232)로 1467건까지, 공모전 이미지
(#233~#236)로 1512건까지, staging 걷기가 낳은 #237~#239 로 1514건까지, append-only
가드와 다운로드 파일명(#240·#241)으로 1524건까지, 알림 문구 분리와 제출 수정 진입
(#244·#245)으로, 채점 사유 청중 분리(#246)와 제출 화면의 「다음 행동」 단일화(#247)로,
제출 화면이 점수와 다음 갈래를 함께 보여주는 것(#248)으로, 신원 파기 뒤에도 제출물을
읽을 수 있게 하고 그 「다음 행동」에 재확인 상태를 접은 것(#250)·자동 0% 의 판정 주체
(#251)·데모 신원 시드(#252)·데모 제출물이 실제로 쓰이고 채점되게 한 것(#253)으로,
Contest 전이 그래프를 한 곳에 선언하고 선언 밖을 정적으로 막고 다이어그램을 낸 것
(#255~#257)으로, 업로드 용량·영상 보존·스크린샷 개수의 정책 필드 자리를 만든 것(#263)
으로 1603건까지, 그 바이트 상한을 presigned POST 서명 조건에 실제로 묶고(#261) ·
시연 영상을 보존 기간 뒤 파기하고(#262) · 스크린샷을 자료 종류로 세우고(#264) · 심사
비교와 공개 프로필이 영상·스크린샷을 실제로 열게 한 것(#265)으로, 옛 자료의 다운로드
확장자를 되돌리는 백필과 과제 소스 파일명에 제출자 이름을 붙인 것(#268 후속)으로
1640건까지, 앱 경계를 테스트로 세운 것(#269)으로 1659건까지, 제출물을 공통 부모와
공모전 자식으로 쪼갠 것(#270)으로 1661건까지, 공모전 제품 스위치(#271)로 1678건까지,
`classroom` 앱을 세우고 경계표에 등록한 것(#275)으로 1679건까지, Class·Problem·
체크리스트(#278·#282·#283)로 1699건까지, 강사의 OpenAI 키(#284)와 가입 링크
발급·재발급(#279)으로, 클래스·문제별 채점 모델(#285)과 링크로 회원가입과 클래스
가입이 한 번에 끝나는 것(#280)으로, 참여자 명단과 내보내기(#281)로 1740건까지,
제출 — 소스나 저장소를 내고 시도가 쌓이는 것(#286)으로 1753건까지, 제출 즉시
비동기로 채점되는 것(#287)으로 1763건까지, 통과 판정과 참여자의 문제 목록
(#288)으로 1772건까지, 강사가 제출물을 열어 보되 그 열람은 기록하지 않는 것
(#291, ADR-0040)으로, 클래스와 문제의 복사(#292·#293)로, 보관(#294)으로,
채점 토큰 예산 경고와 정지(#295)로 1831건까지, 가입 링크를 다시 열면 이름을
또 묻던 것을 고쳐 이미 참여자면(내보내진 사람 포함) 곧장 문제 목록으로
보내는 것(#300)으로, 문제 만들기 화면에서 체크리스트를 함께 받고 바로 여는
것(#315)으로, 문제 하나를 템플릿으로 공개하고 가져오는 것과 그 신고·모더레이션
(#316·#318·#320)으로, 클래스를 통째로 템플릿으로 공개하고 가져오는 것(#319)으로
1931건까지, 도달성 점검이 찾은 넷(#328~#331)으로 1959건까지, 강의실을 여섯 시선으로
걸어 찾은 결함·보충 아홉(#333~#341)으로 1985건까지, 화면이 역할에 맞게 말하게 한 것과
위험 표시·알림 분리(#332·#342~#345)로 1994건까지, staging 을 보통 사람의 감각으로
써 보고 찾은 다섯(#346~#350)으로 2000건까지
여기까지 늘었다. 그리고 처음으로 **줄었다** — 과제를 접으며(#358) 그 전용 테스트와, 마이그레이션을 앱마다 단일 initial 로 접으며(#364) 옛 마이그레이션을 직접 세우던 되감기 테스트 일곱 파일이 함께 빠졌다) `-n 4` 84초 → `-n auto` 57초.
직렬로 보려면 `-n 0`.

**실물을 치는 시험은 표식 둘로 나뉘고 기본 실행에서 빠진다**(`addopts` 의 `-m`, `tests/live.py`).
`live_vendor` 는 돈이 드는 실제 벤더(OpenAI·PortOne·Toss 등), `live_infra` 는 dev 프로필로 띄운
실물 인프라(pgbouncer·Redis·OpenSearch, #751)다. 둘 다 접속값 환경변수(`OPEN_AI_API_KEY`,
`CODEMIT_PGBOUNCER_PORT`, `EVENT_BUS_REDIS_URL`, `OPENSEARCH_URL` …)가 없으면 실패가 아니라 skip
이고, CI 는 둘 다 건너뛴다. 돌릴 때는 `scripts/test.sh backend tests/test_pgbouncer_live.py -m live_infra`
처럼 표식을 직접 준다.

**시험 하나는 CPU 1초를 넘지 못한다**(2026-10-02). `tests/conftest.py` 가 시험 본문(call
단계)의 CPU 시간 — 자식 프로세스 몫 포함 — 을 재서 넘으면 실패로 바꾼다. 한도는
`CODEMIT_TEST_CPU_LIMIT`(로컬 기본 1.0, CI 의 `test` 잡은 1.5, 0 이면 끈다). 벽시계가
아니라 CPU 로 재는 이유는 붐비는 러너에서 한도 근처의 시험이 빌드마다 번갈아 떨어지지
않게 하려는 것이고, 준비(픽스처)는 재지 않는다 — 여러 시험이 같은 비싼 준비를 하면 모듈
픽스처로 옮긴다. 넘으면 **한도를 늘리지 않고 원인을 줄인다.** 처음 걸었을 때 340건이
넘었고 원인은 셋이었다:

- **비밀번호 해시** — 운영자 계정을 만들고 로그인할 때마다 PBKDF2 가 돌았다. 테스트에서만
  `MD5PasswordHasher` 를 쓴다(`config/settings.py` 의 `_RUNNING_TESTS` 블록). 이것 하나로
  340건 → 59건, 전체 106초 → 66초.
- **부팅 검사의 파이썬 기동** — `test_deployment_config.py` 가 시험마다 `manage.py check` 를
  새 파이썬으로 돌렸다. 지금은 설정과 무관한 모듈을 미리 읽어 둔 forkserver 의 자식이
  돌리고(`tests/boot_process.py`, 자식의 CPU 는 시험 몫으로 센다), 이 저장소가 등록한
  부팅 검사에만 붙인 태그(`core.adapters.BOOT_CHECK_TAG`)로 URLconf 적재를 건너뛴다.
- **필요보다 큰 데이터** — 배치 상한(50)을 보려고 공모전 53개를 개최하던 시험은 상한을
  2로 줄여 본다.

**붐비면 CPU 초가 부푼다 — 조용할 때 0.5초를 넘기지 않는다**(#701). CPU 시간은 일의 양이
아니다 — 형제 하이퍼스레드가 바쁘면 같은 일에 1.6~2배가 든다(load 15 에서 0.6초짜리가
1.1초로 떨어졌다). 2026-10-15 에 0.5 를 넘던 69건을 0으로 줄였다(최대 0.48): 부팅 검사
자식이 미리 읽는 모듈을 늘리고(`_PRELOAD` — 마지막의 `tests.boot_preload_check` 가 설정을
건드린 모듈을 막는다), 채점 스캔을 여러 번 도는 시험은 상관없는 문법 검사(시도마다 파서
프로세스 하나)를 끄고, 「처음 세는 상태」·저장소·클래스 준비를 픽스처로 옮겼다. 새 시험이
그 근처면 같은 방법을 먼저 본다.

**시험별 CPU 는 junit 의 `cpu_seconds` 로 본다** — 열차의 테스트 보고서(`junit
keepProperties`)에 시험마다 남고, 로컬은 `--junitxml=<경로>` 를 붙여 돌린 파일에서 본다.

**테스트는 서로를 밟지 않는다 — 손으로 갈라 줄 것이 없다.**

예전에는 체인마다 `CODEMIT_TEST_DB_NAME` 과 `SESSION_REDIS_URL` 의 인덱스를 손으로 달리
줘야 했고, 잊으면 조용히 서로를 떨어뜨렸다(`DROP DATABASE ... is being accessed`, 그리고
남의 로그인 세션이 통째로 지워져 나오는 401 무더기 — 둘 다 코드 회귀와 구분되지 않는다).
지금은 둘 다 자동이다:

- **테스트 DB 이름**이 체크아웃 경로에서 파생된다(`config/settings.py` 의
  `_default_test_db_name`). `CODEMIT_TEST_DB_NAME` 을 주면 그 값이 이긴다.
- **세션 캐시가 테스트에서는 LocMem 이다**(같은 파일의 `_RUNNING_TESTS`). 프로세스별로
  갈리므로 워커 격리도 체인 격리도 공짜다.

**그래서 pytest 에 Redis 가 필요 없다** — `db` 하나만 띄우면 된다. 예전 문장(「Operator
세션은 실제 Redis 에 산다, 그래서 테스트에도 redis 가 필요하다」)은 더 이상 사실이 아니다.
ADR-0018 은 **운영**에서 세션이 Redis 에 산다고 정한 것이고, 실물 Redis 위의 세션 동작은
운영자 로그인 e2e 가 실물 스택으로 계속 덮는다.

```bash
scripts/test.sh backend tests/test_x.py   # db 하나만 띄우고(스크립트가 한다) 그 위에서 돈다
```

**앱 경계는 테스트가 지킨다**(#269, ADR-0037). `tests/test_app_boundaries.py` 가 백엔드
소스를 AST 로 훑어 앱 사이의 참조를 본다. 규칙이 둘이고 **강도가 다르다**:

- **강의실 ↮ 공모전 가족은 양방향으로 막힌다 — 예외가 없다.** 최상단이든 함수 안이든,
  `import` 든 Django 가 import 없이 앱을 묶는 길(`ForeignKey("contests.Contest")` 꼴
  문자열·`apps.get_model`)이든 걸린다. 표시로 열 수 있는 문이 하나라도 있으면 마감에
  몰린 사람이 그 문을 쓴다.
- **공유층**(`accounts`·`core`·`policies`·`storage`·`notifications`·`submissions`,
  #270 이 마지막을 더했다)**이 기능 앱을 부르면 막히되, 같은 줄이나 바로 앞 줄의
  `APP-BOUNDARY-EXCEPTION: <이유>` 로 열린다** — **이유가 비면 표시 자체가
  실패한다**(`scripts/check_screen_language.py` 와 같은 관용구). 지금 **25줄**이 나오는데
  그중 **9줄은 검사 파일 자신**(독스트링·정규식·오류 문구·합성 픽스처)이고 실제 표시는
  **16곳**이다(2026-09-20 확인, #465·#470). 시드·백필 관리 명령이 달던 예외 13곳은
  그 명령을 내용이 속한 공모전 가족 앱(`appeals`·`contests`)으로 옮기며 전부
  사라졌다 — 등록부(`core.e2e_seeds`)가 명령의 위치를 모르므로 이름은 그대로다.
  공모전 수명주기 알림(`notifications.lifecycle` → `contests.lifecycle_notifications`)도
  같은 이유로 옮겨 3곳이 사라졌다. 남은 16곳은 대부분 순환을 끊으려 일부러 함수
  안에 넣은 지연 import 라, 지우지 않고 사유를 적어 세어지게만 했다 — 탈퇴·휴면
  신원 파기는 이제 `verification.purge.purge_identity` 한 곳만 부르지만(#470),
  그 호출 자체도 공유층(`accounts`)이 기능 앱(`verification`)을 부르는 것이라
  표시는 남는다(`accounts/dormancy.py`·`accounts/withdrawal.py`).
  `grep -rn "APP-BOUNDARY-EXCEPTION" backend/` 로 나오는 숫자가 경계의 건강
  지표다 — 늘면 공유층이 기능으로 오염되는 중이라는 뜻이다. **그 grep 은 지금
  27줄인데 실제 표시는 위 16곳이다** — 나머지는 검사기 자신이 들고 있는 문자열
  (`tests/test_app_boundaries.py`)과 같은 관용구를 설명하는 문장이라, 세려면
  검사기와 문서를 뺀다.

**`INSTALLED_APPS` 에 앱을 더하면 그 표에 분류를 적기 전까지 빨갛다.** 한 방향으로만
그렇다 — 표는 아직 설치되지 않은 앱(`classroom`)을 미리 이름 지을 수 있다.

`scripts/` 의 스크립트가 아니라 테스트인 이유는 **로컬 게이트**다(아래 「티켓을 닫는
기준」) — `scripts/` 검사는 그 셋 중 어디에도 안 걸려 push 해야만 결과를 안다. import
경계는 쓰는 순간 막혀야 뜻이 있다. 새 CI 잡도 늘지 않는다: 기존 `test` 잡이 돌린다.

**Next 앱이 빌드 때 바깥에 매달리는 길도 같은 모양의 시험이 막는다** — 세 앱과 `packages/` 의
소스를 줄 단위로 훑고, 시험 파일과 주석 줄은 보지 않는다(금지를 설명하는 문장은 남아야 한다).
`tests/test_next_public_env_stays_out.py`(#727·#733)는 `process.env.NEXT_PUBLIC_*` 가 다시
들어오는 것과 세 앱 `next.config.*` 의 `env:` 키를 막는다 — 둘 다 값을 빌드 때 번들에 굳혀 이미지가
환경을 알게 한다. 줄 단위 정규식이라 `process.env?.NEXT_PUBLIC_X`·구조 분해·`env,` 단축 속성은
못 잡는다. `tests/test_next_font_stays_local.py`(#743)는 `next/font/google` 을 막는다 — 빌드가
fonts.gstatic.com 에 매달린다. 왜 그런지는 [Next 프로덕션 빌드](next-build.md).

**그리고 이것이 실제 사고를 하나 막는다.** 호스트 pytest 의 기본 세션 URL 은 dev compose
가 노출한 **바로 그 Redis 의 같은 인덱스**였다. 즉 `uv run pytest` 한 번이 떠 있는 dev
환경의 운영자 세션과 조회 카운터를 통째로 지웠다(`RedisCache.clear()` 는 FLUSHDB 다).
LocMem 으로 바뀌면서 그 경로 자체가 사라졌다.

**빠뜨린 필드는 구조 테스트가 막는다**(#480, spec #474, `tests/
test_banned_word_field_registration.py`) — 사용자가 적는 이름·제목·본문에 금칙어
(사칭·욕설)를 거절하는 장치(`core.banned_words`)가 어느 필드에 적용되는지는
`core.banned_word_rules.RULES` 한 표가 든다. 이 구조 테스트가 백엔드 입력 스키마
(django-ninja `Schema`, 이름이 `In`으로 끝나는 관례 — `payload:` 타입 주석이 전부 이
접미사를 쓴다)를 `ninja.Schema.__subclasses__()`로 훑어 문자열·문자열 목록 필드를 전부
모으고 그 표와 대조한다. **등록되지 않은 필드가 있으면 빨갛다** — 앞으로 사용자 입력을
받는 새 필드를 더하면, 금칙어 검사를 어떻게 할지 정하기 전까지 이 테스트가 막는다.
앱 경계 테스트(`tests/test_app_boundaries.py`)와 같은 관용구를 쓴다: 아직 설치되지 않은
스키마는 표에 없어도 되지만(스캔 대상이 아니므로), 스캔되는 스키마가 표에 없으면
안 된다는 한 방향의 강제다. `test_no_stale_registrations`가 반대 방향(표에는 있는데
더는 스캔되지 않는 죽은 항목)도 잡는다.

**면제는 이유가 있어야 한다.** `BannedWordRule(checks_impersonation=False,
checks_profanity=False, exempt_reason="...")` 로 적는다 — 둘 다 거짓인데
`exempt_reason`이 비어 있으면 실패한다(`scripts/check_screen_language.py`의
`SCREEN-LANGUAGE-EXCEPTION`과 같은 관용구). 이유 없는 면제는 잊힌 누락과 구별되지
않기 때문이다. 검사를 거는 쪽(`checks_impersonation`·`checks_profanity` 중 하나라도
참)은 반대로 `exempt_reason`을 비워야 한다 — 검사와 면제 이유가 동시에 있으면 어느
쪽이 실제 동작인지 코드를 읽어야만 안다. 면제 사유는 크게 셋이다: **운영자 표면**
(운영자 공지·이의 심판 사유·정책/기준데이터 변경 사유 — 운영진이 진짜 운영진이라
사칭이 성립하지 않고, 신고된 표현을 그대로 인용해야 할 때가 있다), **당사자만 읽는
글**(이의제기 사유·템플릿 신고 사유 — 운영자만 읽고, 권리를 행사하는 길이라 낱말로
막을 자리가 아니다), **자유 텍스트가 아닌 것**(식별자·URL·object key·자격증명·벤더
웹훅 페이로드·정해진 값 집합 중 하나로 고정된 값 등).

**#480 이 이 표를 완성하며 실제로 빠진 검사 여덟 줄(네 자리)도 찾았다** — 면제를
적으려 훑다가 이미 검사하는 필드와 같은 범주(공개 이름·공개 본문)인데 어느 티켓에도
없던 자리였다: 클래스 템플릿을 가져올 때 새로 붙이는 이름, 채점 지침 `"custom"` 문장
(만들 때·고칠 때), 공모전 요구사항 문구(만들 때 인라인·따로 추가·수정), 개최자·개발자
공개 소개글(`bio`). 면제 대신 실제 검사를 걸었다 — `core.banned_word_rules` 모듈
docstring 과 `tests/test_banned_word_gap_fields.py` 가 경위와 HTTP 검증을 남긴다.
