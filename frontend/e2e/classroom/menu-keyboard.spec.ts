import { expect, test } from "@playwright/test";

import { classroomApi, establishClassroomSession } from "./lib/cross-app-session";

// 메뉴 단추의 공용 키 규약(#1471 ⑥, use-menu-focus) — 문제 순서 행 메뉴와 테마 메뉴. 참여자 행 메뉴는
// participants-tab.spec.ts 가 같은 훅으로 본다. 열면 첫 (눌릴 수 있는) 항목, ↑↓·Home/End, Escape 는 닫고 여는 단추로, Tab 은 닫는다.

test("문제 순서 행 메뉴는 키보드만으로 열고 오가고 닫으며, 항목을 고르면 ⋮ 로 돌아온다", async ({ page }) => {
  const seed = `menu-problems-${test.info().workerIndex}-${Date.now()}`;
  await establishClassroomSession(page, seed);
  const api = classroomApi(page);
  const classId = (
    await (
      await api.post("/api/backend/classroom/classes", {
        data: { name: `메뉴 ${Date.now()}`, instructor_display_name: "강사" },
      })
    ).json()
  ).id as number;
  const ids: number[] = [];
  for (const title of ["첫째 문제", "둘째 문제"]) {
    const res = await api.post(`/api/backend/classroom/classes/${classId}/problems`, {
      data: { title, submission_formats: ["repository"] },
    });
    ids.push((await res.json()).id as number);
  }
  await page.goto(`/classes/${classId}?tab=problems`);

  const trigger = page.getByTestId(`problem-row-${ids[1]}-menu`);
  const menu = page.getByRole("menu", { name: "둘째 문제 순서 메뉴" });
  const up = menu.getByRole("menuitem", { name: "위로" });
  const down = menu.getByRole("menuitem", { name: "아래로" });

  // 마지막 행: 「아래로」는 꺼져 있다 — 열면 첫 항목 「위로」, 꺼진 항목은 건너뛴다.
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(menu).toBeVisible();
  await expect(up).toBeFocused();
  for (const key of ["ArrowDown", "ArrowUp", "End", "Home"]) {
    await page.keyboard.press(key);
    await expect(up).toBeFocused();
  }
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(trigger).toBeFocused();

  // 첫 행: 「위로」가 꺼져 있고 ↑↓ 는 「아래로」에 머문다. Tab 은 메뉴를 닫는다.
  const firstTrigger = page.getByTestId(`problem-row-${ids[0]}-menu`);
  const firstMenu = page.getByRole("menu", { name: "첫째 문제 순서 메뉴" });
  await firstTrigger.focus();
  await page.keyboard.press("Enter");
  await expect(firstMenu.getByRole("menuitem", { name: "아래로" })).toBeFocused();
  await page.keyboard.press("Tab");
  await expect(firstMenu).toHaveCount(0);
  await expect(page.locator("body:focus")).toHaveCount(0);

  // 항목을 고르면 메뉴는 닫히고 초점이 ⋮ 에 남는다.
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(down).toBeDisabled();
  await page.keyboard.press("Enter");
  await expect(menu).toHaveCount(0);
  await expect(page.getByTestId(`problem-row-${ids[1]}-menu`)).toBeFocused();
});

test("테마 메뉴는 열면 첫 항목에 초점이 서고 ↑↓·Home/End·Escape 로 다루며 고르면 단추로 돌아온다", async ({ page }) => {
  await establishClassroomSession(page, `menu-theme-${test.info().workerIndex}-${Date.now()}`);
  await page.goto("/");
  const trigger = page.getByTestId("theme-toggle-trigger");
  const menu = page.getByRole("menu", { name: "테마 선택" });
  const items = menu.getByRole("menuitemradio");

  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(menu).toBeVisible();
  await expect(items.nth(0)).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(items.nth(1)).toBeFocused();
  await page.keyboard.press("End");
  await expect(items.nth(2)).toBeFocused();
  await page.keyboard.press("ArrowDown");
  await expect(items.nth(0)).toBeFocused();
  await page.keyboard.press("ArrowUp");
  await expect(items.nth(2)).toBeFocused();
  await page.keyboard.press("Home");
  await expect(items.nth(0)).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await expect(menu).toHaveCount(0);
  // Tab 은 ⋮ 에서 이어 간다 — 초점이 body 로 빠지지 않는다.
  await expect(page.locator("body:focus")).toHaveCount(0);

  await trigger.focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("Enter");
  await expect(menu).toHaveCount(0);
  await expect(trigger).toBeFocused();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});
