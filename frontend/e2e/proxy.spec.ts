import { expect, test } from "@playwright/test";

// BFF 프록시 — catch-all + 경로 허용목록 (FE-08, #33, ADR-0016).
//
// 전부 raw `request`로 친다 — 이 티켓의 대상(허용목록·Origin 검증)은 브라우저가
// 필요 없다(ADR-0017).

test.describe("허용목록 — 기본은 거부", () => {
  test("허용목록에 없는 경로는 통과하지 못한다", async ({ request }) => {
    const res = await request.get("/api/backend/no-such-app/whatever");
    expect(res.status()).toBe(404);
  });

  test("/api/internal/* 은 프록시로 도달할 수 없다", async ({ request, baseURL }) => {
    // 실제로 존재하는 내부 엔드포인트(스케줄러 틱)를 겨냥한다 — 존재하지 않는
    // 경로를 막는 것과 실제로 위험한 경로를 막는 것은 다른 증명이다.
    const getRes = await request.get("/api/backend/internal/tick");
    expect(getRes.status()).toBe(404);

    const postRes = await request.post("/api/backend/internal/tick", {
      headers: { origin: baseURL! },
    });
    expect(postRes.status()).toBe(404);

    // 나머지 내부 라우터들도 함께 확인한다(마감 전이·배분·환불·지급·채점·알림).
    for (const path of [
      "/api/backend/internal/scoring/run-pending",
      "/api/backend/internal/payments/run-refunds",
      "/api/backend/internal/distributions/run-due",
      "/api/backend/internal/handovers/release-due",
      "/api/backend/internal/notifications/dispatch-due",
      "/api/backend/internal/appeals",
    ]) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(404);
    }
  });

  test("백엔드에 새 엔드포인트가 생겨도 허용목록에 없으면 노출되지 않는다", async ({
    request,
  }) => {
    // 실제로 존재할 법한 그럴듯한 이름이라도(가짜 새 라우터를 흉내낸 경로),
    // lib/proxy/allowlist.ts에 없으면 통과하지 못한다는 것을 보여준다.
    const res = await request.get("/api/backend/analytics/dashboard");
    expect(res.status()).toBe(404);
  });
});

test.describe("허용된 경로 — 인증이 필요한 호출이 프록시를 통해 정상 응답한다", () => {
  test("공개 GET(카테고리 목록)이 프록시를 거쳐 실제 백엔드 응답을 그대로 전달한다", async ({
    request,
  }) => {
    const res = await request.get("/api/backend/contests/categories");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(Array.isArray(body)).toBe(true);
  });

  test("인증이 필요한 호출은 로그인 없이 401을, 로그인 후에는 200을 낸다", async ({
    request,
    baseURL,
  }) => {
    const anonymous = await request.get("/api/backend/accounts/me");
    expect(anonymous.status()).toBe(401);

    const loginRes = await request.post("/api/auth/social/kakao/login", {
      headers: { origin: baseURL! },
      data: { access_token: "proxy-me-user:proxy-me-user@example.test" },
    });
    expect(loginRes.status()).toBe(200);

    const authed = await request.get("/api/backend/accounts/me");
    expect(authed.status()).toBe(200);
    const me = await authed.json();
    expect(me.username).toContain("proxy-me-user");
  });

  test("백엔드의 에러 상태 코드와 본문을 그대로 전달한다", async ({ request }) => {
    // 존재하지 않는 Contest 조회 — 백엔드가 404 + {"detail": ...}를 낸다.
    const res = await request.get("/api/backend/contests/999999999");
    expect(res.status()).toBe(404);
    const body = await res.json();
    expect(typeof body.detail).toBe("string");
    expect(body.detail.length).toBeGreaterThan(0);
  });
});

test.describe("프록시 경로에도 Origin 검증이 적용된다", () => {
  test("허용된 경로라도 다른 Origin에서 온 변경 요청은 거부된다", async ({ request }) => {
    const res = await request.post("/api/backend/contests/quote", {
      headers: { origin: "https://evil.example.test" },
      data: { deliverable_type_ids: [] },
    });
    expect(res.status()).toBe(403);
  });

  test("같은 Origin의 변경 요청은 Origin 검사를 통과해 백엔드까지 도달한다", async ({
    request,
    baseURL,
  }) => {
    const res = await request.post("/api/backend/contests/quote", {
      headers: { origin: baseURL! },
      data: { deliverable_type_ids: [] },
    });
    // Origin 검사를 통과했다면 403이 아니라 백엔드의 실제 판정(200 등)이 나와야 한다.
    expect(res.status()).not.toBe(403);
  });

  test("GET처럼 읽기 전용인 요청은 Origin 검사 대상이 아니다", async ({ request }) => {
    const res = await request.get("/api/backend/contests/categories", {
      headers: { origin: "https://evil.example.test" },
    });
    expect(res.status()).toBe(200);
  });
});
