import { expect, test } from "@playwright/test";

import {
  classroomApi,
  establishClassroomSession,
} from "./lib/cross-app-session";

// 강의실 알림 목록의 빈 상태는 강사인 클래스가 있든 없든 「아직 알림이 없습니다.」 한 줄이다
// (#1389 시나리오 1·1-2). 강사 여부를 판정하는 동안의 대기 문구도, 언제 채워지는지 말하는 꼬리도 없다.

const EMPTY = "아직 알림이 없습니다.";

async function expectSingleEmptyLine(page: import("@playwright/test").Page) {
  await page.goto("/notifications");
  await expect(page.getByTestId("notifications-heading")).toBeVisible();
  await expect(page.getByTestId("notifications-empty")).toHaveText(EMPTY);
  await expect(page.getByTestId("notifications-empty-pending")).toHaveCount(0);
  await expect(page.getByText("채점 연결에 문제가 생기면")).toHaveCount(0);
  await expect(page.getByText("제출이 채점되면")).toHaveCount(0);
}

test("강사인 클래스가 없는 계정의 빈 알림 목록은 한 줄이다", async ({
  page,
}) => {
  await establishClassroomSession(
    page,
    `e2e-notifications-empty-fresh-${test.info().workerIndex}-${Date.now()}`,
  );
  await expectSingleEmptyLine(page);
});

test("강사인 클래스가 있어도 빈 알림 목록은 같은 한 줄이다", async ({
  page,
}) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(
    page,
    `e2e-notifications-empty-teacher-${stamp}`,
  );
  const created = await classroomApi(page).post(
    "/api/backend/classroom/classes",
    {
      data: { name: `빈 알림 ${stamp}`, instructor_display_name: "강사" },
    },
  );
  expect(created.ok()).toBeTruthy();
  await expectSingleEmptyLine(page);
});
