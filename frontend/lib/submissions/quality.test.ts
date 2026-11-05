import { describe, expect, it } from "vitest";

import { formatCompleteness, orderSubmissions, sortByQuality } from "./quality";

function q(weighted: number) {
  return { completeness: (weighted / 15) * 100, weighted_score: weighted, max_weighted_score: 15, items: [], rank: 1 };
}

describe("formatCompleteness", () => {
  it("소수 첫째 자리까지 보인다", () => {
    expect(formatCompleteness((13 / 15) * 100)).toBe("86.7");
    expect(formatCompleteness(40)).toBe("40.0");
    expect(formatCompleteness(100)).toBe("100.0");
  });
});

describe("sortByQuality", () => {
  it("가중 점수 높은 순, 같으면 제출 순서, 매기지 않은 제출은 뒤", () => {
    const rows = [
      { submission_id: 1, quality: q(6) },
      { submission_id: 2, quality: null },
      { submission_id: 3, quality: q(13) },
      { submission_id: 4, quality: q(6) },
    ];
    expect(sortByQuality(rows).map((r) => r.submission_id)).toEqual([3, 1, 4, 2]);
  });

  it("반올림한 완성도가 아니라 가중 점수로 가른다", () => {
    // 14/15 와 28/30 은 둘 다 93.3 으로 보이지만 가중 점수가 다르다.
    const rows = [
      { submission_id: 1, quality: { ...q(14), completeness: 93.33 } },
      { submission_id: 2, quality: { ...q(28), completeness: 93.33, max_weighted_score: 30 } },
    ];
    expect(sortByQuality(rows).map((r) => r.submission_id)).toEqual([2, 1]);
  });

  it("「제출순」은 받은 순서 그대로다", () => {
    const rows = [{ submission_id: 1, quality: q(1) }, { submission_id: 2, quality: q(9) }];
    expect(orderSubmissions(rows, "submitted").map((r) => r.submission_id)).toEqual([1, 2]);
    expect(orderSubmissions(rows, "quality").map((r) => r.submission_id)).toEqual([2, 1]);
  });
});
