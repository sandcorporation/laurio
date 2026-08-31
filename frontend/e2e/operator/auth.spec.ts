import { expect, test } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";

// 운영자 앱 05(#63) — 로그인·세션·미들웨어 가드·Origin 검증(ADR-0016/0019).
//
// 시임 규약(ADR-0021, playwright.config.ts 상단 주석)을 그대로 따른다: 브라우저가
// 필요한 것은 `page`로, 아닌 것(미들웨어 리다이렉트, Origin 검증)은 raw `request`로
// 친다 — 이 프로젝트("operator")는 운영자 앱의 baseURL만 친다.

test.describe("미들웨어 가드 — 콘텐츠가 그려지기 전에 리다이렉트한다", () => {
  test("세션 쿠키가 전혀 없으면 / 요청 자체가 302/307로 /login을 가리킨다", async ({
    request,
  }) => {
    const res = await request.get("/", { maxRedirects: 0 });
    expect([302, 307]).toContain(res.status());
    expect(res.headers()["location"]).toContain("/login");
  });

  test("리다이렉트를 따라가도 보호된 콘텐츠는 응답 본문에 한 조각도 없다", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("operator-home-protected-content")).toHaveCount(0);
    await expect(page.getByTestId("operator-home-heading")).toHaveCount(0);
  });
});

test.describe("로그인 — 아이디·비밀번호(ADR-0018)", () => {
  test("올바른 아이디·비밀번호로 로그인하면 홈이 아이디와 등급을 보여준다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-basic-${Date.now()}`, superuser: false });

    await page.goto("/login");
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();

    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByTestId("operator-home-heading")).toContainText(operator.username);
    await expect(page.getByTestId("operator-home-grade")).toContainText("일반 등급");
  });

  test("상위 등급 계정은 홈에서 상위 등급이라고 말한다", async ({ page }) => {
    const operator = seedE2eOperator({
      username: `e2e-op-super-${Date.now()}`,
      superuser: true,
    });

    await page.goto("/login");
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();

    await expect(page.getByTestId("operator-home-grade")).toContainText("상위 등급");
  });

  test("틀린 아이디와 틀린 비밀번호가 구별되지 않는 하나의 메시지를 낸다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-wrongpw-${Date.now()}` });

    await page.goto("/login");
    await page.getByTestId("login-username").fill("no-such-operator-9134");
    await page.getByTestId("login-password").fill("whatever");
    await page.getByTestId("login-submit").click();
    const missingMessage = await page.getByTestId("login-error").textContent();

    await page.reload();
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill("wrong-password-9134");
    await page.getByTestId("login-submit").click();
    const wrongMessage = await page.getByTestId("login-error").textContent();

    expect(missingMessage).toBeTruthy();
    expect(missingMessage).toBe(wrongMessage);
  });
});

test.describe("세션 쿠키(ADR-0016/0019)", () => {
  test("세션 쿠키는 HttpOnly라 브라우저 스크립트에서 읽히지 않는다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-httponly-${Date.now()}` });

    await page.goto("/login");
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("operator-home-heading")).toBeVisible();

    const cookies = await page.context().cookies();
    const sessionCookie = cookies.find((cookie) => cookie.name === "laurio_operator_session");
    expect(sessionCookie).toBeDefined();
    expect(sessionCookie?.httpOnly).toBe(true);

    const visibleToJs = await page.evaluate(() => document.cookie);
    expect(visibleToJs).not.toContain("laurio_operator_session");
  });

  test("로그아웃하면 쿠키가 사라지고 보호된 화면에 다시 못 들어간다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-logout-${Date.now()}` });

    await page.goto("/login");
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("operator-home-heading")).toBeVisible();

    await page.getByTestId("logout-button").click();
    await expect(page).toHaveURL(/\/login/);

    const cookies = await page.context().cookies();
    expect(cookies.find((cookie) => cookie.name === "laurio_operator_session")).toBeUndefined();

    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
  });

  test("브라우저의 쿠키 헤더를 통째로 중계하지 않는다 — 무관한 쿠키가 섞여도 정상 응답한다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-cookierelay-${Date.now()}` });

    await page.goto("/login");
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("operator-home-heading")).toBeVisible();

    // 세션과 무관한 쿠키를 이 오리진에 하나 더 심는다 — BFF 가 브라우저의 Cookie
    // 헤더를 통째로 백엔드에 넘긴다면, Django 는 자기가 모르는 쿠키를 무시하므로
    // 이 시나리오만으로는 차이가 드러나지 않는다. 그래서 이 테스트는 "섞여도
    // 세션 조회가 여전히 정상 동작한다"는 것까지만 증명한다 — 실제로 세션 쿠키
    // 하나만 골라 싣는다는 것은 operator/app/api/auth/session/route.ts가 Cookie
    // 헤더를 직접 조립하고 request.headers의 원본 Cookie를 절대 참조하지 않는
    // 코드 구조로 보장된다.
    await page.context().addCookies([
      {
        name: "unrelated_tracking_cookie",
        value: "should-not-matter",
        url: page.url(),
      },
    ]);

    await page.reload();
    await expect(page.getByTestId("operator-home-heading")).toContainText(operator.username);
  });
});

test.describe("Origin 검증 — 로그인도 예외가 아니다(ADR-0016/0019)", () => {
  test("다른 Origin에서 온 로그인 요청은 403으로 거부된다", async ({ request }) => {
    const operator = seedE2eOperator({ username: `e2e-op-badorigin-${Date.now()}` });

    const res = await request.post("/api/auth/login", {
      headers: { origin: "https://evil.example.test" },
      data: { username: operator.username, password: E2E_OPERATOR_PASSWORD },
    });
    expect(res.status()).toBe(403);
  });

  test("Origin 헤더가 아예 없는 로그인 요청도 거부된다(fail-closed)", async ({ request }) => {
    // Playwright의 raw request는 브라우저와 달리 Origin을 자동으로 싣지 않는다 —
    // 그 자체로 "브라우저가 보낸 게 아닌 요청"의 좋은 대리 시험이다
    // (frontend/e2e/auth.spec.ts와 같은 관용구).
    const operator = seedE2eOperator({ username: `e2e-op-noorigin-${Date.now()}` });

    const res = await request.post("/api/auth/login", {
      data: { username: operator.username, password: E2E_OPERATOR_PASSWORD },
    });
    expect(res.status()).toBe(403);
  });
});
