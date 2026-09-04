// ContestView — 조회수와 전환율 (#109, 부모 #105, `CONTEXT.md`의 `ContestView`).
//
// 중복 제거·날짜 경계·Sponsor 자기 조회 배제·방문자 식별값 부재는
// backend/tests/test_contest_metrics.py 가 실물로 검증한다(시임은 HTTP다,
// CLAUDE.md). 여기서 확인할 것은 두 앱을 가로지르는 실제 왕복이다: 브라우저가
// 공개 상세를 열면 백엔드가 조회를 세고, 그 수가 Sponsor 지표 화면에
// 조회수·전환율로 나타나는가 — 그리고 그 신호가 정말 "브라우저가 마운트된
// 뒤"에만 나가는가(JS 를 끈 방문자는 세지 않는다, ADR-0015 와 같은 자리의
// side-effect-free 렌더).
import { expect, test } from "@playwright/test";

import { seedE2eContests } from "./lib/seed";

async function login(page: import("@playwright/test").Page, seed: string): Promise<void> {
  await page.goto("/login");
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId("login-kakao").click();
  await expect(page).toHaveURL(/\/console/, { timeout: 15_000 });
}

test("공모전 상세를 열면 조회가 세어지고 Sponsor 지표에 조회수·전환율로 보인다", async ({
  page,
}) => {
  const seeded = await seedE2eContests();

  // 로그인하지 않은 방문자가 공개 상세를 연다 — 마운트된 뒤 클라이언트
  // 컴포넌트가 `POST /api/backend/contests/{id}/views`를 쏜다. 그 왕복이
  // 끝난 뒤에야 지표를 확인해야 경합 없이 값을 본다.
  const [viewResponse] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.url().includes(`/api/backend/contests/${seeded.judging.id}/views`) &&
        res.request().method() === "POST",
    ),
    page.goto(`/contests/${seeded.judging.id}`),
  ]);
  expect(viewResponse.ok()).toBe(true);

  await login(page, seeded.judging.sponsor_login_seed);
  await page.goto(`/console/contests/${seeded.judging.id}/metrics`);

  await expect(page.getByTestId("metrics-view")).toBeVisible();
  await expect(page.getByTestId("metrics-view-count")).toHaveText("1");
  // 시드가 이 Contest 에 Submission 을 2건 심어 두므로(contest-metrics.spec.ts
  // 참고) 조회가 1이면 전환율 자리가 채워진다 — 정확한 퍼센트가 아니라 "0으로
  // 나누지 않고 값이 나온다"는 것만 여기서 확인한다(정확한 산식은 backend
  // 테스트가 이미 검증했다).
  await expect(page.getByTestId("metrics-conversion-rate")).toBeVisible();
  await expect(page.getByTestId("metrics-conversion-rate")).toContainText("%");
  await expect(page.getByTestId("metrics-conversion-rate-empty")).toHaveCount(0);
});

test("Sponsor 자신의 조회는 지표에 잡히지 않는다", async ({ page }) => {
  const seeded = await seedE2eContests();

  await login(page, seeded.judging.sponsor_login_seed);

  // 로그인한 채로 자기 Contest 의 공개 상세를 새로고침한다 — 자기 지표를
  // 스스로 부풀리지 않아야 한다.
  const [viewResponse] = await Promise.all([
    page.waitForResponse(
      (res) =>
        res.url().includes(`/api/backend/contests/${seeded.judging.id}/views`) &&
        res.request().method() === "POST",
    ),
    page.goto(`/contests/${seeded.judging.id}`),
  ]);
  expect(viewResponse.ok()).toBe(true);

  await page.goto(`/console/contests/${seeded.judging.id}/metrics`);

  await expect(page.getByTestId("metrics-view-count")).toHaveText("0");
  await expect(page.getByTestId("metrics-conversion-rate-empty")).toBeVisible();
});

test("JS 를 끈 방문자는 세지 않는다 — 서버 렌더만으로는 조회가 늘지 않는다", async ({
  browser,
}) => {
  const seeded = await seedE2eContests();

  const noJsContext = await browser.newContext({ javaScriptEnabled: false });
  const noJsPage = await noJsContext.newPage();
  const response = await noJsPage.goto(`/contests/${seeded.judging.id}`);
  expect(response?.status()).toBeLessThan(400);
  await noJsContext.close();

  const sponsorContext = await browser.newContext();
  const sponsorPage = await sponsorContext.newPage();
  await login(sponsorPage, seeded.judging.sponsor_login_seed);
  await sponsorPage.goto(`/console/contests/${seeded.judging.id}/metrics`);

  await expect(sponsorPage.getByTestId("metrics-view-count")).toHaveText("0");
  await sponsorContext.close();
});
