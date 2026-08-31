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

export default defineConfig({
  fullyParallel: true,
  // e2e/tokens.spec.ts 는 app/tokens.css 를 실제로 편집해 렌더링이 갈리는지
  // 확인한다(FE-02, #27 핵심 승인 기준) — tracked 파일 하나를 스위트 전체가
  // 공유한다. `fullyParallel` 과 `describe.configure({ mode: "serial" })` 는
  // 같은 파일 *안에서만* 순서를 강제할 뿐이고, 다른 스펙 파일(다른 프로젝트
  // 포함)은 별도 워커에서 여전히 같은 순간에 같은 페이지를 열어 토큰이 만든
  // 색을 관찰할 수 있다. 워커를 하나로 고정해 전체 실행(두 프로젝트 합쳐)을
  // 진짜로 배타적으로 만든다 — 스펙 파일이나 프로젝트가 늘어도 이 보장은
  // 구조적으로 유지된다.
  workers: 1,
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
