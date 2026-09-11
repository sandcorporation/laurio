// isSafeNextPath/resolveNextPath의 경계를 전수로 덮는다(#162).
//
// 이 파일의 검사는 문자 블랙리스트가 아니라 구조적 확인이다(next-path.ts 상단
// 주석) — placeholder 오리진을 기준으로 실제 `new URL()`에 태워, 파싱 결과가
// 여전히 그 오리진을 가리키는지(호스트가 바뀌지 않았는지)만 본다. 그래서
// "위험한 문자가 섞였는가"가 아니라 "그 결과 다른 호스트로 새는가"가 유일한
// 판정 기준이다 — 아래 표는 그 성질을 직접 확인한다(호스트를 바꾸지 않는
// 제어 문자는 안전하다고 판정되는 것이 버그가 아니라 이 설계의 정확한 결과다).
import { describe, expect, test } from "vitest";

import { isSafeNextPath, resolveNextPath, withoutForeignNext } from "./next-path";

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
      // WHATWG URL 파서가 "\"를 "/"로 바꿔도 이미 첫 세그먼트 안이라 authority
      // 파싱으로 진입하지 않는다 — 그래서 호스트는 그대로다. 문자 자체가 아니라
      // 호스트 변화 여부가 기준이라는 것을 보여주는 경계 사례다.
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
      expect(isSafeNextPath("/console\ttab-in-middle")).toBe(true);
    });

    test("NUL·단위 구분자(0x1f) 같은 그 밖의 제어 문자는 WHATWG 파서가 제거하지 않고 그대로 두므로 호스트가 바뀌지 않아 거부되지 않는다", () => {
      // operator/lib/auth/sanitize-next.ts(블랙리스트 방식)와 달리 이 구현은
      // "문자가 있는가"가 아니라 "호스트가 바뀌는가"만 본다 — 그래서 탭·개행·
      // 캐리지 리턴 이외의 제어 문자는 파서가 건드리지 않는 한 안전 취급된다.
      // 이건 버그가 아니라 설계의 정확한 결과다: 열린 리다이렉트가 되려면
      // 반드시 호스트가 바뀌어야 하는데, 이 문자들은 그러지 못한다.
      expect(isSafeNextPath("/\x00/evil.example.test")).toBe(true);
      expect(isSafeNextPath("/\x1f/evil.example.test")).toBe(true);
    });

    test("경계값 0x20(공백)은 퍼센트 인코딩된 문자로 취급되어 거부되지 않는다", () => {
      expect(isSafeNextPath("/a b")).toBe(true);
    });
  });

  describe("허용 — 같은 오리진의 절대경로", () => {
    test.each(["/", "/console", "/appeals?tab=x#y", "/a/b/c"])("%s는 통과한다", (input) => {
      expect(isSafeNextPath(input)).toBe(true);
    });
  });
});

describe("resolveNextPath — 어떤 입력에도 결과가 '/'로 시작한다", () => {
  test.each<[string | null | undefined, string | undefined, string]>([
    [null, undefined, "/console"],
    [undefined, undefined, "/console"],
    ["", undefined, "/console"],
    ["https://evil.example.test/steal", undefined, "/console"],
    ["//evil.example.test", undefined, "/console"],
    ["/\\evil.example.test", undefined, "/console"],
    ["/\t/evil.example.test", undefined, "/console"],
    ["/appeals", undefined, "/appeals"],
    ["https://evil.example.test", "/payouts", "/payouts"],
  ])("resolveNextPath(%j, %j) -> %j", (next, fallback, expected) => {
    const result = fallback === undefined ? resolveNextPath(next) : resolveNextPath(next, fallback);
    expect(result).toBe(expected);
    expect(result.startsWith("/")).toBe(true);
  });

  test("안전한 next는 정규화하지 않고 원본 문자열 그대로 돌려준다", () => {
    // isSafeNextPath는 파싱 결과(호스트)만 보고 판정하지만, resolveNextPath가
    // 실제로 리다이렉트에 쓰는 값은 원본 문자열이다 — 중간의 역슬래시가
    // 슬래시로 "정규화된" 값이 아니라 사용자가 준 그대로가 나가야 한다.
    expect(resolveNextPath("/a\\b")).toBe("/a\\b");
  });
});

describe("withoutForeignNext — 형제 오리진 요청이 대조에 실패하면 next를 버린다(#334)", () => {
  test("next_origin이 허용목록에 있으면(returnOrigin이 있으면) next를 그대로 쓴다", () => {
    expect(withoutForeignNext("/join/abc123", "http://127.0.0.1:53202", "http://127.0.0.1:53202")).toBe(
      "/join/abc123",
    );
  });

  test("next_origin을 요청했는데 대조에 실패하면(returnOrigin이 null) 기본 경로로 떨어진다", () => {
    // next는 형제 앱(강의실)의 경로일 수 있다 — 이 오리진 안에서 그대로 쓰면
    // 존재하지 않는 경로라 404가 난다(#334 코드리뷰 지적).
    expect(withoutForeignNext("/join/abc123", "http://evil.example.test", null)).toBe("/console");
  });

  test("next_origin을 요청했는데 대조에 실패해도 fallback을 지정하면 그것을 쓴다", () => {
    expect(withoutForeignNext("/join/abc123", "http://evil.example.test", null, "/appeals")).toBe("/appeals");
  });

  test("next_origin이 아예 없으면(평범한 공개 앱 로그인) next를 그대로 쓴다 — 지금까지와 같다", () => {
    expect(withoutForeignNext("/console/profile", null, null)).toBe("/console/profile");
    expect(withoutForeignNext("/console/profile", undefined, null)).toBe("/console/profile");
  });
});
