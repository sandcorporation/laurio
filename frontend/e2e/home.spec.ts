// LP-01 (#93, spec #92) — 사이트에 입구를 낸다.
//
// 이 파일이 세우는 것은 헤더 자체가 아니라 **닿을 수 있음**이다. 티켓의 이유가
// 된 실패는 "119건이 초록인데 입구가 없다"였다 — 모든 기존 e2e가
// `page.goto()`로 URL을 직접 쳤기 때문에 아무도 "첫 방문자가 / 에서 클릭만으로
// 어디까지 갈 수 있는가"를 보지 않았다. 아래 마지막 테스트가 그 구멍을 메운다.
import fs from "node:fs";
import path from "node:path";

import { expect, test } from "@playwright/test";

import { seedE2eContests, type SeededContests } from "./lib/seed";

let seeded: SeededContests;

test.beforeAll(() => {
  seeded = seedE2eContests();
});

test.describe("헤더 — 모든 페이지에 같은 모양으로 선다", () => {
  for (const target of ["/", "/contests", "/login"]) {
    test(`${target} 에도 브랜드·공모전·개최 CTA 가 있다`, async ({ page }) => {
      await page.goto(target);
      await expect(page.getByTestId("header-brand")).toBeVisible();
      await expect(page.getByTestId("header-nav-contests")).toBeVisible();
      await expect(page.getByTestId("header-cta-new-contest")).toBeVisible();
    });
  }

  test("로그인하지 않아도 개최 CTA 가 보이고, 누르면 로그인으로 안내된다", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("header-login-link")).toBeVisible();

    await page.getByTestId("header-cta-new-contest").click();
    await expect(page).toHaveURL(/\/login/);
  });

  test("로그인하면 로그인 대신 내 콘솔 링크를 보여준다", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill(`e2e-home-header-${Date.now()}`);
    await page.getByTestId("login-kakao").click();
    await expect(page).toHaveURL(/\/console/);

    await expect(page.getByTestId("header-console-link")).toBeVisible();
    await expect(page.getByTestId("header-login-link")).toHaveCount(0);
  });

  test("모바일 폭에서도 헤더 링크가 보이고 클릭 가능한 상태로 남는다", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 700 });
    await page.goto("/");

    await expect(page.getByTestId("header-brand")).toBeVisible();
    await expect(page.getByTestId("header-nav-contests")).toBeVisible();
    await expect(page.getByTestId("header-cta-new-contest")).toBeVisible();
  });
});

test.describe("홈 — 자리표시가 아니라 실제 공모전을 보여준다", () => {
  test('이 페이지에 "use client" 가 없다', () => {
    // ADR-0015 — 홈은 공개 표면이라 서버 컴포넌트로 남아야 색인된다.
    const source = fs.readFileSync(path.join(__dirname, "../app/page.tsx"), "utf-8");
    expect(source).not.toContain('"use client"');
  });

  test.describe("자바스크립트 없이", () => {
    test.use({ javaScriptEnabled: false });

    test("공개 공모전이 서버 렌더링된 HTML 에 들어 있다", async ({ page }) => {
      await page.goto("/");
      const html = await page.content();
      expect(html).toContain(seeded.funded.title);
    });

    test("draft Contest 는 홈에 나타나지 않는다", async ({ page }) => {
      await page.goto("/");
      const html = await page.content();
      expect(html).not.toContain(seeded.draft.title);
    });
  });
});

// 이 스펙의 존재 이유. 티켓 #93 본문 그대로: 이 테스트가 있었다면 입구 없는
// staging 이 나가지 않았다. `page.goto`는 맨 처음 한 번뿐이고, 그 뒤로는 전부
// 클릭이다.
test("첫 방문자가 / 에서 시작해 클릭만으로 공모전 목록과 로그인 화면에 닿는다", async ({
  page,
}) => {
  await page.goto("/");

  // 공모전 목록.
  await page.getByTestId("header-nav-contests").click();
  await expect(page).toHaveURL(/\/contests$/);
  await expect(page.getByTestId("contest-count")).toBeVisible();

  // 브랜드를 눌러 홈으로 — 이것도 클릭이다, URL 을 다시 치지 않는다.
  await page.getByTestId("header-brand").click();
  await expect(page).toHaveURL(/\/$/);

  // 로그인 화면.
  await expect(page.getByTestId("header-login-link")).toBeVisible();
  await page.getByTestId("header-login-link").click();
  await expect(page).toHaveURL(/\/login/);
  await expect(page.getByTestId("login-kakao")).toBeVisible();
});
