import { expect, test } from "@playwright/test";

// 로그인 뒤 목적지는 공개 앱 서버가 정한다(#1388 T2, `/api/auth/continue`).
// 허용된 형제(강의실)로의 복귀는 단위 시험(lib/auth/login-destination.test.ts)이 맡는다 —
// 이 프로젝트는 강의실 오리진을 쓰지 않는다(scripts/test_e2e_origins.py).

const FAKE_PROVIDER = "kakao";
const FOREIGN_ORIGINS = ["https://evil.example", "http://localhost:53003"];

async function seedLogin(page: import("@playwright/test").Page, path: string, seed: string): Promise<void> {
  await page.goto(path);
  await page.getByTestId("fake-login-seed").fill(seed);
  await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
}

test.describe("시드 로그인 뒤 목적지 (#1388)", () => {
  test("next 가 같은 오리진 경로면 거기로 간다", async ({ page }) => {
    await seedLogin(page, `/login?next=${encodeURIComponent("/console/profile")}`, "continue-profile-user");
    await expect(page).toHaveURL(/\/console\/profile$/, { timeout: 15_000 });
  });

  for (const [index, foreign] of FOREIGN_ORIGINS.entries()) {
    test(`next_origin=${foreign} 이면 공개 앱 첫 화면에 남는다`, async ({ page, baseURL }) => {
      const leaked: string[] = [];
      await page.route(
        (url) => url.origin !== new URL(baseURL!).origin,
        async (route) => {
          if (route.request().isNavigationRequest()) leaked.push(route.request().url());
          await route.abort();
        },
      );

      const query = new URLSearchParams({ next: "/console/profile", next_origin: foreign });
      await seedLogin(page, `/login?${query.toString()}`, `continue-foreign-${index}`);

      await expect(page).toHaveURL(`${new URL(baseURL!).origin}/`, { timeout: 15_000 });
      await expect(page.getByTestId("account-menu-trigger")).toBeVisible();
      expect(leaked).toEqual([]);
    });
  }

  test("로그인한 채 /api/auth/continue 에 바깥 next_origin 을 주어도 / 로 303 이다", async ({ page }) => {
    await seedLogin(page, "/login", "continue-request-user");
    await expect(page.getByTestId("account-menu-trigger")).toBeVisible({ timeout: 15_000 });

    for (const foreign of FOREIGN_ORIGINS) {
      const query = new URLSearchParams({ next: "/console/profile", next_origin: foreign });
      const res = await page.request.get(`/api/auth/continue?${query.toString()}`, { maxRedirects: 0 });
      expect(res.status(), foreign).toBe(303);
      expect(res.headers()["location"], foreign).toBe("/");
    }
  });

  test("세션이 없으면 /api/auth/continue 는 /login 으로 보내고 바깥 next_origin 을 싣지 않는다", async ({
    request,
  }) => {
    const query = new URLSearchParams({ next: "/console/profile", next_origin: "https://evil.example" });
    const res = await request.get(`/api/auth/continue?${query.toString()}`, { maxRedirects: 0 });
    expect(res.status()).toBe(303);
    const location = new URL(res.headers()["location"]!, "http://localhost.invalid");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/");
    expect(location.searchParams.has("next_origin")).toBe(false);
  });
});
