import { expect, test, type Browser } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 13차 사용 리뷰 #1507 B·C·D — 학생의 문제 목록·홈 링크.
//  B: 보관된 클래스는 목록 위에 「보관됨 · 읽기 전용」이 있고 마감을 재촉하지 않으며, 홈 링크는 읽기 전용을 말한다.
//  C: 홈의 「문제 풀기」·「지난 시도 보기」 링크는 접근성 이름에 클래스 이름을 담는다.
//  D: 「채점 대기 · 마감 기한 뒤」 배지가 행 상자 안에 머문다(데스크톱·390px).

async function setup(browser: Browser, baseURL: string | undefined, seed: string, className: string) {
  const instructorContext = await browser.newContext({ baseURL });
  const instructorPage = await instructorContext.newPage();
  await establishClassroomSession(instructorPage, seed);
  const api = classroomApi(instructorPage);
  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", { data: { name: className, instructor_display_name: "강사" } })
    ).json()
  ).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;
  async function openProblem(title: string, due: Date): Promise<number> {
    const created = await api.post(`${base}/problems`, {
      data: { title, submission_formats: ["repository"], due_at: due.toISOString() },
    });
    expect(created.ok()).toBeTruthy();
    const id = (await created.json()).id as number;
    expect(
      (await api.post(`${base}/problems/${id}/checklist-items`, { data: { label: "통과 조건", required: true } })).ok(),
    ).toBeTruthy();
    expect((await api.post(`${base}/problems/${id}/open`)).ok()).toBeTruthy();
    return id;
  }
  const joinCode = (await (await api.get(base)).json()).join_code as string;
  return { api, classId, base, openProblem, joinCode };
}

test("보관된 클래스의 학생 목록은 보관을 알리고 마감을 재촉하지 않으며 홈 링크가 읽기 전용을 말한다", async ({ page, browser }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  const seed = `participant-archived-${stamp}`;
  const archivedName = `보관된 클래스 ${stamp}`;
  const liveName = `진행 중 클래스 ${stamp}`;
  const baseURL = test.info().project.use.baseURL;

  const archived = await setup(browser, baseURL, seed, archivedName);
  const soon = await archived.openProblem("곧 마감 문제", new Date(Date.now() + 40 * 60_000));
  const past = await archived.openProblem("마감 지난 문제", new Date(Date.now() - 36 * 3600_000));
  const live = await setup(browser, baseURL, `${seed}-live`, liveName);
  await live.openProblem("진행 중 문제", new Date(Date.now() + 40 * 60_000));

  await establishClassroomSession(page, `${seed}-participant`);
  const participantApi = classroomApi(page);
  for (const joinCode of [archived.joinCode, live.joinCode]) {
    expect(
      (await participantApi.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "서지우" } })).ok(),
    ).toBeTruthy();
  }
  expect((await archived.api.post(`${archived.base}/archive`)).ok()).toBeTruthy();

  // C·B — 홈 링크: 이름에 클래스가 있고, 보관이면 읽기 전용을 말한다.
  await page.goto("/");
  const archivedLink = page.getByRole("link", { name: `지난 시도 보기 ${archivedName}`, exact: true });
  await expect(archivedLink).toHaveText("지난 시도 보기");
  await expect(archivedLink).toHaveAttribute("href", `/classes/${archived.classId}/problems/mine`);
  const liveLink = page.getByRole("link", { name: `문제 풀기 ${liveName}`, exact: true });
  await expect(liveLink).toHaveText("문제 풀기");

  // B — 목록: 보관 안내가 있고, 「곧 마감」·「마감 지남」·주의색이 없다.
  await archivedLink.click();
  await expect(page.getByTestId("my-problems-archived-note")).toHaveText("보관됨 · 읽기 전용");
  for (const id of [soon, past]) {
    const due = page.getByTestId(`my-problem-row-${id}-due`);
    await expect(due).toBeVisible();
    await expect(due).not.toContainText("곧 마감");
    await expect(due).not.toContainText("마감 지남");
    await expect(due).toHaveAttribute("data-tone", "faint");
  }

  // 진행 중인 클래스는 그대로 재촉한다 — 보관 안내도 없다.
  await page.goto(`/classes/${live.classId}/problems/mine`);
  await expect(page.getByTestId("my-problems-archived-note")).toHaveCount(0);
  await expect(page.locator('[data-testid$="-due"]').first()).toContainText("곧 마감");
});

