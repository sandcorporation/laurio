import { expect, test, type Page } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 11차 사용 리뷰 #1478 1·2·6 — 탭 목록의 화살표 키(WAI-ARIA 탭 규약), 390px 가져오기 시트, 문제 순서 이동 안내.

async function newClass(page: Page, label: string) {
  await establishClassroomSession(page, `${label}-${test.info().workerIndex}-${Date.now()}`);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `${label} ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(created.ok()).toBeTruthy();
  return { api, classId: (await created.json()).id as number };
}

async function newProblem(api: ReturnType<typeof classroomApi>, classId: number, title: string) {
  const response = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
    data: { title, submission_formats: ["repository"] },
  });
  const problemId = (await response.json()).id as number;
  await api.post(`/api/backend/classroom/classes/${classId}/problems/${problemId}/open`);
  return problemId;
}

test("클래스 상세 탭: 고른 탭만 Tab 이 닿고 ←/→·Home/End 로 옮겨 가며 탭 패널이 탭 이름을 갖는다", async ({ page }) => {
  const { classId } = await newClass(page, "탭 키 클래스");
  await page.goto(`/classes/${classId}`);

  const problems = page.getByRole("tab", { name: "문제" });
  const participants = page.getByRole("tab", { name: "참여자" });
  const instructors = page.getByRole("tab", { name: "강사" });
  await expect(problems).toHaveAttribute("tabindex", "0");
  await expect(participants).toHaveAttribute("tabindex", "-1");
  await expect(instructors).toHaveAttribute("tabindex", "-1");
  await expect(page.getByRole("tabpanel", { name: "문제" })).toBeVisible();

  await problems.focus();
  await page.keyboard.press("ArrowRight");
  await expect(page).toHaveURL(/tab=participants/);
  await expect(participants).toBeFocused();
  await expect(participants).toHaveAttribute("aria-selected", "true");
  await expect(participants).toHaveAttribute("tabindex", "0");
  await expect(problems).toHaveAttribute("tabindex", "-1");
  const panelId = await participants.getAttribute("aria-controls");
  await expect(page.locator(`[id="${panelId}"]`)).toHaveAttribute("role", "tabpanel");
  await expect(page.getByRole("tabpanel", { name: "참여자" })).toBeVisible();

  await page.keyboard.press("End");
  await expect(page).toHaveURL(/tab=instructors/);
  await expect(instructors).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(problems).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(instructors).toBeFocused();
  await page.keyboard.press("Home");
  await expect(problems).toBeFocused();
});

test("템플릿 종류 탭과 새 문제의 작성·미리보기 탭도 화살표 키로 옮겨 간다", async ({ page }) => {
  const { classId } = await newClass(page, "탭 키 템플릿");

  await page.goto("/templates");
  const problemKind = page.getByRole("tab", { name: "문제" });
  const classKind = page.getByRole("tab", { name: "클래스" });
  await expect(classKind).toHaveAttribute("tabindex", "-1");
  await problemKind.focus();
  await page.keyboard.press("ArrowRight");
  await expect(classKind).toBeFocused();
  await expect(classKind).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("tabpanel", { name: "클래스" })).toBeVisible();

  await page.goto(`/classes/${classId}/problems/new`);
  const write = page.getByRole("tab", { name: "작성" });
  const preview = page.getByRole("tab", { name: "미리보기" });
  await expect(preview).toHaveAttribute("tabindex", "-1");
  await write.focus();
  await page.keyboard.press("ArrowRight");
  await expect(preview).toBeFocused();
  await expect(page.getByRole("tabpanel", { name: "미리보기" })).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(write).toBeFocused();
  await expect(page.getByRole("tabpanel", { name: "작성" })).toBeVisible();
});

test("문제 가져오기 시트의 탭이 화살표 키로 옮겨 간다", async ({ page }) => {
  const { classId } = await newClass(page, "시트 탭 키");
  await page.goto(`/classes/${classId}/problems/new`);
  await page.getByTestId("open-problem-import").click();
  const dialog = page.getByRole("dialog", { name: "문제 가져오기" });
  const first = dialog.getByRole("tab", { name: "공개된 문제" });
  await first.focus();
  await page.keyboard.press("ArrowRight");
  await expect(dialog.getByRole("tab", { name: "내가 올린 것" })).toBeFocused();
  await expect(dialog.getByRole("tabpanel", { name: "내가 올린 것" })).toBeVisible();
  await page.keyboard.press("End");
  await expect(dialog.getByRole("tab", { name: "공모전" })).toBeFocused();
  await page.keyboard.press("ArrowRight");
  await expect(first).toBeFocused();
});

test("390px 에서 가져오기 시트의 탭이 잘리지 않고, 문제를 골라도 목록이 한 줄로 줄지 않는다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 667 });
  const { api, classId } = await newClass(page, "시트 390 원본");
  const longDescription = Array.from({ length: 30 }, (_, i) => `설명 ${i + 1}번째 줄입니다.`).join("\n\n");
  for (let i = 1; i <= 8; i++) {
    const response = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title: `가져올 문제 ${i}`, description: longDescription, submission_formats: ["repository"] },
    });
    expect(response.ok()).toBeTruthy();
  }
  const target = await api.post("/api/backend/classroom/classes", {
    data: { name: `시트 390 대상 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const targetId = (await target.json()).id as number;

  await page.goto(`/classes/${targetId}/problems/new`);
  await page.getByTestId("open-problem-import").click();
  const dialog = page.getByTestId("problem-import-sheet");
  const box = (await dialog.boundingBox())!;
  const tablist = page.getByRole("tablist", { name: "가져올 곳" });
  expect(await tablist.evaluate((el) => el.scrollWidth - el.clientWidth)).toBeLessThanOrEqual(0);
  for (const name of ["공개된 문제", "내가 올린 것", "다른 클래스", "공모전"]) {
    const tab = page.getByRole("tab", { name });
    await expect(tab).toBeVisible();
    const tabBox = (await tab.boundingBox())!;
    expect(tabBox.x).toBeGreaterThanOrEqual(box.x - 0.5);
    expect(tabBox.x + tabBox.width).toBeLessThanOrEqual(box.x + box.width + 0.5);
  }

  await page.getByRole("tab", { name: "다른 클래스" }).click();
  const rows = page.locator("[data-testid^=problem-import-row-other-classes-]");
  await expect(rows).toHaveCount(8);
  await rows.first().check();
  await expect(page.getByTestId("problem-import-preview-title")).toBeVisible();
  const list = (await rows.first().locator("xpath=ancestor::div[contains(@class,'overflow-y-auto')][1]").boundingBox())!;
  expect(list.height).toBeGreaterThanOrEqual(120);
  // 방향을 가리키는 말이 없다 — 390 에서는 목록이 위에 있다.
  await expect(dialog).not.toContainText("왼쪽");
});

