import { expect, test, type Browser, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 강사 탭 — 공동 강사가 다른 곳에서 떠나거나 내보내져 줄이 사라질 때(#1517 1), 소유자 탭은 그 사실을 상태로
// 읽어 주고 줄 안에 있던 초점을 늘 있는 「초대 링크 만들기」로 옮긴다. 묵은 안내는 새 상태가 오면 걷힌다(취향 1).

async function otherSession(browser: Browser, seed: string) {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const page = await context.newPage();
  await establishClassroomSession(page, seed);
  return { context, api: classroomApi(page) };
}

async function ownerClass(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const classId = (
    await (await api.post("/api/backend/classroom/classes", { data: { name: `떠남 ${seed}`, instructor_display_name: "김소유" } })).json()
  ).id as number;
  const invite = async () =>
    (await (await api.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)).json()).token as string;
  return { classId, api, invite };
}

async function openWithStream(page: Page, url: string) {
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(url);
  await stream;
}

for (const viewport of [
  { width: 1280, height: 900 },
  { width: 390, height: 844 },
]) {
  for (const how of ["leave", "remove"] as const) {
    test(`${viewport.width}px — 다른 곳에서 공동 강사가 ${how === "leave" ? "떠나면" : "내보내지면"} 소유자 탭이 읽어 주고 초점이 초대 링크 만들기로 간다`, async ({
      page,
      browser,
    }) => {
      await page.setViewportSize(viewport);
      const seed = `depart-${how}-${viewport.width}-${test.info().workerIndex}-${Date.now()}`;
      const { classId, api, invite } = await ownerClass(page, seed);
      const helper = await otherSession(browser, `${seed}-helper`);
      const accepted = await helper.api.post(`/api/backend/classroom/co-instructor-invites/${await invite()}/accept`, {
        data: { display_name: "박조교" },
      });
      expect(accepted.ok()).toBeTruthy();

      await openWithStream(page, `/classes/${classId}?tab=instructors`);
      await expect(page.getByTestId("class-instructors-count")).toHaveText("2명");
      await page.getByTestId("co-instructor-remove").focus();

      if (how === "leave") {
        expect((await helper.api.post(`/api/backend/classroom/classes/${classId}/instructors/me/leave`)).ok()).toBeTruthy();
      } else {
        const roster = (await (await api.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as Array<{
          co_instructor_id: number | null;
        }>;
        const id = roster.find((r) => r.co_instructor_id !== null)!.co_instructor_id;
        expect((await api.post(`/api/backend/classroom/classes/${classId}/co-instructors/${id}/remove`)).ok()).toBeTruthy();
      }
      await helper.context.close();

      await expect(page.getByTestId("class-instructors-count")).toHaveText("1명", { timeout: 10_000 });
      const note = page.getByTestId("co-instructor-departed-note");
      await expect(note).toHaveText(how === "leave" ? "박조교님이 클래스를 떠났습니다" : "박조교님이 클래스에서 내보내졌습니다");
      await expect(note).toHaveAttribute("role", "status");
      await expect(page.getByTestId("co-instructor-invite-create")).toBeFocused();
    });
  }
}

test("묵은 안내 — 초대 수락 문구는 새 소유권 이전 요청이 걸리면 걷힌다", async ({ page, browser }) => {
  const seed = `depart-stale-${test.info().workerIndex}-${Date.now()}`;
  const { classId, invite } = await ownerClass(page, seed);
  await openWithStream(page, `/classes/${classId}?tab=instructors`);
  const helper = await otherSession(browser, `${seed}-helper`);
  expect(
    (
      await helper.api.post(`/api/backend/classroom/co-instructor-invites/${await invite()}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  await helper.context.close();
  const accepted = page.getByTestId("co-instructor-accepted-note");
  await expect(accepted).toHaveText("박조교 님이 초대를 수락했습니다", { timeout: 10_000 });

  await page.getByTestId("ownership-transfer-start").click();
  await page.getByTestId("ownership-transfer-confirm-button").click();
  await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
  await expect(accepted).toHaveText("");
});

test("묵은 안내 — 「넘겨받았습니다」 안내는 새 이전 요청이 오면 클래스 상세에서 사라진다", async ({ page, browser }) => {
  const seed = `stale-taken-${test.info().workerIndex}-${Date.now()}`;
  const { classId, api, invite } = await ownerClass(page, seed);
  const helper = await otherSession(browser, `${seed}-helper`);
  expect(
    (
      await helper.api.post(`/api/backend/classroom/co-instructor-invites/${await invite()}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  const base = `/api/backend/classroom/classes/${classId}`;
  const rosterOf = async (who: typeof api) =>
    (await (await who.get(`${base}/instructors`)).json()) as { co_instructor_id: number | null }[];
  const toHelper = (await rosterOf(api)).find((r) => r.co_instructor_id !== null)!.co_instructor_id;
  const requested = await api.post(`${base}/ownership-transfers`, { data: { co_instructor_id: toHelper } });
  expect(requested.ok()).toBeTruthy();
  const transferId = (await requested.json()).id as number;

  await openWithStream(page, `/classes/${classId}?tab=instructors`);
  expect((await helper.api.post(`${base}/ownership-transfers/${transferId}/accept`)).ok()).toBeTruthy();
  const taken = page.getByTestId("ownership-transfer-taken-note");
  await expect(taken).toBeVisible({ timeout: 10_000 });

  // 새 소유자가 나에게 다시 넘기려 한다 — 지난 「넘겨받았습니다」는 새 요청 카드와 함께 남지 않는다.
  const back = (await rosterOf(helper.api)).find((r) => r.co_instructor_id !== null)!.co_instructor_id;
  expect((await helper.api.post(`${base}/ownership-transfers`, { data: { co_instructor_id: back } })).ok()).toBeTruthy();
  await expect(page.getByTestId("ownership-transfer-offer-arrived-note")).not.toBeEmpty({ timeout: 10_000 });
  await expect(taken).toHaveCount(0);
  await helper.context.close();
});
