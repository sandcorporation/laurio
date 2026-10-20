// 강의실 세션 라우트(#767) — 공개 앱 `/api/auth/session` 과 같은 계약이다. 액세스가
// 만료돼 있으면 리프레시로 조용히 회전해 새 쿠키를 응답에 싣고, 회전에 지면(형제
// 요청이 먼저 돌렸을 수 있다) 401 을 내되 쿠키는 지우지 않는다.
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { ACCESS_COOKIE, REFRESH_COOKIE } from "./cookies";
import { sessionResponse } from "./session-endpoint";

const ORIGINAL_FETCH = globalThis.fetch;

function fakeJwt(expSecondsFromNow: number): string {
  const payload = { sub: "1", exp: Math.floor(Date.now() / 1000) + expSecondsFromNow };
  const base64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `header.${base64}.signature`;
}

function requestWith(cookies: Record<string, string>): NextRequest {
  const cookie = Object.entries(cookies)
    .map(([name, value]) => `${name}=${value}`)
    .join("; ");
  return new NextRequest("http://classroom.test/api/auth/session", { headers: { cookie } });
}

beforeEach(() => {
  process.env.CODEMIT_API_BASE_URL = "http://backend.test";
});

afterEach(() => {
  globalThis.fetch = ORIGINAL_FETCH;
  delete process.env.CODEMIT_API_BASE_URL;
});

describe("sessionResponse (#767)", () => {
  test("만료된 액세스 + 유효한 리프레시 → 회전해 200 과 새 쿠키를 돌려준다", async () => {
    const rotated = { access: fakeJwt(300), refresh: fakeJwt(1_209_600) };
    const calls: { url: string; authorization: string | null }[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push({ url, authorization: new Headers(init?.headers).get("authorization") });
      if (url.endsWith("/api/auth/refresh")) return Response.json(rotated);
      if (url.endsWith("/api/accounts/me")) return Response.json({ id: 1, email: "t@example.com" });
      return new Response(null, { status: 404 });
    }) as typeof fetch;

    const response = await sessionResponse(
      requestWith({ [ACCESS_COOKIE]: fakeJwt(-60), [REFRESH_COOKIE]: fakeJwt(1_209_600) }),
    );

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({ id: 1, email: "t@example.com" });
    expect(response.cookies.get(ACCESS_COOKIE)?.value).toBe(rotated.access);
    expect(response.cookies.get(REFRESH_COOKIE)?.value).toBe(rotated.refresh);
    expect(calls.map((c) => c.url)).toEqual([
      "http://backend.test/api/auth/refresh",
      "http://backend.test/api/accounts/me",
    ]);
    expect(calls[1].authorization).toBe(`Bearer ${rotated.access}`);
  });

  test("리프레시 회전에 지면 401 이되 쿠키를 지우지 않는다 — 형제 요청이 이겼을 수 있다", async () => {
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/auth/refresh")) return new Response(null, { status: 401 });
      if (url.endsWith("/api/accounts/me")) return new Response(null, { status: 401 });
      return new Response(null, { status: 404 });
    }) as typeof fetch;

    const response = await sessionResponse(
      requestWith({ [ACCESS_COOKIE]: fakeJwt(-60), [REFRESH_COOKIE]: fakeJwt(1_209_600) }),
    );

    expect(response.status).toBe(401);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  test("exp 상 유효한 액세스를 백엔드가 401 로 거절하면 한 번 회전해 다시 시도한다(공개 앱과 같다)", async () => {
    const rotated = { access: fakeJwt(300), refresh: fakeJwt(1_209_600) };
    const meAuthorizations: (string | null)[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/auth/refresh")) return Response.json(rotated);
      if (url.endsWith("/api/accounts/me")) {
        const authorization = new Headers(init?.headers).get("authorization");
        meAuthorizations.push(authorization);
        return authorization === `Bearer ${rotated.access}`
          ? Response.json({ id: 1 })
          : new Response(null, { status: 401 });
      }
      return new Response(null, { status: 404 });
    }) as typeof fetch;

    // 요청의 액세스는 exp 상 유효하되 회전된 것과 다른 토큰이다(같은 초에 만들면 문자열이 같아진다).
    const response = await sessionResponse(
      requestWith({ [ACCESS_COOKIE]: fakeJwt(200), [REFRESH_COOKIE]: fakeJwt(1_209_600) }),
    );

    expect(response.status).toBe(200);
    expect(meAuthorizations).toHaveLength(2);
    expect(response.cookies.get(ACCESS_COOKIE)?.value).toBe(rotated.access);
  });

  test("그 재시도의 회전까지 실패하면 401 이고 죽은 쿠키를 지운다", async () => {
    globalThis.fetch = vi.fn(async () => new Response(null, { status: 401 })) as typeof fetch;

    const response = await sessionResponse(
      requestWith({ [ACCESS_COOKIE]: fakeJwt(300), [REFRESH_COOKIE]: fakeJwt(1_209_600) }),
    );

    expect(response.status).toBe(401);
    expect(response.cookies.get(ACCESS_COOKIE)?.value).toBe("");
  });

  test("리프레시까지 만료됐으면 401 이고 죽은 쿠키를 지운다", async () => {
    globalThis.fetch = vi.fn(async () => new Response(null, { status: 401 })) as typeof fetch;

    const response = await sessionResponse(
      requestWith({ [ACCESS_COOKIE]: fakeJwt(-60), [REFRESH_COOKIE]: fakeJwt(-60) }),
    );

    expect(response.status).toBe(401);
    expect(response.cookies.get(ACCESS_COOKIE)?.value).toBe("");
    expect(response.cookies.get(REFRESH_COOKIE)?.value).toBe("");
  });
});
