import { describe, expect, it } from "vitest";

import { bucketLabel, spansDays, isolatedPoints, labelIndexes, linePath, niceScale, seriesMax, stackedBars, stackedMax } from "./chart";

describe("niceScale", () => {
  it("보기 좋은 눈금으로 올린다", () => {
    expect(niceScale(87).ticks).toEqual([0, 25, 50, 75, 100]);
    expect(niceScale(3).max).toBe(4);
    expect(niceScale(0.12).ticks).toEqual([0, 0.05, 0.1, 0.15, 0.2]);
  });
  it("0·음수·NaN 은 0..1", () => {
    for (const v of [0, -5, NaN, Infinity]) {
      const s = niceScale(v);
      expect(s.max).toBe(1);
      expect(s.ticks[0]).toBe(0);
    }
  });
});

describe("max", () => {
  it("null 을 건너뛴다", () => {
    expect(seriesMax([[1, null, 4], [2]])).toBe(4);
    expect(seriesMax([])).toBe(0);
  });
  it("쌓은 합의 최대", () => {
    expect(stackedMax([[1, 5], [2, null], [3]])).toBe(6);
    expect(stackedMax([])).toBe(0);
  });
});

describe("linePath", () => {
  it("null 에서 선을 끊는다", () => {
    expect(linePath([0, 10, null, 5], 10, 30, 10)).toBe("M0 10 L10 0 M30 5");
  });
  it("비었거나 전부 null 이면 빈 문자열", () => {
    expect(linePath([], 1, 10, 10)).toBe("");
    expect(linePath([null, null], 1, 10, 10)).toBe("");
  });
  it("점 하나는 가운데, max 0 이어도 NaN 이 없다", () => {
    expect(linePath([3], 0, 100, 10)).toBe("M50 10");
    expect(linePath([0, 0], 0, 10, 10)).not.toContain("NaN");
  });
  it("홀로 선 점을 찾는다", () => {
    expect(isolatedPoints([null, 5, null, 5, 5], 10, 40, 10)).toEqual([{ x: 10, y: 5 }]);
  });
});

describe("stackedBars", () => {
  it("아래에서 위로 쌓고 0 은 건너뛴다", () => {
    const rects = stackedBars([[2, 0], [2, 4]], 4, 20, 40, 0);
    expect(rects).toEqual([
      { x: 0, y: 20, width: 10, height: 20, series: 0, bucket: 0 },
      { x: 0, y: 0, width: 10, height: 20, series: 1, bucket: 0 },
      { x: 10, y: 0, width: 10, height: 40, series: 1, bucket: 1 },
    ]);
  });
  it("빈 입력·max 0 에서 깨지지 않는다", () => {
    expect(stackedBars([], 1, 10, 10)).toEqual([]);
    expect(stackedBars([[0, 0]], 0, 10, 10)).toEqual([]);
  });
});

describe("labelIndexes", () => {
  it("처음과 끝을 포함한다", () => {
    expect(labelIndexes(61, 4)).toEqual([0, 20, 40, 60]);
    expect(labelIndexes(1)).toEqual([0]);
    expect(labelIndexes(0)).toEqual([]);
    expect(labelIndexes(2, 4)).toEqual([0, 1]);
  });
});

describe("bucketLabel", () => {
  it("분 단위는 시:분, 시간 단위는 날짜", () => {
    expect(bucketLabel("2026-10-30T00:05:00Z", 60)).toBe("09:05");
    expect(bucketLabel("2026-10-30T00:00:00Z", 3600)).toBe("10. 30. 09시");
    expect(bucketLabel("nope", 60)).toBe("");
    expect(bucketLabel("2026-10-30T00:05:00Z", 900, true)).toBe("10. 30. 09:05");
  });
  it("하루 이상이면 날짜가 필요하다", () => {
    expect(spansDays(["2026-10-29T00:00:00Z", "2026-10-30T00:00:00Z"])).toBe(true);
    expect(spansDays(["2026-10-30T00:00:00Z", "2026-10-30T01:00:00Z"])).toBe(false);
    expect(spansDays([])).toBe(false);
  });
});
