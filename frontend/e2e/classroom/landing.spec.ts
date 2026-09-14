import { expect, test } from "@playwright/test";

import { establishClassroomSession } from "./lib/cross-app-session";

// 강의실 랜딩(#395, ADR-0017 위험 1 — 공개 페이지 SSR). 강의실에 색인되는
// 공개 표면은 이 랜딩 하나뿐이다(middleware.ts·lib/landing/decide-root-view.ts).
//
// 자바스크립트를 끈 비로그인 요청으로도 랜딩 문구와 「클래스 만들기」 링크가
// HTML 에 그대로 있어야 색인이 된다 — 클라이언트 컴포넌트로 만들면 이 사실이
// 조용히 깨진다(seam.spec.ts 와 같은 기법).
test.describe("자바스크립트 없이, 로그인 쿠키 없이", () => {
  test.use({ javaScriptEnabled: false });

  test("루트에 랜딩이 SSR 되고, 로그인으로 튕기지 않는다", async ({ page }) => {
    await page.goto("/");

    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("classroom-landing-heading")).toBeVisible();
    await expect(page.getByTestId("classroom-landing-participant-note")).toBeVisible();

    const cta = page.getByTestId("classroom-landing-cta");
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute("href", "/login?next=/classes/new");
  });
});

test.describe("로그인 쿠키가 있으면", () => {
  test("루트가 랜딩이 아니라 내 클래스다", async ({ page }) => {
    await establishClassroomSession(page, "e2e-classroom-landing");

    await page.goto("/");

    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("classroom-home-heading")).toBeVisible();
    await expect(page.getByTestId("classroom-landing-heading")).toHaveCount(0);
  });
});

test.describe("검색 노출 표면 — 랜딩 하나만 연다(#395)", () => {
  test("robots.txt 가 루트만 허용한다", async ({ request }) => {
    const res = await request.get("/robots.txt");
    expect(res.status()).toBe(200);

    const body = await res.text();
    expect(body).toContain("Allow: /$");
    expect(body).toContain("Disallow: /");
    expect(body).toMatch(/Sitemap: .*\/sitemap\.xml/);
  });

  test("sitemap.xml 에 루트 하나만 있다", async ({ request }) => {
    const res = await request.get("/sitemap.xml");
    expect(res.status()).toBe(200);

    const body = await res.text();
    const locCount = (body.match(/<loc>/g) ?? []).length;
    expect(locCount).toBe(1);
    expect(body).toMatch(/<loc>[^<]*\/<\/loc>/);
  });

  test("아이콘 응답이 200이다 — 비로그인 탭에서도 파비콘이 뜬다(#392)", async ({ request }) => {
    for (const path of ["/icon", "/apple-icon"]) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(200);
      expect(res.headers()["content-type"], path).toContain("image/png");
    }
  });
});
