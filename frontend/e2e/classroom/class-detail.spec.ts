import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 클래스 상세 화면(시안 v2, #633). 판정 로직(집계·채점 상태 조건)은 백엔드 pytest 와 프런트
// 단위 시험이 고정하므로, 여기서 브라우저로 걷는 것은 화면의 두 갈래뿐이다 — 방금 연 클래스의
// 「시작하기」와, 문제·참여자가 생긴 뒤의 머리·가입 링크·표·「채점」 카드(키가 없는 상태).
// 준비는 API 로 직접 친다(ADR-0017/0021).

test("방금 연 클래스는 시작하기 카드와 빈 목록의 입구를 보이고, 탭은 주소가 말한다", async ({ page }) => {
  const seed = `class-detail-empty-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `방금 연 클래스 ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(created.ok()).toBeTruthy();
  const classId = (await created.json()).id as number;

  await page.goto(`/classes/${classId}`);
  await expect(page.getByTestId("class-stat-members")).toContainText("0");
  await expect(page.getByTestId("class-stat-average-rate")).toContainText("—");
  await expect(page.getByTestId("join-link")).toContainText("/join/");
  await expect(page.getByTestId("getting-started")).toBeVisible();
  await expect(page.getByTestId("getting-started-connect")).toHaveAttribute("data-done", "false");
  await expect(page.getByTestId("problems-empty-state")).toBeVisible();
  await expect(page.getByTestId("problems-empty-copy")).toBeVisible();
  // 방금 연 클래스에는 「채점」 카드가 아직 없다 — 시작하기가 그 자리다.
  await expect(page.getByTestId("scoring-card-status")).toHaveCount(0);

  await page.getByTestId("detail-tab-instructors").click();
  await expect(page).toHaveURL(`/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("class-instructors")).toBeVisible();
  await page.getByTestId("detail-tab-participants").click();
  await expect(page).toHaveURL(`/classes/${classId}?tab=participants`);
  await expect(page.getByTestId("members-link")).toBeVisible();
});

test("문제와 참여자가 생기면 표와 채점 카드가 들어오고, 키가 없으면 연결 없음을 말한다", async ({ page }) => {
  const seed = `class-detail-table-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);

  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `표 확인용 클래스 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;

  const problemTitle = `표 확인 문제 ${Date.now()}`;
  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title: problemTitle, submission_formats: ["repository"] },
  });
  const problemId = (await problemResponse.json()).id as number;
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`, {
    data: { label: "통과 조건", required: true },
  });
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/open`);

  await page.context().clearCookies();
  await establishClassroomSession(page, `${seed}-participant`);
  await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "참여자" } });
  await page.context().clearCookies();
  await establishClassroomSession(page, seed);

  await page.goto(`/classes/${classId}`);
  await expect(page.getByTestId("class-stat-members")).toContainText("1");
  await expect(page.getByTestId("class-stat-problems")).toContainText("1");
  await expect(page.getByTestId(`problem-row-${problemId}`)).toContainText(problemTitle);
  await expect(page.getByTestId(`problem-row-${problemId}-submissions`)).toBeVisible();

  // 문제와 참여자가 둘 다 있으면 시작하기 대신 채점 카드다 — 키가 없으니 연결 없음과 갈 곳.
  await expect(page.getByTestId("getting-started")).toHaveCount(0);
  await expect(page.getByTestId("classroom-missing-api-key-banner")).toContainText("연결 없음");
  await expect(page.getByTestId("classroom-missing-api-key-settings-link")).toHaveAttribute(
    "href",
    `/classes/${classId}/settings#scoring-key`,
  );

  // 가입 링크 띠 — 다시 뽑으면 주소가 바뀐다.
  const before = await page.getByTestId("join-link").innerText();
  await page.getByTestId("join-link-regenerate").click();
  await expect(page.getByTestId("join-link")).not.toHaveText(before);
});
