// 로그인 뒤 목적지(#1388 D2). Spec D5 둘째 표가 그대로 사례표다 — 허용목록을 시험마다
// 바꿔 끼워 「허용된 형제로의 복귀」를 여기서 확인한다(e2e 는 강의실 오리진 글자를
// 쓰지 못한다, scripts/test_e2e_origins.py).
import * as fs from "node:fs";
import * as path from "node:path";

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { continuePath, destinationLocation, resolveLoginDestination } from "./login-destination";
import { loginPathWithError } from "./redirect";

const DEV_CLASSROOM = "http://localhost:53002";

beforeEach(() => {
  vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", DEV_CLASSROOM);
});
afterEach(() => {
  vi.unstubAllEnvs();
});

describe("resolveLoginDestination — 허용된 형제로 돌아간다", () => {
  for (const nextOrigin of ["http://localhost:53002", "http://localhost:53002/", "http://LOCALHOST:53002"]) {
    it(`next_origin=${nextOrigin} → 강의실`, () => {
      const destination = resolveLoginDestination("/join/abc", nextOrigin);
      expect(destination).toEqual({ next: "/join/abc", returnOrigin: DEV_CLASSROOM });
      expect(destinationLocation(destination)).toBe(`${DEV_CLASSROOM}/join/abc`);
    });
  }

  it("(운영) https://<강의실>:443 → 강의실 — 기본 포트를 적어도 정규화하면 같다", () => {
    vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", "https://classroom.codemit.example");
    const destination = resolveLoginDestination("/join/abc", "https://classroom.codemit.example:443");
    expect(destination.returnOrigin).toBe("https://classroom.codemit.example");
    expect(destinationLocation(destination)).toBe("https://classroom.codemit.example/join/abc");
  });
});

describe("resolveLoginDestination — 나머지는 공개 앱에 남고 next 는 / 다", () => {
  const STAYS_HERE: string[] = [
    "http://localhost:53003",
    "http://localhost",
    "https://localhost:53002",
    "http://localhost:53002.evil.example",
    "http://localhost:53002@evil.example",
    "http://evil.example#@localhost:53002",
    "http%3A%2F%2Fevil.example",
    "javascript:alert(1)",
    "data:text/html,<script>alert(1)</script>",
    "https://evil.example",
  ];
  for (const nextOrigin of STAYS_HERE) {
    it(`next_origin=${nextOrigin} → 공개 앱 /`, () => {
      const destination = resolveLoginDestination("/join/abc", nextOrigin);
      expect(destination).toEqual({ next: "/", returnOrigin: null });
      expect(destinationLocation(destination)).toBe("/");
    });
  }

  it("(운영) https://<강의실>:8443 → 공개 앱", () => {
    vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", "https://classroom.codemit.example");
    expect(resolveLoginDestination("/join/abc", "https://classroom.codemit.example:8443")).toEqual({
      next: "/",
      returnOrigin: null,
    });
  });

  it("허용목록이 비면(설정 없음) 강의실 next_origin 도 공개 앱 /", () => {
    vi.stubEnv("CODEMIT_CLASSROOM_ORIGIN", "");
    expect(resolveLoginDestination("/join/abc", DEV_CLASSROOM)).toEqual({ next: "/", returnOrigin: null });
  });
});

describe("resolveLoginDestination — next 자체", () => {
  it("next_origin 이 없으면 공개 앱 안의 검증된 경로", () => {
    expect(resolveLoginDestination("/console/profile", null)).toEqual({
      next: "/console/profile",
      returnOrigin: null,
    });
  });

  for (const next of ["//evil.example", "/\\evil.example", "https://evil.example/", "/\t/evil.example"]) {
    it(`형제로 돌아갈 때도 바깥 next(${JSON.stringify(next)})는 / 다`, () => {
      const destination = resolveLoginDestination(next, DEV_CLASSROOM);
      expect(destination.next).toBe("/");
      expect(new URL(destinationLocation(destination)).origin).toBe(DEV_CLASSROOM);
    });
  }
});

describe("continuePath", () => {
  it("next·next_origin 을 그대로 실어 서버가 판정하게 한다", () => {
    const path = continuePath("/join/abc", DEV_CLASSROOM);
    const url = new URL(path, "http://public.test");
    expect(url.pathname).toBe("/api/auth/continue");
    expect(url.searchParams.get("next")).toBe("/join/abc");
    expect(url.searchParams.get("next_origin")).toBe(DEV_CLASSROOM);
  });

  it("값이 없으면 쿼리도 없다", () => {
    expect(continuePath("", null)).toBe("/api/auth/continue");
  });
});

// 목적지를 정하는 곳이 한 곳으로 남는지 — 라우트·화면은 이 러너에서 import 할 수 없어
// 소스를 읽는다(runtime-config 시험과 같은 방식).
describe("목적지 판정은 resolveLoginDestination 한 곳이다", () => {
  const read = (rel: string) => fs.readFileSync(path.resolve(__dirname, "..", "..", rel), "utf8");

  it("OAuth 콜백과 authorize 가 이 함수를 쓴다", () => {
    for (const rel of [
      "app/api/auth/social/[provider]/callback/route.ts",
      "app/api/auth/social/[provider]/authorize/route.ts",
    ]) {
      const source = read(rel);
      expect(source, rel).toContain("resolveLoginDestination(");
      expect(source, rel).not.toContain("resolveSiblingOrigin(");
    }
  });

  it("로그인 폼은 next_origin 으로 직접 이동하지 않고 /api/auth/continue 로 replace 한다", () => {
    const source = read("app/login/login-form.tsx");
    expect(source).toContain("window.location.replace(continuePath(next, nextOrigin))");
    expect(source).not.toMatch(/new URL\(\s*next\s*,\s*nextOrigin\s*\)/);
    expect(source).not.toContain("window.location.assign(");
  });
});

// 시나리오 9 의 CI 몫 — dev 는 카카오 자격증명이 없어 첫 시도가 늘 이 분기로 돌아온다.
describe("authorize 미설정(oauth_unconfigured) 복귀가 돌아갈 곳을 잃지 않는다", () => {
  function unconfiguredReturn(next: string, nextOrigin: string | null) {
    const { next: safeNext, returnOrigin } = resolveLoginDestination(next, nextOrigin);
    return new URL(loginPathWithError("oauth_unconfigured", safeNext, returnOrigin), "http://public.test");
  }

  it("허용된 next_origin 과 next 를 그대로 싣는다", () => {
    const url = unconfiguredReturn("/join/abc", DEV_CLASSROOM);
    expect(url.pathname).toBe("/login");
    expect(url.searchParams.get("error")).toBe("oauth_unconfigured");
    expect(url.searchParams.get("next")).toBe("/join/abc");
    expect(url.searchParams.get("next_origin")).toBe(DEV_CLASSROOM);
  });

  it("바깥 next_origin 은 싣지 않고 next 는 / 다", () => {
    const url = unconfiguredReturn("/join/abc", "https://evil.example");
    expect(url.searchParams.get("next")).toBe("/");
    expect(url.searchParams.has("next_origin")).toBe(false);
  });

  it("authorize 의 두 미설정 분기가 판정된 returnOrigin 을 넘긴다", () => {
    const source = fs.readFileSync(
      path.resolve(__dirname, "..", "..", "app/api/auth/social/[provider]/authorize/route.ts"),
      "utf8",
    );
    const calls = source.match(/loginPathWithError\("oauth_unconfigured", next, returnOrigin\)/g) ?? [];
    expect(calls).toHaveLength(2);
  });
});
