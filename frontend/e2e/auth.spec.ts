import { expect, test } from "@playwright/test";

// BFF 인증 — 쿠키 세션 + 소셜 로그인 + 미들웨어 가드 + CSRF (FE-07, #32, ADR-0016).
//
// 시임 규약(ADR-0017, e2e/seam.spec.ts)을 그대로 따른다: 브라우저가 필요한 것은
// `page`로, 아닌 것(Origin 검증, 미들웨어 리다이렉트, 허용목록)은 raw `request`로
// 친다.

const FAKE_PROVIDER = "kakao";

function fakeAccessToken(seed: string): string {
  // 백엔드 FakeSocialAdapter(dev/test 기본값, SOCIAL_AUTH_MODE=fake)가 그대로
  // 신뢰하는 형식이다 — accounts/social.py 참고.
  return `${seed}:${seed}@example.test`;
}

async function loginViaApi(
  request: import("@playwright/test").APIRequestContext,
  baseURL: string,
  seed: string,
) {
  return request.post(`/api/auth/social/${FAKE_PROVIDER}/login`, {
    headers: { origin: baseURL },
    data: { access_token: fakeAccessToken(seed) },
  });
}

test.describe("미들웨어 가드 — 콘텐츠가 그려지기 전에 리다이렉트한다", () => {
  test("세션 쿠키가 전혀 없으면 /console 요청 자체가 302/307로 /login을 가리킨다", async ({
    request,
  }) => {
    const res = await request.get("/console", { maxRedirects: 0 });
    expect([302, 307]).toContain(res.status());
    expect(res.headers()["location"]).toContain("/login");
  });

  test("리다이렉트를 따라가도 보호된 콘텐츠는 응답 본문에 한 조각도 없다", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/console");
    // 미들웨어가 /login으로 보냈으므로 최종 URL이 /console이 아니어야 하고,
    // 로그인 이후 화면의 표식(app-home-protected-content)이 전혀 없어야 한다.
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("app-home-protected-content")).toHaveCount(0);
    await expect(page.getByTestId("app-home-heading")).toHaveCount(0);
  });
});

test.describe("Origin 검증 — CSRF 방어의 성립 조건 (ADR-0016)", () => {
  test("다른 Origin에서 온 변경 요청은 403으로 거부된다", async ({ request }) => {
    const res = await request.post("/api/auth/logout", {
      headers: { origin: "https://evil.example.test" },
    });
    expect(res.status()).toBe(403);
  });

  test("Origin 헤더가 아예 없는 변경 요청도 거부된다(fail-closed)", async ({ request }) => {
    // Playwright의 raw request는 브라우저와 달리 Origin을 자동으로 싣지 않는다 —
    // 그 자체로 "브라우저가 보낸 게 아닌 요청"의 좋은 대리 시험이다.
    const res = await request.post("/api/auth/logout");
    expect(res.status()).toBe(403);
  });

  test("같은 Origin에서 온 요청은 Origin 검사를 통과한다", async ({ request, baseURL }) => {
    // 세션이 없는 상태의 로그아웃은 멱등하게 200이다 — Origin 검사만 따로
    // 검증하려는 것이라 로그인 상태는 필요 없다.
    const res = await request.post("/api/auth/logout", {
      headers: { origin: baseURL! },
    });
    expect(res.status()).toBe(200);
  });
});

test.describe("쿠키 Secure — 배포 여부에 따라 갈린다 (ADR-0016, FE-13 #38)", () => {
  // lib/auth/cookies.ts의 isDeployedEnvironment()는 LAURIO_DEPLOYMENT_TARGET이
  // "staging"|"production"일 때만 Secure를 켠다. 이 dev 스택(compose.dev.yaml)은
  // 그 값을 절대 설정하지 않으므로 — 컨테이너 간 http로만 통신하고 Secure를 걸면
  // 쿠키가 아예 안 실린다 — 여기서는 항상 꺼져 있어야 한다.
  //
  // "production에서는 켜진다"는 반대쪽 절반은 이 e2e 시임으로 증명할 수 없다 —
  // 이 스택 자체가 production 설정으로 뜨지 않기 때문이다. 그건
  // .github/workflows/ci.yaml의 frontend-deploy-guard 잡이 실제 프로덕션
  // 이미지를 프로덕션 환경변수로 띄워 별도로 증명한다. 이 테스트는 그 짝 —
  // "dev에서는 꺼져 있다"만 이 시임 안에서 확인한다.
  test("dev(LAURIO_DEPLOYMENT_TARGET 미설정)에서는 Secure가 붙지 않는다", async ({
    request,
    baseURL,
  }) => {
    const res = await request.post("/api/auth/logout", {
      headers: { origin: baseURL! },
    });
    expect(res.status()).toBe(200);
    const setCookie = (res.headers()["set-cookie"] ?? "").toLowerCase();
    expect(setCookie).toContain("laurio_access");
    expect(setCookie).not.toContain("secure");
  });
});

