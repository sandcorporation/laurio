import { describe, expect, it } from "vitest";

import { estimateLine, formatCompleteness, formatQualityCost, myRankLine } from "./format";

describe("formatCompleteness", () => {
  it("소수 첫째 자리까지 보인다", () => {
    expect(formatCompleteness(11 / 15 * 100)).toBe("73.3");
    expect(formatCompleteness(100)).toBe("100.0");
    expect(formatCompleteness(0)).toBe("0.0");
  });
});

describe("formatQualityCost", () => {
  it("단가를 모르면 그렇다고 말한다", () => {
    expect(formatQualityCost(null)).toBe("단가 모름");
  });

  it("작은 값은 100원 미만, 큰 값은 10원 단위로 반올림한다", () => {
    expect(formatQualityCost(12.4)).toBe("100원 미만");
    expect(formatQualityCost(1234.5)).toBe("약 1,230원");
  });
});

describe("estimateLine", () => {
  it("새로 채점할 사람 수와 예상 비용을 한 줄로", () => {
    expect(estimateLine({ new_count: 3, reuse_count: 1, cost_krw: 1500, blocked_reason: null })).toBe(
      "새로 채점할 3명 · 약 1,500원",
    );
  });
});

describe("myRankLine", () => {
  it("본인의 등수와 순위에 든 사람 수", () => {
    expect(myRankLine(2, 5)).toBe("완성도 순위 2등 / 5명");
  });
});
