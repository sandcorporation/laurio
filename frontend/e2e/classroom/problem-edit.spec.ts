import { expect, test } from "@playwright/test";
import type { Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 문제 편집 화면 (#637, 시안 v2). 저장은 머리, 상태 전이는 오른쪽 열의 상태 카드,
// 체크리스트는 끌기 손잡이로 순서를 바꾼다(키보드 화살표 대안 포함). 준비 단계는 `request`
// 로 API 를 직접 친다(ADR-0017/0021) — 브라우저로 걷는 것은 화면의 동작뿐이다.

async function seedProblem(page: Page, seed: string, labels: string[], open = false) {
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const classResponse = await api.post("/api/backend/classroom/classes", {
    data: { name: `문제 편집 테스트 ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(classResponse.ok()).toBeTruthy();
  const classId = (await classResponse.json()).id as number;
  const problemResponse = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: {
      title: `편집할 문제 ${Date.now()}`,
      submission_formats: ["source"],
      checklist_items: labels.map((label) => ({ label, required: true })),
      open,
    },
  });
  expect(problemResponse.ok()).toBeTruthy();
  const problemId = (await problemResponse.json()).id as number;
  return { api, classId, problemId };
}

async function labelsInOrder(page: Page): Promise<string[]> {
  await expect(page.getByTestId("checklist-items")).toBeVisible();
  return page.getByTestId("checklist-items").getByRole("textbox").evaluateAll((inputs) =>
    inputs.map((input) => (input as HTMLInputElement).value),
  );
}

test("머리의 저장이 제목을 저장하고 클래스 상세로 돌아간다", async ({ page }) => {
  const { api, classId, problemId } = await seedProblem(page, `edit-save-${test.info().workerIndex}-${Date.now()}`, ["통과 조건"]);
  await page.goto(`/classes/${classId}/problems/${problemId}`);

  const newTitle = `고친 제목 ${Date.now()}`;
  await page.getByTestId("edit-problem-title-input").fill(newTitle);
  await page.getByTestId("edit-problem-submit").click();

  await expect(page).toHaveURL(`/classes/${classId}`);
  const saved = await (await api.get(`/api/backend/classroom/classes/${classId}/problems/${problemId}`)).json();
  expect(saved.title).toBe(newTitle);
});

test("체크리스트 순서를 손잡이의 화살표로 바꾸면 새로고침 뒤에도 남는다", async ({ page }) => {
  const { classId, problemId } = await seedProblem(page, `edit-order-key-${test.info().workerIndex}-${Date.now()}`, ["첫째", "둘째", "셋째"]);
  await page.goto(`/classes/${classId}/problems/${problemId}`);
  expect(await labelsInOrder(page)).toEqual(["첫째", "둘째", "셋째"]);

  const handles = page.locator('[data-testid$="-drag-handle"]');
  await handles.nth(2).focus();
  const reorder = page.waitForResponse((r) => r.url().includes("/checklist-items/reorder") && r.ok());
  await page.keyboard.press("ArrowUp");
  await reorder;
  expect(await labelsInOrder(page)).toEqual(["첫째", "셋째", "둘째"]);

  await page.reload();
  expect(await labelsInOrder(page)).toEqual(["첫째", "셋째", "둘째"]);
});

test("체크리스트 항목을 손잡이로 끌어 놓으면 새로고침 뒤에도 순서가 남는다", async ({ page }) => {
  const { classId, problemId } = await seedProblem(page, `edit-order-drag-${test.info().workerIndex}-${Date.now()}`, ["첫째", "둘째", "셋째"]);
  await page.goto(`/classes/${classId}/problems/${problemId}`);

  const handles = page.locator('[data-testid$="-drag-handle"]');
  const reorder = page.waitForResponse((r) => r.url().includes("/checklist-items/reorder") && r.ok());
  await handles.nth(0).dragTo(page.getByTestId("checklist-items").locator("li").nth(2));
  await reorder;
  expect(await labelsInOrder(page)).toEqual(["둘째", "셋째", "첫째"]);

  await page.reload();
  expect(await labelsInOrder(page)).toEqual(["둘째", "셋째", "첫째"]);
});

test("상태 카드로 초안을 연다", async ({ page }) => {
  const { classId, problemId } = await seedProblem(page, `edit-open-${test.info().workerIndex}-${Date.now()}`, ["통과 조건"]);
  await page.goto(`/classes/${classId}/problems/${problemId}`);
  const badge = page.getByTestId("edit-problem-status-badge");
  await expect(badge).toHaveText("초안");
  await page.getByTestId("open-problem-button").click();
  await expect(badge).toHaveText("열림");
});

test("상태 카드로 열린 문제를 숨기고 다시 연다", async ({ page }) => {
  const { classId, problemId } = await seedProblem(page, `edit-hide-${test.info().workerIndex}-${Date.now()}`, ["통과 조건"], true);
  await page.goto(`/classes/${classId}/problems/${problemId}`);
  const badge = page.getByTestId("edit-problem-status-badge");
  await expect(badge).toHaveText("열림");
  await page.getByTestId("hide-problem-button").click();
  await page.getByTestId("hide-problem-confirm").click();
  await expect(badge).toHaveText("숨김");
  await page.getByTestId("reopen-problem-button").click();
  await expect(badge).toHaveText("열림");
});

test("1200px 이상에서는 두 열, 그보다 좁으면 한 열이다", async ({ page }) => {
  const { classId, problemId } = await seedProblem(page, `edit-columns-${test.info().workerIndex}-${Date.now()}`, ["통과 조건"]);
  const url = `/classes/${classId}/problems/${problemId}`;

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(url);
  const side = page.getByTestId("edit-problem-side-rail");
  const title = page.getByTestId("edit-problem-title-input");
  await expect(side).toBeVisible();
  const wide = { side: await side.boundingBox(), title: await title.boundingBox() };
  expect(wide.side!.x).toBeGreaterThan(wide.title!.x + wide.title!.width);
  expect(wide.side!.width).toBeLessThanOrEqual(301);

  await page.setViewportSize({ width: 1024, height: 900 });
  const narrow = { side: await side.boundingBox(), title: await title.boundingBox() };
  expect(narrow.side!.y).toBeGreaterThan(narrow.title!.y);
});

test("미리보기 탭은 지금 입력한 제목을 참여자 화면으로 비춘다", async ({ page }) => {
  const { classId, problemId } = await seedProblem(page, `edit-preview-${test.info().workerIndex}-${Date.now()}`, ["통과 조건"]);
  await page.goto(`/classes/${classId}/problems/${problemId}`);
  await page.getByTestId("edit-problem-title-input").fill("저장 전 제목");
  await page.getByTestId("edit-problem-tab-preview").click();
  await expect(page.getByTestId("edit-problem-preview-panel")).toContainText("저장 전 제목");
  await expect(page.getByTestId("edit-problem-preview-panel")).toContainText("통과 조건");
});
