// 「내 참가 현황」 (#74) — 로그인한 Developer 가 자기 제출들과 「다음 행동」을 본다.
//
// 시임은 실행 중인 공개 앱 하나다(ADR-0017/0021). 로그인·본인확인·제출은
// submit.spec.ts 가 세운 것과 같은 방식으로 브라우저를 통해 한다 — 백엔드를
// 직접 찌르지 않고 사용자가 걷는 길을 그대로 걷는다.
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";
import { establishDeveloperSession } from "./lib/session";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await establishDeveloperSession(page, seed);
}

test("참가한 게 없으면 빈 목록이라고 말한다 — 조회 실패와 구별된다", async ({ page }) => {
  await login(page, `e2e-part-empty-${Date.now()}`);

  await page.goto("/console/participation");

  await expect(page.getByTestId("participation-heading")).toBeVisible();
  await expect(page.getByTestId("participation-empty")).toContainText("아직 참가한 공모전이 없습니다");
  await expect(page.getByTestId("participation-error")).toHaveCount(0);
  await expect(page.getByTestId("participation-list")).toHaveCount(0);
});

test("조회에 실패하면 실패했다고 말한다 — 0건처럼 보이지 않는다", async ({ page }) => {
  await login(page, `e2e-part-error-${Date.now()}`);

  // 이 화면이 부르는 경로만 좁게 실패시킨다.
  await page.route("**/api/backend/submissions/mine*", (route) =>
    route.fulfill({ status: 500, contentType: "application/json", body: "{}" }),
  );

  await page.goto("/console/participation");

  await expect(page.getByTestId("participation-error")).toBeVisible();
  await expect(page.getByTestId("participation-empty")).toHaveCount(0);
});

test("홈에서 클릭으로 도달한다 — URL 을 직접 쳐야만 닿는 화면이 아니다", async ({ page }) => {
  await login(page, `e2e-part-link-${Date.now()}`);

  await page.getByTestId("app-home-participation-link").click();

  await expect(page).toHaveURL(/\/console\/participation/);
  await expect(page.getByTestId("participation-heading")).toBeVisible();
});

test("세션이 없으면 렌더링 전에 로그인으로 돌아간다 — 보호된 내용이 응답에 없다", async ({
  page,
}) => {
  const response = await page.goto("/console/participation");

  expect(response?.status()).toBeLessThan(400);
  await expect(page).toHaveURL(/\/login/);
  const body = await page.content();
  expect(body).not.toContain("내 참가 현황");
});

test("제출한 뒤에는 그 행이 「다음 행동」을 먼저 말한다", async ({ page }) => {
  // 시드가 만든 "제출이 있는 Developer" 로 로그인한다 — 개최·결제·제출을 UI 로
  // 다시 걷는 것은 이 화면이 검증하려는 것과 무관한 비용이다.
  const seeded = await seedE2eContests();
  await login(page, seeded.judging.developer_login_seed);

  await page.goto("/console/participation");

  await expect(page.getByTestId("participation-list")).toBeVisible();
  const rows = page.getByTestId("participation-list").locator("li");
  await expect(rows.first()).toBeVisible();
  expect(await rows.count()).toBeGreaterThan(0);

  // 값 자체는 서버가 판정한다 — 화면은 그것을 문구로 옮길 뿐이다. 어떤 값이든
  // 「알 수 없음」으로 떨어지지 않는 것이 여기서 확인할 것이다.
  const first = rows.first();
  const action = await first.getAttribute("data-next-action");
  expect(action).toBeTruthy();
  await expect(first.getByTestId(/participation-row-\d+-next-action/)).not.toBeEmpty();
});
