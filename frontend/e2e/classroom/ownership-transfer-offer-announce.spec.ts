import { expect, test, type Browser, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 받는 공동 강사에게 소유권 제안이 왔다는 것이 낭독된다(#1490). 처음 열 때는 초점이 카드로 가고(이름·설명이 읽힌다),
// 열어 둔 채 신호로 오면 다른 곳의 초점을 빼앗지 않고 늘 있는 상태 영역이 읽는다. 보내는 쪽의 「답을 기다립니다」는
// 받는 사람에게 상태로 읽히지 않는다.

const ARRIVED = "김소유님이 소유권을 넘기려 합니다 — 받기 또는 거절할 수 있습니다.";

async function setup(page: Page, browser: Browser, seed: string) {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const ownerPage = await context.newPage();
  await establishClassroomSession(ownerPage, seed);
  const owner = classroomApi(ownerPage);
  const classId = (
    await (
      await owner.post("/api/backend/classroom/classes", {
        data: { name: `제안 낭독 ${seed}`, instructor_display_name: "김소유" },
      })
    ).json()
  ).id as number;
  const token = (await (await owner.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)).json())
    .token as string;
  await establishClassroomSession(page, `${seed}-helper`);
  expect(
    (
      await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  async function requestTransfer() {
    const roster = (await (await owner.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
      co_instructor_id: number | null;
    }[];
    const requested = await owner.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
      data: { co_instructor_id: roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id },
    });
    expect(requested.ok()).toBeTruthy();
  }
  return { classId, requestTransfer, close: () => context.close() };
}

async function expectOfferFocused(page: Page) {
  const region = page.getByRole("region", { name: "소유권 이전 요청" });
  await expect(region).toBeFocused();
  await expect(region).toHaveAccessibleDescription(/김소유님이 이 클래스의 소유권을 나에게 넘기려 합니다/);
  await expect(page.getByRole("status").filter({ hasText: "까지 답을 기다립니다" })).toHaveCount(0);
  await expect(page.getByTestId("ownership-transfer-pending-other")).toHaveText(/나에게 온 요청 · .* 까지 답할 수 있습니다/);
}

test("처음 열 때 — 이미 와 있는 제안이 초점으로 낭독되고 보내는 쪽 문구는 상태로 읽히지 않는다", async ({ page, browser }) => {
  const seed = `offer-open-${test.info().workerIndex}-${Date.now()}`;
  const ctx = await setup(page, browser, seed);
  await ctx.requestTransfer();
  await page.goto(`/classes/${ctx.classId}?tab=instructors`);
  await expectOfferFocused(page);
  // 키보드: 카드에서 Tab 한 번에 수락 단추.
  await page.keyboard.press("Tab");
  await expect(page.getByTestId("ownership-transfer-accept")).toBeFocused();
  await ctx.close();
});

test("열어 둔 채 — 신호로 도착한 제안이 상태 영역으로 읽히고 다른 곳의 초점을 빼앗지 않는다", async ({ page, browser }) => {
  const seed = `offer-signal-${test.info().workerIndex}-${Date.now()}`;
  const ctx = await setup(page, browser, seed);
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(`/classes/${ctx.classId}?tab=instructors`);
  await stream;
  await expect(page.getByTestId("class-instructors-count")).toHaveText("2명");
  const tab = page.getByRole("tab", { name: /강사/ });
  await tab.focus();

  await ctx.requestTransfer();
  await expect(page.getByTestId("ownership-transfer-offer")).toBeVisible({ timeout: 10_000 });
  await expect(page.getByRole("status").filter({ hasText: ARRIVED })).toHaveCount(1);
  await expect(tab).toBeFocused();
  await expect(page.getByRole("status").filter({ hasText: "까지 답을 기다립니다" })).toHaveCount(0);
  await expect(page.getByTestId("ownership-transfer-pending-other")).toHaveText(/나에게 온 요청/);
  await ctx.close();
});

test("열어 둔 채 초점이 아무 데도 없으면 — 신호로 도착한 제안이 초점을 받는다", async ({ page, browser }) => {
  const seed = `offer-signal-body-${test.info().workerIndex}-${Date.now()}`;
  const ctx = await setup(page, browser, seed);
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(`/classes/${ctx.classId}?tab=instructors`);
  await stream;
  await expect(page.getByTestId("class-instructors-count")).toHaveText("2명");
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());

  await ctx.requestTransfer();
  await expectOfferFocused(page);
  await ctx.close();
});

test.describe("390px 터치", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("처음 열면 제안 카드가 화면 안에 있고 수락 단추가 눌린다", async ({ page, browser }) => {
    const seed = `offer-touch-${test.info().workerIndex}-${Date.now()}`;
    const ctx = await setup(page, browser, seed);
    await ctx.requestTransfer();
    await page.goto(`/classes/${ctx.classId}?tab=instructors`);
    await expectOfferFocused(page);
    const accept = page.getByTestId("ownership-transfer-accept");
    await expect(accept).toBeInViewport();
    await page.getByTestId("ownership-transfer-decline").tap();
    await expect(page.getByTestId("ownership-transfer-offer")).toHaveCount(0);
    await ctx.close();
  });
});
