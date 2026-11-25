import { expect, test } from "@playwright/test";

import { backendBase } from "../../lib/feedback-permission";
import { e2eRunId } from "../../lib/run-id";
import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../../lib/seed-operator";
import { establishOperatorSession } from "../../lib/session";

// 운영자 앱 제보 권한·제보 (#1243, 스펙 #1237) — 계정 켜기 → 제보(API) → 작업 중으로 바꾸면 이력에 남는다.
// 준비(운영자·제보자 계정)는 시험 한도(3초) 밖 beforeAll 에서 한다. 제보자 로그인·제보는 backend 포트를 직접
// 친다 — CI 의 운영자 조각은 공개 앱(53000)을 띄우지 않는다(seed-operator.ts 의 직접 호출과 같은 길).
test.describe.configure({ mode: "serial" });

let operatorName: string;
let reporterEmail: string;
let reporterAccess: string;
let reportId: number;
let reportBody: string;

test.beforeAll(async () => {
  test.setTimeout(60_000);
  const runId = e2eRunId();
  operatorName = `e2e-fbop-${runId}`.slice(0, 40);
  await seedE2eOperator({ username: operatorName, superuser: true });
  const seed = `fbopuser${runId}`;
  reporterEmail = `${seed}@example.test`;
  const login = await fetch(`${backendBase()}/api/auth/social/kakao/login`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ access_token: `${seed}:${reporterEmail}` }),
  });
  const loginText = await login.text();
  expect(login.ok, loginText).toBe(true);
  reporterAccess = (JSON.parse(loginText) as { access: string }).access;
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
  reportBody = `운영자 e2e 제보 ${e2eRunId()}`;
  const created = await fetch(`${backendBase()}/api/feedback/reports`, {
    method: "POST",
    headers: { "content-type": "application/json", authorization: `Bearer ${reporterAccess}` },
    body: JSON.stringify({ kind: "bug", body: reportBody, app: "contest", page_url: "http://127.0.0.1:53000/", user_agent: "e2e-agent", screen_width: 1280, screen_height: 720, screenshot_key: "" }),
  });
  const createdText = await created.text();
  expect(created.status, createdText).toBe(201);
  reportId = (JSON.parse(createdText) as { id: number }).id;
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

// 운영자 앱도 공용 `normalizeDetail` 의 422 한국어를 받는다(#1390) — 응답만 바꿔 끼운다.
test("상태 바꾸기가 422 면 한국어가 보이고 영어 원문은 없다", async ({ page }) => {
  await page.route(
    (url) => url.pathname === `/api/backend/operator/feedback-reports/${reportId}/status`,
    (route) =>
      route.fulfill({
        status: 422,
        json: {
          detail: [
            {
              type: "string_too_long",
              loc: ["body", "payload", "title"],
              msg: "String should have at most 200 characters",
              ctx: { max_length: 200 },
            },
          ],
        },
      }),
  );
  await establishOperatorSession(page, operatorName, E2E_OPERATOR_PASSWORD, `/feedback-reports/${reportId}`);

  await page.getByTestId("feedback-report-change").click();

  await expect(page.getByTestId("feedback-report-change-error")).toHaveText("200자까지 쓸 수 있습니다.");
  await expect(page.getByText("String should")).toHaveCount(0);
});
