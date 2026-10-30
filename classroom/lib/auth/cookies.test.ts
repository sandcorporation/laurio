// 강의실도 공개 앱과 똑같은 domain 계약을 지키는지 확인한다 (ADR-0038, #276).
// 이 앱은 자기 쿠키를 발급하지 않지만(로그인이 없다), 프록시가 리프레시한 쿠키를
// 다시 구울 때(lib/proxy/forward.ts) 같은 부모 도메인으로 나가야 공개 앱이 심은
// 쿠키와 충돌 없이 같은 자리를 덮어쓴다.
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

describe("setSessionCookies — domain 속성이 공개 앱과 같다", () => {
  test("CODEMIT_SESSION_COOKIE_DOMAIN이 비어 있으면(dev) domain을 주지 않는다", () => {
    delete process.env.CODEMIT_SESSION_COOKIE_DOMAIN;
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    expect(response.cookies.get(ACCESS_COOKIE)?.domain).toBeUndefined();
    expect(response.cookies.get(REFRESH_COOKIE)?.domain).toBeUndefined();
  });

  test("CODEMIT_SESSION_COOKIE_DOMAIN이 설정되면 부모 도메인을 domain으로 쓴다", () => {
    process.env.CODEMIT_SESSION_COOKIE_DOMAIN = ".laurio.honeycombpizza.link";
    const response = new NextResponse();

    setSessionCookies(response, { access: fakeJwt(300), refresh: fakeJwt(1209600) });

    expect(response.cookies.get(ACCESS_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
    expect(response.cookies.get(REFRESH_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
  });
});

describe("clearSessionCookies", () => {
  test("domain이 설정되면 삭제 쿠키도 같은 domain을 쓴다", () => {
    process.env.CODEMIT_SESSION_COOKIE_DOMAIN = ".laurio.honeycombpizza.link";
    const response = new NextResponse();

    clearSessionCookies(response);

    expect(response.cookies.get(ACCESS_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
    expect(response.cookies.get(REFRESH_COOKIE)?.domain).toBe(".laurio.honeycombpizza.link");
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
