// sanitizeBackendPath의 1차 방어선(세그먼트 안전성)을 전수로, 2차 방어선(구조적
// URL 정규화 확인)을 실제로 실행해 덮는다(#161).
//
// **2차 방어선은 정상 경로에서 절대 혼자 거부를 내지 않는다** — sanitizeBackendPath가
// 언제나 그 앞에 isSafeSegment 게이트를 두기 때문이다(코드 주석 참고). e2e는 이
// 게이트를 일부러 약화시켜야만 2차에 닿을 수 있는데 그건 e2e가 할 수 없는 일이다 —
// 그래서 이 파일이 `assembleAndVerifyBackendPath`를 직접 불러(1차 게이트를 거치지
// 않고) "1차가 없다고 가정했을 때도 2차가 여전히 거부하는가"를 확인한다. 이 값이
// 통과한다는 사실 자체가 "2차 방어선이 실제로 실행됐다"는 증거다.
import { describe, expect, test } from "vitest";

import { assembleAndVerifyBackendPath, sanitizeBackendPath } from "./path-safety";

describe("sanitizeBackendPath — 1차 방어선(세그먼트 안전성, 전수)", () => {
  test("세그먼트가 하나도 없으면 거부한다", () => {
    expect(sanitizeBackendPath([])).toBeNull();
  });

  describe("빈 세그먼트", () => {
    test.each([
      [["contests", "", "tick"]],
      [[""]],
    ])("%j는 거부된다", (segments) => {
      expect(sanitizeBackendPath(segments)).toBeNull();
    });
  });

  describe("'.' 세그먼트", () => {
    test.each([[["."]], [["contests", "."]], [[".", "internal"]]])(
      "%j는 거부된다",
      (segments) => {
        expect(sanitizeBackendPath(segments)).toBeNull();
      },
    );
  });

  describe("'..' 세그먼트", () => {
    test.each([[[".."]], [["contests", ".."]], [["..", "internal", "tick"]]])(
      "%j는 거부된다",
      (segments) => {
        expect(sanitizeBackendPath(segments)).toBeNull();
      },
    );
  });

  describe("슬래시가 섞인 세그먼트", () => {
    test.each([
      [["contests/internal"]],
      [["a/b", "c"]],
      [["/leading-slash"]],
      [["trailing-slash/"]],
    ])("%j는 거부된다", (segments) => {
      expect(sanitizeBackendPath(segments)).toBeNull();
    });
  });

  describe("역슬래시가 섞인 세그먼트", () => {
    test.each([
      [["contests\\internal"]],
      [["a\\b", "c"]],
      [["..\\internal"]], // 역슬래시 검사가 아니라도 이미 "/"·".."류가 아니므로 역슬래시 검사 자체를 겨냥한다
    ])("%j는 거부된다", (segments) => {
      expect(sanitizeBackendPath(segments)).toBeNull();
    });
  });

  test("하나라도 위험하면 나머지가 안전해도 전체가 거부된다(기본 거부)", () => {
    expect(sanitizeBackendPath(["contests", "..", "internal", "tick"])).toBeNull();
  });

  describe("허용 — 전부 안전한 세그먼트", () => {
    test("단일 세그먼트를 '/api/'에 이어 붙인다", () => {
      expect(sanitizeBackendPath(["contests"])).toBe("/api/contests");
    });

    test("여러 세그먼트를 순서대로 이어 붙인다", () => {
      expect(sanitizeBackendPath(["contests", "123", "award"])).toBe("/api/contests/123/award");
    });

    test("세그먼트 안의 특수문자는 encodeURIComponent로 인코딩되어 실행 시 문자 그대로 남는다", () => {
      // 공백·퍼센트 기호처럼 경로 구분자는 아니지만 그대로 두면 위험할 수 있는
      // 문자가 인코딩되는지 확인한다 — isSafeSegment는 이들을 막지 않으므로
      // 인코딩이 유일한 방어다.
      expect(sanitizeBackendPath(["a b"])).toBe("/api/a%20b");
      expect(sanitizeBackendPath(["100%"])).toBe("/api/100%25");
    });
  });
});

describe("assembleAndVerifyBackendPath — 2차 방어선을 1차 없이 직접 실행한다", () => {
  test("1차가 없었다면 통과했을 '..' 세그먼트를 2차가 단독으로 거부한다", () => {
    // isSafeSegment를 거치지 않고 바로 부른다 — "1차 조건이 실수로 완화됐다"는
    // 시나리오를 재현한다. encodeURIComponent는 "."·".."을 인코딩하지 않으므로
    // (둘 다 unreserved 문자로만 구성된다) candidate 문자열은 "/api/../internal/tick"
    // 그대로 남는데, WHATWG URL 정규화가 ".."을 실제로 접어 "/api/internal/tick"을
    // 만든다 — 두 문자열이 달라지므로 여기서 거부된다. 이게 원래 버그였던
    // "검사한 문자열과 실행한 문자열이 다르다"는 것을 직접 재현한 것이다.
    expect(assembleAndVerifyBackendPath(["..", "internal", "tick"])).toBeNull();
  });

  test("여러 단계의 '..'도 거부한다", () => {
    expect(assembleAndVerifyBackendPath(["contests", "..", "..", "internal"])).toBeNull();
  });

  test("'.' 세그먼트도 정규화로 접혀 원본과 달라지므로 거부한다", () => {
    expect(assembleAndVerifyBackendPath([".", "internal"])).toBeNull();
  });

  test("정상 세그먼트는 정규화 전후가 같아 그대로 통과한다", () => {
    expect(assembleAndVerifyBackendPath(["contests", "123"])).toBe("/api/contests/123");
  });

  test("sanitizeBackendPath 자신은 1차에서 이미 걸러 2차까지 갈 필요가 없다 — 결과는 같다", () => {
    // 두 함수가 같은 입력에 대해 같은 결론(거부)에 이른다는 것을 확인해, 이
    // 리팩터링이 sanitizeBackendPath의 공개 동작을 바꾸지 않았음을 보인다.
    expect(sanitizeBackendPath(["..", "internal", "tick"])).toBeNull();
    expect(assembleAndVerifyBackendPath(["..", "internal", "tick"])).toBeNull();
  });
});
