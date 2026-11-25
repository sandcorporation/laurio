import { expect, test, type Browser, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 클래스 상세 — 다른 곳에서 소유자가 클래스를 보관·해제하면 공동 강사 화면이 status 로 한 번 읽어 주고 초점은 그대로다(#1528 C).

async function helperOnOwnerClass(page: Page, browser: Browser, seed: string) {
  await establishClassroomSession(page, seed);
  const ownerApi = classroomApi(page);
  const classId = (
    await (await ownerApi.post("/api/backend/classroom/classes", { data: { name: `보관 ${seed}`, instructor_display_name: "김소유" } })).json()
  ).id as number;
  const token = (await (await ownerApi.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)).json()).token as string;
  const owner = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const ownerPage = await owner.newPage();
  await establishClassroomSession(ownerPage, seed);
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  const accepted = await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
    data: { display_name: "박조교" },
  });
  expect(accepted.ok()).toBeTruthy();
  return { classId, ownerApi: classroomApi(ownerPage), close: () => owner.close() };
}

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`${viewport.width}px — 소유자가 보관하면 「클래스가 보관됐습니다」가 읽히고 「떠나기」 초점은 그대로, 해제하면 해제가 읽힌다`, async ({ page, browser }) => {
    await page.setViewportSize(viewport);
    const seed = `archived-${viewport.width}-${test.info().workerIndex}-${Date.now()}`;
    const { classId, ownerApi, close } = await helperOnOwnerClass(page, browser, seed);
    const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
    await page.goto(`/classes/${classId}?tab=instructors`);
    await stream;
    const leave = page.getByRole("button", { name: "떠나기", exact: true });
    await leave.focus();
    const note = page.getByTestId("class-archived-note");
    await expect(note).toHaveText("");

    expect((await ownerApi.post(`/api/backend/classroom/classes/${classId}/archive`)).ok()).toBeTruthy();
    await expect(note).toHaveText("클래스가 보관됐습니다", { timeout: 10_000 });
    await expect(note).toHaveAttribute("role", "status");
    await expect(leave).toBeFocused();

    expect((await ownerApi.post(`/api/backend/classroom/classes/${classId}/unarchive`)).ok()).toBeTruthy();
    await expect(note).toHaveText("클래스 보관이 해제됐습니다", { timeout: 10_000 });
    await expect(leave).toBeFocused();
    await close();
  });
}
