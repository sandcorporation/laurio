// 강의실도 공개 앱과 똑같은 domain 계약을 지키는지 확인한다 (ADR-0038, #276).
// 이 앱은 자기 쿠키를 발급하지 않지만(로그인이 없다), 프록시가 리프레시한 쿠키를
// 다시 구울 때(lib/proxy/forward.ts) 같은 부모 도메인으로 나가야 공개 앱이 심은
// 쿠키와 충돌 없이 같은 자리를 덮어쓴다.
import { NextResponse } from "next/server";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import { ACCESS_COOKIE, REFRESH_COOKIE, clearSessionCookies, setSessionCookies } from "./cookies";

const ORIGINAL_ENV = { ...process.env };

beforeEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

afterEach(() => {
  process.env = { ...ORIGINAL_ENV };
});

function fakeJwt(expSecondsFromNow: number): string {
  const payload = { sub: "1", exp: Math.floor(Date.now() / 1000) + expSecondsFromNow };
  const base64 = Buffer.from(JSON.stringify(payload)).toString("base64url");
  return `header.${base64}.signature`;
}

describe("setSessionCookies — domain 속성이 공개 앱과 같다 (ADR-0038)", () => {
  test("LAURIO_SESSION_COOKIE_DOMAIN이 비어 있으면(dev) domain을 주지 않는다", () => {
    delete process.env.LAURIO_SESSION_COOKIE_DOMAIN;
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    expect(response.cookies.get(ACCESS_COOKIE)?.domain).toBeUndefined();
    expect(response.cookies.get(REFRESH_COOKIE)?.domain).toBeUndefined();
  });

  test("LAURIO_SESSION_COOKIE_DOMAIN이 설정되면 부모 도메인을 domain으로 쓴다", () => {
    process.env.LAURIO_SESSION_COOKIE_DOMAIN = ".laurio.honeycombpizza.link";
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    expect(response.cookies.get(ACCESS_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
    expect(response.cookies.get(REFRESH_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
  });
});

describe("clearSessionCookies", () => {
  test("domain이 설정되면 삭제 쿠키도 같은 domain을 쓴다", () => {
    process.env.LAURIO_SESSION_COOKIE_DOMAIN = ".laurio.honeycombpizza.link";
    const response = new NextResponse();

    clearSessionCookies(response);

    expect(response.cookies.get(ACCESS_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
    expect(response.cookies.get(REFRESH_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
  });
});
