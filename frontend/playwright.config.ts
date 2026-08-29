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
  // e2e/tokens.spec.ts 는 app/tokens.css 를 실제로 편집해 렌더링이 갈리는지
  // 확인한다(FE-02, #27 핵심 승인 기준) — tracked 파일 하나를 스위트 전체가
  // 공유한다. `fullyParallel` 과 `describe.configure({ mode: "serial" })` 는
  // 같은 파일 *안에서만* 순서를 강제할 뿐이고, 다른 스펙 파일은 별도 워커에서
  // 여전히 같은 순간에 같은 페이지를 열어 토큰이 만든 색을 관찰할 수 있다.
  // 지금은 seam.spec.ts 가 색을 단언하지 않아 우연히 안전하지만, FE-04·FE-06·
  // FE-07(#29·#35·#36) 이 토큰 기반 스타일을 검증하기 시작하는 순간부터
  // 비결정적으로 깨진다. 워커를 하나로 고정해 전체 실행을 진짜로 배타적으로
  // 만든다 — 스펙 파일이 늘어도 이 보장은 구조적으로 유지된다. 스위트가 아직
  // 작아 속도 손해는 미미하다; 파일이 늘어 느려지면 그때 재검토한다.
  workers: 1,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL,
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