for (const viewport of [
  { name: "데스크톱", width: 1280, height: 900 },
  { name: "390px", width: 390, height: 844 },
]) {
  test(`채점 대기 · 마감 기한 뒤 배지가 행 안에 머문다 (${viewport.name})`, async ({ page, browser }) => {
    const stamp = `${test.info().workerIndex}-${Date.now()}`;
    const seed = `participant-badge-${viewport.width}-${stamp}`;
    const klass = await setup(browser, test.info().project.use.baseURL, seed, `배지 클래스 ${stamp}`);
    const past = await klass.openProblem("마감 지난 문제", new Date(Date.now() - 36 * 3600_000));

    await establishClassroomSession(page, `${seed}-participant`);
    const participantApi = classroomApi(page);
    expect(
      (await participantApi.post(`/api/backend/classroom/join/${klass.joinCode}`, { data: { display_name: "서지우" } })).ok(),
    ).toBeTruthy();
    const submitted = await participantApi.post(`${klass.base}/problems/${past}/submissions`, {
      data: { value: `https://github.com/octocat/e2e-${past}`, submission_format: "repository" },
    });
    expect(submitted.ok()).toBeTruthy();

    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.goto(`/classes/${klass.classId}/problems/mine`);
    const status = page.getByTestId(`my-problem-row-${past}-status`);
    await expect(status).toHaveText("채점 대기 · 마감 기한 뒤");

    const row = (await page.getByTestId(`my-problem-row-${past}-link`).boundingBox())!;
    const badge = (await status.locator("span").first().boundingBox())!;
    // 상태 칸 경계 안에 든다 — 행은 칸보다 넓어 칸 밖으로 넘친 배지가 이웃 칸(마감)과 겹쳐도 행 경계만 보면 통과한다(#1510 이전 판).
    const cell = (await status.boundingBox())!;
    expect(badge.x).toBeGreaterThanOrEqual(cell.x - 1);
    expect(badge.x + badge.width).toBeLessThanOrEqual(cell.x + cell.width + 1);
    expect(badge.y).toBeGreaterThanOrEqual(cell.y - 1);
    expect(badge.y + badge.height).toBeLessThanOrEqual(cell.y + cell.height + 1);
    // 한 픽셀 여유 — 테두리 반올림.
    expect(badge.x).toBeGreaterThanOrEqual(row.x - 1);
    expect(badge.x + badge.width).toBeLessThanOrEqual(row.x + row.width + 1);
    expect(badge.y).toBeGreaterThanOrEqual(row.y - 1);
    expect(badge.y + badge.height).toBeLessThanOrEqual(row.y + row.height + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
}

// #1507 A — 보관된 클래스의 제출 화면은 마감 지남 배지·붉은 마감 줄로 재촉하지 않는다.
test("보관된 클래스의 제출 화면은 마감 지남 배지와 주의색 없이 흐린 마감만 보인다", async ({ page, browser }) => {
  const stamp = `${test.info().workerIndex}-${Date.now()}`;
  const seed = `participant-archived-submit-${stamp}`;
  const archived = await setup(browser, test.info().project.use.baseURL, seed, `보관 제출 ${stamp}`);
  const past = await archived.openProblem("마감 지난 문제", new Date(Date.now() - 36 * 3600_000));
  await establishClassroomSession(page, `${seed}-participant`);
  expect(
    (await classroomApi(page).post(`/api/backend/classroom/join/${archived.joinCode}`, { data: { display_name: "서지우" } })).ok(),
  ).toBeTruthy();
  expect((await archived.api.post(`${archived.base}/archive`)).ok()).toBeTruthy();

  await page.goto(`/classes/${archived.classId}/problems/${past}/submit`);
  await expect(page.getByTestId("class-archived-note")).toBeVisible();
  await expect(page.getByTestId("submit-deadline-passed")).toHaveCount(0);
  await expect(page.getByTestId("submit-deadline-note")).toHaveCount(0);
  const due = page.getByTestId("submit-due-rows-due");
  await expect(due).toBeVisible();
  await expect(due).not.toContainText("마감 지남");
  await expect(due).toHaveAttribute("data-tone", "faint");
});
