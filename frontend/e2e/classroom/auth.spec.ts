import { expect, test } from "@playwright/test";

import { establishClassroomSession } from "./lib/cross-app-session";

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

test.describe("죽은 세션 — 공유 BFF 클라이언트가 로그인으로 보낸다 (#462)", () => {
  // 미들웨어는 쿠키의 "존재"만 본다(hasSessionCookie) — 쿠키가 있지만
  // 값이 죽어 있으면(리프레시까지 실패) 렌더링 전에는 막히지 않고, 화면이
  // 뜬 뒤 백엔드를 부르는 순간 401 을 받는다. 예전에는 그 401 을 화면마다
  // 손으로 쓴 클라이언트가 "찾을 수 없습니다"로만 보여줬다 — 아무도 로그인
  // 으로 보내지 않았다(#461 문제 진술). 지금은 공유 BFF 클라이언트
  // (`@codemit/bff-client`)가 그 자리를 대신해 곧장 로그인으로 보낸다.
  test("쿠키는 있지만 죽은 세션으로 열면 강의실 자신의 /login 을 거쳐 공개 앱 로그인으로 간다", async ({
    page,
  }) => {
    // 먼저 정상 세션을 세워 강의실이 실제로 화면을 그린다는 것을 확인한다
    // — 그래야 아래 리다이렉트가 "애초에 못 열어서"가 아니라 "열었다가
    // 401 을 받아서"라고 말할 수 있다.
    await establishClassroomSession(
      page,
      `e2e-classroom-dead-session-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    );
    await page.goto("/");
    await expect(page).toHaveURL("/");

    // 살아 있던 화면을 먼저 떠난다(2026-10-02). 그 화면은 계속 백엔드를 부른다(알림
    // 벨의 주기 조회 등) — 아래에서 쿠키를 죽이면 **그 화면의** 다음 요청이 401 을
    // 받아 스스로 로그인으로 가고, 그 이동이 이 시험의 다음 `goto` 와 부딪혀
    // `ERR_ABORTED` 로 떨어졌다(40번에 3번, CI 에서는 재시도가 덮었다).
    const classroomUrl = page.url();
    await page.goto("about:blank");

    // 세션을 죽인다 — 리프레시까지 실패하는 상황을 흉내 내려고 값 자체를
    // 못 쓰게 만든다(서명이 깨진 문자열). 미들웨어는 이 쿠키의 존재만
    // 보므로 이 시점에도 렌더링 자체는 막히지 않는다.
    await page.context().addCookies([
      { name: "codemit_access", value: "dead.dead.dead", url: classroomUrl, httpOnly: true, sameSite: "Lax" },
      { name: "codemit_refresh", value: "dead.dead.dead", url: classroomUrl, httpOnly: true, sameSite: "Lax" },
    ]);

    // 「내 클래스」 조회(`useMyClasses`)가 401 을 받고, 공유 BFF 클라이언트가
    // 조회든 변경이든 같은 한 경로 — 이 앱 자신의 `/login` — 로 보낸다.
    // 거기서 공개 앱 로그인으로 다시 보내며 돌아올 자리(`next_origin`·`next`)
    // 를 함께 싣는다(#297 후속·#334) — 로그인을 마치면 이 화면으로 돌아온다.
    await page.goto("/");
    // 이동 사건(`waitForURL`)이 아니라 도착한 주소를 본다(2026-10-02). 이 화면은 요청
    // 둘(내 클래스·알림 벨)이 함께 401 을 받아 같은 로그인 주소로 두 번 이동하는데,
    // 두 번째가 첫 번째를 취소해 `waitForURL` 이 `ERR_ABORTED` 로 떨어졌다(80번에 1번).
    // 이 시험이 고정하는 것은 「결국 로그인으로 간다」다.
    await expect(page).toHaveURL(/\/login\?next=/);
    const loginLink = page.getByTestId("classroom-login-link");
    await expect(loginLink).toBeVisible();
    const href = await loginLink.getAttribute("href");
    expect(href).toContain("/login?");
    expect(href).toContain("next_origin=");
    expect(href).toContain("next=");
  });
});
