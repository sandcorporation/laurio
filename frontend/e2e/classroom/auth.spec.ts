import { expect, test } from "@playwright/test";

// 강의실 01(#276) — 미들웨어 가드와 BFF 프록시 허용목록(ADR-0016/0038).
//
// 시임 규약(ADR-0017/0021, playwright.config.ts 상단 주석)을 그대로 따른다:
// 브라우저가 필요한 것은 `page`로, 아닌 것(미들웨어 리다이렉트, 허용목록)은 raw
// `request`로 친다 — 이 프로젝트("classroom")는 강의실 앱의 baseURL만 친다.
//
// 강의실은 자기 로그인을 갖지 않는다(ADR-0038) — 그래서 이 스펙은 "로그인해서
// 빈 내 클래스를 본다"는 걷지 않는다: 부모 도메인 쿠키 공유는 dev(localhost, 포트로
// 앱을 가른다)에서 재현할 수 없고, 실제 공유는 staging에서 검증한다(#277). 여기서
// 보는 것은 이 앱 혼자 완결되는 계약뿐이다 — 쿠키가 없으면 막힌다는 것.

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
    await expect(page.getByTestId("classroom-home-heading")).toHaveCount(0);
    await expect(page.getByTestId("classroom-empty-state")).toHaveCount(0);
  });

  test("아직 화면이 없는 경로도 가드된다 — 화이트리스트가 아니라 예외 목록이다", async ({
    request,
  }) => {
    for (const path of ["/classes", "/anything-not-yet-built"]) {
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

    // BFF 프록시 자신도 가드 대상이 아니다 — 세션 판정은 프록시가 아니라
    // 백엔드가 401로 한다(지금은 허용목록이 비어 있어 이 요청 자체가 404다,
    // 아래 describe 참고).
    const proxied = await request.get("/api/backend/anything");
    expect(proxied.status()).not.toBe(302);
    expect(proxied.status()).not.toBe(307);
  });
});

test.describe("BFF 프록시 허용목록 — 기본은 거부다 (ADR-0016, #276)", () => {
  test("허용목록이 비어 있으므로 어떤 백엔드 경로도 통과하지 못한다", async ({ request }) => {
    for (const path of ["/api/backend/accounts/me", "/api/backend/anything"]) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(404);
    }
  });
});
