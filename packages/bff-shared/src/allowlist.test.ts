// isAllowedPath의 허용목록 경계를 전수로 덮는다(#161) — 접두어에서 한 글자
// 어긋난 값, 접두어가 세그먼트 경계에서 끝나지 않는 값을 포함한다.
import { describe, expect, test } from "vitest";

import { isAllowedPath } from "./allowlist";

const ALLOWLIST = ["/api/contests", "/api/operator"];

describe("isAllowedPath — 경계(전수)", () => {
  test("접두어와 정확히 같은 경로는 허용된다", () => {
    expect(isAllowedPath("/api/contests", ALLOWLIST)).toBe(true);
    expect(isAllowedPath("/api/operator", ALLOWLIST)).toBe(true);
  });

  test("접두어 뒤에 '/'로 이어지는 하위 경로는 허용된다", () => {
    expect(isAllowedPath("/api/contests/123", ALLOWLIST)).toBe(true);
    expect(isAllowedPath("/api/operator/login", ALLOWLIST)).toBe(true);
  });

  describe("접두어에서 한 글자 어긋난 값 — 거부", () => {
    test.each([
      "/api/contest", // 한 글자 짧다
      "/api/contestss", // 한 글자 길다(그런데 세그먼트 경계가 아니다 — 아래 별도 확인)
      "/api/Contests", // 대소문자
      "/api/contests ", // 끝에 공백
    ])("%s는 거부된다", (pathname) => {
      expect(isAllowedPath(pathname, ALLOWLIST)).toBe(false);
    });
  });

  describe("접두어가 세그먼트 경계에서 끝나지 않는 값 — 거부", () => {
    // "/api/contests"로 "시작"하지만 바로 다음 문자가 '/'가 아니면 다른 리소스다
    // ("/api/contestsx"는 "/api/contests"의 하위 경로가 아니라 "contestsx"라는
    // 별개 이름이다).
    test.each([
      "/api/contestsx",
      "/api/contests-archive",
      "/api/contestsanything",
    ])("%s는 거부된다", (pathname) => {
      expect(isAllowedPath(pathname, ALLOWLIST)).toBe(false);
    });
  });

  test("허용목록에 없는 접두어는 거부된다", () => {
    expect(isAllowedPath("/api/internal/tick", ALLOWLIST)).toBe(false);
  });

  test("빈 허용목록은 무엇도 허용하지 않는다(기본 거부)", () => {
    expect(isAllowedPath("/api/contests", [])).toBe(false);
  });

  test("접두어보다 짧은 경로는 거부된다", () => {
    expect(isAllowedPath("/api/con", ALLOWLIST)).toBe(false);
    expect(isAllowedPath("/api", ALLOWLIST)).toBe(false);
    expect(isAllowedPath("", ALLOWLIST)).toBe(false);
  });

  test("접두어 여럿 중 하나만 맞아도 허용된다", () => {
    expect(isAllowedPath("/api/operator/me", ALLOWLIST)).toBe(true);
  });

  test("접두어의 부분 문자열이 다른 접두어처럼 보여도 정확히 그 접두어여야 한다", () => {
    // "/api/operator"는 허용목록에 있지만 "/api/operator-archive"는 그 접두어의
    // 세그먼트 경계 밖이다.
    expect(isAllowedPath("/api/operator-archive", ALLOWLIST)).toBe(false);
  });
});
