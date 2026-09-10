// 세션 쿠키의 domain 속성이 배포 환경별로 갈리는지 확인한다 (ADR-0038, #273).
// LAURIO_SESSION_COOKIE_DOMAIN이 설정되면 그 값을 쓰고, 비어 있으면(dev) domain을
// 아예 주지 않는다 — dev는 localhost라 domain을 주면 쿠키가 붙지 않기 때문이다.
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

describe("setSessionCookies — domain 속성", () => {
  test("LAURIO_SESSION_COOKIE_DOMAIN이 비어 있으면(dev) domain을 주지 않는다", () => {
    delete process.env.LAURIO_SESSION_COOKIE_DOMAIN;
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    const access = response.cookies.get(ACCESS_COOKIE);
    const refresh = response.cookies.get(REFRESH_COOKIE);
    expect(access?.domain).toBeUndefined();
    expect(refresh?.domain).toBeUndefined();
  });

  test("LAURIO_SESSION_COOKIE_DOMAIN이 설정되면(staging/prod) 부모 도메인을 domain으로 쓴다", () => {
    process.env.LAURIO_SESSION_COOKIE_DOMAIN = ".laurio.honeycombpizza.link";
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    const access = response.cookies.get(ACCESS_COOKIE);
    const refresh = response.cookies.get(REFRESH_COOKIE);
    expect(access?.domain).toBe(".laurio.honeycombpizza.link");
    expect(refresh?.domain).toBe(".laurio.honeycombpizza.link");
  });

  test("httpOnly는 domain 설정 여부와 무관하게 그대로다", () => {
    process.env.LAURIO_SESSION_COOKIE_DOMAIN = ".laurio.honeycombpizza.link";
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    expect(response.cookies.get(ACCESS_COOKIE)?.httpOnly).toBe(true);
    expect(response.cookies.get(REFRESH_COOKIE)?.httpOnly).toBe(true);
  });
});

describe("clearSessionCookies — domain 속성이 setSessionCookies와 일치한다", () => {
  // 로그아웃 시 지우는 쿠키의 domain이 로그인 때 설정한 domain과 다르면 브라우저가
  // 다른 쿠키로 취급해 실제로는 지워지지 않는다.
  test("LAURIO_SESSION_COOKIE_DOMAIN이 설정되면 삭제 쿠키도 같은 domain을 쓴다", () => {
    process.env.LAURIO_SESSION_COOKIE_DOMAIN = ".laurio.honeycombpizza.link";
    const response = new NextResponse();

    clearSessionCookies(response);

    const access = response.cookies.get(ACCESS_COOKIE);
    const refresh = response.cookies.get(REFRESH_COOKIE);
    expect(access?.domain).toBe(".laurio.honeycombpizza.link");
    expect(refresh?.domain).toBe(".laurio.honeycombpizza.link");
  });
});
