import { expect, test } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../../lib/seed-operator";
import { establishOperatorSession } from "../../lib/session";

// 운영자 좁은 화면 내비 덮개(#523, #1484 ⑤) — 모달(역할 dialog)이다: 밖은 inert, 열면 덮개 안으로, 닫으면 버튼으로,
// Tab 은 덮개 안을 돈다(주소창으로 새지 않는다). 낭독기는 이름 붙은 창에 들어가 안의 내비 landmark 를 만난다.

test("좁은 화면 내비 덮개는 이름 붙은 모달이고 Tab 이 안을 돌며 Escape 로 닫으면 메뉴 단추로 돌아온다", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 800 });
  const operator = await seedE2eOperator();
  await establishOperatorSession(page, operator.username, E2E_OPERATOR_PASSWORD);
  await expect(page.getByTestId("operator-home-heading")).toBeVisible();

  const button = page.getByTestId("operator-menu-button");
  await button.focus();
  await page.keyboard.press("Enter");

  const drawer = page.getByRole("dialog", { name: "운영자 메뉴" });
  await expect(drawer).toBeVisible();
  await expect(drawer).toHaveAttribute("aria-modal", "true");
  await expect(drawer.getByRole("navigation", { name: "운영자 내비게이션" })).toBeVisible();
  await expect(drawer.locator(":focus")).toHaveCount(1);

  // Tab·Shift+Tab 을 여러 번 눌러도 초점은 덮개 밖으로 나가지 않는다.
  for (let i = 0; i < 40; i += 1) {
    await page.keyboard.press("Tab");
    await expect(drawer.locator(":focus")).toHaveCount(1);
  }
  for (let i = 0; i < 3; i += 1) {
    await page.keyboard.press("Shift+Tab");
    await expect(drawer.locator(":focus")).toHaveCount(1);
  }

  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(button).toBeFocused();
});
