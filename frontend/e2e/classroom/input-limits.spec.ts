import { expect, test, type Page, type Route } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 입력칸의 글자 수 상한과 422 한국어(#1390). 번역 표 전체는 vitest(`result.test.ts`)가 본다.
const LONG = "가".repeat(600);

async function createClass(page: Page, label: string) {
  await establishClassroomSession(page, `limits-${label}-${test.info().workerIndex}-${Date.now()}`);
  const created = await classroomApi(page).post("/api/backend/classroom/classes", {
    data: { name: `상한 ${Date.now()}`, instructor_display_name: "강사" },
  });
  return (await created.json()) as { id: number; join_code: string };
}

/** 600자를 채우면 상한만 남고 칸 아래에 `상한/상한` 이 보인다. */
async function expectCapped(page: Page, inputTestId: string, countTestId: string, limit: number) {
  await page.getByTestId(inputTestId).fill(LONG);
  await expect(page.getByTestId(inputTestId)).toHaveValue(LONG.slice(0, limit));
  await expect(page.getByTestId(countTestId)).toHaveText(`${limit}/${limit}`);
}

test("새 클래스 칸은 상한에서 멈추고 글자 수는 90% 부터 보인다", async ({ page }) => {
  await establishClassroomSession(page, `limits-new-class-${test.info().workerIndex}-${Date.now()}`);
  await page.goto("/classes/new");
  const name = page.getByTestId("new-class-name-input");
  const count = page.getByTestId("new-class-name-count");

  await name.fill("가".repeat(179));
  await expect(count).toHaveCount(0);
  await name.fill("가".repeat(180));
  await expect(count).toHaveText("180/200");
  await name.fill("가".repeat(300));
  await expect(name).toHaveValue("가".repeat(200));
  await expect(count).toHaveText("200/200");

  await expectCapped(
    page,
    "new-class-instructor-display-name-input",
    "new-class-instructor-display-name-count",
    100,
  );
});

test("가입 이름 칸은 100자에서 멈춘다", async ({ page, browser }) => {
  const context = await browser.newContext({ baseURL: test.info().project.use.baseURL });
  const { join_code } = await createClass(await context.newPage(), "join");
  await establishClassroomSession(page, `limits-joiner-${test.info().workerIndex}-${Date.now()}`);

  await page.goto(`/join/${join_code}`);

  await expectCapped(page, "join-display-name-input", "join-display-name-count", 100);
});

test("새 문제의 제목·체크리스트·직접 입력 지침은 상한에서 멈춘다", async ({ page }) => {
  const { id } = await createClass(page, "new-problem");
  await page.goto(`/classes/${id}/problems/new`);

  await expectCapped(page, "new-problem-title-input", "new-problem-title-count", 200);
  await expectCapped(
    page,
    "new-problem-new-checklist-item-label-input",
    "new-problem-new-checklist-item-label-count",
    200,
  );
  await page.getByTestId("new-problem-new-checklist-item-submit").click();
  await expectCapped(page, "new-problem-checklist-item-0-label-input", "new-problem-checklist-item-0-label-count", 200);
  await page.getByTestId("new-problem-grading-strictness-custom").check({ force: true });
  await expectCapped(
    page,
    "new-problem-grading-guideline-text-input",
    "new-problem-grading-guideline-text-count",
    500,
  );
});

test("문제 편집의 제목·새 항목·기존 항목은 200자에서 멈춘다", async ({ page }) => {
  const { id } = await createClass(page, "edit-problem");
  const api = classroomApi(page);
  const base = `/api/backend/classroom/classes/${id}/problems`;
  const problem = await api.post(base, { data: { title: "편집할 문제", submission_formats: ["repository"] } });
  const problemId = (await problem.json()).id as number;
  const item = await api.post(`${base}/${problemId}/checklist-items`, {
    data: { label: "목록을 그린다", required: true },
  });
  const itemId = (await item.json()).id as number;

  await page.goto(`/classes/${id}/problems/${problemId}`);

  await expectCapped(page, "edit-problem-title-input", "edit-problem-title-count", 200);
  await expectCapped(page, "new-checklist-item-label-input", "new-checklist-item-label-count", 200);
  await expectCapped(page, `checklist-item-${itemId}-label-input`, `checklist-item-${itemId}-label-count`, 200);
});

test("저장이 422 면 라벨을 붙인 한국어가 보이고 영어 원문은 없다", async ({ page }) => {
  const { id } = await createClass(page, "422");
  await page.route(
    (url) => url.pathname === `/api/backend/classroom/classes/${id}/problems`,
    (route: Route) =>
      route.request().method() === "POST"
        ? route.fulfill({
            status: 422,
            json: {
              detail: [
                {
                  type: "string_too_long",
                  loc: ["body", "payload", "title"],
                  msg: "String should have at most 200 characters",
                  ctx: { max_length: 200 },
                },
              ],
            },
          })
        : route.continue(),
  );
  await page.goto(`/classes/${id}/problems/new`);
  await page.getByTestId("new-problem-title-input").fill("제목");

  await page.getByTestId("new-problem-submit").click();

  await expect(page.getByTestId("new-problem-error")).toHaveText("제목: 200자까지 쓸 수 있습니다.");
  await expect(page.getByText("String should")).toHaveCount(0);
});