test.describe("소셜 로그인 → 세션 쿠키 → 보호된 화면", () => {
  test("카카오·GitHub·구글 각각 fake 어댑터로 로그인이 끝까지 된다", async ({
    request,
    baseURL,
  }) => {
    for (const provider of ["kakao", "github", "google"]) {
      const res = await request.post(`/api/auth/social/${provider}/login`, {
        headers: { origin: baseURL! },
        data: { access_token: fakeAccessToken(`${provider}-seed`) },
      });
      expect(res.status(), `${provider} 로그인`).toBe(200);
      const setCookie = res.headers()["set-cookie"] ?? "";
      expect(setCookie).toContain("laurio_access");
      expect(setCookie).toContain("laurio_refresh");
      expect(setCookie.toLowerCase()).toContain("httponly");
    }
  });

  test("로그인 응답 본문에 토큰이 절대 나오지 않는다", async ({ request, baseURL }) => {
    const res = await loginViaApi(request, baseURL!, "no-leak-user");
    expect(res.status()).toBe(200);
    const body = await res.text();
    expect(body).not.toMatch(/eyJ/); // JWT는 항상 "eyJ"로 시작하는 base64url 헤더를 가진다.
    expect(JSON.parse(body)).toEqual({ status: "ok" });
  });

  test("로그인 후 브라우저 JS는 document.cookie로 토큰을 절대 볼 수 없다", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("visible-check-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL(/\/console/);
    await expect(page.getByTestId("app-home-heading")).toBeVisible();

    const jsVisibleCookies = await page.evaluate(() => document.cookie);
    expect(jsVisibleCookies).not.toContain("laurio_access");
    expect(jsVisibleCookies).not.toContain("laurio_refresh");

    // context.cookies()는 브라우저 JS가 아니라 테스트 하네스(CDP)가 보는 것이다 —
    // 여기서는 실제로 HttpOnly가 걸려 있는지를 확인한다.
    const cookies = await page.context().cookies();
    const access = cookies.find((c) => c.name === "laurio_access");
    const refresh = cookies.find((c) => c.name === "laurio_refresh");
    expect(access?.httpOnly).toBe(true);
    expect(refresh?.httpOnly).toBe(true);
  });

  test("로그인하면 미들웨어가 /console 콘텐츠를 그대로 통과시킨다", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("console-visit-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL(/\/console/);
    await expect(page.getByTestId("app-home-protected-content")).toBeVisible();
    await expect(page.getByTestId("app-home-heading")).toContainText("console-visit-user");
  });
});

