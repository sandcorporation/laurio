// `GET /api/auth/continue`(#1388 D2) — 세션 확인 뒤 목적지로, 아니면 로그인으로.
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BackendFetchResult } from "./backend-fetch";
import { handleContinue } from "./continue";

const CLASSROOM = "http://localhost:53002";

beforeEach(() => {
  vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", CLASSROOM);
});
afterEach(() => {
  vi.unstubAllEnvs();
});

function result(status: number, extra: Partial<BackendFetchResult> = {}): BackendFetchResult {
  return { response: new Response("{}", { status }), refreshedPair: null, shouldClearCookies: false, ...extra };
}

function run(query: string, backend: BackendFetchResult) {
  const fetchBackendAuthenticated = vi.fn(async () => backend);
  const request = new NextRequest(`http://public.test/api/auth/continue${query}`);
  return { promise: handleContinue(request, { fetchBackendAuthenticated }), fetchBackendAuthenticated };
}

describe("handleContinue", () => {
  it("인증되면 303 으로 허용된 형제 목적지에 간다", async () => {
    const { promise, fetchBackendAuthenticated } = run(
      `?next=%2Fjoin%2Fabc&next_origin=${encodeURIComponent(CLASSROOM)}`,
      result(200),
    );
    const response = await promise;
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe(`${CLASSROOM}/join/abc`);
    expect(response.headers.get("cache-control")).toContain("no-store");
    expect(fetchBackendAuthenticated).toHaveBeenCalledWith(expect.anything(), "/api/accounts/me", {
      method: "GET",
    });
  });

  it("인증되면 같은 오리진 목적지는 상대 경로다", async () => {
    const response = await run("?next=%2Fconsole%2Fprofile", result(200)).promise;
    expect(response.status).toBe(303);
    expect(response.headers.get("location")).toBe("/console/profile");
  });

  it("바깥 next_origin 은 인증돼도 공개 앱 / 로 떨어진다", async () => {
    const response = await run("?next=%2Fjoin%2Fabc&next_origin=https%3A%2F%2Fevil.example", result(200)).promise;
    expect(response.headers.get("location")).toBe("/");
  });

  it("리프레시된 쌍을 응답 쿠키에 싣는다", async () => {
    const response = await run(
      "?next=%2F",
      result(200, { refreshedPair: { access: "new.access.token", refresh: "new.refresh.token" } }),
    ).promise;
    expect(response.cookies.get("codemit_access")?.value).toBe("new.access.token");
    expect(response.cookies.get("codemit_refresh")?.value).toBe("new.refresh.token");
  });

  it("인증되지 않았으면 검증된 next·next_origin 을 실어 /login 으로 간다", async () => {
    const response = await run(
      `?next=%2Fjoin%2Fabc&next_origin=${encodeURIComponent(CLASSROOM)}`,
      result(401),
    ).promise;
    expect(response.status).toBe(303);
    const location = new URL(response.headers.get("location")!, "http://public.test");
    expect(location.pathname).toBe("/login");
    expect(location.searchParams.get("next")).toBe("/join/abc");
    expect(location.searchParams.get("next_origin")).toBe(CLASSROOM);
  });

  it("인증되지 않았고 바깥 next_origin 이면 그것을 다시 싣지 않는다", async () => {
    const response = await run("?next=%2Fjoin%2Fabc&next_origin=https%3A%2F%2Fevil.example", result(401)).promise;
    const location = new URL(response.headers.get("location")!, "http://public.test");
    expect(location.searchParams.get("next")).toBe("/");
    expect(location.searchParams.has("next_origin")).toBe(false);
  });

  it("죽은 쿠키면 지운다", async () => {
    const response = await run("", result(401, { shouldClearCookies: true })).promise;
    expect(response.cookies.get("codemit_access")?.value).toBe("");
  });
});
