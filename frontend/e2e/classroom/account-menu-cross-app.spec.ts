import { expect, test } from "@playwright/test";

import { establishClassroomSession } from "./lib/cross-app-session";

// 두 앱 계정 메뉴에서 서로의 앱으로 건너간다 (#375·#376, spec #371). 두 앱의
// 계정 버튼·메뉴를 「내 계정」 드롭다운으로 통일한 뒤 남기는 유일한 새 스펙이다
// (spec #371의 Testing Decisions — "실행 중인 앱: 두 앱 헤더 메뉴 ... 를
// 브라우저로 걷는다. 새 스펙은 「두 앱 계정 메뉴에서 서로의 앱으로 건너간다」
// 한 벌만 남긴다").
//
// 이 프로젝트("classroom")는 강의실 baseURL만 치므로, 공개 앱 쪽 단언은 절대
// URL로 직접 오간다 — `establishClassroomSession`이 이미 그렇게 두 오리진을
// 넘나든다(cross-app-session.ts).
function publicOrigin(): string {
  return new URL(process.env.LAURIO_E2E_BASE_URL ?? "http://127.0.0.1:53000").origin;
}

test("공개 앱 계정 메뉴의 「클래스로 가기」로 강의실로 건너간다", async ({ page }) => {
  await establishClassroomSession(page, `cross-app-to-classroom-${Date.now()}`);

  await page.goto(publicOrigin());
  await page.getByTestId("account-menu-trigger").click();
  await page.getByTestId("account-menu-panel").waitFor({ state: "visible" });

  const classroomLink = page.getByTestId("account-menu-classroom-link");
  await expect(classroomLink).toHaveText("클래스로 가기");
  const href = await classroomLink.getAttribute("href");
  expect(href).toBeTruthy();

  await classroomLink.click();
  await expect(page).toHaveURL(new RegExp(`^${href!.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  await expect(page.getByTestId("classroom-home-heading")).toBeVisible();
});

test("강의실 계정 메뉴의 「공모전으로 가기」로 공개 앱으로 건너간다", async ({ page }) => {
  await establishClassroomSession(page, `cross-app-to-public-${Date.now()}`);

  await page.goto("/");
  await page.getByTestId("account-menu-trigger").click();
  await page.getByTestId("account-menu-panel").waitFor({ state: "visible" });

  const contestsLink = page.getByTestId("account-menu-contests-link");
  await expect(contestsLink).toHaveText("공모전으로 가기");
  const href = await contestsLink.getAttribute("href");
  expect(href).toBeTruthy();
  expect(new URL(href!).origin).toBe(publicOrigin());

  await contestsLink.click();
  await expect(page).toHaveURL(new RegExp(`^${publicOrigin().replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  await expect(page.getByTestId("site-header")).toBeVisible();
});
