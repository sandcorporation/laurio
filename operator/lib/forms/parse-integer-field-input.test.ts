// parseIntegerFieldInput의 거부·허용 종류를 전수로 덮는다(#162) — 빈 값·공백·
// 부호·앞 0·숫자가 아닌 값이 각각 무엇이 되는지 표로 단언한다.
//
// 이 함수의 존재 이유는 `Number("")`가 NaN이 아니라 0이라는 함정을 막는
// 것이다(파일 상단 주석) — 그래서 "빈 값이 조용히 0이 되지 않는가"가 가장
// 중요한 단언이다.
import { describe, expect, test } from "vitest";

import { parseIntegerFieldInput } from "./parse-integer-field-input";

describe("parseIntegerFieldInput — 거부·허용(전수)", () => {
  describe("빈 값 — 거부", () => {
    test.each(["", "   ", "\t", "\n"])("%j는 빈 값으로 거부된다(0으로 둔갑하지 않는다)", (raw) => {
      const result = parseIntegerFieldInput(raw);
      expect(result.valid).toBe(false);
      if (!result.valid) expect(result.raw).toBe(raw.trim());
    });
  });

  describe("공백 — trim 후 판정한다", () => {
    test("앞뒤 공백이 있어도 숫자면 유효하다", () => {
      expect(parseIntegerFieldInput("  42  ")).toEqual({ valid: true, value: 42 });
    });

    test("공백만 있으면 빈 값과 같이 취급된다", () => {
      expect(parseIntegerFieldInput("   ")).toEqual({ valid: false, raw: "" });
    });
  });

  describe("부호", () => {
    test.each([
      ["+5", 5],
      ["-5", -5],
      ["+0", 0],
      ["-0", -0],
    ])("%s는 %d로 파싱된다", (raw, value) => {
      expect(parseIntegerFieldInput(raw)).toEqual({ valid: true, value });
    });

    test("부호만 있고 숫자가 없으면 거부된다", () => {
      expect(parseIntegerFieldInput("+")).toEqual({ valid: false, raw: "+" });
      expect(parseIntegerFieldInput("-")).toEqual({ valid: false, raw: "-" });
    });
  });

  describe("앞 0", () => {
    test.each([
      ["007", 7],
      ["0", 0],
      ["00", 0],
      ["01", 1],
    ])("%s는 %d로 파싱된다(값이 그대로 유지되고 앞 0은 사라진다)", (raw, value) => {
      expect(parseIntegerFieldInput(raw)).toEqual({ valid: true, value });
    });
  });

  describe("숫자가 아닌 값 — 거부", () => {
    test.each(["abc", "12abc", "abc12", "1.2.3", "--5", "1-2", "NaN 아님을 확인하는 표식"])(
      "%j는 거부된다",
      (raw) => {
        const result = parseIntegerFieldInput(raw);
        expect(result.valid).toBe(false);
        if (!result.valid) expect(result.raw).toBe(raw.trim());
      },
    );
  });

  describe("호출부가 기대하는 판별 유니언 모양", () => {
    test("유효하면 value 필드만 있고 raw는 없다", () => {
      const result = parseIntegerFieldInput("10");
      expect(result).toEqual({ valid: true, value: 10 });
      expect("raw" in result).toBe(false);
    });

    test("무효하면 raw 필드만 있고 value는 없다 — 서버가 422로 거절하도록 원본을 그대로 싣는다", () => {
      const result = parseIntegerFieldInput("  abc  ");
      expect(result).toEqual({ valid: false, raw: "abc" });
      expect("value" in result).toBe(false);
    });
  });
});
