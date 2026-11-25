import { expect, test, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 문서 제목은 어느 화면이든 「… · Codemit」 한 꼴이다(#393, #1400).
async function newClass(page: Page, label: string) {
  const stamp = `${label}-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, `tab-title-${stamp}`);
  const name = `제목 확인 ${stamp}`;
  const created = await classroomApi(page).post("/api/backend/classroom/classes", {
    data: { name, instructor_display_name: "강사" },
  });
  expect(created.ok()).toBeTruthy();
  const row = (await created.json()) as { id: number; join_code: string };
  return { name, ...row };
}

// 탭 전환은 같은 화면 안의 주소 바꿈이라 제목이 루트 기본값으로 되돌아가면 안 된다.
test("클래스 상세는 탭을 바꿔도 제목이 클래스 이름이다", async ({ page }) => {
  const { id, name } = await newClass(page, "tabs");
  await page.goto(`/classes/${id}`);
  await expect(page).toHaveTitle(`${name} · Codemit`);
  await page.getByTestId("detail-tab-instructors").click();
  await expect(page.getByTestId("co-instructor-invite-create")).toBeVisible();
  await expect(page).toHaveTitle(`${name} · Codemit`);
});

test("알림·초대·가입 화면의 제목도 같은 꼴이다", async ({ page }) => {
  const { name, join_code } = await newClass(page, "screens");
  await page.goto("/notifications");
  await expect(page).toHaveTitle("알림 · Codemit");
  await page.goto("/invite/no-such-token");
  await expect(page).toHaveTitle("강사 초대 · Codemit");
  await page.goto(`/join/${join_code}`);
  await expect(page).toHaveTitle(`${name} · Codemit`);
});
