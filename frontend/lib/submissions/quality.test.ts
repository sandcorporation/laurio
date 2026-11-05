import { describe, expect, it } from "vitest";

import { formatQualityTotal, orderSubmissions, sortByQuality } from "./quality";

function q(raw: number, maxTotal = 3) {
  return {
    total: raw / 5,
    max_total: maxTotal,
    raw_total: raw,
    completeness: (raw / (5 * maxTotal)) * 100,
    weighted_score: raw,
    max_weighted_score: 5 * maxTotal,
    items: [],
    rank: 1,
  };
}

describe("formatQualityTotal", () => {
  it("합은 소수 첫째 자리, 만점은 배점 합으로 「n / 만점점」", () => {
    expect(formatQualityTotal(187 / 5, 45)).toBe("37.4 / 45점");
    expect(formatQualityTotal(3, 3)).toBe("3.0 / 3점");
    expect(formatQualityTotal(0, 12)).toBe("0.0 / 12점");
  });
});

describe("sortByQuality", () => {
  it("정수 합(raw_total) 높은 순, 같으면 제출 순서, 매기지 않은 제출은 뒤", () => {
    const rows = [
      { submission_id: 1, quality: q(6) },
      { submission_id: 2, quality: null },
      { submission_id: 3, quality: q(13) },
      { submission_id: 4, quality: q(6) },
    ];
    expect(sortByQuality(rows).map((r) => r.submission_id)).toEqual([3, 1, 4, 2]);
  });

  it("반올림한 표시값이 아니라 정수 합으로 가른다", () => {
    // 표시값(total)이 같아도 정수 합이 다르면 갈린다.
    const rows = [
      { submission_id: 1, quality: { ...q(186, 45), total: 37.4 } },
      { submission_id: 2, quality: { ...q(187, 45), total: 37.4 } },
    ];
    expect(sortByQuality(rows).map((r) => r.submission_id)).toEqual([2, 1]);
  });

  it("「제출순」은 받은 순서 그대로다", () => {
    const rows = [{ submission_id: 1, quality: q(1) }, { submission_id: 2, quality: q(9) }];
    expect(orderSubmissions(rows, "submitted").map((r) => r.submission_id)).toEqual([1, 2]);
    expect(orderSubmissions(rows, "quality").map((r) => r.submission_id)).toEqual([2, 1]);
  });
});
