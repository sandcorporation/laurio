import { expect, test, type Browser, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 집계 대상이 바뀌면 열어 둔 참여자 격자와 문제 목록이 새로고침 없이 다시 읽는다(#1471 ⑦).
// 참여자가 공동 강사가 되면(instructors-changed) 그 행은 강사 행이 되고, 문제가 열리면(participation-changed)
// n/N 의 N 이 는다. 새 참여·내보내기도 그 클래스 강사에게 instructors-changed 로 온다(#1471 ⑦ 후속) — 격자 줄이
// 늘고 「내보냄」이 붙는다. 신호 하나에 격자(`roster-grid`)와 문제 목록(`problems`)을 각각 한 번만 다시 읽는다.
// `page.reload()` 를 어디서도 부르지 않는 것이 이 스펙의 단언이다.

async function otherSession(browser: Browser, seed: string) {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const page = await context.newPage();
  await establishClassroomSession(page, seed);
  return { context, page, api: classroomApi(page) };
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

// 격자·문제 목록 GET 을 센다. 화면을 열 때 읽고, 스트림이 이어질 때 마운트돼 있던 훅은 한 번 더 읽는다 — 그
// 재조회까지 끝난 뒤부터 센다(그 전에 상대가 움직이면 재연결 재조회가 바뀐 상태를 주워 신호 없이도 통과한다).
async function openParticipantsTab(page: Page, classId: number) {
  const base = `/api/backend/classroom/classes/${classId}`;
  const reads = { grid: 0, problems: 0 };
  page.on("response", (response) => {
    if (response.request().method() !== "GET") return;
    const path = new URL(response.url()).pathname;
    if (path === `${base}/roster-grid`) reads.grid += 1;
    else if (path === `${base}/problems`) reads.problems += 1;
  });
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(`/classes/${classId}?tab=participants`);
  await stream;
  await expect(page.getByTestId("participants-achievement-row")).toBeVisible();
  // 탭이 스트림보다 먼저 마운트됐는지에 따라 재연결 재조회가 있기도 없기도 해 이름 붙일 사건이 하나로 정해지지 않는다.
  // TEST-WAIT-EXCEPTION: 재연결 재조회가 있을지 없을지 모르는 상태에서 조용해질 때까지 기다린다.
  await page.waitForLoadState("networkidle");
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

// 소유자·공동 강사(이 페이지)·참여자 「앨리스」가 있는 클래스 — 공동 강사는 참여자 행이 없다.
async function coInstructorScene(page: Page, browser: Browser, seed: string) {
  const owner = await otherSession(browser, `${seed}-owner`);
  const { api: ownerApi, classId, joinCode } = await setUpClass(owner.page, seed);
  const token = (await (
    await ownerApi.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)
  ).json()).token as string;
  await establishClassroomSession(page, seed);
  expect(
    (
      await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  const alice = await otherSession(browser, `${seed}-alice`);
  expect((await alice.api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "앨리스" } })).ok()).toBeTruthy();
  await alice.context.close();
  return { owner, classId, joinCode };
}

test("공동 강사가 참여자 탭을 연 채로 학생이 새로 참여하면 줄과 참여자 수가 늘고 격자·문제 목록을 한 번씩 다시 읽는다", async ({
  page,
  browser,
}) => {
  const seed = `rt-roster-join-${test.info().workerIndex}-${Date.now()}`;
  const { owner, classId, joinCode } = await coInstructorScene(page, browser, seed);
  await owner.context.close();
  const bob = await otherSession(browser, `${seed}-bob`);

  const rows = page.getByTestId(/^participant-row-\d+$/);
  const { reads, problemsRead } = await openParticipantsTab(page, classId);
  await expect(rows).toHaveCount(1);
  await expect(page.getByTestId("class-stat-members")).toContainText("1");
  const before = { ...reads };
  const problemsReread = problemsRead();

  expect((await bob.api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "밥" } })).ok()).toBeTruthy();
  await bob.context.close();

  await expect(rows).toHaveCount(2);
  await expect(page.getByTestId("class-stat-members")).toContainText("2");
  await problemsReread;
  // TEST-WAIT-EXCEPTION: 「더 오는 요청이 없다」는 사건이 없는 부정 단언이라 조용해질 때까지 기다린다.
  await page.waitForLoadState("networkidle");
  expect(reads.grid - before.grid).toBe(1);
  expect(reads.problems - before.problems).toBe(1);
});

test("공동 강사가 참여자 탭을 연 채로 소유자가 참여자를 내보내면 그 줄에 「내보냄」이 붙고 참여자 수가 준다", async ({
  page,
  browser,
}) => {
  const seed = `rt-roster-expel-${test.info().workerIndex}-${Date.now()}`;
  const { owner, classId } = await coInstructorScene(page, browser, seed);
  const aliceId = await memberIdOf(page, classId, "앨리스");

  await openParticipantsTab(page, classId);
  await expect(page.getByTestId(`participant-row-${aliceId}-name`)).toContainText("앨리스");
  await expect(page.getByTestId(`participant-row-${aliceId}-expelled-badge`)).toHaveCount(0);
  await expect(page.getByTestId("class-stat-members")).toContainText("1");

  expect((await owner.api.post(`/api/backend/classroom/classes/${classId}/members/${aliceId}/expel`)).ok()).toBeTruthy();
  await owner.context.close();

  await expect(page.getByTestId(`participant-row-${aliceId}-expelled-badge`)).toBeVisible();
  await expect(page.getByTestId("class-stat-members")).toContainText("0");
});
