import { expect, test } from "@playwright/test";

import { E2E_OPERATOR_PASSWORD, seedE2eOperator } from "../lib/seed-operator";

// 운영자 앱 06(#64) — BFF 프록시 catch-all + 허용목록(ADR-0016/0019/0021).
//
// 공개 앱의 e2e/proxy.spec.ts와 같은 시임 규약이다 — 이 티켓의 대상(허용목록·
// 경로 순회 방어·Origin 검증)은 브라우저가 필요 없어 전부 raw `request`로 친다.
// 이 파일이 확인하는 건 "운영자 앱의 허용목록이 운영자 표면 하나뿐"이라는 사실 —
// 공개 앱 쪽의 대칭 사실("운영자 표면은 공개 앱 프록시로 도달할 수 없다")은
// frontend/e2e/proxy.spec.ts가 이미 지킨다.

const NOT_ALLOWED_DETAIL = "허용되지 않은 경로입니다.";

async function loginAsOperator(
  request: import("@playwright/test").APIRequestContext,
  baseURL: string,
): Promise<void> {
  const operator = seedE2eOperator({ username: `e2e-op-proxy-${Date.now()}` });
  const res = await request.post("/api/auth/login", {
    headers: { origin: baseURL },
    data: { username: operator.username, password: E2E_OPERATOR_PASSWORD },
  });
  expect(res.status()).toBe(200);
}

test.describe("허용목록 — 운영자 표면 하나뿐(ADR-0021)", () => {
  test("/api/internal/* 은 프록시로 도달할 수 없다 — 백엔드를 직접 쳤을 때의 401과 다르다", async ({
    request,
    baseURL,
  }) => {
    const getRes = await request.get("/api/backend/internal/tick");
    expect(getRes.status()).toBe(404);
    expect((await getRes.json()).detail).toBe(NOT_ALLOWED_DETAIL);

    const postRes = await request.post("/api/backend/internal/tick", {
      headers: { origin: baseURL! },
    });
    expect(postRes.status()).toBe(404);
    expect((await postRes.json()).detail).toBe(NOT_ALLOWED_DETAIL);

    // 나머지 내부 라우터도 함께 — 이 사람이 아니라 Celery beat 가 부르는 자리다.
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

  test("운영자 표면이 아닌 다른 백엔드 접두어는 통과하지 못한다", async ({ request }) => {
    // 공개 앱이라면 정상 허용목록인 경로들이지만, 이 앱의 허용목록은 "/api/operator"
    // 하나뿐이다 — 참가자용 표면이 이 앱에 뜰 이유가 없다(ADR-0021).
    for (const path of [
      "/api/backend/contests/categories",
      "/api/backend/accounts/me",
      "/api/backend/submissions",
      "/api/backend/ledger/entries",
    ]) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(404);
      expect((await res.json()).detail, path).toBe(NOT_ALLOWED_DETAIL);
    }
  });

  test("운영자 표면은 정상적으로 통과한다", async ({ request, baseURL }) => {
    await loginAsOperator(request, baseURL!);

    const res = await request.get("/api/backend/operator/me");
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(typeof body.username).toBe("string");
  });

  test("세그먼트 안에 인코딩된 슬래시를 숨긴 경로 순회는 /api/internal/*에 도달하지 못한다", async ({
    request,
  }) => {
    // 공개 앱에서 실제로 발견됐던 우회(frontend/e2e/proxy.spec.ts 상단 주석)를
    // 운영자 앱에 대해서도 친다 — 같은 공유 코드지만, 이 앱에도 실제로 걸려
    // 있음을 확인하는 것은 별개의 사실이다.
    const bypassPaths = [
      "/api/backend/operator/..%2finternal%2ftick",
      "/api/backend/operator/%2e%2e%2finternal%2ftick",
      "/api/backend/operator/..%5cinternal%5ctick",
      "/api/backend/operator/..%2f..%2finternal%2ftick",
    ];

    for (const path of bypassPaths) {
      const res = await request.get(path);
      expect(res.status(), path).toBe(404);
      expect((await res.json()).detail, path).toBe(NOT_ALLOWED_DETAIL);
    }
  });
});

test.describe("프록시 경로에도 Origin 검증이 적용된다(ADR-0016/0019)", () => {
  test("허용된 경로라도 다른 Origin에서 온 변경 요청은 거부된다", async ({ request, baseURL }) => {
    await loginAsOperator(request, baseURL!);

    const res = await request.post("/api/backend/operator/logout", {
      headers: { origin: "https://evil.example.test" },
    });
    expect(res.status()).toBe(403);
  });

  test("Origin 헤더가 아예 없는 변경 요청도 거부된다(fail-closed)", async ({ request, baseURL }) => {
    await loginAsOperator(request, baseURL!);

    const res = await request.post("/api/backend/operator/logout");
    expect(res.status()).toBe(403);
  });

  test("같은 Origin의 변경 요청은 Origin 검사를 통과해 백엔드까지 도달한다 — 설정 정합성 증명", async ({
    request,
    baseURL,
  }) => {
    // 이 BFF 가 백엔드로 나갈 때 붙이는 Origin(lib/backend.ts의 operatorOrigin)이
    // 백엔드가 기대하는 값(OPERATOR_WEB_ORIGIN, 비어 있으면 Host 헤더 유도)과
    // 어긋나면 이 요청은 403이 된다 — 로그인이 되는 것으로 이미 증명되지만,
    // 여기서는 그것이 "두 앱의 오리진 설정이 서로 맞는가"의 문제임을 로그아웃
    // 경로로도 한 번 더 못박는다. 어긋나면 조용히 매 요청이 403이 되는 사고를
    // 이 저장소가 이미 두 번 겪었다(CLAUDE.md).
    await loginAsOperator(request, baseURL!);

    const res = await request.post("/api/backend/operator/logout", {
      headers: { origin: baseURL! },
    });
    expect(res.status()).not.toBe(403);
    expect(res.status()).toBe(200);
  });

  test("GET처럼 읽기 전용인 요청은 Origin 검사 대상이 아니다", async ({ request, baseURL }) => {
    await loginAsOperator(request, baseURL!);

    const res = await request.get("/api/backend/operator/me", {
      headers: { origin: "https://evil.example.test" },
    });
    expect(res.status()).toBe(200);
  });
});
