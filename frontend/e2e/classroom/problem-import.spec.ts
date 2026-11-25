import { expect, test } from "@playwright/test";

import { runSeed } from "../lib/seed-http";
import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 강의실 — 「문제 가져오기」 시트의 공모전 탭(#876, 한때 따로 된 시트였다). 목록·「따라간다」 문구는
// 단위 시험과 백엔드 시험이 고정하고, 여기서는 실제 스택에서 고르고 들여와 편집 화면으로 가는 한 갈래만 걷는다.

test("새 문제 화면의 「문제 가져오기」에서 공모전 탭으로 공모전을 들여온다", async ({ page }) => {
  const seed = `problem-import-contest-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const created = await api.post("/api/backend/classroom/classes", {
    data: { name: `가져오기 클래스 ${Date.now()}`, instructor_display_name: "강사" },
  });
  expect(created.ok()).toBeTruthy();
  const classId = (await created.json()).id as number;

  const { contest_id: contestId, title } = (await runSeed("importable-contest", { run_id: seed })) as {
    contest_id: number;
    title: string;
  };

  await page.goto(`/classes/${classId}/problems/new`);
  // 가져오기 버튼은 하나다.
  await expect(page.getByTestId("open-problem-import")).toHaveText("문제 가져오기");
  await page.getByTestId("open-problem-import").click();
  await expect(page.getByRole("dialog", { name: "문제 가져오기" })).toBeVisible();

  await page.getByTestId("problem-import-tab-contest").click();
  await page.getByTestId("problem-import-search-input").fill(title);
  await page.getByTestId("problem-import-search-submit").click();
  await page.getByTestId(`problem-import-row-contest-${contestId}`).check();
  await page.getByTestId("problem-import-import-submit").click();

  // 들여온 문제의 편집 화면으로 간다.
  await expect(page).toHaveURL(new RegExp(`/classes/${classId}/problems/\\d+`));
  await expect(page.getByRole("heading", { name: title })).toBeVisible();
});

// 키보드만으로(#1463 의 같은 결함) — 열리면 창 안으로 초점, Tab 은 창 안, Escape 로 닫히고 여는 단추로 돌아온다.
test("「문제 가져오기」 시트는 초점이 안으로 들어가 갇히고 Escape 로 닫히며 단추로 돌아온다", async ({ page }) => {
  const seed = `problem-import-kbd-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const created = await classroomApi(page).post("/api/backend/classroom/classes", {
    data: { name: `가져오기 키보드 ${Date.now()}`, instructor_display_name: "강사" },
  });
  const classId = (await created.json()).id as number;

  await page.goto(`/classes/${classId}/problems/new`);
  const opener = page.getByTestId("open-problem-import");
  await opener.focus();
  await page.keyboard.press("Enter");
  const dialog = page.getByRole("dialog", { name: "문제 가져오기" });
  await expect(dialog).toBeVisible();
  // 낭독기는 이름과 함께 무엇이 일어나는지를 듣는다(#1477).
  await expect(dialog).toHaveAccessibleDescription(/고른 문제가 지금 이 클래스에 초안으로 들어옵니다/);
  await expect(dialog.locator(":focus")).toHaveCount(1);
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Tab");
    await expect(dialog.locator(":focus")).toHaveCount(1);
  }
  for (let i = 0; i < 30; i++) {
    await page.keyboard.press("Shift+Tab");
    await expect(dialog.locator(":focus")).toHaveCount(1);
  }
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await expect(opener).toBeFocused();
});

// 초점 없이 열어도(낭독기 활성화·초점을 못 받는 터치) 닫으면 초점은 연 단추로 돌아온다 — BODY 로 돌아가지 않는다(#1509 ② 같은 꼴).
for (const how of ["Escape", "닫기 단추"] as const) {
  for (const where of ["새 문제 화면", "클래스 문제 탭"] as const) {
    test(`${where}에서 초점 없이 연 「문제 가져오기」를 ${how}로 닫으면 초점이 연 단추에 있다`, async ({ page }) => {
      const seed = `problem-import-nofocus-${test.info().workerIndex}-${Date.now()}`;
      await establishClassroomSession(page, seed);
      const created = await classroomApi(page).post("/api/backend/classroom/classes", {
        data: { name: `가져오기 초점 ${Date.now()}`, instructor_display_name: "강사" },
      });
      const classId = (await created.json()).id as number;

      await page.goto(where === "새 문제 화면" ? `/classes/${classId}/problems/new` : `/classes/${classId}?tab=problems`);
      const opener = page.getByTestId(where === "새 문제 화면" ? "open-problem-import" : "problems-empty-import");
      await expect(opener).toBeVisible();
      await opener.evaluate((el) => (el as HTMLElement).blur());
      expect(await page.evaluate(() => document.activeElement === document.body)).toBe(true);
      await opener.dispatchEvent("click");
      const dialog = page.getByRole("dialog", { name: "문제 가져오기" });
      await expect(dialog).toBeVisible();
      if (how === "Escape") await page.keyboard.press("Escape");
      else await page.getByTestId("problem-import-close").click();
      await expect(dialog).toHaveCount(0);
      await expect(opener).toBeFocused();
    });
  }
}
