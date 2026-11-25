import { expect, test } from "@playwright/test";

import { establishDeveloperSession } from "../lib/session";

// 공개 앱 탭 제목에 화면 이름이 붙는다(#1478 4) — 「Codemit」뿐이면 탭만 봐서는 어느 화면인지 모른다.
// 화면마다 제목을 달았는지는 `lib/rendering/tab-title-coverage.test.ts` 가 전부 본다.
test("로그아웃 화면(/, /login)의 탭 제목은 「화면 이름 · Codemit」이다", async ({ page }) => {
  await page.goto("/login");
  await expect(page).toHaveTitle("로그인 · Codemit");
  await page.goto("/");
  await expect(page).toHaveTitle("홈 · Codemit");
});

test("콘솔 화면(/console/profile, /console/notifications)의 탭 제목은 「화면 이름 · Codemit」이다", async ({ page }) => {
  await establishDeveloperSession(page, `tab-title-${test.info().workerIndex}-${Date.now()}`, null);
  await page.goto("/console/profile");
  await expect(page).toHaveTitle("내 정보 · Codemit");
  await page.goto("/console/notifications");
  await expect(page).toHaveTitle("알림 · Codemit");
});