test.describe("로그아웃 — 쿠키 삭제 + 블랙리스트", () => {
  test("로그아웃하면 쿠키가 지워지고 /console이 다시 막힌다", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("logout-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL(/\/console/);

    await page.getByTestId("logout-button").click();
    await expect(page).toHaveURL(/\/login/);

    const cookies = await page.context().cookies();
    expect(cookies.find((c) => c.name === "laurio_access")).toBeUndefined();
    expect(cookies.find((c) => c.name === "laurio_refresh")).toBeUndefined();

    // 미들웨어가 다시 막는지 새 탐색으로 확인한다.
    await page.goto("/console");
    await expect(page).toHaveURL(/\/login/);
  });

  test("로그아웃한 액세스 토큰은 백엔드 블랙리스트에 올라 즉시 무효가 된다", async ({
    page,
    baseURL,
  }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("blacklist-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL(/\/console/);

    const before = await page.context().cookies();
    const access = before.find((c) => c.name === "laurio_access")?.value;
    expect(access).toBeTruthy();

    await page.getByTestId("logout-button").click();
    await expect(page).toHaveURL(/\/login/);

    // 브라우저가 이미 지운 그 액세스 토큰을 쿠키로 되살려 다시 실어 보낸다 —
    // ADR-0017의 시임(실행 중인 Next 앱 하나)을 벗어나 백엔드에 직접 묻지
    // 않는다: 프록시(FE-08, /api/backend/**)를 통해서만 확인한다. 서명·만료는
    // 아직 유효한 토큰이므로, 이 요청이 401이라면 그건 블랙리스트 때문이다.
    await page.context().addCookies([
      { name: "laurio_access", value: access!, url: baseURL, httpOnly: true, sameSite: "Lax" },
    ]);
    const status = await page.evaluate(async () => {
      const res = await fetch("/api/backend/accounts/me", { cache: "no-store" });
      return res.status;
    });
    expect(status).toBe(401);
  });
});

test.describe("액세스 만료 시 리프레시가 조용히 처리된다", () => {
  test("액세스 쿠키가 깨져 있어도 유효한 리프레시 쿠키가 있으면 세션이 끊기지 않는다", async ({
    page,
    baseURL,
  }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("refresh-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL(/\/console/);

    const cookies = await page.context().cookies();
    const refresh = cookies.find((c) => c.name === "laurio_refresh");
    expect(refresh).toBeTruthy();

    // 액세스 쿠키를 "만료된 것처럼" 만든다 — 프론트는 서명 검증을 하지 않고
    // payload만 낙관적으로 읽으므로(lib/auth/jwt.ts), 디코딩 자체가 실패하는
    // 문자열은 항상 "만료"로 취급된다. 리프레시 쿠키는 로그인 때 발급된 진짜
    // 값 그대로 둔다 — 실제 백엔드 리프레시 엔드포인트가 진짜로 회전시킨다.
    await page.context().addCookies([
      {
        name: "laurio_access",
        value: "not-a-real-jwt",
        url: baseURL,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);

    // 화면이 끊기지 않는다 — 새로고침해도 여전히 로그인된 화면이 보여야 한다.
    await page.reload();
    await expect(page).toHaveURL(/\/console/);
    await expect(page.getByTestId("app-home-protected-content")).toBeVisible();

    // 응답이 새 액세스 쿠키로 교체됐는지도 확인한다 — "not-a-real-jwt"가 아니다.
    const after = await page.context().cookies();
    const rotatedAccess = after.find((c) => c.name === "laurio_access");
    expect(rotatedAccess?.value).not.toBe("not-a-real-jwt");
  });

  test("동시에 여러 요청이 만료를 발견해도 리프레시는 한 번만 나가고 전부 성공한다", async ({
    page,
    baseURL,
  }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("concurrent-refresh-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL(/\/console/);

    await page.context().addCookies([
      {
        name: "laurio_access",
        value: "not-a-real-jwt",
        url: baseURL,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);

    // 리프레시 토큰은 1회용이라(accounts/tokens.py rotate_refresh_token), 서버
    // 프로세스 하나에만 기대는 단일 비행으로는 부족하다는 것을 직접 겪었다 —
    // Next dev 서버가 컴파일 경계에서 라우트 모듈을 새로 평가해 서버 쪽
    // inflightRefresh Map(lib/auth/refresh.ts)이 비워지는 것을 재현했고, 그때는
    // 5개 중 하나만 성공하고 나머지는 이미 회전된 리프레시 토큰으로 401을
    // 받았다. 그래서 진짜 방어선은 브라우저(lib/auth/client-fetch.ts의
    // sessionFetch)에 있다 — 여기서는 그 정확한 알고리즘을 그대로 재현해
    // (같은 페이지 안에서는 항상 하나의 JS 실행 컨텍스트라는 보장이 실제로
    // 성립하는지) 검증한다. 401을 만나면 "세션 되살리기" 시도 하나를 공유하고,
    // 전부 그 결과를 기다렸다가 각자 재시도한다.
    const statuses = await page.evaluate(async () => {
      let inflightRevive: Promise<void> | null = null;
      function reviveSession(): Promise<void> {
        if (inflightRevive) return inflightRevive;
        inflightRevive = fetch("/api/auth/session", { cache: "no-store" })
          .then(() => undefined)
          .catch(() => undefined)
          .finally(() => {
            inflightRevive = null;
          });
        return inflightRevive;
      }
      function sleep(ms: number): Promise<void> {
        return new Promise((resolve) => setTimeout(resolve, ms));
      }
      async function sessionFetch(path: string): Promise<Response> {
        let response = await fetch(path, { cache: "no-store" });
        for (let attempt = 1; response.status === 401 && attempt < 3; attempt += 1) {
          await reviveSession();
          response = await fetch(path, { cache: "no-store" });
          if (response.status === 401) await sleep(75 * attempt);
        }
        return response;
      }

      const results = await Promise.all(
        Array.from({ length: 5 }, () => sessionFetch("/api/auth/session")),
      );
      return results.map((r) => r.status);
    });

    expect(statuses).toEqual([200, 200, 200, 200, 200]);
  });
});
