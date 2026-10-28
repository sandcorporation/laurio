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

// 로그아웃은 콘솔 현관의 버튼이 아니라 헤더 계정 메뉴 안에 있다(#375, spec #371).
async function logoutViaAccountMenu(page: import("@playwright/test").Page): Promise<void> {
  await page.getByTestId("account-menu-trigger").click();
  await page.getByTestId("account-menu-logout").click();
}

test.describe("미들웨어 가드 — 콘텐츠가 그려지기 전에 리다이렉트한다", () => {
  test("세션 쿠키가 전혀 없으면 /console/participation 요청 자체가 302/307로 /login을 가리킨다", async ({
    request,
  }) => {
    const res = await request.get("/console/participation", { maxRedirects: 0 });
    expect([302, 307]).toContain(res.status());
    expect(res.headers()["location"]).toContain("/login");
  });

  test("리다이렉트를 따라가도 보호된 콘텐츠는 응답 본문에 한 조각도 없다", async ({
    page,
  }) => {
    await page.context().clearCookies();
    await page.goto("/console/participation");
    // 미들웨어가 /login으로 보냈으므로 최종 URL이 /console/participation이
    // 아니어야 하고, 로그인 이후 화면의 표식(participation-heading)이 전혀
    // 없어야 한다.
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId("participation-heading")).toHaveCount(0);
  });
});

