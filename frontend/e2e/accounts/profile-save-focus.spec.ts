import { expect, test } from "@playwright/test";

import { establishDeveloperSession } from "../lib/session";

// 「내 정보」 저장 뒤 초점은 저장 버튼에 남는다 — 저장 중 `disabled` 가 초점을 BODY 로 떨구던 자리(#1517 취향2).
for (const [name, viewport] of [
  ["데스크톱", { width: 1280, height: 800 }],
  ["390px", { width: 390, height: 844 }],
] as const) {
  test(`${name}: 저장 버튼 Enter → 저장 완료 안내가 읽히고 초점이 저장 버튼에 남는다`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await establishDeveloperSession(page, `profile-focus-${test.info().workerIndex}-${Date.now()}`, "/console/profile");

    const input = page.getByTestId("profile-developer-display-name-input");
    await input.fill(`초점${Date.now() % 100000}`);
    // 저장 요청이 끝나기 전의 중간 상태를 붙잡는다.
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    await page.route("**/api/backend/accounts/developer-profile", async (route) => {
      if (route.request().postData()?.includes("display_name")) await gate;
      await route.continue();
    });

    const save = page.getByTestId("profile-developer-save");
    await save.focus();
    await page.keyboard.press("Enter");

    // 저장 중에도 초점은 버튼에 있고 낭독기에는 「저장 중」이 비활성으로 읽힌다.
    await expect(save).toBeFocused();
    await expect(save).toHaveAttribute("aria-disabled", "true");
    await expect(save).toHaveAccessibleName("저장 중...");
    release();

    const status = page.getByRole("status").filter({ hasText: "저장했습니다" });
    await expect(status).toHaveText("참가자 표시 이름 · 소개 저장했습니다.");
    await expect(save).toBeFocused();
    await expect(save).not.toHaveAttribute("aria-disabled", "true");
  });
}
