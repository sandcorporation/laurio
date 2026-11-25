import { expect, test, type Browser, type Page, type Route } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 볼 수 없는 클래스 화면의 안내(#1390). 백엔드는 비강사에게 같은 404 를 주고(계약은
// pytest `test_classroom_access_contract.py`), 화면이 그 사람의 목록 둘로 문구와 돌아갈 곳을 고른다.
const NOT_FOUND = "클래스를 찾을 수 없습니다";
const INSTRUCTOR_ONLY = "강사만 볼 수 있는 화면입니다";
const JOINED_PATH = "/api/backend/classroom/classes/joined";

/** 강사(별도 컨텍스트)가 클래스 하나와 저장소 형식 문제 둘(열린 것·초안)을 만든다. */
async function seedClass(browser: Browser, seed: string) {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const instructor = await context.newPage();
  await establishClassroomSession(instructor, seed);
  const api = classroomApi(instructor);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `접근 안내 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;
  const base = `/api/backend/classroom/classes/${classId}`;
  const addProblem = async (title: string) => {
    const response = await api.post(`${base}/problems`, { data: { title, submission_formats: ["repository"] } });
    const id = (await response.json()).id as number;
    const item = await api.post(`${base}/problems/${id}/checklist-items`, {
      data: { label: "목록을 그린다", required: true },
    });
    expect(item.ok()).toBeTruthy();
    return id;
  };
  const openId = await addProblem("열린 문제");
  const draftId = await addProblem("초안 문제");
  expect((await api.post(`${base}/problems/${openId}/open`)).ok()).toBeTruthy();
  const joinCode = (await (await api.get(base)).json()).join_code as string;
  return { classId, openId, draftId, joinCode, instructor };
}

async function joinAs(page: Page, seed: string, joinCode: string) {
  await establishClassroomSession(page, `${seed}-participant`);
  const joined = await classroomApi(page).post(`/api/backend/classroom/join/${joinCode}`, {
    data: { display_name: "서지우" },
  });
  expect(joined.ok()).toBeTruthy();
}

/** 강사 전용 화면의 주소 일곱과 그 안내 제목의 test id. */
function instructorScreens(classId: number, problemId: number) {
  const root = `/classes/${classId}`;
  return [
    [root, "classroom-detail-not-found"],
    [`${root}/members`, "classroom-detail-not-found"],
    [`${root}/settings`, "class-settings-not-found"],
    [`${root}/submissions`, "class-attempts-not-found"],
    [`${root}/problems/new`, "new-problem-not-found"],
    [`${root}/problems/${problemId}`, "edit-problem-not-found"],
    [`${root}/problems/${problemId}/submissions`, "problem-submissions-not-found"],
  ] as const;
}

async function expectNotice(page: Page, testId: string, title: string, label: string, href: string) {
  await expect(page.getByTestId(testId)).toHaveText(title);
  // 안내 화면의 탭 제목은 어느 주소든 안내 제목이다(#1406).
  await expect(page).toHaveTitle(`${title} · Codemit`);
  const link = page.getByTestId("access-notice-link");
  await expect(link).toHaveText(label);
  await expect(link).toHaveAttribute("href", href);
}

/** 새 문제 폼의 제목 칸이 DOM 에 한 번이라도 붙었는지 적어 두는 감시자. */
async function watchForNewProblemForm(page: Page) {
  await page.addInitScript(() => {
    new MutationObserver(() => {
      if (document.querySelector('[data-testid="new-problem-title-input"]')) {
        sessionStorage.setItem("saw-new-problem-form", "yes");
      }
    }).observe(document, { childList: true, subtree: true });
  });
}

const sawNewProblemForm = (page: Page) =>
  page.evaluate(() => sessionStorage.getItem("saw-new-problem-form") !== null);

// 화면 한 벌을 둘씩 나눠 걷는다 — 시험 하나의 시간 한도(3초) 안에 들게.
function pairs<T>(items: readonly T[]): T[][] {
  return Array.from({ length: Math.ceil(items.length / 2) }, (_, index) => items.slice(index * 2, index * 2 + 2));
}

const INSTRUCTOR_SCREEN_GROUPS = pairs(instructorScreens(0, 0).map((_, index) => index));

for (const [group, indexes] of INSTRUCTOR_SCREEN_GROUPS.entries()) {
  test(`참여자는 강사 전용 화면에서 안내를 읽는다 ${group + 1}`, async ({ page, browser }) => {
    const seed = `access-participant-${group}-${test.info().workerIndex}-${Date.now()}`;
    const { classId, openId, joinCode } = await seedClass(browser, seed);
    await joinAs(page, seed, joinCode);
    await watchForNewProblemForm(page);
    const screens = instructorScreens(classId, openId);

    for (const [url, testId] of indexes.map((index) => screens[index])) {
      await page.goto(url);
      await expectNotice(page, testId, INSTRUCTOR_ONLY, "문제 목록으로", `/classes/${classId}/problems/mine`);
      if (url.endsWith("/members")) await expect(page).toHaveURL(/\?tab=participants$/);
      if (url.endsWith("/problems/new")) expect(await sawNewProblemForm(page)).toBe(false);
      if (url.endsWith(`${classId}/submissions`)) {
        await expect(page.getByText("제출을 불러오지 못했습니다.")).toHaveCount(0);
      }
    }
  });
}

test("강사 전용 안내의 링크를 누르면 내 문제 목록이다", async ({ page, browser }) => {
  const seed = `access-link-${test.info().workerIndex}-${Date.now()}`;
  const { classId, openId, joinCode } = await seedClass(browser, seed);
  await joinAs(page, seed, joinCode);

  await page.goto(`/classes/${classId}`);
  await page.getByTestId("access-notice-link").click();

  await expect(page).toHaveURL(new RegExp(`/classes/${classId}/problems/mine$`));
  await expect(page.getByTestId(`my-problem-row-${openId}`)).toBeVisible();
});

const strangerScreens = (classId: number, problemId: number) =>
  [
    ...instructorScreens(classId, problemId),
    [`/classes/${classId}/problems/mine`, "my-problems-not-found"],
    [`/classes/${classId}/problems/${problemId}/submit`, "my-problem-not-found"],
  ] as const;

for (const [group, indexes] of pairs(strangerScreens(0, 0).map((_, index) => index)).entries()) {
  test(`무관한 사람에게는 모든 화면이 같은 안내다 ${group + 1}`, async ({ page, browser }) => {
    const seed = `access-stranger-${group}-${test.info().workerIndex}-${Date.now()}`;
    const { classId, openId } = await seedClass(browser, seed);
    await establishClassroomSession(page, `${seed}-stranger`);
    await watchForNewProblemForm(page);
    const screens = strangerScreens(classId, openId);

    for (const [url, testId] of indexes.map((index) => screens[index])) {
      await page.goto(url);
      await expectNotice(page, testId, NOT_FOUND, "홈으로", "/");
      await expect(page.getByText(INSTRUCTOR_ONLY)).toHaveCount(0);
      if (url.endsWith("/problems/new")) expect(await sawNewProblemForm(page)).toBe(false);
    }
  });
}

test("강사와 참여자는 없는 문제·내 문제 화면에서 제 갈 곳을 받는다", async ({ page, browser }) => {
  const seed = `access-own-${test.info().workerIndex}-${Date.now()}`;
  const { classId, draftId, joinCode, instructor } = await seedClass(browser, seed);
  const root = `/classes/${classId}`;

  await instructor.goto(`${root}/problems/mine`);
  await expectNotice(instructor, "my-problems-not-found", "참여자로 가입하지 않은 클래스입니다", "클래스로", root);
  await instructor.goto(`${root}/problems/999999/submit`);
  await expectNotice(instructor, "my-problem-not-found", "문제를 찾을 수 없습니다", "클래스로", root);

  await joinAs(page, seed, joinCode);
  await page.goto(`${root}/problems/${draftId}/submit`);
  await expectNotice(
    page,
    "my-problem-not-found",
    "문제를 찾을 수 없습니다",
    "문제 목록으로",
    `${root}/problems/mine`,
  );
});

test("목록이 늦으면 불러오는 중만 보이고, 안내를 고르는 목록은 404 뒤에 새로 묻는다", async ({ page, browser }) => {
  const seed = `access-slow-${test.info().workerIndex}-${Date.now()}`;
  const { classId, joinCode } = await seedClass(browser, seed);
  await joinAs(page, seed, joinCode);
  // 홈이 목록을 이미 한 번 받았어도 안내는 그것을 쓰지 않는다.
  await page.goto("/");

  const events: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === JOINED_PATH) events.push("joined 요청");
  });
  page.on("response", (response) => {
    if (new URL(response.url()).pathname === `/api/backend/classroom/classes/${classId}`) {
      events.push(`class ${response.status()}`);
    }
  });
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await page.route(
    (url) => url.pathname === JOINED_PATH,
    async (route: Route) => {
      await held;
      await route.continue();
    },
  );

  await page.goto(`/classes/${classId}`);
  await expect(page.getByTestId("access-notice-loading")).toHaveText("불러오는 중...");
  await expect(page.getByText(NOT_FOUND)).toHaveCount(0);
  await expect(page.getByText(INSTRUCTOR_ONLY)).toHaveCount(0);
  release();
  await expect(page.getByTestId("classroom-detail-not-found")).toHaveText(INSTRUCTOR_ONLY);
  expect(events.indexOf("joined 요청")).toBeGreaterThan(events.indexOf("class 404"));
  expect(events).toContain("class 404");
});

test("강사의 낡은 404 는 한 번만 다시 부른다", async ({ browser }) => {
  const seed = `access-stale-${test.info().workerIndex}-${Date.now()}`;
  const { classId, instructor } = await seedClass(browser, seed);
  const classPath = `/api/backend/classroom/classes/${classId}`;
  let calls = 0;
  let stale = 1;
  await instructor.route(
    (url) => url.pathname === classPath,
    async (route) => {
      calls += 1;
      if (calls <= stale) {
        await route.fulfill({ status: 404, json: { detail: `${NOT_FOUND}.` } });
      } else {
        await route.continue();
      }
    },
  );

  await instructor.goto(`/classes/${classId}`);
  await expect(instructor.getByRole("heading", { level: 1 })).toContainText("접근 안내");
  expect(calls).toBe(2);

  calls = 0;
  stale = Number.POSITIVE_INFINITY;
  await instructor.goto(`/classes/${classId}`);
  await expectNotice(instructor, "classroom-detail-not-found", NOT_FOUND, "홈으로", "/");
  // 안내를 따라 홈까지 가는 동안에도 셋째 호출은 없다.
  await instructor.getByTestId("access-notice-link").click();
  await expect(instructor).toHaveURL(/\/$/);
  expect(calls).toBe(2);
});

const EMPTY_REPOSITORY = "GitHub 저장소 주소를 넣어 주세요.";
const INSTRUCTOR_WARNING = "여기서 낸 시도는 강사 본인 시도로 남고 달성률·제출 현황에 들지 않습니다.";

/** 이 화면에서 나간 제출 POST 의 본문을 모은다. */
function watchSubmissions(page: Page) {
  const bodies: { value: string }[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && new URL(request.url()).pathname.endsWith("/submissions")) {
      bodies.push(request.postDataJSON() as { value: string });
    }
  });
  return bodies;
}

test("강사의 학생 화면은 결과 경고와 갈 곳을 말하고 빈 저장소 제출에는 안내가 뜬다", async ({ browser }) => {
  const seed = `access-view-${test.info().workerIndex}-${Date.now()}`;
  const { classId, openId, instructor } = await seedClass(browser, seed);
  const sent = watchSubmissions(instructor);
  const root = `/classes/${classId}`;

  await instructor.goto(`${root}/problems/${openId}/submit`);

  const banner = instructor.getByTestId("instructor-viewing-banner");
  await expect(banner).toContainText(INSTRUCTOR_WARNING);
  await expect(banner.getByRole("link", { name: "문제 편집" })).toHaveAttribute("href", `${root}/problems/${openId}`);
  await expect(instructor.getByRole("link", { name: "제출 현황" })).toHaveCount(1);
  await expect(banner.getByRole("link", { name: "제출 현황" })).toHaveAttribute(
    "href",
    `${root}/problems/${openId}/submissions`,
  );
  const back = instructor.getByTestId("my-problem-back-link");
  await expect(back).toHaveText("클래스로");
  await expect(back).toHaveAttribute("href", root);
  await expect(instructor.getByRole("heading", { name: "강사 본인 시도" })).toBeVisible();
  await expect(instructor.getByTestId("submissions-empty-state")).toHaveText("강사 본인이 낸 시도가 없습니다.");

  await expect(instructor.getByTestId("repository-url-input")).toBeVisible();
  await instructor.getByTestId("submit-repository").click();
  await expect(instructor.getByTestId("repository-url-invalid")).toHaveText(EMPTY_REPOSITORY);
  expect(sent).toHaveLength(0);
});

test("참여자의 빈 저장소 제출에도 안내가 뜨고 화면 말은 참여자의 것이다", async ({ page, browser }) => {
  const seed = `access-empty-${test.info().workerIndex}-${Date.now()}`;
  const { classId, openId, joinCode } = await seedClass(browser, seed);
  await joinAs(page, seed, joinCode);
  const sent = watchSubmissions(page);

  await page.goto(`/classes/${classId}/problems/${openId}/submit`);
  await page.getByTestId("submit-repository").click();

  await expect(page.getByTestId("repository-url-invalid")).toHaveText(EMPTY_REPOSITORY);
  // 빈 칸 오류도 칸에 무효로 알리고 문구와 이어진다(#1422).
  const urlInput = page.getByTestId("repository-url-input");
  await expect(urlInput).toHaveAttribute("aria-invalid", "true");
  await expect(urlInput).toHaveAttribute("aria-describedby", "repository-url-error");
  await expect(page.locator("#repository-url-error")).toHaveText(EMPTY_REPOSITORY);
  await expect(page.getByTestId("my-problem-back-link")).toHaveText("문제 목록으로");
  await expect(page.getByRole("heading", { name: "내 시도" })).toBeVisible();
  await expect(page.getByTestId("instructor-viewing-banner")).toHaveCount(0);
  expect(sent).toHaveLength(0);
});

test("제출 중에 거듭 내도 누른 시점의 주소로 한 번만 간다", async ({ browser }) => {
  const seed = `access-once-${test.info().workerIndex}-${Date.now()}`;
  const { classId, openId, instructor } = await seedClass(browser, seed);
  const sent = watchSubmissions(instructor);
  let release = () => {};
  const held = new Promise<void>((resolve) => (release = resolve));
  await instructor.route(
    (url) => url.pathname.endsWith(`/problems/${openId}/submissions`),
    async (route: Route) => {
      await held;
      await route.continue();
    },
  );

  await instructor.goto(`/classes/${classId}/problems/${openId}/submit`);
  const input = instructor.getByTestId("repository-url-input");
  await input.fill("https://github.com/octocat/Hello-World");
  // 잠긴 버튼을 거치지 않고 폼을 세 번 낸다 — 다시 그려지기 전의 연타까지 진행 표지가 막아야 한다.
  await input.evaluate((element: HTMLInputElement) => {
    for (let i = 0; i < 3; i += 1) element.form!.requestSubmit();
  });

  await expect(instructor.getByTestId("submit-repository")).toBeDisabled();
  await expect(input).not.toBeEditable();
  release();
  await expect(input).toHaveValue("");
  await expect(input).toBeEditable();
  expect(sent.map((body) => body.value)).toEqual(["https://github.com/octocat/Hello-World"]);
});

test("보관한 클래스의 학생 화면에는 띠에 보관 한 줄이 있고 결과 경고는 없다", async ({ browser }) => {
  const seed = `access-archived-${test.info().workerIndex}-${Date.now()}`;
  const { classId, openId, instructor } = await seedClass(browser, seed);
  const archived = await classroomApi(instructor).post(`/api/backend/classroom/classes/${classId}/archive`);
  expect(archived.ok()).toBeTruthy();

  await instructor.goto(`/classes/${classId}/problems/${openId}/submit`);

  const banner = instructor.getByTestId("instructor-viewing-banner");
  await expect(banner.getByTestId("class-archived-note")).toHaveText("이 클래스는 보관되어 새 제출을 받지 않습니다.");
  await expect(instructor.getByTestId("class-archived-note")).toHaveCount(1);
  await expect(instructor.getByText(INSTRUCTOR_WARNING)).toHaveCount(0);
  await expect(banner.getByRole("link", { name: "문제 편집" })).toBeVisible();
  await expect(banner.getByRole("link", { name: "제출 현황" })).toBeVisible();
  await expect(instructor.getByTestId("submit-form-area")).toHaveCount(0);
});

test("제출 중 내보내짐(403)을 받으면 새로 고친 뒤처럼 폼이 사라진다", async ({ page, browser }) => {
  const seed = `access-403-${test.info().workerIndex}-${Date.now()}`;
  const { classId, openId, joinCode } = await seedClass(browser, seed);
  await joinAs(page, seed, joinCode);
  await page.goto(`/classes/${classId}/problems/${openId}/submit`);
  await expect(page.getByTestId("repository-url-input")).toBeVisible();

  // 폼을 연 채 내보내진 상황 — 제출은 403, 다시 읽은 문제는 내보냄 사유를 준다.
  await page.route(
    (url) => url.pathname.endsWith(`/problems/${openId}/submissions`),
    (route) =>
      route.request().method() === "POST"
        ? route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ detail: "더 이상 이 클래스의 참여자가 아닙니다." }) })
        : route.continue(),
  );
  await page.route(
    (url) => url.pathname.endsWith(`/problems/${openId}/mine`),
    async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      await route.fulfill({ response, json: { ...body, submit_blocked_reason: "expelled" } });
    },
  );
  await page.getByTestId("repository-url-input").fill("https://github.com/owner/repo");
  await page.getByTestId("submit-repository").click();

  await expect(page.getByTestId("member-expelled-note")).toHaveText("이 클래스에서 내보내져 새로 제출할 수 없습니다.");
  await expect(page.getByTestId("submit-repository")).toHaveCount(0);
});
