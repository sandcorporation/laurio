// 헤더 테마 메뉴의 키보드 규약(#1471 ⑥) — 열면 첫 항목, ↑↓·Home/End, Escape 로 닫고 여는 단추로 복귀.
import { expect, test } from "@playwright/test";

async function openMenu(page: import("@playwright/test").Page) {
  await page.goto("/login");
  const trigger = page.getByTestId("theme-toggle-trigger");
  await trigger.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("menu", { name: "테마 선택" })).toBeVisible();
  return trigger;
}

test.describe("@exclusive 테마 메뉴 — 키보드", () => {
  test("열면 첫 항목에 초점이 가고 ↑↓ 는 끝에서 돌며 Home·End 가 처음·끝으로 간다", async ({ page }) => {
    await openMenu(page);
    const items = page.getByRole("menuitemradio");
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
  });

  test("Escape 는 메뉴를 닫고 여는 단추로 초점을 돌린다", async ({ page }) => {
    const trigger = await openMenu(page);
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Escape");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(trigger).toBeFocused();
  });

  test("항목을 Enter 로 고르면 닫히고 여는 단추로 돌아온다", async ({ page }) => {
    const trigger = await openMenu(page);
    await page.route("**/api/theme", (route) => route.fulfill({ status: 204 }));
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Enter");
    await expect(page.getByRole("menu")).toHaveCount(0);
    await expect(trigger).toBeFocused();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  });
});
