import { defineConfig, devices } from "@playwright/test";

// ADR-0017 — 이 프로젝트의 프론트엔드 테스트 시임은 **실행 중인 Next 앱 하나**다.
//
// 그래서 여기에는 `webServer` 블록이 없다. 테스트가 앱의 수명을 소유하지 않는다는
// 뜻이며, 의도적이다. 앱은 compose 로 띄우고 테스트는 그걸 친다:
//
//   docker compose -f docker/compose.dev.yaml up -d
//   pnpm --dir frontend test
//
// 브라우저가 필요한 것은 `page` 로, 아닌 것(라우트 핸들러·프록시 허용목록·Origin
// 검증)은 raw `request` 로 친다 — 같은 시임, 같은 입구다.

const baseURL = process.env.LAURIO_E2E_BASE_URL ?? "http://127.0.0.1:53000";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
