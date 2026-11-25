import { expect, test, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 클래스 상세 — 지난 소유권 안내(넘겨받음·거절)를 걷을 때 그 안에 있던 초점이 BODY 로 떨어지지 않는다(#1525 ①).
// 20초 뒤 걷기는 시계를 앞당겨 보고, 새 이전 요청이 와서 걷는 길은 실제 신호로 본다.

const viewports = [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
];

/** 소유자(seed)가 클래스를 만들고 공동 강사(`${seed}-helper`)가 초대를 수락한 뒤 소유자가 이전 요청을 보낸다. 쿠키는 공동 강사 쪽. */
async function classWithRequestForHelper(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const ownerApi = classroomApi(page);
  const classId = (
    await (await ownerApi.post("/api/backend/classroom/classes", { data: { name: `지난 안내 ${seed}`, instructor_display_name: "김소유" } })).json()
  ).id as number;
  const token = (await (await ownerApi.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)).json()).token as string;
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  const accepted = await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
    data: { display_name: "박조교" },
  });
  expect(accepted.ok()).toBeTruthy();
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const roster = (await (await classroomApi(page).get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  const requested = await classroomApi(page).post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: coId },
  });
  expect(requested.ok()).toBeTruthy();
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  return { classId, coId: coId as number };
}

async function openWithStream(page: Page, url: string) {
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(url);
  await stream;
}

for (const viewport of viewports) {
  test(`${viewport.width}px — 넘겨받은 안내의 「채점 키 넣기」에 초점이 있어도 20초 뒤 안내가 걷히면 제목이 초점을 받는다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const seed = `past-timer-${viewport.width}-${test.info().workerIndex}-${Date.now()}`;
    const { classId } = await classWithRequestForHelper(page, seed);
    await page.clock.install();
    await openWithStream(page, `/classes/${classId}`);
    await page.getByTestId("ownership-transfer-accept").click();
    const note = page.getByRole("status").filter({ has: page.getByTestId("ownership-transfer-accepted-note") });
    await expect(note).toBeFocused();
    await page.getByRole("link", { name: "채점 키 넣기" }).focus();

    await page.clock.fastForward(21_000);
    await expect(page.getByTestId("ownership-transfer-accepted-note")).toHaveCount(0);
    await expect(page.getByTestId("classroom-detail-heading")).toBeFocused();
  });

  test(`${viewport.width}px — 초점이 안내 밖(제목 아닌 다른 칸)이면 걷어도 초점을 빼앗지 않는다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const seed = `past-outside-${viewport.width}-${test.info().workerIndex}-${Date.now()}`;
    const { classId } = await classWithRequestForHelper(page, seed);
    await page.clock.install();
    await openWithStream(page, `/classes/${classId}`);
    await page.getByTestId("ownership-transfer-accept").click();
    await expect(page.getByTestId("ownership-transfer-accepted-note")).toBeVisible();
    const settings = page.getByTestId("class-settings-link");
    await settings.focus();

    await page.clock.fastForward(21_000);
    await expect(page.getByTestId("ownership-transfer-accepted-note")).toHaveCount(0);
    await expect(settings).toBeFocused();
  });

  test(`${viewport.width}px — 거절 안내에 초점이 있을 때 새 이전 요청이 오면 새 요청 카드가 초점을 받는다`, async ({ page, browser }) => {
    await page.setViewportSize(viewport);
    const seed = `past-new-${viewport.width}-${test.info().workerIndex}-${Date.now()}`;
    const { classId } = await classWithRequestForHelper(page, seed);
    await openWithStream(page, `/classes/${classId}`);
    await page.getByTestId("ownership-transfer-decline").click();
    const note = page.getByRole("status").filter({ has: page.getByTestId("ownership-transfer-declined-note") });
    await expect(note).toBeFocused();

    // 소유자가 다시 요청한다 — 지난 「거절했습니다」는 걷히고 초점은 새 요청 카드로 간다.
    const owner = await browser.newContext({ baseURL: test.info().project.use.baseURL });
    const ownerPage = await owner.newPage();
    await establishClassroomSession(ownerPage, seed);
    const roster = (await (await classroomApi(ownerPage).get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
      co_instructor_id: number | null;
    }[];
    const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
    const again = await classroomApi(ownerPage).post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
      data: { co_instructor_id: coId },
    });
    expect(again.ok()).toBeTruthy();
    await owner.close();

    await expect(page.getByTestId("ownership-transfer-declined-note")).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByRole("region", { name: "소유권 이전 요청" })).toBeFocused();
  });

  test(`${viewport.width}px — 넘겨받은 안내에 초점이 있을 때 새 이전 요청을 보내면 제목이 초점을 받는다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const seed = `past-new-owner-${viewport.width}-${test.info().workerIndex}-${Date.now()}`;
    const { classId } = await classWithRequestForHelper(page, seed);
    await openWithStream(page, `/classes/${classId}`);
    await page.getByTestId("ownership-transfer-accept").click();
    await expect(page.getByTestId("ownership-transfer-accepted-note")).toBeVisible();
    await page.getByRole("link", { name: "채점 키 넣기" }).focus();

    // 새 소유자가 예전 소유자에게 다시 넘기려 한다 — 요청은 같은 쿠키(새 소유자)로 API 가 보낸다.
    const roster = (await (await classroomApi(page).get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
      co_instructor_id: number | null;
    }[];
    const back = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
    const requested = await classroomApi(page).post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
      data: { co_instructor_id: back },
    });
    expect(requested.ok()).toBeTruthy();

    await expect(page.getByTestId("ownership-transfer-accepted-note")).toHaveCount(0, { timeout: 10_000 });
    await expect(page.getByTestId("classroom-detail-heading")).toBeFocused();
  });
}
