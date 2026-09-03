// Sponsor 지표 화면 (#107, 부모 #105) — 「참가작을 하나씩 열어보는 것뿐」이던
// Sponsor 가 자기 Contest 의 참가 추이를 본다.
//
// 값 자체(일자별 누적 참가작 수가 실제 Submission 수와 일치하는지, 0 과 「없음」이
// 다른 층에서 결정되는지, 소유권 경계)는 backend/tests/test_contest_metrics.py
// 가 실물로 검증한다 — 여기서 확인할 것은 화면이 콘솔에서 클릭으로 닿고, 백엔드가
// 준 값을 그대로 보여주는가다(ADR-0017/0021).
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/);
}

test("내 공모전 목록에서 클릭만으로 지표 화면에 닿는다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto("/console/contests");
  await page.getByTestId(`my-contest-row-${seeded.judging.id}-metrics`).click();

  await expect(page).toHaveURL(new RegExp(`/console/contests/${seeded.judging.id}/metrics`));
  await expect(page.getByTestId("metrics-contest-title")).toBeVisible();
});

test("일자별 누적 참가작 수가 실제 참가작 수와 함께 보인다", async ({ page }) => {
  const seeded = seedE2eContests();
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto(`/console/contests/${seeded.judging.id}/metrics`);

  // 시드는 이 Contest 에 Submission 을 2건 심는다(seed_e2e_contests.py).
  await expect(page.getByTestId("metrics-total-submission-count")).toHaveText("2");
  await expect(page.getByTestId("metrics-participation-trend")).toBeVisible();
  await expect(page.getByTestId("metrics-participation-table")).toBeVisible();
  await expect(page.getByTestId("metrics-participation-empty")).toHaveCount(0);

  // 누적이 실제 2건과 맞아야 한다 — 화면이 스스로 다시 세지 않고 백엔드가 이미
  // 묶어 준 값을 그대로 보여준다는 뜻이다.
  const rows = page.getByTestId("metrics-participation-table").locator("tbody tr");
  const lastRowText = await rows.last().textContent();
  expect(lastRowText).toContain("2");
});

test("남의 Contest 지표로는 닿을 수 없다 — 있는지가 아니라 없는지를 본다", async ({ page }) => {
  const seeded = seedE2eContests();
  // judging Contest 의 Sponsor 로 로그인해, 자기 것이 아닌 funded Contest 의
  // 지표를 직접 URL 로 열어본다 — 기존 심사 비교 화면과 같은 소유권 검사를
  // 그대로 쓰므로 403 이어야 한다.
  await login(page, seeded.judging.sponsor_login_seed);

  await page.goto(`/console/contests/${seeded.funded.id}/metrics`);

  await expect(page.getByTestId("metrics-forbidden")).toBeVisible();
  await expect(page.getByTestId("metrics-total-submission-count")).toHaveCount(0);
  await expect(page.getByTestId("metrics-participation-trend")).toHaveCount(0);
});

test("세션이 없으면 렌더링 전에 로그인으로 돌아간다 — 보호된 지표가 응답에 없다", async ({
  page,
}) => {
  const seeded = seedE2eContests();

  const response = await page.goto(`/console/contests/${seeded.judging.id}/metrics`);

  expect(response?.status()).toBeLessThan(400);
  await expect(page).toHaveURL(/\/login/);
  expect(await page.content()).not.toContain("참가 추이");
});
