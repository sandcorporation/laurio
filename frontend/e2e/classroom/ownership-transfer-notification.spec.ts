import { expect, test, type Page } from "@playwright/test";

import {
  classroomApi,
  establishClassroomSession,
} from "./lib/cross-app-session";

// 받는 사람이 클래스를 떠나 소유권 이전 요청이 지워졌다(#1448 일부-6·②) — 받은 알림은 「끝난 요청」이라고 말하고
// 수락·거절을 청하지 않는다. 알림 줄은 링크라 키보드 초점·낭독기 이름·390px 터치가 같은 문구에 닿는다.

const GONE = "소유권 이전 요청은 이미 끝났습니다 — 더 답할 것이 없습니다.";

async function recipientWhoseRequestWasRemoved(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const ownerApi = classroomApi(page);
  const created = await ownerApi.post("/api/backend/classroom/classes", {
    data: { name: `이전 알림 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const invited = await ownerApi.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`);
  const token = (await invited.json()).token as string;

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  const accepted = await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
    data: { display_name: "박조교" },
  });
  expect(accepted.ok()).toBeTruthy();

  // 소유자가 이전을 요청한 뒤 그 공동 강사를 내보낸다 — 대기 요청은 행째 지워진다.
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);
  const owner = classroomApi(page);
  const roster = (await (await owner.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  const requested = await owner.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: coId },
  });
  expect(requested.ok()).toBeTruthy();
  const removed = await owner.post(`/api/backend/classroom/classes/${classId}/co-instructors/${coId}/remove`);
  expect(removed.status()).toBe(204);

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
}

test("지워진 요청의 알림은 끝난 요청이라고 말한다 — 키보드 초점과 낭독기 이름", async ({ page }) => {
  await recipientWhoseRequestWasRemoved(page, `transfer-gone-${test.info().workerIndex}-${Date.now()}`);

  await page.goto("/notifications");
  const row = page.getByRole("link", { name: new RegExp(GONE) });
  await expect(row).toBeVisible();
  await expect(page.getByText("수락하거나 거절해 주세요")).toHaveCount(0);

  await row.focus();
  await expect(row).toBeFocused();
});

test.describe("390px 터치", () => {
  test.use({ viewport: { width: 390, height: 844 }, hasTouch: true, isMobile: true });

  test("지워진 요청의 알림은 좁은 화면에서도 끝난 요청이라고 말하고 눌린다", async ({ page }) => {
    await recipientWhoseRequestWasRemoved(page, `transfer-gone-touch-${test.info().workerIndex}-${Date.now()}`);

    await page.goto("/notifications");
    const row = page.getByRole("link", { name: new RegExp(GONE) });
    await expect(row).toBeInViewport();
    await expect(page.getByText("수락하거나 거절해 주세요")).toHaveCount(0);
    const href = await row.getAttribute("href");
    await row.tap();
    await expect(page).toHaveURL(new RegExp(`${href!.split("?")[0]}`));
  });
});
