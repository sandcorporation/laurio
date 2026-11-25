import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 채점 연결이 없는 클래스에 참여자가 내면 소유자에게 「연결 없음」 알림이 한 번 가고,
// 더 내도 늘지 않으며, 누르면 그 클래스 설정의 채점 키 자리로 간다(#1389 시나리오 2·3).
//
// 준비는 시임 규약(ADR-0017/0021)대로 `classroomApi` 로 백엔드 API 를 직접 친다. 키를 넣지 않으므로
// grader 가 시도를 집지 않고, 알림은 제출이 커밋된 뒤의 콜백이 만든다 — 늦어도 60초 스캔이 맡지만
// 이 스펙은 콜백 쪽을 본다(제출 직후 화면을 연다).

test("연결 없는 클래스에 참여자가 두 번 내도 강사 알림은 한 줄이고, 누르면 채점 키 설정으로 간다", async ({
  page,
}) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  const ownerSeed = `e2e-key-missing-owner-${stamp}`;
  const className = `연결 없음 알림 ${stamp}`;

  await establishClassroomSession(page, ownerSeed);
  const api = classroomApi(page);

  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: className, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;

  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: "1주차", submission_formats: ["repository"] },
  });
  expect(problemResponse.ok()).toBeTruthy();
  const problemId = (await problemResponse.json()).id as number;

  const checklistResponse = await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`,
    { data: { label: "README 가 있다", required: true } },
  );
  expect(checklistResponse.ok()).toBeTruthy();

  const openResponse = await api.post(
    `/api/backend/classroom/classes/${classId}/problems/${problemId}/open`,
  );
  expect(openResponse.ok()).toBeTruthy();

  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json())
    .join_code as string;

  const submit = async (n: number) => {
    const response = await api.post(
      `/api/backend/classroom/classes/${classId}/problems/${problemId}/submissions`,
      {
        data: {
          value: `https://github.com/octocat/codemit-e2e-key-missing-${stamp}-${n}`,
          submission_format: "repository",
        },
      },
    );
    expect(response.ok()).toBeTruthy();
  };

  const asOwner = async () => {
    await page.context().clearCookies();
    await establishClassroomSession(page, ownerSeed);
  };

  const missingLink = page.locator(`a[href$="/classes/${classId}/scoring-key"]`);
  const badge = page.getByTestId("classroom-notification-badge");

  // 시나리오 2 — 참여자가 한 번 낸다.
  await page.context().clearCookies();
  await establishClassroomSession(page, `e2e-key-missing-participant-${stamp}`);
  const joinResponse = await api.post(`/api/backend/classroom/join/${joinCode}`, {
    data: { display_name: "참여자" },
  });
  expect(joinResponse.ok()).toBeTruthy();
  await submit(1);

  await asOwner();
  await page.goto("/notifications");
  await expect(page.getByTestId("notifications-heading")).toBeVisible();
  await expect(missingLink).toHaveCount(1);
  await expect(missingLink).toContainText(`'${className}' 클래스에 채점 연결이 없어`);
  await expect(badge).toHaveText("1");

  // 시나리오 3 — 참여자가 한 번 더 낸다. 열린 기록이 있으므로 새 알림이 없다.
  await page.context().clearCookies();
  await establishClassroomSession(page, `e2e-key-missing-participant-${stamp}`);
  await submit(2);

  await asOwner();
  await page.goto("/notifications");
  await expect(page.getByTestId("notifications-heading")).toBeVisible();
  await expect(missingLink).toHaveCount(1);
  await expect(badge).toHaveText("1");

  await missingLink.click();
  await expect(page).toHaveURL(new RegExp(`/classes/${classId}/settings#scoring-key$`));
});
