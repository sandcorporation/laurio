// 세션 쿠키의 domain 속성이 배포 환경별로 갈리는지 확인한다 (ADR-0038, #273).
// CODEMIT_SESSION_COOKIE_DOMAIN이 설정되면 그 값을 쓰고, 비어 있으면(dev) domain을
// 아예 주지 않는다 — dev는 localhost라 domain을 주면 쿠키가 붙지 않기 때문이다.
import { NextResponse } from "next/server";
import { afterEach, beforeEach, describe, expect, test } from "vitest";

import {
  ACCESS_COOKIE,
  REFRESH_COOKIE,
  clearSessionCookies,
  invalidDeploymentTarget,
  isDeployedEnvironment,
  setSessionCookies,
} from "./cookies";

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
  test("CODEMIT_SESSION_COOKIE_DOMAIN이 비어 있으면(dev) domain을 주지 않는다", () => {
    delete process.env.CODEMIT_SESSION_COOKIE_DOMAIN;
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    const access = response.cookies.get(ACCESS_COOKIE);
    const refresh = response.cookies.get(REFRESH_COOKIE);
    expect(access?.domain).toBeUndefined();
    expect(refresh?.domain).toBeUndefined();
  });

  test("CODEMIT_SESSION_COOKIE_DOMAIN이 설정되면(prod) 부모 도메인을 domain으로 쓴다", () => {
    process.env.CODEMIT_SESSION_COOKIE_DOMAIN = ".example.com";
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    const access = response.cookies.get(ACCESS_COOKIE);
    const refresh = response.cookies.get(REFRESH_COOKIE);
    expect(access?.domain).toBe(".example.com");
    expect(refresh?.domain).toBe(".example.com");
  });

  test("httpOnly는 domain 설정 여부와 무관하게 그대로다", () => {
    process.env.CODEMIT_SESSION_COOKIE_DOMAIN = ".example.com";
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    expect(response.cookies.get(ACCESS_COOKIE)?.httpOnly).toBe(true);
    expect(response.cookies.get(REFRESH_COOKIE)?.httpOnly).toBe(true);
  });
});

describe("clearSessionCookies — domain 속성이 setSessionCookies와 일치한다", () => {
  // 로그아웃 시 지우는 쿠키의 domain이 로그인 때 설정한 domain과 다르면 브라우저가
  // 다른 쿠키로 취급해 실제로는 지워지지 않는다.
  test("CODEMIT_SESSION_COOKIE_DOMAIN이 설정되면 삭제 쿠키도 같은 domain을 쓴다", () => {
    process.env.CODEMIT_SESSION_COOKIE_DOMAIN = ".example.com";
    const response = new NextResponse();

    clearSessionCookies(response);

    const access = response.cookies.get(ACCESS_COOKIE);
    const refresh = response.cookies.get(REFRESH_COOKIE);
    expect(access?.domain).toBe(".example.com");
    expect(refresh?.domain).toBe(".example.com");
  });
});

describe("배포 대상 — production 하나만 배포로 본다(staging 은 #836 에서 없앴다)", () => {
  test("production 만 배포 환경이다", () => {
    process.env.CODEMIT_DEPLOYMENT_TARGET = "production";
    expect(isDeployedEnvironment()).toBe(true);

    for (const target of ["development", "staging", ""]) {
      process.env.CODEMIT_DEPLOYMENT_TARGET = target;
      expect(isDeployedEnvironment()).toBe(false);
    }
  });

  test("비어 있거나 development·production 이면 부팅 가드가 받아들인다", () => {
    expect(invalidDeploymentTarget(undefined)).toBeNull();
    expect(invalidDeploymentTarget("")).toBeNull();
    expect(invalidDeploymentTarget("development")).toBeNull();
    expect(invalidDeploymentTarget("production")).toBeNull();
  });

  test("없앤 staging 과 오타는 부팅 가드가 거부한다 — development 로 조용히 흐르지 않는다", () => {
    for (const target of ["staging", "Staging", "prod", "Production", " production"]) {
      expect(invalidDeploymentTarget(target)).toContain(`CODEMIT_DEPLOYMENT_TARGET=${target}`);
    }
  });
});
