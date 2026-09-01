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

  test("아직 화면이 없는 경로도 가드된다 — 화이트리스트가 아니라 예외 목록이다", async ({
    request,
  }) => {
    // #66·#68이 아직 /appeals·/payouts 페이지를 안 만들었지만, 홈(#65)이 이미 그
    // 경로로 링크를 건다 — matcher가 "아는 페이지만" 담는 화이트리스트면 이
    // 라우트들은 가드 없이 태어난다. 페이지 존재 여부와 무관하게 미들웨어가
    // 먼저 가로채는지를 확인한다(실제로 그 페이지가 있는지는 다른 티켓의 몫).
    for (const path of ["/appeals", "/payouts", "/operators", "/anything-not-yet-built"]) {
      const res = await request.get(path, { maxRedirects: 0 });
      expect([302, 307], path).toContain(res.status());
      expect(res.headers()["location"], path).toContain("/login");
    }
  });

  test("/login·/api/**·/healthz는 세션 없이도 가드에 걸리지 않는다", async ({ request }) => {
    const login = await request.get("/login");
    expect(login.status()).toBe(200);

    const health = await request.get("/healthz");
    expect([200, 503]).toContain(health.status());

    // /api/auth/session은 세션이 없으면 401을 내야 정상이다 — 미들웨어가
    // /login으로 리다이렉트하면(302/307) 안 된다. 이 라우트 자신이 세션 판정을
    // 한다(app/api/auth/session/route.ts).
    const session = await request.get("/api/auth/session");
    expect(session.status()).toBe(401);
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

  test("로그아웃 요청이 실패하면 실패했다고 말할 뿐 로그인 화면으로 보내지 않는다", async ({
    page,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-logoutfail-${Date.now()}` });

    await page.goto("/login");
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();
    await expect(page.getByTestId("operator-home-heading")).toBeVisible();

    // 이 앱 자신의 로그아웃 BFF 호출만 실패시킨다 — 실제 세션·쿠키는 그대로 두고
    // "BFF가 실패를 답했을 때 화면이 어떻게 반응하는가"라는 순수 프론트 렌더링
    // 분기만 결정적으로 재현한다(home.spec.ts의 조회 실패 테스트와 같은 원칙 —
    // 백엔드 로직이 아니라 프론트 상태 분기 하나를 좁혀서 겨냥한다).
    await page.route("**/api/auth/logout", (route) =>
      route.fulfill({ status: 500, body: JSON.stringify({ detail: "로그아웃 실패 시뮬레이션" }) }),
    );

    await page.getByTestId("logout-button").click();

    await expect(page.getByTestId("logout-error")).toBeVisible();
    // 로그인 화면으로 보내지지 않는다 — 세션이 죽지 않았는데 "로그아웃됨"으로
    // 보이면 안 된다(코드리뷰 지적).
    await expect(page).not.toHaveURL(/\/login/);
    await expect(page.getByTestId("operator-home-heading")).toBeVisible();

    // 실제 세션 쿠키도 그대로 살아 있다 — 화면만이 아니라 실제로도 로그인
    // 상태다.
    const cookies = await page.context().cookies();
    expect(cookies.find((cookie) => cookie.name === "laurio_operator_session")).toBeDefined();
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

test.describe("open redirect 방어 — ?next= 는 같은 오리진의 절대경로만 허용한다", () => {
  test("완전한 외부 URL을 next로 주면 무시하고 홈으로 보낸다", async ({ page, baseURL }) => {
    const operator = seedE2eOperator({ username: `e2e-op-openredirect-abs-${Date.now()}` });

    await page.goto("/login?next=" + encodeURIComponent("https://evil.example.test/phish"));
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();

    await expect(page.getByTestId("operator-home-heading")).toBeVisible();
    expect(new URL(page.url()).origin).toBe(baseURL);
    expect(page.url()).not.toContain("evil.example.test");
  });

  test("프로토콜 상대 URL(슬래시 두 개로 시작)도 거부하고 홈으로 보낸다", async ({
    page,
    baseURL,
  }) => {
    const operator = seedE2eOperator({ username: `e2e-op-openredirect-proto-${Date.now()}` });
    const protocolRelative = "//" + "evil.example.test";

    await page.goto("/login?next=" + encodeURIComponent(protocolRelative));
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();

    await expect(page.getByTestId("operator-home-heading")).toBeVisible();
    expect(new URL(page.url()).origin).toBe(baseURL);
    expect(page.url()).not.toContain("evil.example.test");
  });

  test("같은 오리진의 상대경로 next는 정상적으로 그리로 보낸다", async ({ page }) => {
    const operator = seedE2eOperator({ username: `e2e-op-openredirect-legit-${Date.now()}` });

    await page.goto("/login?next=" + encodeURIComponent("/appeals"));
    await page.getByTestId("login-username").fill(operator.username);
    await page.getByTestId("login-password").fill(E2E_OPERATOR_PASSWORD);
    await page.getByTestId("login-submit").click();

    await expect(page).toHaveURL(/\/appeals/);
  });
});
