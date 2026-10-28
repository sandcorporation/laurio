# 프론트엔드

`CLAUDE.md` 의 부록이다 — 거기서 앵커로 가리키고, 같은 「지금」을 말한다.

Next.js + React. 저장소 루트가 pnpm 워크스페이스다(운영자 앱 04 #62, ADR-0021) —
락파일은 루트의 `pnpm-lock.yaml` 하나뿐이고, 공개 앱(`frontend/`, 위치·패키지 이름
변경 없음)·운영자 앱(`operator/`)·강의실 앱(`classroom/`, #276)·공유 패키지 셋이
그 멤버다 — `packages/bff-shared`(서버 쪽: 경로 순회 방어·Origin 검증·허용목록 검사
함수·백엔드 전달 기계. 허용목록의 **내용**은 앱마다 자기 파일에 남는다, ADR-0021),
`packages/bff-client`(브라우저 쪽, #146: 인증 구역 호출의 클라이언트·`ApiResult`·
`normalizeDetail`·`useBackendQuery`/`usePagedList`·생성 타입 `schema.gen.ts` — **강의실도
이제 이 패키지를 쓴다**(#462). 손으로 다시 쓴 클라이언트(`lib/backend/client.ts`)와
그 사본이 낳던 결함 — 세션이 끊긴 사람을 로그인으로 보내는 동작이 강의실에만 없던
것 — 을 함께 걷어냈다. 강의실도 공개 앱과 같이 `revive` 를 준다(#767) — 401 이면
이 앱 자신의 `/api/auth/session` 으로 세션을 되살리고 재시도하며, 그래도 401 이면
이 앱 자신의 `/login` 으로 보내고 그 화면이 공개 앱 로그인으로 다시 돌려보낸다.
자기 로그인이 없어도(ADR-0038) 부모 도메인 쿠키를 나눠 쓰므로 되살리는 자리는
가질 수 있다 — 없던 동안은 리프레시 회전 경합에서 진 요청의 401 하나로 켜 둔
탭이 로그인으로 튕겼다), 그리고
`packages/markdown`(설명 마크다운 렌더러, ADR-0047 — 2026-09-16
에 강의실에서 옮겼다: 강의실의 문제 설명과 공개 앱의 공모전 설명이 **같은 허용 목록
스키마와 같은 화면 조각**을 쓴다. 본문은 서버 컴포넌트가 그리고 복사·파일로 저장 버튼만
클라이언트 조각이라 공개 표면의 SSR 이 깨지지 않는다, ADR-0015). 테스트 전용
`packages/route-audit`(#166)도 멤버지만 화면 코드는 아니다. 명령은 그대로다 — 워크스페이스가 생겨도 `pnpm --dir <앱>` 호출법은
바뀌지 않는다.

테스트 시임은 **앱마다 하나**다(ADR-0021·0026). `docker compose -f
docker/compose.dev.yaml up` 으로 세 앱이 다 뜬 스택을 띄운 뒤 `pnpm --dir frontend test`
로 Playwright 가 프로젝트 셋으로 세 앱을 한 번에 친다(공개 앱 스펙은
`frontend/e2e/*.spec.ts`, 운영자 앱 스펙은 `frontend/e2e/operator/*.spec.ts`, 강의실
스펙은 `frontend/e2e/classroom/*.spec.ts` — `playwright.config.ts` 가 프로젝트마다 다른
`testDir`·`baseURL` 을 준다). `CODEMIT_E2E_BASE_URL`/`CODEMIT_OPERATOR_E2E_BASE_URL`/
`CODEMIT_CLASSROOM_E2E_BASE_URL` 로 각 프로젝트의 `baseURL` 을 바꿀 수 있다(기본값은 위
포트 표와 같다). `pnpm --dir frontend typecheck`/`pnpm --dir operator typecheck`/
`pnpm --dir classroom typecheck` 는 스택 없이 돈다.

**강의실은 자기 로그인을 갖지 않는다**(ADR-0038, #276) — 회원은 공개 앱과 공유한다.
그래서 강의실 e2e 스펙은 강의실에서 로그인하지 않는다: 부모 도메인 쿠키 공유는
dev(localhost, 포트로 앱을 가른다)에서 재현할 수 없고, 실제 공유는 staging에서만
검증된다(#277). 강의실의 인증 구역을 걷는 스펙(과 dev에서 눈으로 확인할 때)은 공개
앱에 로그인해 받은 `codemit_access`/`codemit_refresh` 쿠키 값을 강의실 오리진에 수동으로
심는다(`frontend/e2e/classroom/lib/cross-app-session.ts`, Playwright의
`context.addCookies`) — 실제 브라우저가 두 쿠키를 부모 도메인으로 공유하는 것을
로컬에서 흉내 내는 유일한 길이다. **그래서 `frontend-e2e-classroom` CI 잡은 강의실만이
아니라 공개 앱도 띄운다** — 빼면 그 헬퍼가 `ECONNREFUSED 127.0.0.1:53000` 으로 죽는다
(#318 이 그 스펙을 더한 뒤 main 에서 여섯 번 연속 그렇게 빨갛게 났다).

**운영자 앱은 인증의 모양이 다르다**(#63, ADR-0016·0018·0019) — 세션 쿠키 이름은
`codemit_operator_session`(`backend/config/settings.py`)이다. e2e 가 로그인할
Operator 계정은 `backend/accounts/management/commands/seed_e2e_operator.py`
(멱등)로 만든다 — 사람이 쓰는 `create_operator` 부트스트랩 명령과 달리 반복
실행에 안전하다.

**dev 컨테이너의 `backend` 도 바깥 체크아웃을 서빙한다.** 프론트에 대해서만 적혀
있던 함정인데 백엔드도 같다 — `docker/compose.dev.yaml` 이 저장소 전체를 마운트하므로,
워크트리에서 **새 API 라우트를 더하면 58000 번 백엔드에는 그 라우트가 없다.** e2e 가
404 를 받고, 원인은 코드가 아니라 어느 체크아웃을 쳤느냐다. 두 에이전트가 각자 시행
착오로 이걸 다시 발견했다. 워크트리 코드를 치려면 백엔드도 임시로 띄운다:

```bash
cd <worktree>
./scripts/dev-server.sh start backend        # 포트를 출력한다
CODEMIT_API_BASE_URL=http://127.0.0.1:<그 포트> ./scripts/dev-server.sh start front
# … 브라우저로 걷는다 …
./scripts/dev-server.sh stop-all
```

e2e 스펙을 워크트리 코드로 돌릴 때는 `scripts/test.sh e2e <파일>` 이다 — 이 워크트리로 구운
프로덕션 이미지 스택을 따로 띄운다. **`playwright test` 를 바로 치면 설정 파일이 거절한다**
(2026-10-02, `CODEMIT_TEST_ENTRY` — 백엔드 pytest 도 같다).

`STORAGE_BACKEND=s3` 는 도구가 알아서 준다 — dev compose 의 backend 가 그렇게 뜨기
때문이다(업로드 e2e 가 실물 MinIO 를 쳐야 한다). 빼면 업로드 스펙만 갈린다.

**워크트리에서 일한다면 e2e 가 당신 코드를 치지 않는다.** `playwright.config.ts`
에 `webServer` 가 없는 것은 의도다(ADR-0021 — 테스트가 앱의 수명을 소유하지
않는다). 그 결과 compose 로 뜬 `frontend` 컨테이너는 **바깥 체크아웃**을 마운트해
서빙하므로, 격리된 워크트리에서 프론트를 고치고 e2e 를 돌리면 **고치기 전 코드가
통과한다.** 병렬 체인 둘이 각자 이 사실을 재발견했다.

워크트리 코드로 검증하려면 그 워크트리에서 임시 Next 서버를 띄우고 baseURL 을
그쪽으로 돌린다 — 백엔드는 이미 떠 있는 것을 그대로 쓴다:

**`scripts/dev-server.sh` 로 띄우고 걷는다 — 손으로 `&` 와 `kill %1` 을 쓰지 않는다**
(2026-09-20). 포트는 이 워크트리의 `dev-env.sh` 값 +10 으로 스스로 고르므로 compose
스택과도, 다른 워크트리와도 부딪히지 않는다.

```bash
cd <worktree>
./scripts/dev-server.sh start front          # 주소를 출력한다 — 브라우저로 걷는다
./scripts/dev-server.sh stop-all             # 끝나면 반드시
```

**옛 처방(`... &` 뒤에 `kill %1`)은 에이전트에게 성립하지 않는다.** 잡 테이블은 그
셸에만 있는데 에이전트는 **Bash 호출마다 새 셸**이라, 나중 호출의 `kill %1` 은
아무것도 죽이지 않는다 — 지켜질 수 없는 규칙이었다. 2026-09-20 에 병렬 체인 다섯이
그렇게 남긴 호스트 `next dev` **14개가 15.0 GiB** 를 먹어 RSS 25/26 GiB·스왑 8 GiB 중
88 KB 만 남았고, sshd 가 `Maxstartups` 로 연결을 버려 **SSH 로 들어갈 수 없었다**
(커널 OOM 은 `oom_score_adj` 가 높은 chrome 만 죽였을 뿐 원인은 안 건드렸다).

그래서 이 도구는 **PID 파일**로 관리한다 — 어느 셸에서든 걷을 수 있다. 그리고 죽일 때
**나무 전체를 죽인다**: `pnpm exec next dev` 는 자식으로 진짜 `next-server` 를 낳으므로
부모만 죽이면 메모리를 쥔 쪽이 그대로 남는다(실측으로 3단계까지 함께 죽는 것을
확인했다). 다른 명령도 있다 — `list`(이 머신에 뜬 것 전부, **이 도구 밖에서 뜬 것까지**
보여준다)·`reap`(워크트리가 사라진 고아를 걷는다, 5분마다 타이머가 부른다)·`stop <대상>`.

**주 워크트리에서는 안 뜬다 — 그게 맞다.** dev 컨테이너가 이 체크아웃에 root 로 `.next`
를 써 두어 호스트 `next dev` 가 `EACCES` 로 죽는데, 주 워크트리는 애초에 컨테이너가
서빙하므로 호스트에서 띄울 대상이 아니다. 도구가 그 경우를 알아보고 이유를 적는다.

**이 머신에는 그 위에 메모리 한도도 걸려 있다** — 자세한 값과 근거는 커밋되지 않는
`CLAUDE.local.md` 에 있다(사용자 슬라이스만 제한하고 docker 는 `system.slice` 라 밖이다).

**로컬 시험의 입구는 `scripts/test.sh` 하나다**(2026-10-02, web-rpg 의 `deploy/test.sh` 와
같은 방식). `scripts/test.sh backend [pytest 인자]` · `scripts/test.sh e2e [playwright 인자]`.

- **다른 길은 막혀 있다**(2026-10-02) — 스크립트가 칸을 잡은 뒤 `CODEMIT_TEST_ENTRY` 를 내보내고,
  그 표식이 없으면(`CI` 도 없으면) `backend/tests/conftest.py`·`frontend/playwright.config.ts` 가
  시작 전에 거절한다. 바로 친 `uv run pytest` 는 `-n auto` 로 코어를 전부 썼다.
- **기계 전체에서 동시에 둘까지 돈다** — 셋째는 빈 칸을 기다린다(`/tmp/codemit-test-slots`
  의 flock, 워크트리가 달라도 같은 칸을 센다). 이 머신은 여러 에이전트와 다른 프로젝트가
  나눠 쓴다.
- **한 칸은 호스트 코어의 1/3 을 고정해 쓴다**(12코어면 4) — pytest·Playwright 는 `taskset`,
  e2e 스택 컨테이너는 `docker update --cpuset-cpus`. 몫 제한(`--cpus`)이 아니라 코어를 못
  박는다: 몫이 차면 0.1초씩 통째로 멈춰 시험이 흔들린다(web-rpg 실측).
- **한 번에 400개를 넘게 돌리지 않는다** — pytest 는 `tests/conftest.py` 가 수집 단계에서,
  e2e 는 스크립트가 `--list` 로 미리 세어 거절한다. `CI` 환경변수가 있으면(=CI) 제한이 없고,
  로컬에서 정말 필요하면 `CODEMIT_FULL_TESTS=1`.
- **전체 시험은 브랜치 PR 의 CI 로 본다** — 아래 「티켓을 닫는 기준」.
- **e2e 는 CI 와 같은 프로덕션 이미지 스택**(`compose.dev` + `compose.ci`)을 이 워크트리 전용
  이름(`<dev-env 프로젝트>-e2e`)으로 굽고 띄우고, 끝나면 지운다. 되풀이할 때는
  `CODEMIT_E2E_KEEP=1` 로 남기고, 다 쓰면 `scripts/test.sh e2e-down`. 일꾼은 코어 둘에 하나다.
- **공개 값은 실행 env 다**(#711, ADR-0062) — e2e 이미지는 배포 이미지와 같은 것이라 빌드 인자가
  없고, 문의 주소 등은 `compose.dev.yaml` 의 `CODEMIT_PUBLIC_*` 로 받는다(비어도 뜬다). 새 공개 값은
  `<앱>/lib/public-config.ts` 의 목록에 더한다 — `NEXT_PUBLIC_` 을 쓰지 않는다(`next-build.md`).

**e2e 시험 하나는 3초 안에 끝나고, 재시도하지 않는다**(2026-10-02, `playwright.config.ts`
의 `timeout: 3_000`·`retries: 0`). 재시도가 흔들리는 시험을 초록으로 덮고 있었다 — 강의실
「죽은 세션」 시험이 CI 에서 30초 타임아웃으로 떨어졌다가 재시도로 통과한 것이 로그에만
남았다. **흔들리는 시험은 지우지 않고 원인을 고친다**(그 시험의 원인은 앞 화면의 주기 조회가
쿠키를 죽인 직후 스스로 로그인으로 이동해 시험의 다음 이동과 부딪힌 것이었다). 넘으면 한도를
늘리지 않고 줄인다. 열차가 묶음 전체를 한 번 더 도는 예외는 하나 — 붉은 시험이 전부 시간 초과이고
그 마감에 backend 가 3초 넘게 요청을 하나도 받지 않은 틈뿐이다(#716, `docs/ops/ci.md` — 그 틈을 VM 정지로
읽었으나 #723 에서 본 실제 원인은 BFF 가 남긴 빈 연결이 gunicorn 워커를 붙잡은 것이었다).
이번에 쓴 방법:

- **준비는 화면이 아니라 API 로** — 개최 폼을 화면으로 채우던 결제 시험은 초안을
  `e2e/lib/contests-api.ts` 로 깐다(폼 자체는 시험 하나가 화면으로 걷는다). 로그인
  도우미(`establishDeveloperSession`·`establishOperatorSession`)는 열 화면을 받는다 —
  목적지로 바로 가거나(`path`) 아무 화면도 열지 않는다(`null`).
- **긴 시험은 나누되 단언은 버리지 않는다** — 결제 「개최 → 공개」를 「폼 → 결제 화면」과
  「결제 화면 → 공개」로 나눴다.
- **사건을 놓치지 않게 먼저 기다린다** — 응답 대기는 화면을 열기 **전에** 건다(공모전
  이미지 시험이 응답을 놓치고 15초를 채우던 것이 CI 의 17초였다).
- **시간으로 기다리지 않는다 — 기계가 막는다**(#808) — `waitForTimeout`·`waitForFunction`·
  `toPass`·`expect.poll`·`networkidle`·`setTimeout`/`setInterval`/`requestAnimationFrame`·
  e2e 의 `while (` 은 시험 파일과 `e2e/` 지원 파일에서 `scripts/check_test_waits.py` 가
  막는다(JS 린터가 없어 문서 검사와 같은 파이썬 하나; 커밋 훅과 PR CI 의
  `sub-checks-inside.sh` 「시험의 고정 대기 금지」 단계가 부른다). 기다릴 것은 화면 단언
  (`toHaveText`·`toHaveURL`), 동작 전에 건 `waitForResponse`, 요소 `waitFor` 다. 시험의
  대기가 아닌 것(고장 주입의 늦은 서버, 부정 단언의 창, 브라우저 안 백오프 흉내)만 그 줄
  윗줄에 `// TEST-WAIT-EXCEPTION: <이유>` 로 연다 — 이유가 비면 실패한다.
- **서버 쪽 비용** — dev·CI 는 빠른 비밀번호 해셔를 쓴다(운영자 시드 1.06 → 0.08초,
  로그인 0.55 → 0.23초; 배포는 PBKDF2 그대로, `config/settings.py`). dev·CI 의 Postgres 는
  `synchronous_commit=off`(시드 하나가 커밋 대기로 1.5초를 썼다). CI 의 e2e 백엔드는
  `runserver` 가 아니라 gunicorn 넷이다(`compose.ci.yaml`). CI 의 e2e 잡 셋은 한 호스트에서
  노드를 통째로 쓰므로 일꾼은 코어의 1/3 이다(`scripts/ci/e2e.sh` 의 `PLAYWRIGHT_WORKERS`).

**e2e 시드는 입구에서 줄을 선다**(2026-09-18, CI #242). Playwright 는 시드를 스펙 파일마다
`beforeAll` 에서 부르고 `fullyParallel` 로 워커 여럿을 쓰는데, 시드들은 「기존 e2e 데이터를
지우고 다시 만든다」 구조라 **순차로만** 멱등하다 — 둘이 같이 지우고 같이 넣으면 한쪽이
유일 제약에 걸려 죽는다(실측: 동시 2번이면 3/3 으로 한쪽이 500,
`auth_user_username_key` 의 `e2e-seed-sponsor`). `POST /api/internal/e2e/seed/{name}` 이
이름별 `pg_advisory_xact_lock` 을 잡아 그 창을 닫는다. 시드 하나가 0.25초라 워커 여섯이
줄을 서도 최악 1.5초이고 호출부의 하한은 30초다. 호출부를 하나씩 고치지 않고 입구에 둔
이유는 같은 경쟁이 시드마다 다른 제약으로 되살아나기 때문이다(스폰서·심사 스폰서·개발자·
기준데이터가 모두 같은 「지우고 넣기」 모양이다). **매번 새 행만 만드는 시드는 등록부가
줄에서 뺀다**(`SeedEntry.serialized=False`, 2026-10-02 — 이의 시드 셋이 0.4·1.0·1.2초로 줄을
서서 시험 하나 3초 한도를 넘었다).

**그 실패는 한 번 진단이 불가능했다.** `frontend/e2e/lib/seed-http.ts` 가 오류 본문을
400자에서 잘라 역추적의 머리만 남기고 정작 원인 줄(psycopg 예외 클래스와 `DETAIL:`)을
버렸다 — 지금은 4000자다. 내부 토큰 뒤의 표면이고 배포 환경에서는 아예 거부되므로 길게
실어도 잃을 것이 없다.


프론트엔드 티켓 하나에 한 시간씩 쓰던 이유의 절반이 테스트 대기였다(실측: 티켓당 평균
51분 중 대략 절반). 그래서 개발 중의 확인을 e2e 에서 **브라우저로** 옮긴다.

**개발 중에는 에이전트가 Playwright 로 유저스토리를 직접 걸어본다.** 코드를 쓰고, 실제
브라우저로 그 화면을 열어 사람이 걸을 경로를 그대로 걷고, 걸은 경로를 글로 요약해 보고한다
(`mcp__playwright__browser_*`). **모킹이 아니고 새 시임도 아니다** — ADR-0017/0021 이 정한
바로 그 시임(실행 중인 앱)을 자동화 대신 손으로 미는 것이다. 그 ADR 들은 시임의 **위치**를
정하지 「언제 돌리는가」를 정하지 않는다.

**e2e 스펙은 개발 중에 쓰지 않는다.** 티켓이 끝날 때 1~2개만 남긴다. 무엇을 남기는지는
아래 「남길 것」이 정한다. 새로 쓴 스펙은 그 파일만 `scripts/test.sh e2e <파일>` 로 한 번
돌려 3초 안에 드는지 보고, 나머지는 PR 의 CI 가 돌린다.

## 남길 것 — ADR-0017 의 세 위험 + 핵심 흐름

ADR-0017 의 세 위험(공개 페이지 SSR·인증 구역 가드·프록시 허용목록과 Origin 검증)에
해당하면 **반드시** 남긴다. 다만 가드는 `matcher` 하나에 걸린 함수 하나라 **전용 스펙에서
한 번만** 본다 — 화면마다 반복하지 않는다. 허용목록·Origin 검증은 백엔드에 대응 테스트가
**없다**.

그 밖에는 **핵심 흐름**만 남긴다: **돈이 움직이거나 보안이 새는 곳**(결제·지급·이의
심판과 원장·탈퇴·소스 열람)과 **앱마다 유저스토리 한 벌**.

**나머지는 남기지 않는다.** 「로그인된 상태에서 화면이 서버 값을 어떻게 그리는가」는 대개
백엔드 테스트가 같은 사실을 이미 고정하고 있다 — 실제로 여러 스펙이 자기 주석에 「백엔드가
실물로 검증한다」고 적어 두고 같은 값을 다시 단언하고 있었다.

**로그인은 공개 앱 하나뿐이고, 끝나면 온 곳으로 돌려보낸다**(#297 후속). 강의실은
자기 로그인이 없어(ADR-0038) 사람을 공개 앱으로 보내는데, `next` 는 **같은 오리진
상대 경로만** 허용하므로(`frontend/lib/auth/next-path.ts`) 그것만으로는 돌아올 수
없다 — 실제로 로그인한 사람이 공모전 콘솔에 버려졌다.

**그 검사를 느슨하게 하지 않았다.** 대신 오리진을 나르는 자리를 따로 뒀다:
`next_origin` 쿼리를 `frontend/lib/auth/sibling-origins.ts` 가 **설정에 적힌 우리
오리진 목록**(`CODEMIT_CLASSROOM_ORIGIN`)과 대조해 통과한 것만 OAuth 왕복 쿠키에
싣고, 콜백이 거기로 돌려보낸다. 사용자 입력이 고르는 것은 「이 목록 중 어느
것인가」뿐이다. 실패 경로(`oauth_unconfigured` 등)도 같은 값을 실어 보낸다 —
안 그러면 한 번 실패한 사람이 다시 성공해도 공개 앱에 남는다.

**`CODEMIT_CLASSROOM_ORIGIN` 은 공개 앱과 강의실이 같은 `.env` 줄을 나눠 읽는
값이다**(`CODEMIT_OPERATOR_ORIGIN` 과 같은 원칙). 어긋나면 복귀가 조용히 안 되고
사람은 공개 앱에 남는다 — fail-closed 라 보안 구멍은 아니지만 원인을 찾기 어렵다.

**런타임 설정을 읽는 화면은 정적으로 구워지면 안 된다**(#297). Next 는 `searchParams`·
`cookies`·`headers` 를 하나도 안 읽는 서버 컴포넌트를 **빌드 시점에 HTML 로 굽는다.**
그 화면이 `process.env` 를 읽으면 **빌드 머신의 값**(대개 비어 있음)이 박제되고, 폴백이
있으면 그 폴백이 배포에 그대로 나간다. 강의실 로그인 링크가 실제로 그렇게
`http://127.0.0.1:53000` 을 가리켰다(`x-nextjs-prerender: 1`, 1년 캐시).

**세 게이트가 전부 못 본다**: dev 는 매 요청 렌더라 안 보이고, CI e2e 는 그 스택에서
값이 비어 있어 **폴백이 「맞는 답」**이라 통과하고, deploy-guard 는 부팅 여부만 봤다.
프로덕션 이미지에 배포 설정을 물려야만 드러난다. 그래서 두 곳에서 잡는다 —
`classroom/lib/rendering/runtime-config.test.ts` 가 **구조**(런타임 환경변수에 닿는
page/route 는 `export const dynamic = "force-dynamic"` 을 선언해야 한다)를,
`scripts/ci/deploy-guard.sh classroom` 이 **결과**(구운 이미지의 `/login` HTML 에 로컬호스트가
없는가)를 본다.

**강의실은 공개 앱과 같은 토큰·서체를 쓴다**(#298). `classroom/app/tokens.css` 는
`frontend/app/tokens.css` 의 **복사본**이고 서체 파일(Pretendard, IBM Plex Mono 굵기 셋 — #743)도 그렇다. 공유 패키지로
빼지 않은 이유는 손으로 관리되는 목록 셋이 또 늘고 로컬 게이트가 그것을 못 보기
때문이다(#166). 대신 `classroom/lib/design/tokens.test.ts` 가 두 파일이 한 글자라도
갈리면 빨개진다 — 「복사했으니 언젠가 갈라진다」를 규율이 아니라 검사로 바꿨다.
**토큰이 같아도 화면이 그 밖의 이름을 부르면 갈라진다** — 그래서
`frontend/lib/ui/brand-guard.test.ts`(#370)가 세 앱과 `packages/markdown/src`(2026-09-16
— 두 앱의 설명 화면이 그 패키지로 옮겨 갔다)의 소스를 텍스트로 훑어 정의된 적
없는 색(`bg-accent` 등 — Tailwind 는 오류 없이 아무것도 안 만든다)과 토큰 반경을
우회하는 모서리(맨 `rounded`·`rounded-full`)를 막는다 — 예외는 알림 벨의 읽지 않은 수
배지 하나뿐이고(동그란 표식, 2026-09-13 결정) 그 목록이 검사 파일 안에 있다. 새 CI 잡이 아니라 공개 앱의
`test:unit` 에 얹혀 있다. 운영자 앱은 토큰 파일이 없어 사본 대조의 대상이 아니다.

**그 순수 함수 잡(`frontend-pure-unit-tests`)이 이제 다섯을 돈다** —
`packages/bff-shared`·`packages/markdown`·공개 앱·운영자 앱·강의실. 뒤의 둘이
2026-09-16 에 늘었다: 강의실의 `test:unit` 은 **CI 에서 한 번도 돌지 않고 있었고**
(그래서 위 토큰·로고 사본 대조와 런타임 설정 구조 검사가 실제로는 아무 문도 아니었다),
마크다운 허용 목록 검사도 강의실 안에 있던 동안 같은 처지였다.

**다크 테마도 이 토큰 파일 하나에만 산다**(#397, spec #396 「따뜻한 먹」). 여섯
색 각각이 `light-dark(라이트, 다크)`로 두 값을 갖고, 문서 루트(`<html>`)의
`color-scheme`이 어느 쪽을 쓸지 정한다 — `:root`의 기본값은 `light dark`(운영체제
설정을 그대로 따른다), `data-theme="light"`/`"dark"` 속성이 있으면(#398 토글이
붙인다) `color-scheme`도 그 값으로 고정돼 운영체제 설정을 덮는다. 컴포넌트는
`bg-paper`·`text-ink/60` 그대로 쓰고 테마별로 고치지 않는다 — 갈리는 자리가 이
파일 하나이려면 그래야 한다. Tailwind 의 `dark:` 변형도 같은 순서(명시 표시
우선, 없으면 시스템)를 따르게 `@custom-variant`로 재정의했지만, 실제로 그
변형을 쓰는 컴포넌트는 없다 — `frontend/lib/ui/brand-guard.test.ts`가 토큰 파일
밖의 `dark:` 를 막는다(로고의 옛 `dark:text-paper`가 다크 테마 없이 켜져 다크
기기에서 로고 획이 사라지게 한 것이 계기다, #396). `frontend/lib/design/
contrast.test.ts`가 두 테마 각각 여섯 조합(본문/바탕·본문/뜬 면·흐린 글자 60%/
뜬 면·주 버튼 글자/바탕·통과 초록/뜬 면·주의 빨강/뜬 면)의 WCAG AA(4.5:1) 대비를
`tokens.css`를 텍스트로 읽어 계산한다 — 색을 바꿔 대비가 모자라지면 이 테스트가
빨개진다.

**테마 토글은 헤더 알림 벨 옆의 쿠키 하나다**(#398, spec #396). 두 앱 헤더에
같은 모양의 `ThemeToggle`(비로그인 방문자에게도 보인다, `AccountMenu`처럼
세션을 확인하지 않는다)이 시스템·라이트·다크 세 상태를 고른다. 고른 값은
`codemit_theme` 쿠키 하나에 담기고, **로그인 쿠키와 같은 도메인 판정
함수**(`sessionCookieDomain`, `lib/auth/cookies.ts` — dev 는 빈 값(호스트
쿠키), 배포는 부모 도메인)를 그대로 써서 공개 앱·강의실이 공유한다(ADR-0038과
같은 원칙). 쓰기는 각 앱의 `app/api/theme/route.ts`(둘 다 `force-dynamic`,
`assertSameOrigin`만 지키고 인증은 요구하지 않는다)가 하고, 두 앱의
`app/layout.tsx`가 요청마다 이 쿠키를 읽어 문서 루트에 `data-theme`를 붙인
채 그린다 — 그래서 다크를 고른 뒤 새로고침·새 탭에서도 라이트가 비치지
않는다. 쿠키 해석(`parseThemePreference`)과 표시 결정(`themeAttribute`)은
두 앱의 `lib/theme/preference.ts`에 같은 모양의 순수 함수로 복사돼 있다(토큰·
쿠키 도우미와 같은 방식). **dev(localhost 포트 구분)에서는 교차 앱 쿠키
공유가 재현되지 않는다** — 로그인 쿠키와 같은 제약이라 같은 오리진 안에서의
유지만 확인했고, 교차 공유는 staging 확인 항목으로 남는다.

**문제 설명 에디터(Toast UI, 강의실만)도 같은 표시를 따른다**(#399). 이
라이브러리는 색을 CSS 변수가 아니라 `.toastui-editor-dark` 클래스로 켠다 —
그래서 `classroom/app/components/MarkdownEditor.tsx`가
`resolveEffectiveTheme`(`lib/theme/preference.ts`, #397 과 같은 순서)로 지금
다크인지 판정해 그 클래스를 에디터 컨테이너에 직접 붙였다 뗀다. 문서 루트
표시가 바뀌면 `lib/theme/theme-bus.ts`(알림 벨의 `read-bus.ts`와 같은
window 커스텀 이벤트 방식)로, 운영체제 설정이 바뀌면 `matchMedia`로 다시
판정한다. 색 자체(툴바·괘선·코드 블록·인용·표)는 여전히
`toastui-editor-overrides.css`의 토큰 변수(`var(--color-*)`)가 정한다 — 이
클래스는 라이브러리 안쪽(툴바 아이콘 스프라이트 등 클래스 없이는 못 바꾸는
자리)만 건드린다. 참여자가 보는 문제 설명(`ProblemDescription.tsx`)은 처음부터 토큰 색만 썼으므로 이 티켓에서 고칠 것이
없었다.

**로고도 토큰·서체와 같은 방식으로 복사한다**(#392, #391 「커밋 노드 C」). 원본은
`frontend/app/components/logo-mark.tsx`(SVG 심볼)와 그것을 그리는
`frontend/app/icon.tsx`·`frontend/app/apple-icon.tsx`(Next 아이콘 파일 컨벤션)다.
`classroom/app/`의 같은 세 파일은 복사본이고, `classroom/lib/design/logo-mark.test.ts`가
한 글자라도 갈리면 빨개진다. 운영자 앱은 아이콘만 있고(주의색 타일 — 탭에서 다른 두
앱과 구별하기 위해서다) 헤더 로고도 이 비교도 없다. **강의실 가드의 matcher 는 아이콘
경로(`/icon`·`/apple-icon`)도 인증 구역에서 뺀다**(`classroom/middleware.ts`) — 안 그러면
비로그인 탭이 아이콘을 요청할 때마다 `/login`으로 튕긴다.

**두 패스는 `frontend/scripts/e2e-two-pass.sh` 하나가 정의한다(#702).** `@exclusive` 아닌 것을
병렬로(`--grep-invert @exclusive`) 돌리고, `@exclusive` 를 워커 하나로(`--grep @exclusive --workers=1`)
다시 돈다. 첫 패스가 붉어도 둘째 패스까지 간다. `package.json` 의 `test:public`·`test:operator`·
`test:classroom`, CI 의 `scripts/ci/e2e.sh`, 로컬의 `scripts/test.sh e2e` 셋이 모두 이 스크립트를
부른다 — 패스를 바꾸려면 여기만 고친다. 셋이 다른 것은 출력 폴더(환경변수 `E2E_OUTPUT_DIR`·
`E2E_EXCLUSIVE_OUTPUT_DIR`)와 일꾼 수(`PLAYWRIGHT_WORKERS`)뿐이다.

**`--pass-with-no-tests` 는 강의실의 둘째 패스에만 붙는다.** 강의실에는 아직 `@exclusive` 스펙이
없어 둘째 명령이 「No tests found」로 **exit 1** 한다(CI 가 실제로 그렇게 빨갛게 났다). 공개 앱·운영자
앱에는 붙이지 않는다 — 그쪽 `@exclusive` 스펙이 태그가 바뀌어 grep 에서 빠지면 CI 가 붉어져야 한다.
강의실에 배타 스펙이 생기면 아무것도 안 고쳐도 돌아간다(그때 이 예외를 지운다). 예외는 하나 더 —
파일 하나로 좁히는 `scripts/test.sh e2e` 는 그 파일에 한쪽 패스의 시험이 없을 수 있어
`E2E_ALLOW_EMPTY=1` 로 두 패스 모두에 붙인다.

**293건이 102건이 됐다.** 남긴 기준은 위 「남길 것」이다. 지운 것의 대부분은 「로그인된
상태에서 화면이 서버 값을 어떻게 그리는가」였고, 그 사실들은 대개 백엔드 테스트가 이미
고정하고 있다 — 여러 스펙이 자기 주석에 「백엔드가 실물로 검증한다」고 적어 두고 같은 값을
다시 단언하고 있었다. 미들웨어 가드는 `matcher` 하나에 걸린 함수 하나인데 7개 스펙이 경로
문자열만 바꿔 같은 함수를 쳤다.

**그 대가를 알고 지웠다.** 지운 것들의 회귀는 이제 아무도 잡지 않는다 — 되돌리려면 git 에서
꺼낸다(이 커밋 이전). 화면 회귀가 실제로 문제가 되기 시작하면 그때 기준을 다시 연다.

**스위트를 연달아 돌렸다면 `frontend` 컨테이너를 재시작한다.** `next dev` 의 메모리가 회차마다
늘어(측정: 4.8GB → 6.3GB) 로그인 뒤 화면 이동이 5초를 넘기기 시작하고, 그러면 매 회차
무작위로 한두 건이 로그인 헬퍼의 `toHaveURL` 타임아웃으로 붉어진다 — 코드 회귀와 구분되지 않는
모양이다. `docker compose -f docker/compose.dev.yaml restart frontend` 한 번이면 그대로 초록으로
돌아온다(로그인 헬퍼의 단언은 15초로 잡아 뒀지만 근본 원인은 이쪽이다).

**메모리가 워커 수의 실제 상한이다.** 예전 머신(WSL, Docker VM 8GB)에서는 2워커에서도
`next dev` 컨테이너가 OOM 으로 죽어 절반이 `ERR_CONNECTION_REFUSED` 로 실패했고,
VM 을 24GB 로 올린 뒤에야 4워커가 성립했다 — 그때 실측이 공개 스위트 직렬 7.4분 →
4워커 4.4분(병렬 2.8분 + 배타 1.6분)이다. 지금 머신은 네이티브 리눅스 Docker(코어 12,
호스트 RAM 약 26GB)라 조절할 VM 크기가 없고, 컨테이너가 호스트 메모리를 그대로
나눠 쓴다. 기본값 `"50%"` 는 여기서 **6워커**라 검증된 4워커보다 높다 —
`PLAYWRIGHT_WORKERS` 로 바꾸고, 올리기 전에 `docker stats` 로 여유를 먼저 본다.

**우리 화면으로 돌아가는 리다이렉트는 상대 경로로 낸다.** 컨테이너 안의 Next 는
자기가 어떤 공개 주소로 불렸는지 모른다 — `new URL(request.url).origin` 이 리버스
프록시 뒤 standalone 모드에서 공개 도메인이 아니라 **바인드 주소**로 나온다.
카카오 로그인이 실제로 `https://0.0.0.0:3000/console` 로 튕겼다(로그인은 성공하는데
도착지가 존재하지 않아 사용자에게는 깨진 것으로 보인다). `lib/auth/redirect.ts` 의
`redirectToPath` 를 쓴다 — 상대 Location 은 브라우저가 자기가 친 주소 기준으로
풀어 언제나 맞는 오리진이 되고, 환경변수도 `X-Forwarded-*` 설정도 필요 없다.
`NextResponse.redirect()` 는 절대 URL 을 요구하므로 **외부로 나갈 때만** 쓴다
(카카오 authorize 등). dev 에서는 `request.url` 이 우연히 맞아 이 버그가 보이지
않는다 — e2e 가 Location 이 `/` 로 시작하는지를 직접 단언하는 이유다.

**워크스페이스 패키지를 새로 더하면 손으로 관리되는 목록들을 같이 고쳐야 한다.**
`pnpm-workspace.yaml` 은 글롭이라 저절로 잡지만, 그 아래는 멤버를 하나씩 적어 둔다 —
`docker/frontend.Dockerfile`·`docker/operator.Dockerfile`·`docker/classroom.Dockerfile`(#276)의
COPY(각각 base·dev·builder 셋)와 `docker/compose.dev.yaml` 의 **멤버별 `node_modules` 이름
있는 볼륨**(그 패키지를 쓰는 서비스마다 하나 + 볼륨 선언). **로컬 게이트는 둘 다 보지
않는다** — `typecheck` 는 호스트의 node_modules 를 쓰고, e2e 는 로컬에서 돌리지 않기
때문이다. #166 이 `packages/route-audit` 를 더하면서 정확히 이걸 빠뜨려 CI 가 4잡 빨갛게
났고, 증상이 둘로 갈려 원인이 하나로 안 보였다:

- **deploy-guard 둘** — 프로덕션 이미지의 builder 가 `Cannot find module '@codemit/route-audit'`
  로 죽는다. 앱 소스(`lib/routes/allowlist.ts`)가 그 패키지의 타입을 쓰는데 Dockerfile 이
  패키지를 복사하지 않았다. runner 스테이지는 `.next/standalone` 만 가져가므로 실행
  이미지에는 안 들어간다 — 그래도 builder 에는 있어야 한다.
- **e2e 둘** — 러너의 `pnpm install --frozen-lockfile` 이 `EACCES ... packages/route-audit/
  node_modules/.bin/tsc` 로 죽는다. 볼륨이 없으면 바인드 마운트가 그대로 남아, 컨테이너의
  `pnpm install` 이 **호스트 경로에 root 로** 쓴다. compose 의 그 볼륨 목록 옆 주석이 경고하는
  바로 그 상황이다.

**화면을 그리는 패키지라면 둘이 더 있다**(2026-09-16, `packages/markdown`):
각 `next.config.ts` 의 `transpilePackages`(빌드되지 않는 소스 패키지라 앱 코드처럼
컴파일돼야 한다)와 **Tailwind 의 스캔 경로**. 뒤쪽이 조용한 쪽이다 — Tailwind v4 는
`node_modules` 를 건너뛰므로 패키지가 부르는 유틸리티(`mt-5`·`list-disc`·`pt-9`)가
**오류 없이 아예 만들어지지 않는다**. 실제로 한 번 그렇게 났다: 제목이 전부 본문
크기, 목록에 글머리 점 없음, 코드블록 여백이 없어 버튼이 코드 위로 겹침. 그래서
`packages/markdown/markdown.css` 가 `@source "./src"` 로 자기 소스를 등록하고 두 앱의
`globals.css` 가 그 파일을 `@import` 한다 — 앱마다 경로를 적지 않는다.

재현은 CI 와 같은 명령으로 로컬에서 된다(스택 없이 몇 분):

```bash
docker build -f docker/frontend.Dockerfile --target runner -t x .   # deploy-guard 와 같은 것
docker build -f docker/operator.Dockerfile --target runner -t y .
```

**standalone 산출물에는 `public/` 이 들어가지 않는다 — Dockerfile 이 따로 옮긴다.**
`docker/frontend.Dockerfile` 의 runner 스테이지가 `COPY … /app/frontend/public` 한
줄로 옮기고, 그 줄이 없으면 `/kakao/...` 같은 정적 자산이 **배포에서만** 404 가
된다(2026-09-16, 카카오 로그인 버튼 이미지가 prod 에서 그렇게 깨졌다). dev 는 소스를
그대로 서빙하고 부팅 가드는 `/healthz` 만 보므로 세 게이트가 전부 못 본다 — 그래서
`scripts/ci/deploy-guard.sh frontend` 가 구운 이미지에서 그 파일과 `/_next/image` 최적화 주소가
둘 다 200 인지 직접 확인한다(#297 의 「구운 이미지에만 드러나는 실패」와 같은 종류).
`operator/`·`classroom/` 에는 아직 `public/` 이 없다 — 생기면 같은 줄을 그 Dockerfile
에도 더한다.

**세 앱의 프로덕션 빌드는 Turbopack 이고, 그래서 지우면 안 되는 의존성이 둘 있다** → [`docs/ops/next-build.md`](docs/ops/next-build.md).

**API 타입은 손으로 쓰지 않는다.** `packages/bff-client/src/schema.gen.ts` 는
`pnpm --dir frontend generate:api`(`packages/bff-client/scripts/generate-api-types.mjs`)가
백엔드의 OpenAPI 스키마에서 생성해 커밋한 산출물이다. 이 명령은 **스택이 필요
없다** — `uv run python manage.py export_openapi_schema`(DB 접속 없이 등록된
라우터·스키마만 읽는다, `backend/core/management/commands/
export_openapi_schema.py`)로 스키마를 뽑은 뒤 `openapi-typescript` 로 변환한다.
`uv sync` 만 된 신선한 체크아웃에서 바로 돈다 — CI의 `frontend-openapi-types` 잡이
컨테이너를 기다리지 않고 이 명령을 그대로 돌려 `git diff`로 최신성을 확인하는
이유다. 백엔드 스키마가 바뀌었는데 재생성을 안 하면(혹은 재생성해도 필드가
없어졌는데 호출부를 안 고치면) `tsc --noEmit` 이 빌드타임에 잡는다.
