import { expect, test } from "@playwright/test";

// BFF 프록시 — catch-all + 경로 허용목록 (FE-08, #33, ADR-0016).
//
// 전부 raw `request`로 친다 — 이 티켓의 대상(허용목록·Origin 검증)은 브라우저가
// 필요 없다(ADR-0017).

const NOT_ALLOWED_DETAIL = "허용되지 않은 경로입니다.";

test.describe("허용목록 — 기본은 거부", () => {
  test("허용목록에 없는 경로는 통과하지 못한다", async ({ request }) => {
    const res = await request.get("/api/backend/no-such-app/whatever");
    expect(res.status()).toBe(404);
    // 상태 코드만으로는 "프록시가 막았다"와 "백엔드가 다른 이유로 거절했다"를
    // 구분할 수 없다(코드리뷰 지적) — 프록시 고유의 거부 본문까지 확인한다.
    expect((await res.json()).detail).toBe(NOT_ALLOWED_DETAIL);
  });

  test("/api/internal/* 은 프록시로 도달할 수 없다", async ({ request, baseURL }) => {
    // 실제로 존재하는 내부 엔드포인트(스케줄러 틱)를 겨냥한다 — 존재하지 않는
    // 경로를 막는 것과 실제로 위험한 경로를 막는 것은 다른 증명이다.
    const getRes = await request.get("/api/backend/internal/tick");
    expect(getRes.status()).toBe(404);
    expect((await getRes.json()).detail).toBe(NOT_ALLOWED_DETAIL);

    const postRes = await request.post("/api/backend/internal/tick", {
      headers: { origin: baseURL! },
    });
    expect(postRes.status()).toBe(404);
    expect((await postRes.json()).detail).toBe(NOT_ALLOWED_DETAIL);

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
      expect((await res.json()).detail, path).toBe(NOT_ALLOWED_DETAIL);
    }
  });

  test("백엔드에 새 엔드포인트가 생겨도 허용목록에 없으면 노출되지 않는다", async ({
    request,
  }) => {
    // 실제로 존재할 법한 그럴듯한 이름이라도(가짜 새 라우터를 흉내낸 경로),
    // lib/proxy/allowlist.ts에 없으면 통과하지 못한다는 것을 보여준다.
    const res = await request.get("/api/backend/analytics/dashboard");
    expect(res.status()).toBe(404);
    expect((await res.json()).detail).toBe(NOT_ALLOWED_DETAIL);
  });

  test("세그먼트 안에 인코딩된 슬래시를 숨긴 경로 순회는 /api/internal/*에 도달하지 못한다", async ({
    request,
  }) => {
    // 실제로 겪었던 우회다: Next의 catch-all 파라미터는 세그먼트를 이미 URL
    // 디코드해서 넘긴다. "..%2finternal%2ftick"이라는 한 세그먼트는 디코드되면
    // "../internal/tick"이 되고, 예전 코드는 이걸 path.join("/")으로 그대로
    // 이어붙여 문자열 접두어 검사만 했다 — "/api/contests/../internal/tick"이
    // "/api/contests"로 시작한다는 이유로 허용목록을 통과했고, 그 문자열을 그대로
    // 받은 fetch()의 URL 파서가 ".."를 정규화해 실제로는 /api/internal/tick으로
    // 나갔다(프록시의 404가 아니라 백엔드의 401이 그대로 돌아오는 것으로 직접
    // 확인했다). lib/proxy/path-safety.ts의 세그먼트 검사가 이걸 막는다 — 반드시
    // 프록시 고유의 404 + 이 본문이어야 한다. 백엔드의 401이 보이면 우회가 아직
    // 뚫려 있다는 뜻이다.
    const bypassPaths = [
      // 소문자 퍼센트 인코딩.
      "/api/backend/contests/..%2finternal%2ftick",
      // 완전히 인코딩된 형태(".."까지 인코딩).
      "/api/backend/contests/%2e%2e%2finternal%2ftick",
      // 백슬래시 변형.
      "/api/backend/contests/..%5cinternal%5ctick",
      // 다단계 — 세그먼트 하나 안에 ".." 두 번을 숨긴다.
      "/api/backend/contests/..%2f..%2finternal%2ftick",
      // 허용목록에 있는 다른 접두어(submissions)로도 같은 우회를 시도한다 —
      // 특정 접두어 하나만 고친 게 아니라 구조적으로 막혔는지 확인한다.
      "/api/backend/submissions/..%2finternal%2fscoring%2frun-pending",
    ];

    for (const path of bypassPaths) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(404);
      expect((await res.json()).detail, path).toBe(NOT_ALLOWED_DETAIL);
    }
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
