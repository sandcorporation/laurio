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
  // **루트("/")는 더 이상 여기서 검증하지 않는다**(#395) — 세션 쿠키가 없어도
  // /login으로 튕기지 않고 랜딩을 SSR 한다. 그 계약은
  // `frontend/e2e/classroom/landing.spec.ts`가 전담한다(JS 끔 SSR·쿠키 분기·
  // robots·sitemap·아이콘). 예전에는 이 자리에 "/ 는 쿠키가 없으면 /login으로
  // 튕긴다"는 두 스펙이 있었다 — 루트가 가드 예외가 되며 거짓이 됐다.

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
    // 백엔드가 401로 한다(허용목록 밖인 이 경로는 그 전에 404다, 아래 describe
    // 참고).
    const proxied = await request.get("/api/backend/anything");
    expect(proxied.status()).not.toBe(302);
    expect(proxied.status()).not.toBe(307);
  });
});

test.describe("BFF 프록시 허용목록 — 기본은 거부다 (ADR-0016, #276)", () => {
  // #276 이 이 스펙을 쓸 때는 허용목록이 비어 있어 **모든** 경로가 404였다.
  // 그 뒤 #278·#286 이 `/api/classroom`·`/api/accounts`·`/api/storage` 를 열었다
  // (classroom/lib/proxy/allowlist.ts 가 이유를 적고 있다). 그래도 이 스펙이
  // 지키는 것은 그대로다: **목록에 없으면 백엔드에 닿지도 못한다.**
  test("허용목록 밖의 경로는 백엔드에 닿지 못한다", async ({ request }) => {
    for (const path of ["/api/backend/anything", "/api/backend/contests", "/api/backend/payments"]) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(404);
    }
  });

  test("허용목록 안의 경로는 백엔드까지 가고, 거절은 백엔드가 한다", async ({ request }) => {
    // 로그인하지 않았으므로 백엔드가 401 을 준다 — 404 라면 프록시가 막은
    // 것이고, 그러면 참여자가 소스를 낼 때 자기 User pk 를 얻지 못한다(#286).
    const res = await request.get("/api/backend/accounts/me");
    expect(res.status()).toBe(401);
  });
});