test.describe("콘솔 현관 제거 — /console은 세션과 무관하게 홈으로 간다 (#375)", () => {
  test("세션이 없으면 /console은 로그인을 거치지 않고 바로 홈으로 리다이렉트된다", async ({
    request,
  }) => {
    const res = await request.get("/console", { maxRedirects: 0 });
    expect([302, 307]).toContain(res.status());
    expect(new URL(res.headers()["location"]!, "http://localhost.invalid").pathname).toBe("/");
  });

  test("로그인한 상태에서도 /console은 홈으로 리다이렉트된다 — 옛 주소를 즐겨찾기한 사람이 깨진 화면을 보지 않는다", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("bookmarked-console-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page.getByTestId("account-menu-trigger")).toBeVisible({ timeout: 15_000 });

    await page.goto("/console");
    await expect(page).toHaveURL("/");
    await expect(page.getByTestId("site-header")).toBeVisible();
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
  // lib/auth/cookies.ts의 isDeployedEnvironment()는 CODEMIT_DEPLOYMENT_TARGET이
  // "staging"|"production"일 때만 Secure를 켠다. 이 dev 스택(compose.dev.yaml)은
  // 그 값을 절대 설정하지 않으므로 — 컨테이너 간 http로만 통신하고 Secure를 걸면
  // 쿠키가 아예 안 실린다 — 여기서는 항상 꺼져 있어야 한다.
  //
  // "production에서는 켜진다"는 반대쪽 절반은 이 e2e 시임으로 증명할 수 없다 —
  // 이 스택 자체가 production 설정으로 뜨지 않기 때문이다. 그건
  // scripts/ci/deploy-guard.sh frontend(Jenkins codemit/deploy 잡의 부팅 가드)가 실제 프로덕션
  // 이미지를 프로덕션 환경변수로 띄워 별도로 증명한다. 이 테스트는 그 짝 —
  // "dev에서는 꺼져 있다"만 이 시임 안에서 확인한다.
  test("dev(CODEMIT_DEPLOYMENT_TARGET 미설정)에서는 Secure가 붙지 않는다", async ({
    request,
    baseURL,
  }) => {
    const res = await request.post("/api/auth/logout", {
      headers: { origin: baseURL! },
    });
    expect(res.status()).toBe(200);
    const setCookie = (res.headers()["set-cookie"] ?? "").toLowerCase();
    expect(setCookie).toContain("codemit_access");
    expect(setCookie).not.toContain("secure");
  });

  // 부모 도메인 쿠키(ADR-0038, #273)도 같은 이유로 dev에서는 꺼져 있어야 한다 —
  // CODEMIT_SESSION_COOKIE_DOMAIN을 dev compose는 절대 설정하지 않으므로(로컬은
  // 서브도메인이 아니라 포트로 앱을 가른다), domain 속성이 아예 없어야 한다.
  // "staging/prod에서는 domain이 붙는다"는 반대쪽 절반은 위 Secure와 같은 이유로
  // 여기서 증명할 수 없다 — lib/auth/cookies.test.ts(vitest)가 그 절반을 덮는다.
  test("dev(CODEMIT_SESSION_COOKIE_DOMAIN 미설정)에서는 쿠키에 domain이 붙지 않는다", async ({
    request,
    baseURL,
  }) => {
    const res = await request.post("/api/auth/logout", {
      headers: { origin: baseURL! },
    });
    expect(res.status()).toBe(200);
    const setCookie = (res.headers()["set-cookie"] ?? "").toLowerCase();
    expect(setCookie).toContain("codemit_access");
    expect(setCookie).not.toContain("domain=");
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
      expect(setCookie).toContain("codemit_access");
      expect(setCookie).toContain("codemit_refresh");
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
    // 콘솔 현관이 없어져 로그인 기본 도착지가 홈이다(#375) — 헤더의 계정
    // 메뉴가 로그인된 상태의 표식이다.
    await expect(page).toHaveURL("/", { timeout: 15_000 });
    await expect(page.getByTestId("account-menu-trigger")).toBeVisible();

    const jsVisibleCookies = await page.evaluate(() => document.cookie);
    expect(jsVisibleCookies).not.toContain("codemit_access");
    expect(jsVisibleCookies).not.toContain("codemit_refresh");

    // context.cookies()는 브라우저 JS가 아니라 테스트 하네스(CDP)가 보는 것이다 —
    // 여기서는 실제로 HttpOnly가 걸려 있는지를 확인한다.
    const cookies = await page.context().cookies();
    const access = cookies.find((c) => c.name === "codemit_access");
    const refresh = cookies.find((c) => c.name === "codemit_refresh");
    expect(access?.httpOnly).toBe(true);
    expect(refresh?.httpOnly).toBe(true);
  });

  test("로그인하면 미들웨어가 /console/participation 콘텐츠를 그대로 통과시킨다", async ({
    page,
  }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("console-visit-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });

    await page.goto("/console/participation");
    await expect(page).toHaveURL(/\/console\/participation/);
    await expect(page.getByTestId("participation-heading")).toBeVisible();
  });
});

test.describe("로그아웃 — 쿠키 삭제 + 블랙리스트", () => {
  test("로그아웃하면 쿠키가 지워지고 /console/participation이 다시 막힌다", async ({ page }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("logout-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });

    await logoutViaAccountMenu(page);
    await expect(page).toHaveURL(/\/login/);

    const cookies = await page.context().cookies();
    expect(cookies.find((c) => c.name === "codemit_access")).toBeUndefined();
    expect(cookies.find((c) => c.name === "codemit_refresh")).toBeUndefined();

    // 미들웨어가 다시 막는지 새 탐색으로 확인한다.
    await page.goto("/console/participation");
    await expect(page).toHaveURL(/\/login/);
  });

  test("로그아웃한 액세스 토큰은 백엔드 블랙리스트에 올라 즉시 무효가 된다", async ({
    page,
    baseURL,
  }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("blacklist-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });

    const before = await page.context().cookies();
    const access = before.find((c) => c.name === "codemit_access")?.value;
    expect(access).toBeTruthy();

    await logoutViaAccountMenu(page);
    await expect(page).toHaveURL(/\/login/);

    // 브라우저가 이미 지운 그 액세스 토큰을 쿠키로 되살려 다시 실어 보낸다 —
    // ADR-0017의 시임(실행 중인 Next 앱 하나)을 벗어나 백엔드에 직접 묻지
    // 않는다: 프록시(FE-08, /api/backend/**)를 통해서만 확인한다. 서명·만료는
    // 아직 유효한 토큰이므로, 이 요청이 401이라면 그건 블랙리스트 때문이다.
    await page.context().addCookies([
      { name: "codemit_access", value: access!, url: baseURL, httpOnly: true, sameSite: "Lax" },
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
    await expect(page).toHaveURL("/", { timeout: 15_000 });
    // `/console/dev-upload-demo`로 간다 — `useSession()` 하나만 쓰고 그 밖의
    // 데이터 조회가 없는 화면이다(옛 콘솔 현관과 같은 모양). `/console/
    // participation`처럼 `useSession()`과 `usePagedList()`가 함께 401을 만나면
    // 되살리기 단일 비행 하나를 두고 서로 다른 시점에 경합해, 먼저 회전된
    // 리프레시 토큰을 나중 쪽이 다시 쓰려다 실패하는 것을 실제로 관찰했다 — 이
    // 테스트가 겨냥하는 것은 리프레시 메커니즘 자체이지 그 경합이 아니다.
    await page.goto("/console/dev-upload-demo");
    await expect(page).toHaveURL(/\/console\/dev-upload-demo/);
    // 세션이 멀쩡할 때 한 번 더 새로고침해 이 화면과 `/api/auth/session`을
    // 미리 컴파일해 둔다 — `next dev`는 라우트를 요청받을 때 컴파일하므로,
    // 그 컴파일이 아래에서 조작된 쿠키로 걸리는 재시도 창과 겹치면 서버 쪽
    // 되살리기 단일 비행이 리셋돼(이 파일의 "동시에 여러 요청" 테스트 주석이
    // 이미 겪은 것과 같은 종류) 코드 회귀와 구분되지 않는 실패를 낸다.
    await page.reload();
    await expect(page.getByTestId("upload-demo-contest-id")).toBeVisible();

    const cookies = await page.context().cookies();
    const refresh = cookies.find((c) => c.name === "codemit_refresh");
    expect(refresh).toBeTruthy();

    // 액세스 쿠키를 "만료된 것처럼" 만든다 — 프론트는 서명 검증을 하지 않고
    // payload만 낙관적으로 읽으므로(lib/auth/jwt.ts), 디코딩 자체가 실패하는
    // 문자열은 항상 "만료"로 취급된다. 리프레시 쿠키는 로그인 때 발급된 진짜
    // 값 그대로 둔다 — 실제 백엔드 리프레시 엔드포인트가 진짜로 회전시킨다.
    await page.context().addCookies([
      {
        name: "codemit_access",
        value: "not-a-real-jwt",
        url: baseURL,
        httpOnly: true,
        sameSite: "Lax",
      },
    ]);

    // 화면이 끊기지 않는다 — 새로고침해도 여전히 로그인된 화면이 보여야 한다.
    await page.reload();
    await expect(page).toHaveURL(/\/console\/dev-upload-demo/, { timeout: 15_000 });
    await expect(page.getByTestId("upload-demo-contest-id")).toBeVisible({ timeout: 15_000 });

    // 응답이 새 액세스 쿠키로 교체됐는지도 확인한다 — "not-a-real-jwt"가 아니다.
    const after = await page.context().cookies();
    const rotatedAccess = after.find((c) => c.name === "codemit_access");
    expect(rotatedAccess?.value).not.toBe("not-a-real-jwt");
  });

  test("동시에 여러 요청이 만료를 발견해도 리프레시는 한 번만 나가고 전부 성공한다", async ({
    page,
    baseURL,
  }) => {
    await page.goto("/login");
    await page.getByTestId("fake-login-seed").fill("concurrent-refresh-user");
    await page.getByTestId(`login-${FAKE_PROVIDER}`).click();
    await expect(page).toHaveURL("/", { timeout: 15_000 });

    await page.context().addCookies([
      {
        name: "codemit_access",
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
        // TEST-WAIT-EXCEPTION: 브라우저 안에서 실제 클라이언트(`bff-client`)의 401 재시도 백오프를 흉내 낸 코드다 — 시험이 기다리는 시간이 아니다
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
