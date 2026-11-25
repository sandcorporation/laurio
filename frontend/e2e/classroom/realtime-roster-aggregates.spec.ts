import { expect, test, type Browser, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 집계 대상이 바뀌면 열어 둔 참여자 격자와 문제 목록이 새로고침 없이 다시 읽는다(#1471 ⑦).
// 참여자가 공동 강사가 되면(instructors-changed) 그 행은 강사 행이 되고, 문제가 열리면(participation-changed)
// n/N 의 N 이 는다. 두 신호 모두 격자(`roster-grid`)와 문제 목록(`problems`)을 각각 한 번만 다시 읽는다.
// `page.reload()` 를 어디서도 부르지 않는 것이 이 스펙의 단언이다.

async function otherSession(browser: Browser, seed: string) {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const page = await context.newPage();
  await establishClassroomSession(page, seed);
  return { context, api: classroomApi(page) };
}

async function setUpClass(page: Page, seed: string) {
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `집계 ${seed}`, instructor_display_name: "김소유" },
  });
  expect(created.ok()).toBeTruthy();
  const classId = (await created.json()).id as number;
  const joinCode = (await (await api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;
  const problemId = (await (
    await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title: "열린 문제", submission_formats: ["repository"] },
    })
  ).json()).id as number;
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`, {
    data: { label: "통과 조건", required: true },
  });
  expect((await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/open`)).ok()).toBeTruthy();
  return { api, classId, joinCode };
}

async function memberIdOf(page: Page, classId: number, name: string) {
  const members = (await (
    await classroomApi(page).get(`/api/backend/classroom/classes/${classId}/members`)
  ).json()) as { id: number; display_name: string }[];
  return members.find((m) => m.display_name === name)!.id;
}

// 격자·문제 목록 GET 을 센다. 화면을 열 때 한 번, 스트림이 이어질 때 한 번 읽는다 — 그 둘째 읽기가 끝난 뒤부터
// 센다(그 전에 상대가 움직이면 재연결 재조회가 바뀐 상태를 주워 신호 없이도 통과한다).
async function openParticipantsTab(page: Page, classId: number) {
  const base = `/api/backend/classroom/classes/${classId}`;
  const reads = { grid: 0, problems: 0 };
  let settled!: () => void;
  const secondReads = new Promise<void>((resolve) => (settled = resolve));
  page.on("response", (response) => {
    if (response.request().method() !== "GET") return;
    const path = new URL(response.url()).pathname;
    if (path === `${base}/roster-grid`) reads.grid += 1;
    else if (path === `${base}/problems`) reads.problems += 1;
    else return;
    if (reads.grid >= 2 && reads.problems >= 2) settled();
  });
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(`/classes/${classId}?tab=participants`);
  await stream;
  await secondReads;
  const problemsRead = () =>
    page.waitForResponse(
      (r) => r.request().method() === "GET" && new URL(r.url()).pathname === `${base}/problems`,
    );
  return { reads, problemsRead };
}

test("참여자 탭을 연 채로 참여자가 공동 강사가 되면 그 행이 강사 행이 되고 격자·문제 목록을 한 번씩 다시 읽는다", async ({
  page,
  browser,
}) => {
  const seed = `rt-roster-instr-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const { api, classId, joinCode } = await setUpClass(page, seed);
  const token = (await (
    await api.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)
  ).json()).token as string;
  const helper = await otherSession(browser, `${seed}-helper`);
  expect((await helper.api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "박참여" } })).ok()).toBeTruthy();
  const memberId = await memberIdOf(page, classId, "박참여");

  const { reads, problemsRead } = await openParticipantsTab(page, classId);
  await expect(page.getByTestId(`participant-row-${memberId}-name`)).toContainText("박참여");
  await expect(page.getByTestId(`participant-row-${memberId}-instructor-badge`)).toHaveCount(0);
  const before = { ...reads };
  const problemsReread = problemsRead();

  expect(
    (
      await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  await helper.context.close();

  await expect(page.getByTestId(`participant-row-${memberId}-instructor-badge`)).toBeVisible();
  await problemsReread;
  // TEST-WAIT-EXCEPTION: 「더 오는 요청이 없다」는 사건이 없는 부정 단언이라 조용해질 때까지 기다린다.
  await page.waitForLoadState("networkidle");
  expect(reads.grid - before.grid).toBe(1);
  expect(reads.problems - before.problems).toBe(1);
});

test("참여자이기도 한 강사가 참여자 탭을 연 채로 문제가 열리면 n/N 이 바뀌고 격자·문제 목록을 한 번씩 다시 읽는다", async ({
  page,
}) => {
  const seed = `rt-roster-part-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const { api, classId, joinCode } = await setUpClass(page, seed);
  // participation-changed 는 그 클래스의 참여자에게 간다 — 강사가 자기 클래스에 참여자로도 들어와 있어야 받는다.
  expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "김소유" } })).ok()).toBeTruthy();
  const memberId = await memberIdOf(page, classId, "김소유");
  const draftId = (await (
    await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title: "초안 문제", submission_formats: ["repository"] },
    })
  ).json()).id as number;
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${draftId}/checklist-items`, {
    data: { label: "통과 조건", required: true },
  });

  const { reads, problemsRead } = await openParticipantsTab(page, classId);
  await expect(page.getByTestId(`participant-row-${memberId}-passed`)).toHaveText("0/1");
  const before = { ...reads };
  const problemsReread = problemsRead();

  // 다른 탭에서 연 것과 같다 — 이 페이지의 화면 조작이 아니라 API 로 연다.
  expect((await api.post(`/api/backend/classroom/classes/${classId}/problems/${draftId}/open`)).ok()).toBeTruthy();

  await expect(page.getByTestId(`participant-row-${memberId}-passed`)).toHaveText("0/2");
  await problemsReread;
  // TEST-WAIT-EXCEPTION: 「더 오는 요청이 없다」는 사건이 없는 부정 단언이라 조용해질 때까지 기다린다.
  await page.waitForLoadState("networkidle");
  expect(reads.grid - before.grid).toBe(1);
  expect(reads.problems - before.problems).toBe(1);
});
