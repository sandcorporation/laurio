// #395 Testing Decisions 「강의실 판정 함수」 — 순수 함수라 스택 없이 돈다.
// `middleware.ts`·`app/page.tsx` 둘 다 이 함수를 부르므로 여기서 검증한
// 분기가 곧 그 둘의 분기다.
import { describe, expect, it } from "vitest";

import { decideRootView } from "./decide-root-view";

describe("decideRootView (#395)", () => {
  it("루트에 로그인 쿠키가 없으면 랜딩이다", () => {
    expect(decideRootView({ pathname: "/", hasSessionCookie: false })).toBe("landing");
  });

  it("루트에 로그인 쿠키가 있으면 내 클래스다", () => {
    expect(decideRootView({ pathname: "/", hasSessionCookie: true })).toBe("my-classes");
  });

  it("루트가 아니면 쿠키 유무와 무관하게 해당 없음이다", () => {
    expect(decideRootView({ pathname: "/classes/new", hasSessionCookie: true })).toBe("not-applicable");
    expect(decideRootView({ pathname: "/login", hasSessionCookie: false })).toBe("not-applicable");
    expect(decideRootView({ pathname: "/join/abc123", hasSessionCookie: false })).toBe("not-applicable");
  });
});
