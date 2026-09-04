// sanitizeNextPath의 다섯 거부 종류를 전수로 덮는다(#160, ADR-0026).
//
// sanitize-next.ts의 주석이 다섯 종류를 적어 두었는데 e2e(frontend/e2e/operator/
// auth.spec.ts)는 그중 완전한 외부 URL·프로토콜 상대 URL 둘만 브라우저로 쳤다.
// 나머지 둘(역슬래시·제어 문자)은 주석이 "일부 파서가 조용히 건너뛰어 우회를 다시
// 연다"고 스스로 경고한 바로 그 위험인데 테스트가 없었다 — 여기서 다섯 종류 전부와
// 그 경계를 표로 단언한다.
import { describe, expect, test } from "vitest";

import { sanitizeNextPath } from "./sanitize-next";

describe("sanitizeNextPath — 다섯 거부 종류(전수)", () => {
  describe("1) 빈 값", () => {
    test.each<[string, string | null]>([
      ["null", null],
      ["빈 문자열", ""],
    ])("%s는 홈(/)으로 떨어진다", (_label, input) => {
      expect(sanitizeNextPath(input)).toBe("/");
    });
  });

  describe("2) 완전한 외부 URL", () => {
    test.each([
      "https://evil.example.test/phish",
      "http://evil.example.test",
      "evil.example.test",
      "ftp://evil.example.test",
      "javascript:alert(1)",
    ])("%s는 '/'로 시작하지 않으므로 거부된다", (input) => {
      expect(sanitizeNextPath(input)).toBe("/");
    });
  });

  describe("3) 프로토콜 상대 URL", () => {
    test.each([
      "//evil.example.test",
      "//evil.example.test/phish",
      "///evil.example.test",
    ])("%s는 슬래시 두 개로 시작하므로 거부된다", (input) => {
      expect(sanitizeNextPath(input)).toBe("/");
    });

    test("슬래시가 맨 앞이 아니라 중간에 두 개 붙은 정상 경로는 거부되지 않는다", () => {
      // 경계 확인 — "//"로 "시작"하는지만 본다. 중간의 이중 슬래시는 다른 문제고
      // 이 함수의 책임이 아니다.
      expect(sanitizeNextPath("/foo//bar")).toBe("/foo//bar");
    });
  });

  describe("4) 역슬래시가 섞인 값", () => {
    test.each([
      "/\\evil.example.test",
      "\\evil.example.test",
      "/a/\\b",
      "/\\/evil.example.test",
    ])("%s는 역슬래시를 포함하므로 거부된다", (input) => {
      expect(sanitizeNextPath(input)).toBe("/");
    });
  });

  describe("5) 제어 문자가 섞인 값", () => {
    test.each([
      ["탭", "/\t/evil.example.test"],
      ["개행", "/\n/evil.example.test"],
      ["캐리지 리턴", "/\r/evil.example.test"],
      ["NUL", "/\x00/evil.example.test"],
      ["경계값 0x1f(단위 구분자)", "/\x1f/evil.example.test"],
    ])("%s가 섞이면 거부된다", (_label, input) => {
      expect(sanitizeNextPath(input)).toBe("/");
    });

    test("경계값 0x20(공백)은 제어 문자가 아니므로 거부되지 않는다", () => {
      expect(sanitizeNextPath("/a b")).toBe("/a b");
    });
  });

  describe("허용 — 같은 오리진의 절대경로", () => {
    test.each(["/", "/console", "/appeals", "/payouts?tab=queue#top", "/a/b/c"])(
      "%s는 그대로 통과한다",
      (input) => {
        expect(sanitizeNextPath(input)).toBe(input);
      },
    );
  });
});
