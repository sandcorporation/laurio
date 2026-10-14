import { expect, test, type Page } from "@playwright/test";

import {
  classroomApi,
  establishClassroomSession,
} from "./lib/cross-app-session";

// 강의실 — 클래스 상세의 강사 탭(시안 v2, #635). 소유권 이전·초대 링크 만들기·떠나기는 서버 상태를
// 바꾸므로 화면만 보고 끝내지 않고 끝까지 간다. 권한 표·만료·1회용은 백엔드 pytest 가 고정한다.
// 준비(클래스·초대 수락)는 세션을 바꿔 가며 API 를 직접 친다.

async function openClassWithCoInstructor(page: Page, seed: string) {
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `강사 탭 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const invited = await api.post(
    `/api/backend/classroom/classes/${classId}/co-instructor-invites`,
  );
  const token = (await invited.json()).token as string;
  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-helper`);
  const accepted = await classroomApi(page).post(
    `/api/backend/classroom/co-instructor-invites/${token}/accept`,
    {
      data: { display_name: "박조교" },
    },
  );
  expect(accepted.ok()).toBeTruthy();
  return classId;
}

test("강사 탭 — 소유자가 초대 링크를 만들고 소유권을 넘기겠다 요청했다가 취소한다", async ({
  page,
}) => {
  const seed = `instructors-tab-owner-${test.info().workerIndex}-${Date.now()}`;
  const classId = await openClassWithCoInstructor(page, seed);
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);

  await page.goto(`/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("class-instructors-count")).toHaveText("2명");
  await expect(page.getByTestId("class-leave")).toBeDisabled();

  await page.getByTestId("co-instructor-invite-create").click();
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1);

  await page.getByTestId("ownership-transfer-start").click();
  await page.getByTestId("ownership-transfer-confirm-button").click();
  await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
  await expect(page.getByTestId("ownership-transfer-start")).toHaveCount(0);
  // 대기 중인 줄에는 「요청 취소」만 — 내보내기가 없다(#669).
  await expect(page.getByTestId("co-instructor-remove")).toHaveCount(0);

  // 새로고침해도 대기 중이고, 취소하면 다시 넘길 수 있다.
  await page.reload();
  await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
  await page.getByTestId("ownership-transfer-cancel").click();
  await expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0);
  await expect(page.getByTestId("ownership-transfer-start")).toBeVisible();
  await expect(page.getByTestId("co-instructor-remove")).toBeVisible();
});

test("강사 탭 — 공동 강사는 소유자 전용 행동 없이 떠나기만 보고, 떠나면 내 클래스 목록으로 간다", async ({
  page,
}) => {
  const seed = `instructors-tab-helper-${test.info().workerIndex}-${Date.now()}`;
  const classId = await openClassWithCoInstructor(page, seed);

  await page.goto(`/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("class-instructor-row")).toHaveCount(2);
  await expect(page.getByTestId("ownership-transfer-start")).toHaveCount(0);
  await expect(page.getByTestId("co-instructor-remove")).toHaveCount(0);

  await page.getByTestId("class-leave").click();
  await page.getByTestId("class-leave-confirm-button").click();
  await expect(page).toHaveURL("/");
  const gone = await classroomApi(page).get(
    `/api/backend/classroom/classes/${classId}`,
  );
  expect(gone.ok()).toBeFalsy();
});
