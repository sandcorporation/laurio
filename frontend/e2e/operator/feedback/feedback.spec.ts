import { type APIRequestContext, expect, request as playwrightRequest, test } from "@playwright/test";

import { e2eRunId } from "../../lib/run-id";
import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../../lib/seed-operator";
import { establishOperatorSession, publicOrigin } from "../../lib/session";

// 운영자 앱 제보 권한·제보 (#1243, 스펙 #1237) — 계정 켜기 → 제보(API) → 작업 중으로 바꾸면 이력에 남는다.
// 준비(운영자·제보자 계정)는 시험 한도(3초) 밖 beforeAll 에서 한다.
test.describe.configure({ mode: "serial" });

let operatorName: string;
let reporterEmail: string;
let reporter: APIRequestContext;
let reportId: number;
let reportBody: string;

test.beforeAll(async () => {
  test.setTimeout(60_000);
  const runId = e2eRunId();
  operatorName = `e2e-fbop-${runId}`.slice(0, 40);
  await seedE2eOperator({ username: operatorName, superuser: true });
  const origin = publicOrigin();
  const seed = `fbopuser${runId}`;
  reporterEmail = `${seed}@example.test`;
  reporter = await playwrightRequest.newContext({ baseURL: origin });
  const login = await reporter.post("/api/auth/social/kakao/login", {
    data: { access_token: `${seed}:${reporterEmail}` },
    headers: { origin },
  });
  expect(login.ok(), await login.text()).toBe(true);
});

test("계정을 찾아 제보 권한을 켠다", async ({ page }) => {
  await establishOperatorSession(page, operatorName, E2E_OPERATOR_PASSWORD, "/feedback-permissions");
  await page.getByTestId("feedback-permission-search-query").fill(reporterEmail);
  await page.getByTestId("feedback-permission-search-button").click();
  const row = page.locator('[data-testid^="feedback-permission-account-row-"]').filter({ hasText: reporterEmail }).first();
  await row.getByRole("button", { name: "권한 부여" }).click();
  await row.locator('input').fill("e2e");
  await row.getByRole("button", { name: "부여 확정" }).click();
  await expect(page.getByTestId("feedback-permission-granted-table")).toContainText(reporterEmail);

  // 켠 뒤 제보자가 제보 하나를 보낸다(API) — 다음 시험이 이 제보를 다룬다.
  const origin = publicOrigin();
  reportBody = `운영자 e2e 제보 ${e2eRunId()}`;
  const created = await reporter.post("/api/backend/feedback/reports", {
    data: { kind: "bug", body: reportBody, app: "contest", page_url: `${origin}/`, user_agent: "e2e-agent", screen_width: 1280, screen_height: 720, screenshot_key: "" },
    headers: { origin },
  });
  expect(created.status(), await created.text()).toBe(201);
  reportId = ((await created.json()) as { id: number }).id;
});

test("제보를 작업 중으로 바꾸면 이력에 남는다", async ({ page }) => {
  await establishOperatorSession(page, operatorName, E2E_OPERATOR_PASSWORD, "/feedback-reports");
  await page.getByTestId(`feedback-report-row-${reportId}`).click();
  await expect(page.getByTestId("feedback-report-body")).toHaveText(reportBody);
  await expect(page.getByTestId("feedback-report-user-agent")).toHaveText("e2e-agent");
  await page.getByTestId("feedback-report-next-status").selectOption("in_progress");
  await page.getByTestId("feedback-report-note").fill("확인했습니다.");
  await page.getByTestId("feedback-report-change").click();
  await expect(page.getByTestId("feedback-report-status")).toHaveText("작업 중");
  await expect(page.getByTestId("feedback-report-history").locator("li")).toHaveCount(1);
  await expect(page.getByTestId("feedback-report-history")).toContainText("확인했습니다.");
});
