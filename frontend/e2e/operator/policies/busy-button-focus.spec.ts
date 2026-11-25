import { expect, test } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../../lib/seed-operator";
import { establishOperatorSession } from "../../lib/session";

// 운영 설정 저장 중 단추는 `disabled` 가 아니라 `aria-disabled` 라 초점이 BODY 로 떨어지지 않는다(#1517 취향2).
const MODEL_ROW = "runtime-setting-LLM_OPENAI_MODEL";

for (const [name, viewport] of [
  ["데스크톱", { width: 1280, height: 800 }],
  ["390px", { width: 390, height: 844 }],
] as const) {
  test(`@exclusive ${name}: 저장 Enter → 저장 중에도 초점이 단추에 남고 aria-disabled 다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    const su = await seedE2eOperator({ username: `e2e-op-busy-${Date.now()}`, superuser: true });
    await establishOperatorSession(page, su.username, E2E_OPERATOR_PASSWORD, "/settings");
    await page.getByTestId(`${MODEL_ROW}-input`).fill("gpt-e2e-busy");

    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/**", async (route) => {
      if (route.request().method() !== "GET") await gate;
      await route.continue();
    });

    const save = page.getByTestId(`${MODEL_ROW}-save`);
    await save.focus();
    await page.keyboard.press("Enter");
    await expect(save).toHaveAttribute("aria-disabled", "true");
    await expect(save).toBeFocused();
    release();
    await expect(save).not.toHaveAttribute("aria-disabled", "true");
    await expect(save).toBeFocused();

    // 뒷정리 — 바꾼 값을 지워 env 로 돌린다.
    await page.getByTestId(`${MODEL_ROW}-clear`).click();
  });
}
