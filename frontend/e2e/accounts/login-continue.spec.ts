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

// 로그인한 사람이 /login 을 열면 폼 대신 목적지로(#1388 T3). 형제(강의실)로의 자동 넘김과
// 순환 차단기는 단위 시험(lib/auth/login-auto-continue.test.ts·continue.test.ts)이 맡는다.
test.describe("로그인한 채 /login 을 열면 (#1388 T3)", () => {
  test("폼 없이 공개 앱 첫 화면으로 간다", async ({ page, baseURL }) => {
    await seedLogin(page, "/login", "auto-home-user");
    await expect(page.getByTestId("account-menu-trigger")).toBeVisible({ timeout: 15_000 });

    await page.goto("/login");
    await expect(page).toHaveURL(`${new URL(baseURL!).origin}/`, { timeout: 15_000 });
    await expect(page.getByTestId("fake-login-seed")).toHaveCount(0);
  });

  test("next=/console/profile 이면 프로필로 간다", async ({ page }) => {
    await seedLogin(page, "/login", "auto-profile-user");
    await expect(page.getByTestId("account-menu-trigger")).toBeVisible({ timeout: 15_000 });

    await page.goto(`/login?next=${encodeURIComponent("/console/profile")}`);
    await expect(page).toHaveURL(/\/console\/profile$/, { timeout: 15_000 });
  });

  test("바깥 next_origin 이면 공개 앱 첫 화면에 남는다", async ({ page, baseURL }) => {
    await seedLogin(page, "/login", "auto-foreign-user");
    await expect(page.getByTestId("account-menu-trigger")).toBeVisible({ timeout: 15_000 });
    const leaked: string[] = [];
    await page.route(
      (url) => url.origin !== new URL(baseURL!).origin,
      async (route) => {
        if (route.request().isNavigationRequest()) leaked.push(route.request().url());
        await route.abort();
      },
    );

    for (const foreign of FOREIGN_ORIGINS) {
      const query = new URLSearchParams({ next: "/console/profile", next_origin: foreign });
      await page.goto(`/login?${query.toString()}`);
      await expect(page, foreign).toHaveURL(`${new URL(baseURL!).origin}/`, { timeout: 15_000 });
    }
    expect(leaked).toEqual([]);
  });

  test("?error= 가 있으면 넘기지 않고 폼과 이유를 보여 준다", async ({ page }) => {
    await seedLogin(page, "/login", "auto-error-user");
    await expect(page.getByTestId("account-menu-trigger")).toBeVisible({ timeout: 15_000 });

    await page.goto("/login?error=oauth_unconfigured&next=%2F");
    await expect(page.getByTestId("login-error")).toBeVisible();
    await expect(page.getByTestId("fake-login-seed")).toBeVisible();
    await expect(page).toHaveURL(/\/login\?error=oauth_unconfigured/);
  });
});

test.describe("죽은 쿠키로 /login 을 열면 순환하지 않는다 (#1388 T3, 시나리오 7)", () => {
  async function plantDeadCookies(page: import("@playwright/test").Page, baseURL: string): Promise<void> {
    await page.context().addCookies(
      ["codemit_access", "codemit_refresh"].map((name) => ({ name, value: "dead.dead.dead", url: baseURL })),
    );
  }

  test("폼이 보이고 주소가 그대로이며 쿠키가 지워진다", async ({ page, baseURL }) => {
    await plantDeadCookies(page, baseURL!);
    // 문서 요청만 센다 — framenavigated 는 하이드레이션의 같은 문서 history 갱신에도 뜬다.
    const navigations: string[] = [];
    page.on("request", (request) => {
      if (request.isNavigationRequest() && request.frame() === page.mainFrame()) navigations.push(request.url());
    });

    const path = `/login?next=${encodeURIComponent("/console/profile")}`;
    await page.goto(path);
    await expect(page.getByTestId("fake-login-seed")).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(`${new URL(baseURL!).origin}${path}`);
    expect(navigations).toHaveLength(1);

    const cookies = await page.context().cookies();
    expect(cookies.find((c) => c.name === "codemit_access" && c.value)).toBeUndefined();
  });

  test("continue 가 실패로 /login 에 보내도 거기서 다시 넘기지 않는다", async ({ page, baseURL }) => {
    await plantDeadCookies(page, baseURL!);
    const continueHits: string[] = [];
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/auth/continue") continueHits.push(request.url());
    });

    await page.goto(`/api/auth/continue?next=${encodeURIComponent("/console/profile")}&auto=1`);
    await expect(page.getByTestId("fake-login-seed")).toBeVisible({ timeout: 15_000 });
    await expect(page).toHaveURL(/\/login\?next=%2Fconsole%2Fprofile$/);
    expect(continueHits).toHaveLength(1);
  });
});
