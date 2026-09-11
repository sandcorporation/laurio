// isSafeNextPath/resolveNextPath의 경계를 전수로 덮는다(#334).
//
// frontend/lib/auth/next-path.test.ts와 같은 표다 — 검증 로직이 같은 기법
// (placeholder 오리진을 기준으로 실제 `new URL()` 파싱 결과가 그 오리진을
// 벗어났는지만 본다)이기 때문이다. 이 파일은 그 표를 강의실의 next-path.ts에
// 대해 재확인한다 — 여기서만 통과하고 공개 앱에서는 거부되는(혹은 그 반대인)
// 경계가 생기면 이 표가 바로 잡는다.
import { describe, expect, test } from "vitest";

import { isSafeNextPath, resolveNextPath } from "./next-path";

describe("isSafeNextPath — 다섯 거부 종류(전수) + 구조적 판정의 경계", () => {
  describe("빈 값", () => {
    test.each<string | null | undefined>([null, undefined, ""])("%j는 거부된다", (input) => {
      expect(isSafeNextPath(input)).toBe(false);
    });
  });

  describe("완전한 외부 URL — '/'로 시작하지 않으므로 거부", () => {
    test.each([
      "https://evil.example.test/steal",
      "http://evil.example.test",
      "evil.example.test",
      "javascript:alert(1)",
      "\\\\evil.example.test", // "/"로 시작하지 않으므로 이 단계에서 이미 거부
    ])("%s는 거부된다", (input) => {
      expect(isSafeNextPath(input)).toBe(false);
    });
  });

  describe("프로토콜 상대 URL", () => {
    test.each(["//evil.example.test", "//evil.example.test/phish"])(
      "%s는 다른 호스트로 파싱되어 거부된다",
      (input) => {
        expect(isSafeNextPath(input)).toBe(false);
      },
    );
  });

  describe("역슬래시 — 리딩 위치에서 프로토콜 상대 URL과 같은 효과를 낼 때만 거부된다", () => {
    test.each(["/\\evil.example.test", "/\\/evil.example.test"])(
      "%s는 파싱되면 다른 호스트가 되므로 거부된다",
      (input) => {
        expect(isSafeNextPath(input)).toBe(false);
      },
    );

    test("경로 중간의 역슬래시는 슬래시로 정규화될 뿐 호스트를 바꾸지 않으므로 거부되지 않는다", () => {
      expect(isSafeNextPath("/a\\b")).toBe(true);
      expect(isSafeNextPath("/foo/../\\bar")).toBe(true);
    });
  });

  describe("제어 문자 — 파싱 첫 단계에서 제거되는 탭·개행·캐리지 리턴이 호스트를 바꿀 때만 거부된다", () => {
    test.each([
      ["탭", "/\t/evil.example.test"],
      ["개행", "/\n/evil.example.test"],
      ["캐리지 리턴", "/\r/evil.example.test"],
      ["탭 두 개", "/\t\t//evil.example.test"],
    ])("%s가 리딩 위치에서 '//'를 재구성하면 거부된다", (_label, input) => {
      expect(isSafeNextPath(input)).toBe(false);
    });

    test("탭이 경로 중간에 있으면 제거될 뿐 호스트를 바꾸지 않으므로 거부되지 않는다", () => {
      expect(isSafeNextPath("/classes\ttab-in-middle")).toBe(true);
    });

    test("NUL·단위 구분자(0x1f) 같은 그 밖의 제어 문자는 WHATWG 파서가 제거하지 않고 그대로 두므로 호스트가 바뀌지 않아 거부되지 않는다", () => {
      expect(isSafeNextPath("/\x00/evil.example.test")).toBe(true);
      expect(isSafeNextPath("/\x1f/evil.example.test")).toBe(true);
    });

    test("경계값 0x20(공백)은 퍼센트 인코딩된 문자로 취급되어 거부되지 않는다", () => {
      expect(isSafeNextPath("/a b")).toBe(true);
    });
  });

  describe("허용 — 같은 오리진의 절대경로", () => {
    test.each(["/", "/classes/42", "/join/abc123", "/classes/1/problems/mine?tab=x#y"])(
      "%s는 통과한다",
      (input) => {
        expect(isSafeNextPath(input)).toBe(true);
      },
    );
  });
});

describe("string[] — 같은 쿼리 키가 반복되면 Next.js가 배열을 준다(#334 코드리뷰)", () => {
  test("배열은 안전하지 않은 값으로 거부된다", () => {
    expect(isSafeNextPath(["/classes/1", "/classes/2"])).toBe(false);
    expect(isSafeNextPath([])).toBe(false);
  });

  test("resolveNextPath도 배열이면 fallback으로 떨어진다 — .startsWith 호출로 터지지 않는다", () => {
    expect(resolveNextPath(["/a", "/b"])).toBe("/");
    expect(resolveNextPath(["/a", "/b"], "/join/x")).toBe("/join/x");
  });
});

describe("resolveNextPath — 어떤 입력에도 결과가 '/'로 시작한다", () => {
  test.each<[string | null | undefined, string | undefined, string]>([
    [null, undefined, "/"],
    [undefined, undefined, "/"],
    ["", undefined, "/"],
    ["https://evil.example.test/steal", undefined, "/"],
    ["//evil.example.test", undefined, "/"],
    ["/\\evil.example.test", undefined, "/"],
    ["/\t/evil.example.test", undefined, "/"],
    ["/classes/42", undefined, "/classes/42"],
    ["https://evil.example.test", "/join/abc", "/join/abc"],
  ])("resolveNextPath(%j, %j) -> %j", (next, fallback, expected) => {
    const result = fallback === undefined ? resolveNextPath(next) : resolveNextPath(next, fallback);
    expect(result).toBe(expected);
    expect(result.startsWith("/")).toBe(true);
  });

  test("안전한 next는 정규화하지 않고 원본 문자열 그대로 돌려준다", () => {
    expect(resolveNextPath("/a\\b")).toBe("/a\\b");
  });
});
