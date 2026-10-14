import { defineConfig, devices } from "@playwright/test";

// ADR-0021(ADR-0017 개정) — 이 프로젝트의 프론트엔드 테스트 시임은 **앱마다 실행
// 중인 Next 앱 하나**다. 앱이 둘(공개 앱·운영자 앱)이 됐지만 그 아래로 내려가는
// 컴포넌트 테스트·모킹은 여전히 없다 — Playwright 프로젝트를 둘로 나눠 한 번의
// 실행으로 둘 다 검증한다.
//
// 그래서 여기에는 `webServer` 블록이 없다. 테스트가 앱의 수명을 소유하지 않는다는
// 뜻이며, 의도적이다. 앱은 compose 로 띄우고 테스트는 그걸 친다:
//
//   docker compose -f docker/compose.dev.yaml up -d
//   pnpm --dir frontend test
//
// 브라우저가 필요한 것은 `page` 로, 아닌 것(라우트 핸들러·프록시 허용목록·Origin
// 검증)은 raw `request` 로 친다 — 같은 시임, 같은 입구다.
//
// 스펙 파일은 앱별로 디렉터리로 갈린다: 공개 앱은 `e2e/*.spec.ts`(기존과 동일),
// 운영자 앱은 `e2e/operator/*.spec.ts`. 프로젝트마다 자기 testDir 과 baseURL 을
// 갖는다 — 허용목록의 내용이 앱마다 갈려 있다는 사실(ADR-0021)이 여기서도 같은
// 모양으로 반복된다.

// **로컬 실행은 `scripts/test.sh e2e` 를 거쳐야만 한다**(2026-10-02) — 그 스크립트가 기계 전체 동시
// 둘·코어 1/3 을 지키고, 이 워크트리 코드로 구운 프로덕션 이미지 스택을 띄운다. 칸을 잡은 뒤
// `CODEMIT_TEST_ENTRY` 를 내보낸다. CI(Jenkins 의 scripts/ci/e2e.sh)도 같은 표식을 준다.
if (!process.env.CI && !process.env.CODEMIT_TEST_ENTRY) {
  throw new Error(
    "로컬 e2e 는 scripts/test.sh e2e 로만 돌린다 — 예) scripts/test.sh e2e --project=operator e2e/operator/appeals.spec.ts",
  );
}

const publicBaseURL = process.env.CODEMIT_E2E_BASE_URL ?? "http://127.0.0.1:53000";
const operatorBaseURL = process.env.CODEMIT_OPERATOR_E2E_BASE_URL ?? "http://127.0.0.1:53001";
const classroomBaseURL = process.env.CODEMIT_CLASSROOM_E2E_BASE_URL ?? "http://127.0.0.1:53002";

function workersFromEnv(value: string | undefined): number | string | undefined {
  if (value === undefined || value.trim() === "") return undefined;
  return /^\d+$/.test(value.trim()) ? Number(value) : value;
}

