import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 「모두 읽음」(#1476) — 누르면 단추가 사라지므로 초점이 목록 제목으로 가고, 늘 있는 status 영역이 결과를 읽는다.
// 키보드(Enter)·낭독기(status 글) 길을 본다. 안 읽은 알림은 소유권 이전 요청을 받은 공동 강사에게 생긴다.

test("「모두 읽음」을 Enter 로 누르면 초점이 알림 제목으로 가고 status 가 결과를 읽는다", async ({ page }) => {
  const seed = `mark-all-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const owner = classroomApi(page);
  const created = await owner.post("/api/backend/classroom/classes", {
    data: { name: `모두 읽음 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const token = (await (await owner.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)).json()).token as string;

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
  await page.goto("/notifications");
  const status = page.getByTestId("notifications-status");
  await expect(status).toHaveAttribute("role", "status");
  await expect(status).toHaveText("");

  const markAll = page.getByTestId("notifications-mark-all-read");
  await markAll.focus();
  await page.keyboard.press("Enter");

  await expect(markAll).toHaveCount(0);
  await expect(page.getByTestId("notifications-heading")).toBeFocused();
  await expect(status).toHaveText("알림을 모두 읽음으로 표시했습니다");
});
