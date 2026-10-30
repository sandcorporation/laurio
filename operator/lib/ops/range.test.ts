import { describe, expect, it } from "vitest";

import { formatCount, formatSeconds, rangeFromSearchParams } from "./range";

function params(range: string | null) {
  return { get: (name: string) => (name === "range" ? range : null) };
}

describe("운영 지표 기간 (#827)", () => {
  it("주소의 기간을 읽고, 모르는 값이면 1시간이다", () => {
    expect(rangeFromSearchParams(params("24h"))).toBe("24h");
    expect(rangeFromSearchParams(params("7d"))).toBe("7d");
    expect(rangeFromSearchParams(params("30d"))).toBe("1h");
    expect(rangeFromSearchParams(params(null))).toBe("1h");
  });
});

describe("값 표기", () => {
  it("관측이 없는 분위수는 「—」다", () => {
    expect(formatSeconds(null)).toBe("—");
  });

  it("초는 크기에 따라 자릿수를 줄이고 60초부터 분으로 쓴다", () => {
    expect(formatSeconds(1.5)).toBe("1.50초");
    expect(formatSeconds(22.25)).toBe("22.3초");
    expect(formatSeconds(225)).toBe("3분 45초");
    expect(formatSeconds(300)).toBe("5분");
  });

  it("수는 천 단위로 끊는다", () => {
    expect(formatCount(12345)).toBe("12,345");
  });
});
