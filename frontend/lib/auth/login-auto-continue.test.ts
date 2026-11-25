// 로그인한 사람이 공개 앱 /login 을 열면 목적지로 넘긴다(#1388 T3, Spec D3).
import * as fs from "node:fs";
import * as path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  LOGIN_BOUNCE_COOKIE,
  LOGIN_BOUNCE_MAX_AGE_SECONDS,
  autoContinuePath,
  isAutoContinueStopped,
  shouldCheckSessionOnLogin,
} from "./login-auto-continue";

const CLASSROOM = "http://localhost:53002";

beforeEach(() => {
  vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", CLASSROOM);
});
afterEach(() => {
  vi.unstubAllEnvs();
});

const base = { hasSessionCookie: true, error: null, bounced: false, next: "/join/x", nextOrigin: CLASSROOM };

describe("shouldCheckSessionOnLogin", () => {
  it("세션 쿠키가 없으면 세션을 조회하지 않는다", () => {
    expect(shouldCheckSessionOnLogin({ ...base, hasSessionCookie: false })).toBe(false);
  });

  it("세션 쿠키가 있으면 조회한다", () => {
    expect(shouldCheckSessionOnLogin(base)).toBe(true);
  });

  it("?error= 가 있으면 넘기지 않는다", () => {
    expect(shouldCheckSessionOnLogin({ ...base, error: "oauth_unconfigured" })).toBe(false);
  });

  it("bounce 쿠키가 있고 목적지가 형제(강의실)이면 폼을 그린다 — 순환 차단기", () => {
    expect(shouldCheckSessionOnLogin({ ...base, bounced: true })).toBe(false);
  });

  it("bounce 쿠키가 있어도 목적지가 공개 앱 안이면 넘긴다", () => {
    expect(shouldCheckSessionOnLogin({ ...base, bounced: true, nextOrigin: null, next: "/console/profile" })).toBe(
      true,
    );
  });

  it("bounce 쿠키가 있어도 허용목록 밖 next_origin 은 공개 앱 안 목적지라 넘긴다", () => {
    expect(shouldCheckSessionOnLogin({ ...base, bounced: true, nextOrigin: "https://evil.example" })).toBe(true);
  });
});

describe("isAutoContinueStopped — 차단기가 폼을 세웠을 때만 알린다(#1406)", () => {
  it("세션 쿠키 + bounce 쿠키 + 형제 목적지면 참이다", () => {
    expect(isAutoContinueStopped({ ...base, bounced: true })).toBe(true);
  });

  it.each([
    ["처음 로그인하는 사람", { hasSessionCookie: false, bounced: true }],
    ["bounce 쿠키 없음", { bounced: false }],
    ["?error= 는 그 이유를 따로 보인다", { bounced: true, error: "login_failed" }],
    ["공개 앱 안 목적지", { bounced: true, nextOrigin: null }],
  ])("%s 이면 거짓이다", (_name, patch) => {
    expect(isAutoContinueStopped({ ...base, ...patch })).toBe(false);
  });
});

describe("autoContinuePath", () => {
  it("/api/auth/continue 에 auto=1 을 더한다", () => {
    const url = new URL(autoContinuePath("/join/x", CLASSROOM), "http://public.test");
    expect(url.pathname).toBe("/api/auth/continue");
    expect(url.searchParams.get("next")).toBe("/join/x");
    expect(url.searchParams.get("next_origin")).toBe(CLASSROOM);
    expect(url.searchParams.get("auto")).toBe("1");
  });

  it("값이 없어도 auto=1 은 있다", () => {
    expect(autoContinuePath(null, null)).toBe("/api/auth/continue?auto=1");
  });
});

describe("bounce 쿠키 상수", () => {
  it("이름과 수명", () => {
    expect(LOGIN_BOUNCE_COOKIE).toBe("codemit_login_bounce");
    expect(LOGIN_BOUNCE_MAX_AGE_SECONDS).toBe(30);
  });
});

// 화면·서버 컴포넌트는 이 러너에서 import 할 수 없어 소스를 읽는다.
describe("/login 이 이 판정을 쓴다", () => {
  const read = (rel: string) => fs.readFileSync(path.resolve(__dirname, "..", "..", rel), "utf8");

  it("page.tsx 가 쿠키 유무·bounce 쿠키·error 로 판정해 boolean 하나만 넘긴다", () => {
    const source = read("app/login/page.tsx");
    expect(source).toContain("shouldCheckSessionOnLogin(");
    expect(source).toContain("LOGIN_BOUNCE_COOKIE");
    expect(source).toContain("checkSessionFirst={");
    expect(source).toContain('export const dynamic = "force-dynamic"');
  });

  it("차단기가 세운 폼은 그렇다고 알린다(#1406)", () => {
    expect(read("app/login/page.tsx")).toContain("autoContinueStopped={isAutoContinueStopped(");
    expect(read("app/login/login-form.tsx")).toMatch(
      /autoContinueStopped && \([\s\S]*?data-testid="login-bounce-notice">자동 이동을 멈췄습니다\. 다시 로그인해 주세요\./,
    );
  });

  it("로그인 폼은 /api/auth/session 이 200 일 때만 auto=1 로 replace 한다", () => {
    const source = read("app/login/login-form.tsx");
    expect(source).toMatch(/fetch\("\/api\/auth\/session"/);
    expect(source).toMatch(/if \(res\.status === 200\)\s*\{?\s*window\.location\.replace\(autoContinuePath\(next, nextOrigin\)\)/);
  });
});
