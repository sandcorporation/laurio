import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 참여자 문제 목록(#639, 시안 v2 Mine). 머리의 진행 한 줄(n/m 통과 · 채점 중 a · 채점 대기 c · 미제출 b),
// 한 줄 행(시도 k회 · 마지막 …, 배지 하나, 행 전체가 링크), 접힌 「숨겨진 문제 N」을 본다.
// 통과·미통과 낱말은 백엔드 시험(test_classroom_my_problems_progress.py)이 맡는다 — 채점은 상주
// grader 라 여기서 「채점 중」을 붙들 수 없어, 키 없는 클래스로 「채점 대기」를 만든다 — 멈춘 시도는
// 참여자 제출 화면·제출 현황과 같은 「채점 대기」다(#670).
test("참여자 문제 목록이 진행 한 줄과 한 줄 행으로 보인다", async ({ page, browser }) => {
  const seed = `participant-list-${test.info().workerIndex}-${Date.now()}`;

  const instructorContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructorPage = await instructorContext.newPage();
  await establishClassroomSession(instructorPage, seed);
  const api = classroomApi(instructorPage);

  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `목록 테스트 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;

  async function openProblem(title: string): Promise<number> {
    const created = await api.post(`${base}/problems`, {
      data: { title, submission_formats: ["repository"] },
    });
    expect(created.ok()).toBeTruthy();
    const id = (await created.json()).id as number;
    const item = await api.post(`${base}/problems/${id}/checklist-items`, {
      data: { label: "통과 조건", required: true },
    });
    expect(item.ok()).toBeTruthy();
    expect((await api.post(`${base}/problems/${id}/open`)).ok()).toBeTruthy();
    return id;
  }
  const waiting = await openProblem("제출한 문제");
  const untouched = await openProblem("안 낸 문제");
  const hidden = await openProblem("숨길 문제");

  const joinCode = (await (await api.get(base)).json()).join_code as string;
  await establishClassroomSession(page, `${seed}-participant`);
  const participantApi = classroomApi(page);
  expect(
    (await participantApi.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } })).ok(),
  ).toBeTruthy();
  for (const id of [waiting, hidden]) {
    const submitted = await participantApi.post(`${base}/problems/${id}/submissions`, {
      data: { value: `https://github.com/octocat/e2e-${id}`, submission_format: "repository" },
    });
    expect(submitted.ok()).toBeTruthy();
  }
  expect((await api.post(`${base}/problems/${hidden}/hide`)).ok()).toBeTruthy();

  await page.goto(`/classes/${classId}/problems/mine`);

  await expect(page.getByTestId("my-problems-progress-count")).toHaveText("0/2 통과");
  await expect(page.getByText(/^목록 테스트 \d+ · 강사$/)).toBeVisible();
  await expect(page.getByTestId("my-problems-progress-rest")).toHaveText("채점 대기 1 · 미제출 1");
  await expect(page.getByTestId(`my-problem-row-${waiting}-status`)).toHaveText("채점 대기");
  await expect(page.getByTestId(`my-problem-row-${waiting}-attempts`)).toContainText("시도 1회 · 마지막");
  await expect(page.getByTestId(`my-problem-row-${untouched}-status`)).toHaveText("미제출");
  await expect(page.getByTestId(`my-problem-row-${untouched}-attempts`)).toHaveCount(0);

  const toggle = page.getByTestId("hidden-problems-toggle");
  await expect(toggle).toHaveText(/숨겨진 문제 1/);
  await expect(page.getByTestId("hidden-problems-list")).toHaveCount(0);
  await toggle.click();
  await expect(page.getByTestId(`my-problem-row-${hidden}-status`)).toHaveText("채점 대기");

  await page.getByTestId(`my-problem-row-${untouched}-link`).click();
  await expect(page).toHaveURL(new RegExp(`/problems/${untouched}/submit$`));
});

// 390px 에서도 기한·「곧 마감」·「마감 지남」이 제목 아래 줄에 보이고, 시도 수 칸만 숨는다(#1440).
test("390px 문제 목록은 제목 아래 줄에 기한·곧 마감·마감 지남을 보인다", async ({ page, browser }) => {
  const seed = `participant-due-${test.info().workerIndex}-${Date.now()}`;
  const instructorContext = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructorPage = await instructorContext.newPage();
  await establishClassroomSession(instructorPage, seed);
  const api = classroomApi(instructorPage);
  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `기한 테스트 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;

  async function openProblem(title: string, due: Date | null): Promise<number> {
    const created = await api.post(`${base}/problems`, {
      data: { title, submission_formats: ["repository"], due_at: due ? due.toISOString() : null },
    });
    expect(created.ok()).toBeTruthy();
    const id = (await created.json()).id as number;
    expect(
      (await api.post(`${base}/problems/${id}/checklist-items`, { data: { label: "통과 조건", required: true } })).ok(),
    ).toBeTruthy();
    expect((await api.post(`${base}/problems/${id}/open`)).ok()).toBeTruthy();
    return id;
  }
  const soon = await openProblem("곧 마감 문제", new Date(Date.now() + 40 * 60_000));
  const past = await openProblem("마감 지난 문제", new Date(Date.now() - 36 * 3600_000));
  const none = await openProblem("기한 없는 문제", null);

  const joinCode = (await (await api.get(base)).json()).join_code as string;
  await establishClassroomSession(page, `${seed}-participant`);
  expect(
    (await classroomApi(page).post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } })).ok(),
  ).toBeTruthy();

  await page.setViewportSize({ width: 390, height: 900 });
  await page.goto(`/classes/${classId}/problems/mine`);

  const soonDue = page.getByTestId(`my-problem-row-${soon}-due`);
  const pastDue = page.getByTestId(`my-problem-row-${past}-due`);
  await expect(soonDue).toBeVisible();
  await expect(soonDue).toContainText("곧 마감");
  await expect(pastDue).toBeVisible();
  await expect(pastDue).toContainText("마감 지남");
  // 기한 줄은 제목 아래에 선다 — 같은 행 안, 제목보다 아래.
  const title = await page.getByTestId(`my-problem-row-${soon}-link`).locator("span").first().boundingBox();
  const dueBox = await soonDue.boundingBox();
  expect(dueBox!.y).toBeGreaterThan(title!.y + title!.height - 1);
  // 기한 없는 행엔 빈 줄이 없다 — 높이가 기한 있는 행보다 낮다.
  const noneRow = await page.getByTestId(`my-problem-row-${none}`).boundingBox();
  const soonRow = await page.getByTestId(`my-problem-row-${soon}`).boundingBox();
  expect(noneRow!.height).toBeLessThan(soonRow!.height);
  // 가로로 넘치지 않는다.
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);

  // 넓은 폭에서는 한 줄 그대로 — 기한이 제목과 같은 높이에 선다.
  await page.setViewportSize({ width: 1280, height: 900 });
  const wideTitle = await page.getByTestId(`my-problem-row-${soon}-link`).locator("span").first().boundingBox();
  const wideDue = await soonDue.boundingBox();
  expect(Math.abs(wideDue!.y - wideTitle!.y)).toBeLessThan(wideTitle!.height);
});
