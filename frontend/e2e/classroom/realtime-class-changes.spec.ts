import { expect, test, type Browser, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 상대편이 한 일이 열어 둔 화면에 새로고침 없이 닿는다(#1447 10-1·10-2). 강사 탭은 초대 수락·소유권
// 이전의 답을, 참여자 제출 화면은 문제 숨김·클래스 보관·내보내기를 받는다. `page.reload()` 를 어디서도 부르지
// 않는 것이 이 스펙의 단언이다. 상대편은 다른 브라우저 컨텍스트에서 API 를 직접 친다.

async function otherSession(browser: Browser, seed: string) {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const page = await context.newPage();
  await establishClassroomSession(page, seed);
  return { context, api: classroomApi(page) };
}

async function createClass(page: Page, seed: string) {
  const created = await classroomApi(page).post("/api/backend/classroom/classes", {
    data: { name: `실시간 ${seed}`, instructor_display_name: "김소유" },
  });
  expect(created.ok()).toBeTruthy();
  return (await created.json()).id as number;
}

async function createInvite(page: Page, classId: number) {
  const invited = await classroomApi(page).post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`);
  expect(invited.ok()).toBeTruthy();
  return (await invited.json()).token as string;
}

// 화면을 열고 실시간 스트림이 이어질 때까지 기다린다. 이어지는 순간 화면이 한 번 다시 읽는데
// (`decideStreamRefresh`), 그 전에 상대가 움직이면 그 재조회가 바뀐 상태를 주워 신호 없이도 통과한다 —
// 그 재조회(`settledBy`)까지 끝난 뒤에 상대를 움직인다.
async function openWithStream(page: Page, url: string, settledBy?: string) {
  const stream = page.waitForResponse((r) => r.url().includes("/api/backend/classroom/events/stream"));
  await page.goto(url);
  await stream;
  if (settledBy) await page.waitForResponse((r) => r.url().endsWith(settledBy));
}

// 탭을 숨겼다가 다시 보인다 — 숨긴 동안 스트림이 닫혀 신호를 놓친다(stream-context).
async function setVisibility(page: Page, state: "hidden" | "visible") {
  await page.evaluate((value) => {
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => value });
    document.dispatchEvent(new Event("visibilitychange"));
  }, state);
}

test("강사 탭을 연 채로 상대가 초대를 수락하면 강사 명단과 대기 초대가 바뀐다", async ({ page, browser }) => {
  const seed = `rt-invite-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const classId = await createClass(page, seed);
  const token = await createInvite(page, classId);

  await openWithStream(page, `/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("class-instructors-count")).toHaveText("1명");
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1);

  const helper = await otherSession(browser, `${seed}-helper`);
  const accepted = await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
    data: { display_name: "박조교" },
  });
  expect(accepted.ok()).toBeTruthy();
  await helper.context.close();

  await expect(page.getByTestId("class-instructors-count")).toHaveText("2명", { timeout: 10_000 });
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(0);
});

test("탭을 숨긴 사이 초대가 수락되면 탭으로 돌아올 때 명단과 대기 초대를 다시 읽는다", async ({ page, browser }) => {
  const seed = `rt-visible-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const classId = await createClass(page, seed);
  const token = await createInvite(page, classId);

  await openWithStream(page, `/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1);
  await setVisibility(page, "hidden");

  const helper = await otherSession(browser, `${seed}-helper`);
  const accepted = await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
    data: { display_name: "박조교" },
  });
  expect(accepted.ok()).toBeTruthy();
  await helper.context.close();

  await setVisibility(page, "visible");
  await expect(page.getByTestId("class-instructors-count")).toHaveText("2명", { timeout: 10_000 });
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(0);
});

for (const answer of ["decline", "accept"] as const) {
  test(`강사 탭을 연 채로 받는 사람이 소유권 이전을 ${answer === "accept" ? "수락" : "거절"}하면 역할과 이전 대기가 바뀐다`, async ({
    page,
    browser,
  }) => {
    const seed = `rt-transfer-${answer}-${test.info().workerIndex}-${Date.now()}`;
    await establishClassroomSession(page, seed);
    const classId = await createClass(page, seed);
    const token = await createInvite(page, classId);
    const helper = await otherSession(browser, `${seed}-helper`);
    expect(
      (
        await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
          data: { display_name: "박조교" },
        })
      ).ok(),
    ).toBeTruthy();
    const api = classroomApi(page);
    const roster = (await (await api.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
      co_instructor_id: number | null;
    }[];
    const coInstructorId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
    const requested = await api.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
      data: { co_instructor_id: coInstructorId },
    });
    expect(requested.ok()).toBeTruthy();
    const transferId = (await requested.json()).id as number;

    await openWithStream(page, `/classes/${classId}?tab=instructors`);
    await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
    // 소유자의 초점이 곧 사라질 「요청 취소」에 있다.
    await page.getByTestId("ownership-transfer-cancel").focus();

    const answered = await helper.api.post(
      `/api/backend/classroom/classes/${classId}/ownership-transfers/${transferId}/${answer}`,
    );
    expect(answered.ok()).toBeTruthy();
    await helper.context.close();

    await expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0, { timeout: 10_000 });
    if (answer === "accept") {
      // 넘긴 사람은 공동 강사가 됐다 — 떠나기 카드가 생긴다.
      await expect(page.getByTestId("class-leave")).toBeVisible();
      await expect(
        page.getByRole("status").filter({ has: page.getByTestId("ownership-transfer-taken-note") }),
      ).toBeFocused();
    } else {
      await expect(page.getByTestId("ownership-transfer-start")).toBeVisible();
      // 끝난 것이 읽히고, 초점은 BODY 가 아니라 강사 표 제목으로 간다(#1448 ③).
      await expect(
        page.getByRole("status").filter({ hasText: "박조교님에게 보낸 소유권 이전 요청이 끝났습니다. 소유자는 그대로입니다." }),
      ).toBeVisible();
      await expect(page.getByRole("heading", { name: /이 클래스의 강사/ })).toBeFocused();
    }
  });
}

const BLOCKERS = [
  { name: "문제를 숨기면", expected: "my-problem-not-found" },
  { name: "클래스를 보관하면", expected: "class-archived-note" },
  { name: "참여자를 내보내면", expected: "member-expelled-note" },
] as const;

for (const blocker of BLOCKERS) {
  test(`제출 화면을 연 채로 강사가 ${blocker.name} 새로고침 없이 낼 수 없는 화면이 된다`, async ({ page, browser }) => {
    const seed = `rt-blocked-${blocker.expected}-${test.info().workerIndex}-${Date.now()}`;
    const instructor = await otherSession(browser, seed);
    const created = await instructor.api.post("/api/backend/classroom/classes", {
      data: { name: `실시간 제출 ${seed}`, instructor_display_name: "강사" },
    });
    const classId = (await created.json()).id as number;
    const problem = await instructor.api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title: "1주차", submission_formats: ["repository"] },
    });
    const problemId = (await problem.json()).id as number;
    await instructor.api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/checklist-items`, {
      data: { label: "동작한다", required: true },
    });
    expect((await instructor.api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/open`)).ok()).toBeTruthy();
    const joinCode = (await (await instructor.api.get(`/api/backend/classroom/classes/${classId}`)).json()).join_code as string;

    await establishClassroomSession(page, `${seed}-participant`);
    expect(
      (await classroomApi(page).post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "참여자" } })).ok(),
    ).toBeTruthy();

    await openWithStream(
      page,
      `/classes/${classId}/problems/${problemId}/submit`,
      `/classes/${classId}/problems/${problemId}/mine`,
    );
    await expect(page.getByTestId("submit-repository")).toBeVisible();

    let changed;
    if (blocker.expected === "my-problem-not-found") {
      changed = await instructor.api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/hide`);
    } else if (blocker.expected === "class-archived-note") {
      changed = await instructor.api.post(`/api/backend/classroom/classes/${classId}/archive`);
    } else {
      const members = (await (await instructor.api.get(`/api/backend/classroom/classes/${classId}/members`)).json()) as {
        id: number;
        display_name: string;
      }[];
      const memberId = members.find((m) => m.display_name === "참여자")!.id;
      changed = await instructor.api.post(`/api/backend/classroom/classes/${classId}/members/${memberId}/expel`);
    }
    expect(changed.ok()).toBeTruthy();
    await instructor.context.close();

    await expect(page.getByTestId(blocker.expected)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByTestId("submit-repository")).toHaveCount(0);
    if (blocker.expected === "my-problem-not-found") {
      // 열어 둔 화면은 이유를 말한다(#1465 2). 새로 연 주소는 낸 적 없는 숨긴 문제와 없는 문제를 가르지 않는다.
      await expect(page.getByTestId("my-problem-not-found")).toContainText("강사가 이 문제를 숨기거나 삭제했습니다");
      await expect(page.getByRole("heading", { name: "강사가 이 문제를 숨기거나 삭제했습니다" })).toBeFocused();
      await page.goto(`/classes/${classId}/problems/${problemId}/submit`);
      await expect(page.getByTestId("my-problem-not-found")).toContainText("문제를 찾을 수 없습니다");
    }
    if (blocker.expected !== "my-problem-not-found") {
      // 보관·내보내기 안내는 낭독되고 초점을 받는다(#1459 ③) — 폼과 함께 초점이 body 로 빠지지 않는다.
      await expect(page.getByTestId(blocker.expected)).toHaveAttribute("role", "alert");
      await expect(page.getByTestId(blocker.expected)).toBeFocused();
    }
  });
}

test("소유자가 「요청 취소」로 이전 요청을 거두면 취소가 읽히고 초점이 강사 표 제목으로 간다", async ({ page, browser }) => {
  const seed = `rt-cancel-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const classId = await createClass(page, seed);
  const token = await createInvite(page, classId);
  const helper = await otherSession(browser, `${seed}-helper`);
  expect(
    (
      await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  await helper.context.close();

  await page.goto(`/classes/${classId}?tab=instructors`);
  await page.getByTestId("ownership-transfer-start").click();
  await page.getByTestId("ownership-transfer-confirm-button").click();
  await expect(page.getByTestId("ownership-transfer-pending")).toBeFocused();

  await page.getByTestId("ownership-transfer-cancel").press("Enter");
  await expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0);
  await expect(page.getByRole("status").filter({ hasText: "소유권 이전 요청을 취소했습니다." })).toBeVisible();
  await expect(page.getByRole("heading", { name: /이 클래스의 강사/ })).toBeFocused();
});

test("공동 강사가 클래스 화면을 연 채로 소유자가 이전을 요청하면 수락·거절이 나타나고, 취소하면 사라진다", async ({
  page,
  browser,
}) => {
  const seed = `rt-offer-${test.info().workerIndex}-${Date.now()}`;
  const owner = await otherSession(browser, seed);
  const created = await owner.api.post("/api/backend/classroom/classes", {
    data: { name: `실시간 이전 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const token = (await (await owner.api.post(`/api/backend/classroom/classes/${classId}/co-instructor-invites`)).json())
    .token as string;
  await establishClassroomSession(page, `${seed}-helper`);
  expect(
    (
      await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();

  await openWithStream(page, `/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("class-instructors-count")).toHaveText("2명");
  await expect(page.getByTestId("ownership-transfer-offer")).toHaveCount(0);

  const roster = (await (await owner.api.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const requested = await owner.api.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id },
  });
  expect(requested.ok()).toBeTruthy();
  await expect(page.getByTestId("ownership-transfer-offer")).toBeVisible({ timeout: 10_000 });

  // 받는 공동 강사의 초점이 카드의 「거절」에 있다 — 곧 카드가 사라진다.
  await page.getByTestId("ownership-transfer-decline").focus();

  const transferId = (await requested.json()).id as number;
  expect(
    (await owner.api.post(`/api/backend/classroom/classes/${classId}/ownership-transfers/${transferId}/cancel`)).ok(),
  ).toBeTruthy();
  await owner.context.close();
  await expect(page.getByTestId("ownership-transfer-offer")).toHaveCount(0, { timeout: 10_000 });

  // 끝남이 읽히고, 초점은 BODY 가 아니라 그 안내로 간다.
  const ended = page
    .getByRole("status")
    .filter({ hasText: "김소유님이 보낸 소유권 이전 요청이 끝났습니다. 공동 강사로 남습니다." });
  await expect(ended).toBeVisible();
  await expect(ended).toBeFocused();
});

test("390px 터치 — 「요청 취소」를 누르면 취소가 화면에 보이고 초점이 강사 표 제목으로 간다", async ({ browser }) => {
  const seed = `rt-cancel-touch-${test.info().workerIndex}-${Date.now()}`;
  const context = await browser.newContext({
    baseURL: test.info().project.use.baseURL,
    viewport: { width: 390, height: 844 },
    hasTouch: true,
    isMobile: true,
  });
  const page = await context.newPage();
  await establishClassroomSession(page, seed);
  const classId = await createClass(page, seed);
  const token = await createInvite(page, classId);
  const helper = await otherSession(browser, `${seed}-helper`);
  expect(
    (
      await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  await helper.context.close();

  await page.goto(`/classes/${classId}?tab=instructors`);
  await page.getByTestId("ownership-transfer-start").tap();
  await page.getByTestId("ownership-transfer-confirm-button").tap();
  await page.getByTestId("ownership-transfer-cancel").tap();

  const note = page.getByRole("status").filter({ hasText: "소유권 이전 요청을 취소했습니다." });
  await expect(note).toBeInViewport();
  await expect(page.getByRole("heading", { name: /이 클래스의 강사/ })).toBeFocused();
  await context.close();
});

// #1459 ④ — 초대 행 안에 초점이 있는 채로 상대가 초대를 수락하면 그 행이 사라진다. 초점은 BODY 로 빠지지 않고
// 늘 있는 「초대 링크 만들기」로 가고, 수락은 늘 있는 상태 영역에서 읽힌다.
for (const width of [1280, 390]) {
test(`${width}px — 초대 행의 「링크 복사」에 초점이 있을 때 상대가 수락하면 초점이 「초대 링크 만들기」로 가고 수락이 읽힌다`, async ({
  page,
  browser,
}) => {
  await page.setViewportSize({ width, height: 800 });
  const seed = `rt-invite-focus-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const classId = await createClass(page, seed);
  const token = await createInvite(page, classId);

  await openWithStream(page, `/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1);
  const status = page.getByTestId("co-instructor-accepted-note");
  await expect(status).toHaveAttribute("role", "status");
  await expect(status).toHaveText("");
  await page.getByTestId("co-instructor-invite-copy").focus();

  const helper = await otherSession(browser, `${seed}-helper`);
  expect(
    (
      await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  await helper.context.close();

  await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(0, { timeout: 10_000 });
  await expect(status).toHaveText("박조교 님이 초대를 수락했습니다", { timeout: 10_000 });
  await expect(page.getByRole("button", { name: "초대 링크 만들기" })).toBeFocused();
});
}

// #1459 ⑥ — 이전 요청 하나의 변경 신호가 클래스·강사·초대 GET 을 5번 일으켰다. 같은 변경의 재조회는 한 곳에서.
test("이전 요청에 답이 오면 클래스·강사·초대 재조회가 세 번 이하다", async ({ page, browser }) => {
  const seed = `rt-refetch-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const classId = await createClass(page, seed);
  const token = await createInvite(page, classId);
  const helper = await otherSession(browser, `${seed}-helper`);
  expect(
    (
      await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  const api = classroomApi(page);
  const roster = (await (await api.get(`/api/backend/classroom/classes/${classId}/instructors`)).json()) as {
    co_instructor_id: number | null;
  }[];
  const coInstructorId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  const requested = await api.post(`/api/backend/classroom/classes/${classId}/ownership-transfers`, {
    data: { co_instructor_id: coInstructorId },
  });
  const transferId = (await requested.json()).id as number;

  const base = `/api/backend/classroom/classes/${classId}`;
  const reads = { all: 0, invites: 0 };
  let secondInvitesRead!: () => void;
  const invitesReadTwice = new Promise<void>((resolve) => (secondInvitesRead = resolve));
  page.on("request", (request) => {
    if (request.method() !== "GET") return;
    const path = new URL(request.url()).pathname;
    if (path === base || path === `${base}/instructors` || path === `${base}/co-instructor-invites`) reads.all += 1;
    if (path === `${base}/co-instructor-invites`) {
      reads.invites += 1;
      if (reads.invites === 2) secondInvitesRead();
    }
  });
  await openWithStream(page, `/classes/${classId}?tab=instructors`);
  await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
  // 열릴 때 한 번, 스트림이 이어질 때 한 번 대기 초대를 읽는다 — 그 재조회 사슬이 끝난 뒤부터 센다.
  await invitesReadTwice;
  const before = reads.all;

  expect(
    (await helper.api.post(`${base}/ownership-transfers/${transferId}/decline`)).ok(),
  ).toBeTruthy();
  await helper.context.close();

  await expect(page.getByTestId("ownership-transfer-pending")).toHaveCount(0, { timeout: 10_000 });
  // TEST-WAIT-EXCEPTION: 「더 오는 요청이 없다」는 사건이 없는 부정 단언이라 조용해질 때까지 기다린다.
  await page.waitForLoadState("networkidle");
  expect(reads.all - before).toBeGreaterThan(0);
  expect(reads.all - before).toBeLessThanOrEqual(3);
});

// #1464 — 거절 뒤의 「소유자는 그대로입니다」는 다음 요청이 걸리거나 역할이 바뀌면 지워진다.
for (const next of ["다시 요청", "수락"] as const) {
  test(`이전 요청 거절 문구는 ${next} 뒤에 강사 탭에서 사라진다`, async ({ page, browser }) => {
    const seed = `rt-note-${next === "수락" ? "a" : "r"}-${test.info().workerIndex}-${Date.now()}`;
    await establishClassroomSession(page, seed);
    const classId = await createClass(page, seed);
    const token = await createInvite(page, classId);
    const helper = await otherSession(browser, `${seed}-helper`);
    expect(
      (
        await helper.api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
          data: { display_name: "박조교" },
        })
      ).ok(),
    ).toBeTruthy();
    const api = classroomApi(page);
    const base = `/api/backend/classroom/classes/${classId}`;
    const roster = (await (await api.get(`${base}/instructors`)).json()) as { co_instructor_id: number | null }[];
    const coInstructorId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
    async function request() {
      const requested = await api.post(`${base}/ownership-transfers`, { data: { co_instructor_id: coInstructorId } });
      expect(requested.ok()).toBeTruthy();
      return (await requested.json()).id as number;
    }
    const first = await request();

    await openWithStream(page, `/classes/${classId}?tab=instructors`);
    await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible();
    expect((await helper.api.post(`${base}/ownership-transfers/${first}/decline`)).ok()).toBeTruthy();
    const ended = page.getByTestId("ownership-transfer-ended-note");
    await expect(ended).toHaveText("박조교님에게 보낸 소유권 이전 요청이 끝났습니다. 소유자는 그대로입니다.", {
      timeout: 10_000,
    });

    const second = await request();
    await expect(page.getByTestId("ownership-transfer-pending")).toBeVisible({ timeout: 10_000 });
    if (next === "수락") {
      expect((await helper.api.post(`${base}/ownership-transfers/${second}/accept`)).ok()).toBeTruthy();
      await expect(page.getByTestId("class-leave")).toBeVisible({ timeout: 10_000 });
    }
    await expect(ended).toHaveText("");
    await helper.context.close();
  });
}

// #1465 3 — 「초대 링크 만들기」 결과가 읽히고 초점이 새 링크의 「복사」로 간다.
for (const width of [1280, 390]) {
  test(`${width}px — 「초대 링크 만들기」를 누르면 만들었다는 안내가 읽히고 초점이 새 링크의 「복사」로 간다`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 });
    const seed = `rt-create-${test.info().workerIndex}-${Date.now()}`;
    await establishClassroomSession(page, seed);
    const classId = await createClass(page, seed);
    await page.goto(`/classes/${classId}?tab=instructors`);
    const note = page.getByTestId("co-instructor-created-note");
    await expect(note).toHaveAttribute("role", "status");
    await expect(note).toHaveText("");
    await page.getByRole("button", { name: "초대 링크 만들기" }).press("Enter");
    await expect(note).toHaveText("초대 링크를 만들었습니다");
    await expect(page.getByTestId("co-instructor-invite-row")).toHaveCount(1);
    await expect(page.getByTestId("co-instructor-invite-copy")).toBeFocused();
  });
}

// #1465 2 — 강사에서 빠진 사람에게는 「클래스를 찾을 수 없습니다」가 아니라 이유를 말한다. 열어 둔 화면과 새로 연 주소 둘 다.
// 처음부터 관계 없는 사람에게는 그대로 「찾을 수 없습니다」다(존재를 말하지 않는다).
test("공동 강사가 내보내지면 열어 둔 화면과 새로 연 주소가 이유를 말하고, 관계 없는 사람은 찾을 수 없음이다", async ({
  page,
  browser,
}) => {
  const seed = `rt-removed-${test.info().workerIndex}-${Date.now()}`;
  const owner = await otherSession(browser, seed);
  const created = await owner.api.post("/api/backend/classroom/classes", {
    data: { name: `내보냄 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;
  const token = (await (await owner.api.post(`${base}/co-instructor-invites`)).json()).token as string;
  await establishClassroomSession(page, `${seed}-co`);
  expect(
    (
      await classroomApi(page).post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, {
        data: { display_name: "박조교" },
      })
    ).ok(),
  ).toBeTruthy();
  const roster = (await (await owner.api.get(`${base}/instructors`)).json()) as { co_instructor_id: number | null }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;

  await openWithStream(page, `/classes/${classId}`);
  await expect(page.getByTestId("class-instructors-count").or(page.getByRole("tab", { name: /강사/ }))).toBeVisible();
  expect((await owner.api.post(`${base}/co-instructors/${coId}/remove`)).ok()).toBeTruthy();
  await owner.context.close();

  await expect(page.getByTestId("classroom-detail-not-found")).toContainText("더 이상 이 클래스의 강사가 아닙니다", {
    timeout: 10_000,
  });
  await expect(page.getByRole("heading", { name: "더 이상 이 클래스의 강사가 아닙니다" })).toBeFocused();
  await page.goto(`/classes/${classId}`);
  await expect(page.getByTestId("classroom-detail-not-found")).toContainText("더 이상 이 클래스의 강사가 아닙니다");

  const stranger = await otherSession(browser, `${seed}-stranger`);
  await stranger.context.pages()[0].goto(`/classes/${classId}`);
  await expect(stranger.context.pages()[0].getByTestId("classroom-detail-not-found")).toContainText(
    "클래스를 찾을 수 없습니다",
  );
  await stranger.context.close();
});

// 참여자 이력이 있는 공동 강사 — 소유자와 같은 클래스의 학생 화면을 본다.
async function seedCoInstructorWithParticipantRow(page: Page, browser: Browser, seed: string) {
  const owner = await otherSession(browser, seed);
  const created = await owner.api.post("/api/backend/classroom/classes", {
    data: { name: `공동 강사 ${seed}`, instructor_display_name: "김소유" },
  });
  const classId = (await created.json()).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;
  const problemId = (
    await (await owner.api.post(`${base}/problems`, { data: { title: "1주차", submission_formats: ["repository"] } })).json()
  ).id as number;
  await owner.api.post(`${base}/problems/${problemId}/checklist-items`, { data: { label: "동작한다", required: true } });
  const joinCode = (await (await owner.api.get(base)).json()).join_code as string;
  const token = (await (await owner.api.post(`${base}/co-instructor-invites`)).json()).token as string;
  await establishClassroomSession(page, `${seed}-co`);
  const api = classroomApi(page);
  expect((await api.post(`/api/backend/classroom/join/${joinCode}`, { data: { display_name: "박참여" } })).ok()).toBeTruthy();
  expect(
    (await api.post(`/api/backend/classroom/co-instructor-invites/${token}/accept`, { data: { display_name: "박조교" } })).ok(),
  ).toBeTruthy();
  const roster = (await (await owner.api.get(`${base}/instructors`)).json()) as { co_instructor_id: number | null }[];
  const coId = roster.find((row) => row.co_instructor_id !== null)!.co_instructor_id;
  return { owner, classId, base, problemId, coId };
}

// #1471 ① — 강사가 학생 화면을 연 채 클래스가 보관되면 제출 폼과 함께 폼 안의 초점 효과가 사라진다.
// 참여자 이력이 없는 강사도 보관 신호를 받는다(백엔드는 강사에게 instructors-changed 를 보낸다).
test("강사의 학생 화면을 연 채 클래스가 보관되면 띠의 보관 안내가 낭독되고 초점을 받는다", async ({ page, browser }) => {
  const seed = `rt-instructor-archived-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const classId = await createClass(page, seed);
  const base = `/api/backend/classroom/classes/${classId}`;
  const api = classroomApi(page);
  const problemId = (
    await (await api.post(`${base}/problems`, { data: { title: "1주차", submission_formats: ["repository"] } })).json()
  ).id as number;
  await api.post(`${base}/problems/${problemId}/checklist-items`, { data: { label: "동작한다", required: true } });
  expect((await api.post(`${base}/problems/${problemId}/open`)).ok()).toBeTruthy();

  await openWithStream(page, `/classes/${classId}/problems/${problemId}/submit`, `${base}/problems/${problemId}/mine`);
  await expect(page.getByTestId("submit-repository")).toBeVisible();
  const other = await otherSession(browser, seed);
  expect((await other.api.post(`${base}/archive`)).ok()).toBeTruthy();
  await other.context.close();

  const note = page.getByTestId("instructor-viewing-banner").getByTestId("class-archived-note");
  await expect(note).toBeVisible({ timeout: 10_000 });
  await expect(page.getByTestId("submit-repository")).toHaveCount(0);
  await expect(note).toHaveAttribute("role", "alert");
  await expect(note).toBeFocused();
});

// #1471 ③ — 참여자 이력이 있는 공동 강사가 학생 화면을 보던 중 내보내지면 문제 비공개가 아니라 강사 권한 상실이다.
test("학생 화면을 보던 공동 강사가 내보내지면 문제 비공개가 아니라 강사 권한 상실을 읽는다", async ({ page, browser }) => {
  const seed = `rt-removed-submit-${test.info().workerIndex}-${Date.now()}`;
  const { owner, classId, base, problemId, coId } = await seedCoInstructorWithParticipantRow(page, browser, seed);

  await openWithStream(page, `/classes/${classId}/problems/${problemId}/submit`, `${base}/problems/${problemId}/mine`);
  await expect(page.getByTestId("instructor-viewing-banner")).toBeVisible();
  expect((await owner.api.post(`${base}/co-instructors/${coId}/remove`)).ok()).toBeTruthy();
  await owner.context.close();

  await expect(page.getByTestId("my-problem-not-found")).toContainText("더 이상 이 클래스의 강사가 아닙니다", {
    timeout: 10_000,
  });
  await expect(page.getByRole("heading", { name: "더 이상 이 클래스의 강사가 아닙니다" })).toBeFocused();
});