export default defineConfig({
  // 운영자 큐 시드가 "이번 실행"과 "이전 실행"을 구별할 토큰을 스위트 시작 시
  // 한 번 발급한다(코드리뷰 지적, #70 — e2e/lib/run-id.ts 상단 주석 참고).
  globalSetup: require.resolve("./e2e/global-setup.ts"),
  fullyParallel: true,
  // **워커 여럿으로 돈다** (#104). 예전에는 `workers: 1` 이었다 —
  // `e2e/tokens.spec.ts` 가 app/tokens.css 를 실제로 편집해(FE-02 #27 의 핵심
  // 승인 기준) 그 창 동안 다른 워커가 여는 모든 페이지가 바뀐 색을 보기
  // 때문이었다(그 스펙 자체는 01a4ae3 에서 지워졌다 — 아래 장치는 남는다:
  // 전역 상태를 건드리는 스펙은 언제든 다시 생긴다). `fullyParallel` 과 `describe.configure({ mode: "serial" })` 는
  // 같은 파일 안에서만 순서를 강제해 그것을 막지 못한다.
  //
  // 이제 그 보장은 워커 수가 아니라 **실행을 두 패스로 나누는 것**이 진다
  // (scripts/e2e-two-pass.sh — package.json 의 test 스크립트·CI·scripts/test.sh 가 부른다) — `@exclusive` 태그가 없는 것을 먼저 병렬로,
  // 그 다음 태그가 붙은 것만 워커 하나로 돌린다. 스펙 파일이 늘어도 그 보장은
  // 유지된다: 전역 상태를 건드리는 스펙은 그 태그를 붙이면 된다.
  //
  // 시드 충돌은 다른 방식으로 막았다 — `seed_e2e_contests` 가 워커별
  // 네임스페이스로 자기 범위만 지운다(e2e/lib/seed.ts 의 workerNamespace).
  // **운영자 프로젝트는 이 값을 쓰지 않는다** — package.json 의 test:operator 가
  // `--workers=1` 로 못 박는다. 그쪽 스펙은 큐의 **전체 건수**를 단언하고(홈의 세
  // 숫자가 심은 것과 정확히 맞는지), 「0건은 0건이라고 말한다」는 테스트는 아예
  // 빈 큐를 요구한다 — 다른 워커가 무엇이든 심는 순간 둘 다 깨진다. 실제로 2워커로
  // 돌려 4건이 그렇게 실패하는 것을 확인했다. 그걸 풀려면 운영자 큐 시드에도
  // 워커별 네임스페이스가 필요하고, 그건 이 티켓 범위를 넘는다.
  // 기본값은 머신에 맞춰 정해진다("50%" = 코어의 절반) — 하드코딩하면 작은
  // 머신에서는 죽고 큰 머신에서는 논다. 실측: 이 저장소의 개발 머신에서 공개
  // 스위트가 직렬 7.4분 → 4워커 4.4분(병렬 패스 2.8분 + 배타 패스 1.6분).
  //
  // **메모리가 워커 수의 실제 상한이다.** Docker VM 이 8GB 였을 때는 2워커에서도
  // `next dev` 컨테이너가 OOM 으로 죽어 절반이 ERR_CONNECTION_REFUSED 로
  // 실패했다 — 24GB 로 올린 뒤에야 4워커가 성립했다. 이 값을 올리기 전에
  // `docker stats` 로 여유를 먼저 본다.
  // `PLAYWRIGHT_WORKERS` 는 숫자("4")와 퍼센트("50%") 둘 다 받는다 — 문자열 "4" 를 그대로 넘기면
  // Playwright 가 "config.workers must be a number or percentage" 로 **설정 로딩 단계에서** 죽는다
  // (CLAUDE.md 가 이 변수로 워커를 낮추라고 안내하는데 그 말대로 하면 실행조차 안 됐다).
  workers: workersFromEnv(process.env.PLAYWRIGHT_WORKERS) ?? "50%",
  forbidOnly: !!process.env.CI,
  // **재시도하지 않는다**(2026-10-02). 예전에는 CI 에서 한 번 재시도했는데, 그것이
  // 흔들리는 시험을 초록으로 덮었다 — 강의실 「죽은 세션」 시험이 30초 타임아웃으로
  // 떨어졌다가 재시도로 통과한 것이 로그에만 남아 아무도 보지 못했다. 흔들리는
  // 시험은 지우지 않고 그 자리에서 원인을 고친다.
  retries: 0,
  // **시험 하나는 3초 안에 끝난다**(앞뒤 걸이 포함, 2026-10-02). 넘으면 한도를
  // 늘리지 않고 원인을 줄인다 — 준비는 화면이 아니라 API 로, 기다림은 시간이 아니라
  // 사건으로 한다.
  timeout: 3_000,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    // 재시도가 없으니 "on-first-retry" 는 영영 남지 않는다 — 실패한 시험의 것만 남긴다.
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "public",
      testDir: "./e2e",
      testIgnore: ["**/operator/**", "**/classroom/**"],
      use: { ...devices["Desktop Chrome"], baseURL: publicBaseURL },
    },
    {
      name: "operator",
      testDir: "./e2e/operator",
      use: { ...devices["Desktop Chrome"], baseURL: operatorBaseURL },
    },
    {
      name: "classroom",
      testDir: "./e2e/classroom",
      use: { ...devices["Desktop Chrome"], baseURL: classroomBaseURL },
    },
  ],
});