test("문제 순서를 옮기면 상태 영역이 「<문제> — N번째로 옮겼습니다」를 읽는다", async ({ page }) => {
  const { api, classId } = await newClass(page, "순서 안내");
  const ids: number[] = [];
  for (const title of ["첫째 문제", "둘째 문제", "셋째 문제"]) ids.push(await newProblem(api, classId, title));

  await page.goto(`/classes/${classId}`);
  const status = page.getByRole("status").filter({ has: page.locator("xpath=self::*[@data-testid='problems-move-status']") });
  await expect(status).toHaveText("");

  await page.getByTestId(`problem-row-${ids[0]}-menu`).click();
  await page.getByTestId(`problem-row-${ids[0]}-move-down`).click();
  await expect(status).toHaveText("첫째 문제 — 2번째로 옮겼습니다");

  await page.getByTestId(`problem-row-${ids[2]}-menu`).click();
  await page.getByTestId(`problem-row-${ids[2]}-move-up`).click();
  await expect(status).toHaveText("셋째 문제 — 2번째로 옮겼습니다");
});

test("순서 변경을 서버가 거절하면 상태 영역은 성공 대신 원래 자리로 돌아갔다고 읽고 순서도 원복된다", async ({ page }) => {
  const { api, classId } = await newClass(page, "순서 거절");
  const ids: number[] = [];
  for (const title of ["첫째 문제", "둘째 문제"]) ids.push(await newProblem(api, classId, title));

  await page.goto(`/classes/${classId}`);
  const status = page.getByRole("status").filter({ has: page.locator("xpath=self::*[@data-testid='problems-move-status']") });
  const rows = page.locator("[data-testid^='problem-row-'][data-testid$='-menu']");
  await expect(rows).toHaveCount(2);

  await page.route("**/classroom/classes/*/problems/reorder", (route) =>
    route.fulfill({ status: 400, contentType: "application/json", body: JSON.stringify({ detail: "거절" }) }),
  );
  await page.getByTestId(`problem-row-${ids[0]}-menu`).click();
  await page.getByTestId(`problem-row-${ids[0]}-move-down`).click();
  await expect(status).toHaveText("첫째 문제 — 순서를 바꾸지 못해 원래 자리로 돌아갔습니다");
  await expect(status).not.toContainText("옮겼습니다");
  await expect(rows.first()).toHaveAttribute("data-testid", `problem-row-${ids[0]}-menu`);
});
