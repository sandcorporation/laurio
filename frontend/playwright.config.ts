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

const publicBaseURL = process.env.LAURIO_E2E_BASE_URL ?? "http://127.0.0.1:53000";
const operatorBaseURL = process.env.LAURIO_OPERATOR_E2E_BASE_URL ?? "http://127.0.0.1:53001";

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
  // 때문이었다. `fullyParallel` 과 `describe.configure({ mode: "serial" })` 는
  // 같은 파일 안에서만 순서를 강제해 그것을 막지 못한다.
  //
  // 이제 그 보장은 워커 수가 아니라 **실행을 두 패스로 나누는 것**이 진다
  // (package.json 의 test 스크립트) — `@exclusive` 태그가 없는 것을 먼저 병렬로,
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
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    trace: "on-first-retry",
  },
  projects: [
    {
      name: "public",
      testDir: "./e2e",
      testIgnore: ["**/operator/**"],
      use: { ...devices["Desktop Chrome"], baseURL: publicBaseURL },
    },
    {
      name: "operator",
      testDir: "./e2e/operator",
      use: { ...devices["Desktop Chrome"], baseURL: operatorBaseURL },
    },
  ],
});
